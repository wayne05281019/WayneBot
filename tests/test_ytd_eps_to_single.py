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


def test_gap_q1_q3_no_cross_season_fake_single():
    """有 Q1＋前三季、缺上半年 → Q3 不准用前三季−Q1 當假單季；Q4 仍可對 Q3 差分。"""
    rows = [
        {"year": 2026, "season": 1, "eps": 1.27, "revenue": 131082.0},
        {"year": 2026, "season": 3, "eps": 5.99, "revenue": 500000.0},
        {"year": 2026, "season": 4, "eps": 8.00, "revenue": 700000.0},
    ]
    m = expand_ytd_income_eps_to_single(rows)
    assert abs(m[(2026, 1)] - 1.27) < 1e-9
    assert (2026, 3) not in m  # 缺 Q2，不准 5.99−1.27
    assert abs(m[(2026, 4)] - (8.00 - 5.99)) < 1e-9


def test_recent_eps_sum_uses_ytd_expand(tmp_path):
    """比價 _recent_eps_sum 必須吃還原後單季，不准把 H1 累計當單季加總。"""
    import sqlite3

    from industry_brief import _recent_eps_sum
    from wayne_db import ensure_core_schema

    db = str(tmp_path / "eps_sum.db")
    ensure_core_schema(db)
    try:
        from fundamentals import ensure_fundamentals_tables

        ensure_fundamentals_tables(db)
    except Exception:
        pass
    conn = sqlite3.connect(db)
    for season, eps, rev in (
        (1, 1.27, 131082.0),
        (2, 3.02, 332692.0),
        (3, 5.99, 500000.0),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO quarterly_income"
            "(stock_id,year,season,stock_name,market,revenue,gross_profit,"
            "gross_margin_pct,operating_income,net_income,eps) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("3595", 2026, season, "山太士", "TW", rev, 0, 0, 0, 0, eps),
        )
    conn.commit()
    rec = _recent_eps_sum(conn, "3595", max_n=2)
    conn.close()
    # 近兩季真實單季＝2.97＋1.75＝4.72，不是 5.99＋3.02
    assert rec["eps_n"] == 2
    assert abs(float(rec["eps_sum"]) - 4.72) < 1e-9
    assert rec["eps_seasons"] == ["2026Q3", "2026Q2"]
