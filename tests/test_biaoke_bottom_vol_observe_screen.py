# -*- coding: utf-8 -*-
"""量價落底觀察掃（非買訊）單元測。"""
from __future__ import annotations

from scripts.biaoke_bottom_vol_observe_screen import score_bottom_vol


def _bar(i: int, *, close: float, low: float, vol: float) -> dict:
    # synthetic monotonic YYYYMMDD-ish keys（只給排序用）
    return {
        "date": f"{20260101 + i}",
        "open": close,
        "high": close + 1,
        "low": low,
        "close": close,
        "volume": vol,
        "turnover_k": vol * close,
    }


def test_score_rejects_far_from_60_low():
    bars = [_bar(i, close=120.0, low=100.0, vol=1000.0) for i in range(90)]
    bars[-1] = _bar(89, close=150.0, low=149.0, vol=5000.0)  # far above 60-low
    assert score_bottom_vol(bars) is None


def test_score_hits_giant_consec_near_low():
    bars = []
    for i in range(90):
        bars.append(_bar(i, close=100.0 + (i % 5), low=95.0, vol=1000.0))
    # near 60-low + 2 consecutive huge bars
    bars[-2] = _bar(88, close=97.0, low=95.0, vol=8000.0)
    bars[-1] = _bar(89, close=98.0, low=95.5, vol=9000.0)
    hit = score_bottom_vol(bars)
    assert hit is not None
    assert hit.style in ("giant_consec", "both")
    assert hit.consec_huge >= 2
    assert hit.dist_to_low_pct <= 18.0
