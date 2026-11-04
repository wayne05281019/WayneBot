# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path

from scripts.decade_lab_outer_backfill import OUTER_SERIES, STILL_MISSING, ensure_index, upsert_bars


def test_outer_series_covers_oil_fx_vix_us_leaders():
    syms = {s for s, _, _ in OUTER_SERIES}
    for need in (
        "TWII",
        "IXIC",
        "SOX",
        "VIX",
        "BRENT",
        "DXY",
        "USDTWD",
        "DJI",
        "SPX",
        "TSM",
        "NVDA",
        "NQ_F",
    ):
        assert need in syms
    assert any("active_etf" in x for x in STILL_MISSING)
    assert any("fear_greed" in x for x in STILL_MISSING)


def test_upsert_bars_writes_index_daily(tmp_path):
    db = tmp_path / "m.db"
    conn = sqlite3.connect(str(db))
    ensure_index(conn)
    n = upsert_bars(
        conn,
        "VIX",
        [
            {
                "date": "20260102",
                "open": 14.0,
                "high": 15.0,
                "low": 13.5,
                "close": 14.5,
                "volume": 0,
                "pct_change": 1.2,
            }
        ],
        stamp="2026-01-02T08:00:00",
    )
    conn.commit()
    assert n == 1
    row = conn.execute(
        "SELECT close, regime FROM index_daily WHERE symbol='VIX' AND date='20260102'"
    ).fetchone()
    conn.close()
    assert row[0] == 14.5
    assert row[1] == "yahoo_outer"
