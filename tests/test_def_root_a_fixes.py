# -*- coding: utf-8 -*-
"""定義根治 A 類：ETF 榜、連買法人日、月線3日、低估同行門檻、美股新鮮度。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


def _flow_db_with_etf(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE daily_quotes ("
            "stock_id TEXT, stock_name TEXT, market TEXT, date TEXT, close REAL, "
            "volume INTEGER, pct_change REAL, foreign_net INTEGER, "
            "trust_net INTEGER, dealer_net INTEGER, turnover_k REAL)"
        )
        conn.execute(
            "CREATE TABLE stock_universe ("
            "stock_id TEXT PRIMARY KEY, name TEXT, market TEXT, "
            "industry TEXT, asset_type TEXT)"
        )
        # 法人有料日：0050 ETF 買超最大 + 兩檔個股
        rows = [
            ("0050", "元大台灣50", "TW", 100.0, 1e6, 1.0, 99999, 0, 0, "ETF", "ETF"),
            ("2317", "鴻海", "TW", 100.0, 1e5, 1.0, 5000, 0, 0, "電子工業", "STOCK"),
            ("2330", "台積電", "TW", 500.0, 2e5, 0.5, 4000, 0, 0, "半導體", "STOCK"),
        ]
        for sid, name, mkt, close, vol, pct, fn, tn, dn, ind, atype in rows:
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, name, mkt, "20261103", close, vol, pct, fn, tn, dn, 1e6),
            )
            conn.execute(
                "INSERT INTO stock_universe VALUES (?,?,?,?,?)",
                (sid, name, mkt, ind, atype),
            )
        # 現貨齊但法人全 0 的新日
        for sid, name, mkt, close, vol, pct, _fn, _tn, _dn, ind, atype in rows:
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, name, mkt, "20261117", close, vol, pct, 0, 0, 0, 1e6),
            )
        # 湊齊最新日樣本（latest_chip 門檻）
        for i in range(900):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"{i:04d}", f"S{i}", "TW", "20261103", 10, 100, 0, 1, 0, 0, 1),
            )
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"{i:04d}", f"S{i}", "TW", "20261117", 10, 100, 0, 0, 0, 0, 1),
            )
        for i in range(700):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"{i+2000:04d}", f"O{i}", "OTC", "20261103", 10, 100, 0, 1, 0, 0, 1),
            )
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"{i+2000:04d}", f"O{i}", "OTC", "20261117", 10, 100, 0, 0, 0, 0, 1),
            )
        conn.commit()
    finally:
        conn.close()


def test_money_flow_top_excludes_etf(tmp_path):
    from money_flow import _top

    db = str(tmp_path / "etf.db")
    _flow_db_with_etf(db)
    conn = sqlite3.connect(db)
    try:
        rows = _top(conn, "20261103", "foreign_net", True, limit=6)
        ids = [str(r["stock_id"]) for r in rows]
        assert "0050" not in ids
        assert "2317" in ids
    finally:
        conn.close()


def test_buy_streak_as_of_uses_chip_day(tmp_path):
    from buy_streak import resolve_official_as_of

    db = str(tmp_path / "streak.db")
    _flow_db_with_etf(db)
    now = datetime(2026, 11, 19, 9, 40, tzinfo=ZoneInfo("Asia/Taipei"))
    as_of = resolve_official_as_of(db, now=now)
    assert as_of == "20261103"


def test_falling_risk_three_closes_below_ma20():
    from taiwan_market import compute_falling_risk

    # 22 根在月線上、最後 3 根明顯跌破月線 → 要命中「3日未站回」
    closes = [100.0] * 22 + [90.0, 89.0, 88.0]
    idx = pd.DataFrame(
        {
            "close": closes,
            "volume": [1e9] * len(closes),
            "pct_change": [0.0] * 22 + [-1.0, -1.0, -1.0],
        }
    )
    fr = compute_falling_risk(idx, breadth_pct=50.0)
    assert "跌破月線且3日未站回" in fr["falling_risk_hits"]


def test_falling_risk_two_closes_below_not_enough():
    from taiwan_market import compute_falling_risk

    closes = [100.0] * 23 + [90.0, 89.0]
    idx = pd.DataFrame(
        {
            "close": closes,
            "volume": [1e9] * len(closes),
            "pct_change": [0.0] * len(closes),
        }
    )
    fr = compute_falling_risk(idx, breadth_pct=50.0)
    assert "跌破月線且3日未站回" not in fr["falling_risk_hits"]


def test_undervalue_peer_min_aligned():
    from undervalue_growth import PEER_PE_FINE_MIN_N
    from undervalue_scan import PEER_MIN_N

    assert PEER_MIN_N == PEER_PE_FINE_MIN_N == 5


def test_stale_us_snap_not_fresh():
    """過舊／fallback 美股快取不准當現況（下跌風險閘與大盤頁同一套）。"""
    from taiwan_market import _us_snap_fresh_for_tw

    stale = {"regime": "risk_off", "as_of": "20260101", "_fallback": True, "vix": 30}
    assert _us_snap_fresh_for_tw(stale, "20261117", None) is False
    # analyze／Regime+ 只在 fresh 且非 press_miss 才設 us_risk_off
    import inspect
    from taiwan_market import analyze_taiwan_market, _regime_plus_raw_history

    src = inspect.getsource(analyze_taiwan_market) + inspect.getsource(_regime_plus_raw_history)
    assert "_resolve_us_for_display" in src
    assert "us_fresh" in src
    assert "_press_miss" in src


def test_regime_plus_history_no_up_ratio_as_breadth():
    """歷史 Regime+ 不准把漲跌比×100 冒充站月線％。"""
    import inspect
    from taiwan_market import _regime_plus_raw_history

    src = inspect.getsource(_regime_plus_raw_history)
    assert "up_ratio * 100" not in src
    assert "_resolve_breadth_for_date" in src
