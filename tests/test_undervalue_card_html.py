# -*- coding: utf-8 -*-
"""低估 D3 HTML／Playwright 路徑（有 chromium 才測）。"""
import os
from pathlib import Path

import pytest
from PIL import Image

from undervalue_card import BASE_H, BASE_W, render_undervalue_pages


def test_html_d3_page_canvas(tmp_path):
    prev = os.environ.get("WAYNE_UV_HTML")
    os.environ["WAYNE_UV_HTML"] = "1"
    try:
        from undervalue_card_html import playwright_available

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
            }
        ]
        try:
            paths = render_undervalue_pages(
                rows, str(tmp_path), as_of="20261117", prefix="html"
            )
        except Exception as exc:
            pytest.skip(f"chromium 不可用：{exc}")
        assert len(paths) == 1
        im = Image.open(paths[0])
        assert im.size == (BASE_W, BASE_H)
        assert Path(paths[0]).stat().st_size > 20000
    finally:
        if prev is None:
            os.environ.pop("WAYNE_UV_HTML", None)
        else:
            os.environ["WAYNE_UV_HTML"] = prev
