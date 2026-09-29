# -*- coding: utf-8 -*-
"""全鈕靜默對質骨架：缺鈕補落檔、個人本分開、壓撐三軌並存。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from button_silent_verify import (
    BOOK_KINDS,
    BUTTON_CATALOG,
    coverage_counts,
    is_personal_book_kind,
    is_screen_kind,
    optimize_status_one_liner,
    pressure_coexists,
    snapshot_ai_desk,
    snapshot_all_button_gaps,
    snapshot_biaoke_named,
    snapshot_book_buy,
    snapshot_book_hold,
    snapshot_book_watch,
    snapshot_money_flow,
)
from judge_tape import remember_rows, score_live_judges, store_path
from wayne_db import ensure_core_schema


def _seed(db: str, last: dict[str, float], as_of: str = "20260915") -> None:
    ensure_core_schema(db)
    start = datetime(2026, 8, 1)
    end = datetime.strptime(as_of, "%Y%m%d")
    conn = sqlite3.connect(db)
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        is_last = d == end
        for sid, px in last.items():
            close = float(px if is_last else 50.0)
            conn.execute(
                "INSERT OR REPLACE INTO daily_quotes("
                "date,stock_id,stock_name,market,open,high,low,close,volume,"
                "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ymd,
                    sid,
                    sid,
                    "TW",
                    close,
                    close,
                    close,
                    close,
                    8000,
                    400000,
                    1.6 if is_last else 0.0,
                    close,
                    500 if is_last else 0,
                    200 if is_last else 0,
                    0,
                ),
            )
        d += timedelta(days=1)
    conn.commit()
    conn.close()


def test_catalog_covers_full_keyboard():
    names = {r["btn"] for r in BUTTON_CATALOG}
    want = {
        "海選",
        "持股",
        "觀察",
        "飆大",
        "台股大盤",
        "資金輪動",
        "當沖",
        "隔日沖",
        "壓撐觀察",
        "大量區×季線",
        "AI倉",
        "連買區",
        "剛脫離零",
        "洞燭先機",
        "記買入",
    }
    assert want <= names
    cov = coverage_counts()
    assert cov["missing"] == 0
    assert cov["gap_filled"] >= 5
    assert cov["total"] == len(want)


def test_personal_vs_screen_kinds_do_not_mix():
    for k in BOOK_KINDS:
        assert is_personal_book_kind(k)
        assert not is_screen_kind(k)
    assert is_screen_kind("money_flow")
    assert is_screen_kind("leave_zero")
    assert not is_screen_kind("book_hold")
    assert not is_screen_kind("market")


def test_money_flow_snapshot_freezes_official_bars(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.0, "2330": 900.0}, "20260915")
    n = snapshot_money_flow(db, "20260915")
    assert n >= 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    row = conn.execute(
        "SELECT sid, extra FROM live_judge WHERE kind='money_flow' AND as_of='20260915' LIMIT 1"
    ).fetchone()
    conn.close()
    assert row
    extra = json.loads(row[1] or "{}")
    assert extra.get("c") is not None
    assert extra.get("v") is not None
    assert "png" not in json.dumps(extra).lower()


def test_empty_book_does_not_count_as_recorded(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.0}, "20260915")
    assert snapshot_book_hold(db, "20260915") == 0
    assert snapshot_book_watch(db, "20260915") == 0
    assert snapshot_book_buy(db, "20260915") == 0


def test_book_hold_and_watch_remember_with_uid_pick(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.0, "2330": 900.0}, "20260915")
    from wayne_db import add_to_portfolio, ensure_core_schema

    ensure_core_schema(db)
    add_to_portfolio(db, "u1", "1101", "台泥", 1.0, 49.0)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO user_watchlist(user_id, stock_code, stock_name, created_at) "
        "VALUES (?,?,?,?)",
        ("u1", "2330", "台積電", "2026-09-15T10:00:00"),
    )
    conn.commit()
    conn.close()
    assert snapshot_book_hold(db, "20260915") == 1
    assert snapshot_book_watch(db, "20260915") == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    hold = conn.execute(
        "SELECT pick, sid FROM live_judge WHERE kind='book_hold'"
    ).fetchone()
    watch = conn.execute(
        "SELECT pick, sid FROM live_judge WHERE kind='book_watch'"
    ).fetchone()
    conn.close()
    assert hold == ("u1", "1101")
    assert watch == ("u1", "2330")


def test_ai_and_biaoke_snapshots(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"2454": 100.0}, "20260915")
    from screen_review import ensure_ai_fills_table

    ensure_ai_fills_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO ai_fills(as_of, user_id, stock_id, stock_name, action, price, shares, bucket) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("20260915", "wayne_ai", "2454", "聯發科", "BUY", 100.0, 1000, "leave_zero"),
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS biaoke_tape (
            post_id TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL DEFAULT '',
            post_date TEXT NOT NULL DEFAULT '',
            post_time TEXT NOT NULL DEFAULT '',
            snippet TEXT NOT NULL DEFAULT '',
            bar_date TEXT NOT NULL DEFAULT '',
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            pct_change REAL,
            note TEXT NOT NULL DEFAULT '',
            charts TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (post_id, stock_id)
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO biaoke_tape("
        "post_id,stock_id,stock_name,post_date,bar_date,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("p1", "2454", "聯發科", "20260915", "20260915", 99, 101, 98, 100, 9000),
    )
    conn.commit()
    conn.close()
    assert snapshot_ai_desk(db, "20260915") == 1
    assert snapshot_biaoke_named(db, "20260915") == 1


def test_gap_runner_and_score_do_not_raise(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.0}, "20260915")
    stats = snapshot_all_button_gaps(db, "20260915")
    assert "money_flow" in stats
    remember_rows(
        db,
        "money_flow",
        [{"stock_id": "1101", "close": 50.0}],
        as_of="20260915",
        pick="rule",
        src="flow",
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO daily_quotes("
        "date,stock_id,stock_name,market,open,high,low,close,volume,"
        "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260916", "1101", "台泥", "TW", 51, 51, 51, 51, 8000, 400000, 2.0, 51),
    )
    conn.commit()
    conn.close()
    filled = score_live_judges(db, "20260916")
    assert filled >= 1


def test_pressure_coexists_with_all_button_skeleton():
    assert pressure_coexists() is True
    assert Path("pressure_rank_verify.py").is_file()
    src = Path("judge_tape.py").read_text(encoding="utf-8")
    assert "pressure_rank_verify" in src
    assert "snapshot_all_button_gaps" in src
    line = optimize_status_one_liner("")
    assert line.startswith("明確優化狀態：")
    assert "個人本" in line
    assert "%" not in line or "n≥" in line  # 不准堆過程％；門檻字樣可有


def test_optimize_status_no_process_pct_spam():
    line = optimize_status_one_liner("")
    assert "還在收集" not in line or "繼續收集" in line
    assert "試畫" not in line
    assert "偷偷" not in line
