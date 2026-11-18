# -*- coding: utf-8 -*-
"""低估 D3 HTML／Playwright：430×932 @3x → 1290×2796。"""
from pathlib import Path

import pytest
from PIL import Image

from undervalue_card import BASE_H, BASE_W, render_undervalue_pages
from undervalue_card_html import (
    calc_forward_12m_eps,
    detect_market_regime,
    pick_row_to_screener_stock,
    playwright_available,
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
