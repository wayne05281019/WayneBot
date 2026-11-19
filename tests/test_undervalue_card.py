# -*- coding: utf-8 -*-
"""低估名單 D3 PNG：1290×2796（430×932@3x）、≤4 卡、Playwright HTML。"""
import os
from pathlib import Path

import pytest
from PIL import Image

from undervalue_card import (
    BASE_H,
    BASE_W,
    CARDS_PER_PAGE,
    SAFE_BOTTOM,
    SAFE_TOP,
    render_undervalue_pages,
    render_undervalue_png,
)


def _require_playwright():
    from undervalue_card_html import playwright_available

    if not playwright_available():
        pytest.skip("無 Playwright／已關 WAYNE_UV_HTML")


def _growth_rows():
    return [
        {
            "mark": "star",
            "stock_id": "6442",
            "name": "光聖",
            "close": 1045,
            "pe": 20,
            "pe_fwd": 15,
            "pe_year": 26,
            "pe_next": 21,
            "gross_margin": 59.3,
            "core_ratio_pct": 94,
            "yoy_pct": 83,
            "eps_earned": 34.9,
            "eps_2026": 52,
            "eps_2027": 68,
            "fair_year": 1300,
            "target_next": 1625,
            "ups_fair_pct": 24,
            "ups_tgt_pct": 55,
            "rev_threshold_yi": 20.5,
            "rev_oct_yi": 18,
            "support": 1045,
            "resistance": 1210,
            "chip_note": "外投同買",
            "foreign_5d": ["B", "B", "N", "B", "B"],
            "trust_5d": ["B", "B", "B", "B", "B"],
        },
        {
            "mark": "watch",
            "stock_id": "2383",
            "name": "台光電",
            "close": 3795,
            "pe": 18,
            "fair_year": 4800,
            "target_next": 6120,
            "ups_fair_pct": 26,
            "ups_tgt_pct": 61,
            "support": 4160,
            "resistance": 5200,
            "tech_broken": True,
            "chip_note": "投信買・外資調節",
            "foreign_5d": ["S", "S", "N", "S", "B"],
            "trust_5d": ["B", "B", "B", "N", "B"],
        },
        {
            "mark": "emerging",
            "stock_id": "3595",
            "name": "山太士",
            "close": 580,
            "pe": 25,
            "fair_year": 700,
            "target_next": 900,
            "ups_fair_pct": 20,
            "ups_tgt_pct": 55,
            "chip_note": "興櫃無法人",
        },
    ]


def test_d3_page_canvas_and_paginate(tmp_path):
    _require_playwright()
    base = _growth_rows()
    extra = dict(base[0], stock_id="4971", name="IET-KY", mark="star")
    extra2 = dict(base[0], stock_id="7711", name="永擎", mark="watch")
    rows = base + [extra, extra2]
    paths = render_undervalue_pages(rows, str(tmp_path), as_of="20261117")
    assert len(paths) == 2
    im1 = Image.open(paths[0])
    assert im1.size == (BASE_W, BASE_H)
    assert Path(paths[0]).stat().st_size > 8000
    p = render_undervalue_png(rows, str(tmp_path / "first.png"), as_of="20261117")
    im = Image.open(p)
    assert im.size == (BASE_W, BASE_H)
    assert CARDS_PER_PAGE == 4
    assert SAFE_TOP == 144 and SAFE_BOTTOM == 180


def test_sanitize_drops_blacklist_and_dup_name():
    from undervalue_card import _sanitize_paint_rows

    rows = _sanitize_paint_rows(
        [
            {"stock_id": "3006", "name": "晶豪科", "close": 100, "mark": "watch"},
            {"stock_id": "6265", "name": "方土昶", "close": 40, "mark": "watch"},
            {
                "stock_id": "2383",
                "name": "2383",
                "close": 3795,
                "mark": "watch",
                "fair_year": 4800,
                "target_next": 4800,
                "ups_tgt_pct": 0,
            },
            {"stock_id": "6442", "name": "光聖", "close": 1045, "mark": "star"},
        ]
    )
    sids = {r["stock_id"] for r in rows}
    assert "3006" not in sids and "6265" not in sids
    assert "6442" in sids
    hit = next(r for r in rows if r["stock_id"] == "2383")
    assert hit.get("name") == ""
    assert hit.get("target_next") in (None, "")


def test_d3_header_mark_and_chip_split():
    from undervalue_card import _fmt_eps, _mark_glyph, _split_chip_pills

    g, _c, _e, lab = _mark_glyph("star")
    assert g == "★" and lab == "折價大"
    g2, _, _, lab2 = _mark_glyph("emerging")
    assert g2 == "⚠" and lab2 == "量小"
    assert _split_chip_pills("投信連買・外資調節") == ["投信連買・外資調節"]
    assert _fmt_eps(34.9) is not None


def test_legacy_list_png_without_growth(tmp_path):
    """無成長欄的舊列表仍可出圖（相容測）。"""
    rows = [
        {
            "mark": "star",
            "stock_id": "2330",
            "name": "台積電",
            "close": 980,
            "pe": 22.4,
            "peer_pe_median": 28.1,
            "dist_to_floor_pct": -18.2,
            "flow_shares": 12345,
            "reason": "同鏈 PE 低於中位近兩成",
        }
    ]
    filled = str(tmp_path / "uv_filled.png")
    assert Path(render_undervalue_png(rows, filled, as_of="20261114")).is_file()
    im_f = Image.open(filled)
    assert im_f.size[0] == BASE_W or im_f.size[0] == 1080
