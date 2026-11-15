# -*- coding: utf-8 -*-
"""A4：極端 YoY 不准線性外推；g 夾 −5%～+10%。"""
from undervalue_scan import (
    EXTREME_YOY_ABS_PCT,
    clamp_mom_g,
    estimate_year_revenue,
    is_extreme_yoy_pct,
    project_remaining_month_revenues,
)


def test_clamp_mom_g_bounds():
    g, meta = clamp_mom_g([0.20, 0.15, 0.12])  # 遠高於 +10%
    assert abs(g - 0.10) < 1e-12
    assert meta["clamped"] is True
    g2, meta2 = clamp_mom_g([-0.30, -0.20, -0.25])
    assert abs(g2 - (-0.05)) < 1e-12
    assert meta2["clamped"] is True
    g3, _ = clamp_mom_g([3.0, 4.0, 2.0])  # 百分點 → /100 → 0.03
    assert abs(g3 - 0.03) < 1e-9


def test_extreme_yoy_not_used_as_slope():
    assert is_extreme_yoy_pct(EXTREME_YOY_ABS_PCT) is True
    assert is_extreme_yoy_pct(12.0) is False
    # YoY +300% 也不准當斜率；遞推只用夾限 g
    g, _ = clamp_mom_g([0.50, 0.40, 0.60])  # → 夾到 +10%
    out = project_remaining_month_revenues(100.0, g, 3, yoy_pct=300.0)
    assert out["extreme_yoy"] is True
    assert abs(out["g_used"] - 0.10) < 1e-12
    # 每步 ×1.05（g×0.5），不是 ×4（YoY）
    assert abs(out["months"][0] - 105.0) < 1e-9
    assert "極端YoY" in out["note"]


def test_estimate_year_revenue_uses_clamp_not_yoy():
    # 已公告到 9 月；剩餘 3 月；近月 MoM 誇張＋YoY 極端
    est = estimate_year_revenue(
        ytd_rev=900.0,
        last_month_rev=100.0,
        moms=[0.40, 0.50, 0.60],
        m_last=9,
        yoy_pct=250.0,
    )
    assert est["ok"] is True
    assert est["label"] == "推估"
    assert abs(est["g"] - 0.10) < 1e-12
    # 900 + 105 + 110.25 + 115.7625
    assert abs(est["est_year_rev"] - (900.0 + 105.0 + 110.25 + 115.7625)) < 1e-6
    assert est["proj"]["extreme_yoy"] is True


def test_full_year_announced_not_labeled_estimate():
    est = estimate_year_revenue(
        ytd_rev=1200.0,
        last_month_rev=100.0,
        moms=[0.02],
        m_last=12,
    )
    assert est["ok"] is True
    assert est["r_m"] == 0
    assert est["label"] == "已公告"
    assert abs(est["est_year_rev"] - 1200.0) < 1e-9
