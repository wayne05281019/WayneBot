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


def test_vol_room_bands_and_tier_ladder():
    from scripts.focus_targets_screen import (
        assign_tier,
        room_band_of,
        vol_tier_of,
    )

    assert vol_tier_of(3) == "ge2"
    assert vol_tier_of(1) == "eq1"
    assert vol_tier_of(0) == "none"
    assert room_band_of(24.7) == "near25"
    assert room_band_of(9.0) == "tight"
    assert room_band_of(40.0) == "wide"
    assert room_band_of(60.0) == "deep"
    assert room_band_of(-3.0) == "past"
    # A：雙爆＋EPS＋AI＋近／緊空間
    assert (
        assign_tier(
            vol_tier="ge2", eps_profit=True, taught_ai=True, room_band="near25"
        )
        == "A"
    )
    assert (
        assign_tier(
            vol_tier="ge2", eps_profit=True, taught_ai=True, room_band="tight"
        )
        == "A"
    )
    # B：單爆或 AI＋EPS＋非深
    assert (
        assign_tier(
            vol_tier="eq1", eps_profit=True, taught_ai=False, room_band="wide"
        )
        == "B"
    )
    assert (
        assign_tier(
            vol_tier="none", eps_profit=True, taught_ai=True, room_band="near25"
        )
        == "B"
    )
    # C：可畫＋EPS 或 AI（深空仍可 C）
    assert (
        assign_tier(
            vol_tier="none", eps_profit=True, taught_ai=False, room_band="deep"
        )
        == "C"
    )
    assert (
        assign_tier(
            vol_tier="none", eps_profit=False, taught_ai=True, room_band="deep"
        )
        == "C"
    )
    # D：僅可畫
    assert (
        assign_tier(
            vol_tier="none", eps_profit=False, taught_ai=False, room_band="near25"
        )
        == "D"
    )


def test_chip_label_dominant_and_retail():
    from scripts.focus_targets_screen import classify_chip_label

    lab, ok, _ = classify_chip_label(
        5000, 200, -100, vol_mean=3000, vol_median_prior=2000
    )
    assert lab == "外資" and ok
    lab, ok, _ = classify_chip_label(
        100, 4000, 50, vol_mean=3000, vol_median_prior=2000
    )
    assert lab == "投信" and ok
    lab, ok, _ = classify_chip_label(
        10, -20, 3500, vol_mean=3000, vol_median_prior=2000
    )
    assert lab == "自營" and ok
    # 近乎平＋量熱 → 偏散戶
    lab, ok, _ = classify_chip_label(
        5, -3, 2, vol_mean=8000, vol_median_prior=2000
    )
    assert lab == "偏散戶" and not ok
    # 三者全賣 → 不准標外資愛
    lab, ok, _ = classify_chip_label(
        -36075, -3805, -780, vol_mean=20000, vol_median_prior=15000
    )
    assert lab == "偏散戶" and not ok


def test_character_bucket_eps_and_ai():
    from scripts.focus_targets_screen import assign_character_bucket

    assert (
        assign_character_bucket(
            {
                "eps_last": 10.0,
                "eps_profit": True,
                "taught_ai": True,
                "chip_constructive": False,
                "chip_label": "外資",
            }
        )
        == "最值得介入"
    )
    assert (
        assign_character_bucket(
            {
                "eps_last": 5.0,
                "eps_profit": True,
                "taught_ai": False,
                "chip_constructive": True,
                "chip_label": "投信",
            }
        )
        == "最值得介入"
    )
    assert (
        assign_character_bucket(
            {
                "eps_last": None,
                "eps_profit": False,
                "taught_ai": True,
                "chip_constructive": True,
                "chip_label": "外資",
            }
        )
        == "短衝搶一波"
    )
    assert (
        assign_character_bucket(
            {
                "eps_last": 1.0,
                "eps_profit": True,
                "taught_ai": False,
                "chip_constructive": False,
                "chip_label": "偏散戶",
            }
        )
        == "短衝搶一波"
    )
