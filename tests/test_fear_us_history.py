# -*- coding: utf-8 -*-
"""美股／外圍歷史：本庫優先、對映邏輯；不靠外網單測。"""
from __future__ import annotations

from fear_us_history import map_us_session_to_tw_day, outer_present


def test_map_us_session_strictly_before_tw_day():
    by = {
        "20260901": {"ixic_pct": -1.0, "vix": 20.0},
        "20260902": {"ixic_pct": -2.0, "vix": 22.0},
        "20260903": {"ixic_pct": 0.5, "vix": 15.0},
    }
    sess, snap = map_us_session_to_tw_day("20260903", by)
    assert sess == "20260902"
    assert snap["ixic_pct"] == -2.0
    sess2, snap2 = map_us_session_to_tw_day("20260901", by)
    assert sess2 == "" and snap2 == {}


def test_outer_present():
    assert not outer_present({})
    assert outer_present({"usdtwd_pct": 0.2})
    assert not outer_present({"usdtwd_pct": None})
