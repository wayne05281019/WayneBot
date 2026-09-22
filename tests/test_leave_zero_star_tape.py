# -*- coding: utf-8 -*-
"""黃金買點五星／四星／三星隔日對質：只落檔，不改評選、不改桶權重、不推話筒。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from screen_review import (
    adapt_bucket_weights,
    bucket_weight,
    format_leave_zero_star_html,
    format_review_html,
    leave_zero_star_stats,
    save_screen_picks,
    score_screen_picks,
)
from screening_engine import entry_star_count
from wayne_db import PRIVATE_USER_TABLES, ensure_core_schema


def _quote(conn: sqlite3.Connection, date: str, sid: str, name: str, close: float) -> None:
    conn.execute(
        """
        INSERT INTO daily_quotes(
            date,stock_id,stock_name,market,open,high,low,close,volume,
            turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (date, sid, name, "TW", close, close, close, close, 1000, 1000, 0, close, 0, 0, 0),
    )


def test_leave_zero_star_next_day_splits_five_four_three(tmp_path):
    db = str(tmp_path / "star.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    _quote(conn, "20260828", "2330", "台積電", 102.0)
    _quote(conn, "20260828", "2303", "聯電", 101.0)
    _quote(conn, "20260828", "2317", "鴻海", 99.0)
    _quote(conn, "20260828", "1101", "台泥", 105.0)
    _quote(conn, "20260828", "2412", "中華電", 110.0)
    conn.commit()
    conn.close()

    n = save_screen_picks(
        db,
        "20260827",
        {
            "leave_zero": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 100.0, "entry_stars": 5},
                {"stock_id": "2303", "stock_name": "聯電", "close": 100.0, "entry_stars": 4},
                {"stock_id": "2317", "stock_name": "鴻海", "close": 100.0, "entry_stars": 3},
                {"stock_id": "1101", "stock_name": "台泥", "close": 100.0, "entry_stars": 1},
            ],
            "golden_buy": [
                {"stock_id": "2412", "stock_name": "中華電", "close": 100.0, "entry_stars": 5},
            ],
        },
    )
    assert n == 5
    filled = score_screen_picks(db, "20260828")
    assert filled == 5

    conn = sqlite3.connect(db)
    tape = {
        int(s): (int(nn), float(avg), int(h))
        for s, nn, avg, h in conn.execute(
            "SELECT stars, n, avg_pct, hits FROM leave_zero_star_tape WHERE as_of='20260827' AND n>0"
        )
    }
    saved_stars = dict(
        conn.execute(
            "SELECT stock_id, entry_stars FROM screen_picks WHERE as_of='20260827' AND bucket='leave_zero'"
        )
    )
    gb_bucket = conn.execute(
        "SELECT bucket FROM screen_picks WHERE stock_id='2412'"
    ).fetchone()[0]
    conn.close()
    assert saved_stars == {"2330": 5, "2303": 4, "2317": 3, "1101": 1}
    assert tape[5] == (1, 2.0, 1)
    assert tape[4] == (1, 1.0, 1)
    assert tape[3] == (1, -1.0, 0)
    assert tape[2] == (1, 5.0, 1)
    assert gb_bucket == "golden_buy"

    stats = {s: (n, avg, h) for s, n, avg, h in leave_zero_star_stats(db)}
    assert stats[5][0] == 1 and abs(stats[5][1] - 2.0) < 1e-9
    html = format_leave_zero_star_html(db)
    assert "黃金買點星級隔日" in html
    assert "五星" in html and "四星" in html and "三星" in html and "二星內" in html
    review = format_review_html(db)
    assert "海選復盤" in review
    assert "五星" not in review
    assert "四星" not in review
    assert "星級隔日" not in review


def test_star_tape_does_not_pause_leave_zero_bucket(tmp_path):
    """五星隔日弱、四星隔日強：整張黃金買點權重仍合併算，不准用星帶去停桶。"""
    db = str(tmp_path / "w.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    leave = []
    for i in range(5):
        sid = f"5{i:03d}"
        _quote(conn, "20260828", sid, "五星弱", 97.0)
        leave.append(
            {"stock_id": sid, "stock_name": "五星弱", "close": 100.0, "entry_stars": 5}
        )
    for i in range(3):
        sid = f"4{i:03d}"
        _quote(conn, "20260828", sid, "四星強", 103.0)
        leave.append(
            {"stock_id": sid, "stock_name": "四星強", "close": 100.0, "entry_stars": 4}
        )
    conn.commit()
    conn.close()
    assert save_screen_picks(db, "20260827", {"leave_zero": leave}) == 8
    assert score_screen_picks(db, "20260828") == 8
    adapt_bucket_weights(db)
    assert bucket_weight(db, "leave_zero") == 1.0
    stats = {s: (n, avg, h) for s, n, avg, h in leave_zero_star_stats(db)}
    assert stats[5] == (5, -3.0, 0)
    assert stats[4][0] == 3 and abs(stats[4][1] - 3.0) < 1e-9 and stats[4][2] == 3


def test_null_stars_not_invented_into_bands(tmp_path):
    db = str(tmp_path / "null.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    _quote(conn, "20260828", "2330", "台積電", 102.0)
    conn.commit()
    conn.close()
    save_screen_picks(
        db,
        "20260827",
        {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}]},
    )
    score_screen_picks(db, "20260828")
    conn = sqlite3.connect(db)
    n_tape = conn.execute(
        "SELECT COUNT(*) FROM leave_zero_star_tape WHERE as_of='20260827' AND n>0"
    ).fetchone()[0]
    stars = conn.execute(
        "SELECT entry_stars FROM screen_picks WHERE stock_id='2330'"
    ).fetchone()[0]
    conn.close()
    assert stars is None
    assert n_tape == 0


def test_star_formula_and_surfaces_unchanged():
    assert entry_star_count({"profit_pct": 0.8}, bucket_key="leave_zero") == 5
    src = Path("screening_engine.py").read_text(encoding="utf-8")
    i_stamp = src.find("results[key] = stamp_entry_stars(rows, key)")
    i_save = src.find("save_screen_picks(engine.db_path, target_date, results)")
    assert 0 < i_stamp < i_save
    review = Path("screen_review.py").read_text(encoding="utf-8")
    adapt_i = review.find("def adapt_bucket_weights")
    tape_i = review.find("leave_zero_star_tape")
    assert adapt_i > 0 and tape_i > 0
    adapt_block = review[adapt_i : adapt_i + 1800]
    assert "leave_zero_star" not in adapt_block
    assert "format_leave_zero_star_html" not in Path("ai_trader.py").read_text(encoding="utf-8")
    assert "format_leave_zero_star_html" not in Path("main_runner.py").read_text(encoding="utf-8")
    assert "leave_zero_star_tape" not in PRIVATE_USER_TABLES
    silent = Path("silent_progress.py").read_text(encoding="utf-8")
    assert "score_screen_picks" not in silent
    assert "leave_zero_star_tape" not in silent
    assert "send_telegram" not in Path("screen_review.py").read_text(encoding="utf-8")
