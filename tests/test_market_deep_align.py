# -*- coding: utf-8 -*-
from unittest.mock import patch

import pandas as pd

from decision_card_signals import calc_volume_rank, compute_card_temperature
from taiwan_market import (
    apply_market_weights,
    ensure_index_daily_table,
    sync_index_daily,
    _regime_from_closes,
)


def test_calc_volume_rank_prefers_turnover_k():
    vols = [100, 200, 150, 180, 120]
    turns = [1000, 2000, 3000, 1800, 6000]
    assert calc_volume_rank(vols, 5, turnovers=turns) == 1


def test_hot_stock_temperature_band():
    """南亞型熱股：貼 20 日高 + 大 space60 時溫度約 70°C。"""
    t = compute_card_temperature(
        close=184.0,
        high20=185.0,
        low20=165.0,
        bias_monthly=2.5,
        high60=190.0,
        low60=140.0,
    )
    assert 68.0 <= t <= 73.5


def test_apply_market_weights_bear_caps_select():
    items = [{"stock_id": f"{i:04d}", "q60r": float(i)} for i in range(10, 0, -1)]
    out = apply_market_weights(
        {"select_01": items},
        {"ok": True, "regime": "bear", "confidence": 40},
    )
    assert len(out["select_01"]) == 5


@patch("taiwan_market._fetch_index_daily")
@patch("taiwan_market._fetch_twse_index_close", return_value=None)
def test_sync_index_daily_writes_table(mock_twse, mock_fetch, tmp_path):
    import sqlite3

    db = str(tmp_path / "t.db")
    mock_fetch.return_value = pd.DataFrame(
        {
            "date": ["20260829", "20260830", "20260901"],
            "close": [22000.0, 22100.0, 22200.0],
            "volume": [1e9, 1.1e9, 1.2e9],
            "pct_change": [0.1, 0.45, 0.45],
        }
    )
    ensure_index_daily_table(db)
    r = sync_index_daily(db)
    assert r["ok"] and r["rows"] == 3
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0]
    conn.close()
    assert n == 3


def test_regime_from_closes_bull():
    closes = pd.Series([float(20000 + i * 30) for i in range(80)])
    snap = _regime_from_closes(closes, breadth_pct=55, sector_flow=1000)
    assert snap["regime"] in ("bull", "neutral")
