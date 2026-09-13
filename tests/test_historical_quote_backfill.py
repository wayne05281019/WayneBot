# -*- coding: utf-8 -*-
"""從發文起始回補官方日K：已齊不重抓、週末略過、不往未來寫。"""
from __future__ import annotations

import inspect
import sqlite3

from data_fetcher import BIAOKE_QUOTE_BACKFILL_START, DataFetcher
from wayne_db import ensure_core_schema


def _quote(conn, date, sid, name="測", market="TW"):
    conn.execute(
        """
        INSERT INTO daily_quotes(
            date, stock_id, stock_name, market, open, high, low, close,
            volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (date, sid, name, market, 10, 10, 10, 10, 1, 10, 0, 10, 0, 0, 0),
    )


def test_backfill_start_is_post_origin_week():
    assert BIAOKE_QUOTE_BACKFILL_START == "20231201"


def test_fill_historical_skips_weekend_and_complete_days(tmp_path, monkeypatch):
    monkeypatch.setattr(DataFetcher, "_ensure_database_ready", lambda self: None)
    db = str(tmp_path / "hist.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    _quote(conn, "20231219", "2330", "台積電")
    _quote(conn, "20231219", "2382", "廣達")
    conn.commit()
    conn.close()

    called = []

    def fake_update(self, target_date=None, *, skip_chips=False, skip_repair=False):
        called.append(
            {
                "date": str(target_date),
                "skip_chips": skip_chips,
                "skip_repair": skip_repair,
            }
        )
        conn2 = sqlite3.connect(db)
        _quote(conn2, str(target_date), "2330")
        _quote(conn2, str(target_date), "2382")
        conn2.commit()
        conn2.close()
        return 80

    monkeypatch.setattr(DataFetcher, "update_daily_market_data", fake_update)
    fetcher = DataFetcher(db_path=db)
    stats = fetcher.fill_historical_market_days(
        start_date="20231216",
        end_date="20231220",
        max_days=10,
        sleep_s=0,
        min_rows=2,
        skip_chips=True,
    )
    dates = [item["date"] for item in called]
    assert "20231216" not in dates  # 週六
    assert "20231217" not in dates  # 週日
    assert "20231219" not in dates  # 已齊
    assert dates == ["20231218", "20231220"]
    assert all(item["skip_chips"] and item["skip_repair"] for item in called)
    assert stats["filled"] == ["20231218", "20231220"]
    assert "20231219" in stats["already"]
    assert stats["pending"] == 0


def test_fill_historical_skips_existing_and_continues_past_hole(tmp_path, monkeypatch):
    monkeypatch.setattr(DataFetcher, "_ensure_database_ready", lambda self: None)
    db = str(tmp_path / "cap.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    _quote(conn, "20250220", "2330")
    conn.commit()
    conn.close()
    called = []
    monkeypatch.setattr(
        DataFetcher,
        "update_daily_market_data",
        lambda self, target_date=None, **kw: called.append(str(target_date)) or 0,
    )
    fetcher = DataFetcher(db_path=db)
    stats = fetcher.fill_historical_market_days(
        start_date="20250220",
        end_date="20250221",
        max_days=5,
        sleep_s=0,
        min_rows=1,
    )
    assert "20250220" not in called
    assert "20250220" in stats["already"]
    assert "20250221" in called


def test_update_daily_keeps_source_lineage():
    src = inspect.getsource(DataFetcher.update_daily_market_data)
    assert '"twse", fetched_at,' in src
    assert '"tpex", fetched_at,' in src
    assert "skip_chips" in src
    assert "skip_repair" in src
