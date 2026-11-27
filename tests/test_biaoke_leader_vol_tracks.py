# -*- coding: utf-8 -*-
"""量規則多軌：狀態機／產業風向（觀察非買訊）。"""
from __future__ import annotations

from scripts.biaoke_leader_vol_tracks import PhaseSnap, classify_phase, industry_vane


def _bar(i: int, *, close: float, low: float, high: float, vol: float) -> dict:
    return {
        "date": f"{20260101 + i}",
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
        "turnover_k": vol * close,
    }


def _base_bars(*, n: int = 250, close: float = 105.0, low: float = 100.0, high: float = 150.0, vol: float = 1000.0):
    return [_bar(i, close=close, low=low, high=high, vol=vol) for i in range(n)]


def test_classify_low_explode_consec():
    bars = _base_bars()
    bars[-2] = _bar(248, close=103.0, low=100.0, high=150.0, vol=8500.0)
    bars[-1] = _bar(249, close=104.0, low=100.5, high=150.0, vol=9000.0)
    phase, flags, m = classify_phase(bars)
    assert phase == "low_explode"
    assert m["consec"] >= 2
    assert "consec_low_explode" in flags or "low_year_grade" in flags


def test_classify_sediment_after_low_yg():
    bars = _base_bars()
    # 低位一年級後量縮
    bars[-5] = _bar(245, close=102.0, low=100.0, high=150.0, vol=9000.0)
    bars[-1] = _bar(249, close=104.0, low=101.0, high=150.0, vol=4000.0)
    phase, flags, _ = classify_phase(bars)
    assert phase == "sediment"
    assert "sediment_ok" in flags


def test_classify_high_explode():
    bars = _base_bars(close=148.0, low=100.0, high=150.0, vol=1000.0)
    # 貼近120高爆一年級
    bars[-1] = _bar(249, close=148.0, low=145.0, high=150.0, vol=9000.0)
    phase, flags, _ = classify_phase(bars)
    assert phase == "high_explode"
    assert "high_year_grade" in flags


def test_industry_vane_needs_majority_or_two():
    def snap(sid: str, phase: str) -> PhaseSnap:
        return PhaseSnap(
            stock_id=sid,
            stock_name=sid,
            industry="光通訊",
            role="vane",
            as_of="20261126",
            close=1.0,
            phase=phase,
            flags=[],
            year_grade_floor=1.0,
            vol_today=1.0,
            vol_year_max=1.0,
            consec_year_grade=0,
            dist_to_low60_pct=1.0,
            dist_to_high120_pct=1.0,
            rs_5_vs_twii_pct=None,
            note_zh="",
        )

    three = [
        snap("6442", "sediment"),
        snap("2345", "quiet"),
        snap("3081", "quiet"),
    ]
    assert industry_vane(three)["vane_on"] is False
    three[1] = snap("2345", "low_explode")
    assert industry_vane(three)["vane_on"] is True
