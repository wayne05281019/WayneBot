# -*- coding: utf-8 -*-
"""量價落底觀察掃（一年級巨量，非買訊）單元測。"""
from __future__ import annotations

from scripts.biaoke_bottom_vol_observe_screen import score_bottom_vol, year_grade_floor


def _bar(i: int, *, close: float, low: float, high: float | None = None, vol: float) -> dict:
    h = high if high is not None else close + 1
    return {
        "date": f"{20260101 + i}",
        "open": close,
        "high": h,
        "low": low,
        "close": close,
        "volume": vol,
        "turnover_k": vol * close,
    }


def test_year_grade_floor_uses_year_max_not_short_median():
    vols = [1000.0] * 200 + [9000.0]
    floor, ymax = year_grade_floor(vols)
    assert ymax == 9000.0
    assert floor >= 9000.0 * 0.70 - 1e-6


def test_score_rejects_event_vol_not_year_grade():
    bars = []
    for i in range(200):
        v = 50000.0 if i == 20 else 2000.0
        bars.append(_bar(i, close=100.0, low=95.0, high=130.0, vol=v))
    for i in range(200, 250):
        bars.append(_bar(i, close=98.0, low=95.0, high=120.0, vol=6500.0))
    assert score_bottom_vol(bars) is None


def test_score_hits_year_grade_consec_near_low():
    bars = []
    for i in range(200):
        bars.append(_bar(i, close=120.0, low=100.0, high=150.0, vol=1000.0))
    for i in range(200, 248):
        bars.append(_bar(i, close=105.0, low=100.0, high=150.0, vol=1100.0))
    bars.append(_bar(248, close=103.0, low=100.0, high=150.0, vol=8500.0))
    bars.append(_bar(249, close=104.0, low=100.5, high=150.0, vol=9000.0))
    hit = score_bottom_vol(bars)
    assert hit is not None
    assert hit.style in ("year_grade_consec", "both")
    assert hit.consec_year_grade >= 2
    assert hit.vol_ratio_year >= 0.70
