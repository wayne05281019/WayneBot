# -*- coding: utf-8 -*-
from unittest.mock import patch

import pandas as pd

from decision_card_signals import calc_volume_rank
from taiwan_market import analyze_taiwan_market, apply_market_weights, market_screening_note


def test_calc_volume_rank_turnover_changes_order():
    vols = [100, 200, 150, 180, 120]
    closes = [10, 10, 10, 10, 50]
    assert calc_volume_rank(vols, 5) == 4
    assert calc_volume_rank(vols, 5, closes=closes) == 1


def test_apply_market_filter_trims_bear_lists():
    base = {"day_trade": [{"stock_id": f"{i:04d}"} for i in range(10)], "overnight": [{"stock_id": "x"}]}
    out = apply_market_weights(base, {"ok": True, "regime": "bear", "confidence": 40})
    assert len(out["day_trade"]) == 4
    assert len(out["overnight"]) == 1


def test_market_screening_note_bull():
    note = market_screening_note({"ok": True, "regime": "bull", "confidence": 72})
    assert "多頭" in note


@patch("taiwan_market._fetch_index_daily")
def test_analyze_taiwan_market_regime(mock_fetch, tmp_path):
    import sqlite3

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT, is_active INT)"
    )
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, close REAL, volume REAL)"
    )
    conn.execute("INSERT INTO stock_universe VALUES ('2330', 1)")
    for i, c in enumerate([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120]):
        conn.execute(
            "INSERT INTO daily_quotes VALUES ('2330', ?, ?, 1000)",
            (f"202608{i+1:02d}", float(c)),
        )
    conn.commit()
    conn.close()
    mock_fetch.return_value = pd.DataFrame(
        {
            "date": [f"202608{i:02d}" for i in range(1, 25)],
            "close": [float(22000 + i * 50) for i in range(24)],
            "volume": [1e9] * 24,
        }
    )
    snap = analyze_taiwan_market(str(db), "20260824")
    assert snap.get("ok")
    assert snap.get("regime") in ("bull", "neutral", "bear")
    assert snap.get("confidence", 0) > 0
