# -*- coding: utf-8 -*-
"""日K 溯源欄位。

index_daily 與 ex_rights 早就有 source，daily_quotes 這張最核心的表反而沒有：
出現可疑數字時查不出是官方資料本身錯、還是我們某條補齊路徑寫壞的。
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_health import quote_lineage  # noqa: E402
from wayne_db import ensure_core_schema  # noqa: E402

COLS = (
    "date, stock_id, stock_name, market, open, high, low, close,"
    " volume, turnover_k, pct_change, avg_price"
)
PLACEHOLDERS = ", ".join(["?"] * 12)


def _row(conn, date, stock_id, market, source=None, fetched_at=None):
    cols = COLS
    vals = [date, stock_id, f"股{stock_id}", market, 100, 105, 95, 100, 1000, 1000, 0.5, 100]
    ph = PLACEHOLDERS
    if source is not None:
        cols += ", source"
        ph += ", ?"
        vals.append(source)
    if fetched_at is not None:
        cols += ", fetched_at"
        ph += ", ?"
        vals.append(fetched_at)
    conn.execute(f"INSERT INTO daily_quotes ({cols}) VALUES ({ph})", vals)


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "w.db")
    ensure_core_schema(path)
    return path


def test_schema_has_lineage_columns(db):
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_quotes)")}
    conn.close()
    assert {"source", "fetched_at"} <= cols


def test_lineage_columns_default_to_empty(db):
    conn = sqlite3.connect(db)
    _row(conn, "20260902", "2330", "TWSE")
    conn.commit()
    got = conn.execute("SELECT source, fetched_at FROM daily_quotes").fetchone()
    conn.close()
    assert got == ("", "")


def test_ensure_core_schema_is_idempotent(db):
    ensure_core_schema(db)
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_quotes)")]
    conn.close()
    assert cols.count("source") == 1
    assert cols.count("fetched_at") == 1


def test_upgrade_from_schema_without_lineage(tmp_path):
    """既有生產庫升級路徑：舊表加欄位，資料不能掉。"""
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT NOT NULL, stock_id TEXT NOT NULL, stock_name TEXT NOT NULL,
            market TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL,
            low REAL NOT NULL, close REAL NOT NULL, volume INTEGER NOT NULL,
            turnover_k REAL NOT NULL, pct_change REAL NOT NULL, avg_price REAL NOT NULL,
            foreign_net INTEGER DEFAULT 0, trust_net INTEGER DEFAULT 0,
            dealer_net INTEGER DEFAULT 0,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    _row(conn, "20260901", "2330", "TWSE")
    conn.commit()
    conn.close()

    ensure_core_schema(path)

    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_quotes)")}
    rows = conn.execute("SELECT stock_id, source FROM daily_quotes").fetchall()
    conn.close()
    assert {"source", "fetched_at"} <= cols
    assert rows == [("2330", "")]


def test_lineage_groups_sources_per_day(db):
    conn = sqlite3.connect(db)
    _row(conn, "20260902", "2330", "TWSE", "twse", "2026-09-02T16:40:00")
    _row(conn, "20260902", "2317", "TWSE", "twse", "2026-09-02T16:41:00")
    _row(conn, "20260902", "6488", "TPEX", "tpex", "2026-09-02T16:42:00")
    conn.commit()
    conn.close()

    out = quote_lineage(db)
    assert out["ok"] is True
    day = out["days"][0]
    assert day["date"] == "20260902"
    assert day["sources"] == {"twse": 2, "tpex": 1}
    assert day["last_fetch"] == "2026-09-02T16:42:00"


def test_lineage_marks_unrecorded_rows(db):
    conn = sqlite3.connect(db)
    _row(conn, "20260902", "2330", "TWSE")
    conn.commit()
    conn.close()

    out = quote_lineage(db)
    assert out["days"][0]["sources"] == {"(未記錄)": 1}


def test_lineage_limits_to_recent_days(db):
    conn = sqlite3.connect(db)
    for i, d in enumerate(("20260828", "20260829", "20260901", "20260902")):
        _row(conn, d, "2330", "TWSE", "twse", f"2026-09-0{i+1}T16:40:00")
    conn.commit()
    conn.close()

    out = quote_lineage(db, days=2)
    assert [d["date"] for d in out["days"]] == ["20260902", "20260901"]


def test_lineage_reports_missing_db(tmp_path):
    out = quote_lineage(str(tmp_path / "nope.db"))
    assert out["ok"] is False
    assert out["days"] == []


def test_lineage_reports_pre_upgrade_schema(tmp_path):
    """還沒升級的庫要照實說，不能假裝查得到。"""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, close REAL)")
    conn.commit()
    conn.close()

    out = quote_lineage(path)
    assert out["ok"] is False
    assert "溯源" in out["reason"]


@pytest.mark.production_db
def test_inventory_payload_exposes_lineage():
    """/inventory 要看得到溯源；db_quick_check_ok 會擋掉非生產規模的庫。"""
    from config import get_db_path
    from import_health import inventory_payload

    payload = inventory_payload(get_db_path())
    assert "lineage" in payload
    assert isinstance(payload["lineage"].get("days"), list)


def test_fetcher_upsert_stamps_source_and_time(db):
    """走真的 UPSERT 語句，確認欄位真的被寫進去、重抓會更新。"""
    stamped = [
        ("20260902", "2330", "台積電", "TWSE", 100, 105, 95, 100, 1000, 1000, 0.5, 100, 0, 0, 0, "twse", "2026-09-02T16:40:00"),
        ("20260902", "6488", "環球晶", "TPEX", 200, 205, 195, 200, 900, 900, 0.3, 200, 0, 0, 0, "tpex", "2026-09-02T16:40:00"),
    ]
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT INTO daily_quotes (date, stock_id, stock_name, market, open, high, low,"
        " close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net,"
        " dealer_net, source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(date, stock_id) DO UPDATE SET"
        " source=excluded.source, fetched_at=excluded.fetched_at",
        stamped,
    )
    conn.commit()
    got = dict(conn.execute("SELECT stock_id, source FROM daily_quotes").fetchall())
    conn.close()
    assert got == {"2330": "twse", "6488": "tpex"}


def test_fetcher_insert_column_list_matches_tuple_width():
    """溯源欄位加在 tuple 末尾，欄位清單與佔位符數量必須一起改到。"""
    import inspect

    import data_fetcher

    src = inspect.getsource(data_fetcher.DataFetcher.update_daily_market_data)
    assert "source, fetched_at)" in src
    assert src.count("?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?") == 1
    assert '"twse", fetched_at,' in src
    assert '"tpex", fetched_at,' in src
