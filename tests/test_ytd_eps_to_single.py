# -*- coding: utf-8 -*-
"""綜合損益累計 EPS → 真實單季（山太士範本）。"""
from fundamentals import attach_quarter_box_eps, expand_ytd_income_eps_to_single


def test_shan_taishi_ytd_eps_diff_to_single():
    """Q1=1.27、H1累計=3.02、前三季累計=5.99 → 單季 1.27／1.75／2.97。"""
    rows = [
        {"year": 2026, "season": 1, "eps": 1.27, "revenue": 131082.0},
        {"year": 2026, "season": 2, "eps": 3.02, "revenue": 332692.0},
        {"year": 2026, "season": 3, "eps": 5.99, "revenue": 500000.0},
    ]
    m = expand_ytd_income_eps_to_single(rows)
    assert abs(m[(2026, 1)] - 1.27) < 1e-9
    assert abs(m[(2026, 2)] - 1.75) < 1e-9
    assert abs(m[(2026, 3)] - 2.97) < 1e-9
    filled = attach_quarter_box_eps(
        [{"year": 2026, "season": 1}, {"year": 2026, "season": 2}, {"year": 2026, "season": 3}],
        rows,
    )
    assert [b["eps_lab"] for b in filled] == ["1.27", "1.75", "2.97"]
    assert filled[1]["eps_better"] is True  # 1.75 > 1.27
    assert filled[2]["eps_better"] is True  # 2.97 > 1.75


def test_equal_revenue_treated_as_already_single():
    """興櫃種子：同營收＝已是單季，不准再相減。"""
    rows = [
        {"year": 2026, "season": 1, "eps": 0.37, "revenue": 100000.0},
        {"year": 2026, "season": 2, "eps": 0.95, "revenue": 100000.0},
    ]
    m = expand_ytd_income_eps_to_single(rows)
    assert abs(m[(2026, 1)] - 0.37) < 1e-9
    assert abs(m[(2026, 2)] - 0.95) < 1e-9


def test_missing_q1_ytd_q2_no_fake_single():
    """只有上半年累計、缺 Q1 → Q2 不上假單季。"""
    rows = [{"year": 2026, "season": 2, "eps": 42.46, "revenue": 80_000_000.0}]
    m = expand_ytd_income_eps_to_single(rows)
    assert (2026, 2) not in m
    filled = attach_quarter_box_eps([{"year": 2026, "season": 2}], rows)
    assert filled[0]["eps"] is None and filled[0]["eps_lab"] == ""
