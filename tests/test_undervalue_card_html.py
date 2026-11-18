# -*- coding: utf-8 -*-
"""低估 D3 HTML／Playwright：430×932 @3x → 1290×2796；真資料映射。"""
from pathlib import Path

import pytest
from PIL import Image

from undervalue_card import BASE_H, BASE_W, render_undervalue_pages
from undervalue_card_html import (
    _pe_scale_labels,
    _pill_from_5d_flags,
    _q4_progress_from_rev_yyyymm,
    calc_forward_12m_eps,
    detect_market_regime,
    pick_row_to_screener_stock,
    playwright_available,
    resolve_regime,
)


def test_calc_forward_12m_eps_weights():
    from datetime import date

    # 7 月：剩 6 個月 → 今年權重 0.5
    v = calc_forward_12m_eps(52.0, 68.0, date(2026, 7, 1))
    assert abs(v - 60.0) < 0.01


def test_detect_regime_normal():
    r = detect_market_regime(31.2, 0, True)
    assert r["class"] == "regime-normal"
    assert "31.20" in r["fx_text"]


def test_detect_regime_fx_stress():
    r = detect_market_regime(33.05, 4, False)
    assert r["class"] == "regime-fx"
    assert "急貶" in r["text"]
    assert "33.05" in r["fx_text"]


def test_resolve_regime_no_fake_fx():
    r = resolve_regime(usd_twd=None, foreign_sell_days=0, market_above_ma20=True)
    assert "31.50" not in r["fx_text"]
    assert "—" in r["fx_text"]


def test_q4_from_published_month_not_calendar():
    assert _q4_progress_from_rev_yyyymm("202610") == "Q4: 10月✓・11·12待補"
    assert _q4_progress_from_rev_yyyymm("202611") == "Q4: 10月✓・11月✓・12待補"
    assert "11月✓" not in _q4_progress_from_rev_yyyymm("202610")


def test_pe_scale_dynamic_per_stock():
    # 永擎：滾動 ~10.5、合理帶 14–18 → 刻度約 10x–20x 帶，圓點不卡死 15–25
    lo, mid, hi, pct = _pe_scale_labels(10.5, 14.0, 18.0)
    assert lo.endswith("x") and hi.endswith("x")
    assert int(lo[:-1]) <= 12
    assert int(hi[:-1]) >= 18
    assert 8 <= pct <= 40
    # 山太士：~33、合理帶 22–28 → 上沿須蓋到實際倍數
    lo2, mid2, hi2, pct2 = _pe_scale_labels(33.3, 22.0, 28.0)
    assert int(lo2[:-1]) <= 22
    assert int(hi2[:-1]) >= 33
    assert pct2 >= 70


def test_pill_matches_chip_squares():
    ft, pill = _pill_from_5d_flags(
        ["S", "B", "S", "S", "S"], ["B", "B", "B", "B", "B"], emerging=False
    )
    assert ft == "sell"
    assert "投信護盤" in pill
    ft2, pill2 = _pill_from_5d_flags(
        ["S", "S", "S", "S", "S"], ["B", "B", "B", "B", "N"], emerging=False
    )
    # 投信第 5 格灰 → 不可寫「投信連買5日」
    assert "投信連買5日" not in pill2
    assert "投信連買4日" not in pill2  # 連買從右算，右端 N 則 streak=0


def test_support_break_downgrades_star():
    s = pick_row_to_screener_stock(
        {
            "mark": "star",
            "stock_id": "6442",
            "name": "光聖",
            "close": 969,
            "support": 1045,
            "resistance": 1210,
            "eps_earned": 34.9,
            "eps_2026": 52,
            "eps_2027": 68,
            "pe_year": 28,
            "pe_next": 22,
            "rev_yyyymm": "202610",
            "rev_oct_yi": 18.4,
            "foreign_5d": ["B", "B", "B", "B", "B"],
            "trust_5d": ["N", "B", "B", "B", "B"],
        },
        as_of="20261118",
    )
    assert s["status"] == "wait"
    assert s["icon"] == "☆"
    assert "11月✓" not in s["q4_progress"]
    assert "10月✓" in s["q4_progress"]


def test_emerging_placement_price_in_note():
    s = pick_row_to_screener_stock(
        {
            "mark": "emerging",
            "stock_id": "3595",
            "name": "山太士",
            "close": 580,
            "placement_price": 400,
            "tech_status": "60日均量過小",
            "rev_yyyymm": "202610",
            "rev_oct_yi": 0.95,
            "eps_earned": 5.99,
            "eps_2026": 9.5,
            "eps_2027": 19.0,
            "pe_year": 28,
            "pe_next": 22,
        },
        as_of="20261118",
    )
    assert "400" in s["emerging_note"]
    assert "60日均量過小" in s["emerging_note"]
    assert "0.95" in s["rev_now"] or "0.9" in s["rev_now"]


def test_html_d3_page_canvas(tmp_path):
    if not playwright_available():
        pytest.skip("無 Playwright")
    rows = [
        {
            "mark": "star",
            "stock_id": "6442",
            "name": "光聖",
            "close": 1045,
            "pe": 20.1,
            "pe_fwd": 15.2,
            "pe_year": 28,
            "pe_next": 22,
            "gross_margin": 59.3,
            "yoy_pct": 83,
            "eps_earned": 34.9,
            "eps_2026": 52,
            "eps_2027": 68,
            "fair_year": 1350,
            "target_next": 1625,
            "ups_fair_pct": 29,
            "ups_tgt_pct": 55,
            "rev_threshold_yi": 20.5,
            "rev_oct_yi": 18.4,
            "rev_yyyymm": "202610",
            "support": 1045,
            "resistance": 1210,
            "chip_note": "外投同買",
            "foreign_5d": ["B", "B", "B", "B", "B"],
            "trust_5d": ["N", "B", "B", "B", "B"],
        }
    ]
    paths = render_undervalue_pages(rows, str(tmp_path), as_of="20261117", prefix="html")
    assert len(paths) == 1
    im = Image.open(paths[0])
    assert im.size == (BASE_W, BASE_H) == (1290, 2796)
    assert Path(paths[0]).stat().st_size > 20000


def test_pick_row_mapper_fills_template_keys():
    s = pick_row_to_screener_stock(
        {
            "mark": "star",
            "stock_id": "6442",
            "name": "光聖",
            "close": 1045,
            "eps_earned": 34.9,
            "eps_2026": 52,
            "eps_2027": 68,
            "pe_year": 28,
            "pe_next": 22,
            "fair_year": 1350,
            "target_next": 1625,
            "gross_margin": 59.3,
            "rev_threshold_yi": 20.5,
            "rev_oct_yi": 18.4,
            "rev_yyyymm": "202610",
            "support": 1045,
            "resistance": 1210,
            "chip_note": "外投同買",
            "foreign_5d": ["B", "S", "N", "B", "B"],
            "trust_5d": ["B", "B", "B", "B", "B"],
        },
        as_of="20261117",
    )
    for k in (
        "icon",
        "status_label",
        "ticker",
        "price",
        "eps_ytd",
        "pe_fwd12m",
        "pe_min",
        "target_norm",
        "foreign_5d",
        "support_text",
    ):
        assert k in s
    assert s["status"] == "buy"
    assert len(s["foreign_5d"]) == 5
    assert s["pe_min"] != "15x" or s["pe_max"] != "25x" or float(s["pe_fwd12m"]) == 20
    assert "11月✓" not in s["q4_progress"]
