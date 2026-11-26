# -*- coding: utf-8 -*-
"""最近重點標的：五波主閘＋一年前巨量輔證。"""
from __future__ import annotations

from scripts.focus_targets_screen import (
    count_bottom_near_year_ago,
    score_hit,
    year_ago_peak_vol,
)


def test_year_ago_peak_picks_dec_window():
    bars = []
    # 遠古小量
    for i in range(10):
        bars.append({"date": f"202505{i+1:02d}", "volume": 100.0})
    # 約一年前巨量
    bars.append({"date": "20251215", "volume": 9000.0})
    bars.append({"date": "20251220", "volume": 5000.0})
    # 近窗
    for i in range(5):
        bars.append({"date": f"2026112{i}", "volume": 2000.0 + i})
    v, d = year_ago_peak_vol(bars, "20261126")
    assert d == "20251215"
    assert abs(v - 9000.0) < 1e-9


def test_score_requires_five_and_positive_room():
    assert score_hit(room=20.0, bottom_near=2, ok_five=True, wave_bars=30) > 0
    assert score_hit(room=0.0, bottom_near=2, ok_five=True) < 0
    assert score_hit(room=20.0, bottom_near=2, ok_five=False) < 0


def test_score_prefers_teach_face_room_not_extreme_deep():
    # 台光電／光聖臉 ≈25%；115% 深空不該贏
    mid = score_hit(room=24.7, bottom_near=3, ok_five=True, wave_bars=30)
    deep = score_hit(room=115.0, bottom_near=0, ok_five=True, wave_bars=30)
    assert mid > deep
    face = score_hit(room=24.0, bottom_near=0, ok_five=True, wave_bars=30)
    wide = score_hit(room=45.0, bottom_near=0, ok_five=True, wave_bars=30)
    assert face > wide


def test_bottom_near_counts_against_ref():
    bars = [{"date": f"202611{10+i:02d}", "volume": v} for i, v in enumerate([100, 8000, 8100, 200])]
    n = count_bottom_near_year_ago(bars, ref_vol=10000.0, new_start_i=1)
    assert n >= 2


def test_taught_ai_sids_include_heat_abf_passive():
    from scripts.focus_targets_screen import _taught_ai_sids

    m = _taught_ai_sids()
    # 使用者點名：健策／奇鋐／國巨／南電都要在母體強制列
    for sid in ("3653", "3017", "2327", "8046"):
        assert sid in m, sid
