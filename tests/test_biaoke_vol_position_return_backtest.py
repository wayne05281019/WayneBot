# -*- coding: utf-8 -*-
from scripts.biaoke_vol_position_return_backtest import position_zone, summarize


def test_position_zone_low_high_mid():
    assert position_zone(5.0, 40.0) == "low"
    assert position_zone(30.0, 5.0) == "high"
    assert position_zone(20.0, 20.0) == "mid"


def test_summarize_empty_and_basic():
    assert summarize([])["n"] == 0
    rows = [
        {"fwd_5": 1.0, "fwd_10": 2.0, "fwd_20": 3.0, "rs_5": 0.5, "rs_10": 1.0, "rs_20": 1.5, "mdd_20": -4.0},
        {"fwd_5": -1.0, "fwd_10": 4.0, "fwd_20": 5.0, "rs_5": -0.5, "rs_10": 2.0, "rs_20": 2.5, "mdd_20": -6.0},
    ]
    s = summarize(rows)
    assert s["n"] == 2
    assert s["fwd_10_med"] == 3.0
