# -*- coding: utf-8 -*-
"""介紹圖籌碼要用最後完整 T86，不能把盤中／融合後的 DEFAULT 0 當法人。"""
from __future__ import annotations

import sqlite3

from wayne_db import ensure_core_schema

Q = (
    "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,"
    "volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _ins(conn, date, sid, name, close, vol, f, t, d, market="TWO"):
    conn.execute(
        Q,
        (date, sid, name, market, close, close, close, close, vol, 1, 0, close, f, t, d),
    )


def _seed_5351(path: str, *, today_zero: bool = False, other_ready_today: bool = False):
    conn = sqlite3.connect(path)
    _ins(conn, "20260908", "5351", "鈺創", 117, 29848, -7030, -40, -200)
    _ins(conn, "20260909", "5351", "鈺創", 118, 8941, 767, -20, -329)
    if today_zero:
        _ins(conn, "20260910", "5351", "鈺創", 116.2, 4681, 0, 0, 0)
    if other_ready_today:
        _ins(conn, "20260910", "2330", "台積電", 100, 1000, 100, 0, 0, market="TW")
    conn.commit()
    conn.close()


def test_build_tape_skips_fused_zero_t86_like_5351(tmp_path):
    from chip_tape import build_tape, last_complete_chip_nets

    path = str(tmp_path / "t.db")
    ensure_core_schema(path)
    _seed_5351(path, today_zero=True)
    tape = build_tape(path, "5351", merge_live=False) or {}
    assert tape.get("has_chips") is True
    assert tape["foreign"]["net"] == 767
    assert tape["trust"]["net"] == -20
    assert tape["dealer"]["net"] == -329
    assert tape["three"]["net"] == 418
    assert tape["inst_pct"] == 4.7
    assert tape["chip_date"] == "20260909"
    assert tape["chip_asof_label"] == "9/9"
    assert "後轉平" not in (tape["foreign"].get("phrase") or "")
    nets = last_complete_chip_nets(path, "5351", "20260910")
    assert nets["foreign_net"] == 767
    assert nets["quote_date"] == "20260909"


def test_build_tape_keeps_real_zero_when_market_t86_ready(tmp_path):
    from chip_tape import build_tape, last_complete_chip_nets

    path = str(tmp_path / "t.db")
    ensure_core_schema(path)
    _seed_5351(path, today_zero=True, other_ready_today=True)
    tape = build_tape(path, "5351", merge_live=False) or {}
    assert tape["foreign"]["net"] == 0
    assert tape["chip_date"] == "20260910"
    assert tape.get("chip_asof_label") == ""
    nets = last_complete_chip_nets(path, "5351")
    assert nets["foreign_net"] == 0
    assert nets["quote_date"] == "20260910"


def test_build_tape_live_extra_does_not_zero_chips(tmp_path):
    from chip_tape import build_tape
    import live_quote as lq
    import trading_calendar as tc

    path = str(tmp_path / "t.db")
    ensure_core_schema(path)
    _seed_5351(path, today_zero=False)
    rt = {
        "open": 117.0,
        "high": 118.5,
        "low": 116.0,
        "close": 116.2,
        "volume": 4681,
        "pct_change": -1.48,
    }
    old_today = lq.taipei_today_str
    old_win = lq.is_live_merge_window
    old_cal = tc.is_tw_open_calendar_day
    try:
        lq.taipei_today_str = lambda: "20260910"
        lq.is_live_merge_window = lambda now=None: True
        tc.is_tw_open_calendar_day = lambda d: True
        tape = build_tape(path, "5351", merge_live=True, live_quote=rt) or {}
    finally:
        lq.taipei_today_str = old_today
        lq.is_live_merge_window = old_win
        tc.is_tw_open_calendar_day = old_cal
    assert str(tape["last"]["date"]).replace("-", "") == "20260910"
    assert tape["foreign"]["net"] == 767
    assert tape["three"]["net"] == 418
    assert tape["inst_pct"] == 4.7
    assert tape["chip_asof_label"] == "9/9"
    assert "後轉平" not in (tape["foreign"].get("phrase") or "")


def test_major_player_rows_skip_trailing_pending(tmp_path):
    from chips import major_player_rows

    path = str(tmp_path / "t.db")
    ensure_core_schema(path)
    _seed_5351(path, today_zero=True)
    rows = major_player_rows(path, "5351", limit=15)
    assert rows
    assert str(rows[0]["date"]) == "20260909"
    assert rows[0]["foreign_net"] == 767
    assert rows[0]["three_net"] == 418
    assert rows[0]["ratio_pct"] == 4.7


def test_chips_header_stamp_has_weekday_and_produced_clock():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from chips import _chips_header_stamp

    s = _chips_header_stamp(
        "20260909",
        generated_at=datetime(2026, 9, 10, 10, 15, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert "9/9（三）" in s
    assert "盤中 10:15" in s
    closed = _chips_header_stamp(
        "20260909",
        generated_at=datetime(2026, 9, 10, 21, 40, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert "13:30收盤" in closed
