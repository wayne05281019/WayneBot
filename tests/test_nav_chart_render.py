# -*- coding: utf-8 -*-
"""導航圖產出回歸（圖例 ncol 等）。"""
import os
import tempfile
import unittest

import pandas as pd
import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


class NavChartRenderTests(unittest.TestCase):
    def test_generate_chart_writes_png(self):
        from wayne_navigator import generate_chart

        db = get_db_path()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "2421.png")
            path = generate_chart("2421", "", db, out)
            self.assertTrue(path and os.path.isfile(path))
            self.assertGreater(os.path.getsize(path), 8000)

    def test_nav_chart_hi_dpi_and_marker_arrows(self):
        import inspect

        from PIL import Image

        from wayne_navigator import NAV_CHART_DPI, _paint_nav_on_axes, generate_chart

        self.assertGreaterEqual(NAV_CHART_DPI, 320)
        src = inspect.getsource(_paint_nav_on_axes)
        self.assertIn("arrow_hw = 0.72", src)
        self.assertNotIn("arrow_hw = 1.15", src)
        self.assertNotIn("arrow_hw = 0.48", src)
        self.assertIn("dn_pick", src)
        self.assertNotIn("dn_stack.append", src)
        self.assertIn("_paint_nav_volume_zone", src)
        self.assertIn("vol_zone_note", src)
        zone_src = inspect.getsource(__import__("wayne_navigator")._paint_nav_volume_zone)
        self.assertIn("大量區", zone_src)
        db = get_db_path()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nav.png")
            path = generate_chart("2330", "", db, out)
            self.assertTrue(path)
            with Image.open(path) as im:
                self.assertGreaterEqual(im.size[0], 2400)

    def test_nav_volume_zone_picks_max_volume_bar(self):
        from wayne_navigator import _nav_volume_zone

        rows = []
        for i in range(12):
            rows.append(
                {
                    "date": f"202609{i+1:02d}",
                    "open": 100 + i,
                    "high": 105 + i,
                    "low": 95 + i,
                    "close": 102 + i,
                    "volume": 1000 + i * 10,
                    "is_halt": False,
                }
            )
        rows[4]["volume"] = 90000
        rows[4]["high"] = 1530
        rows[4]["low"] = 1365
        work = pd.DataFrame(rows)
        zone = _nav_volume_zone(work, lookback=40)
        self.assertIsNotNone(zone)
        self.assertEqual(zone["i"], 4)
        self.assertEqual(zone["high"], 1530)
        self.assertEqual(zone["low"], 1365)

    def test_nav_volume_zone_skips_biaoke_overlay_bars(self):
        from wayne_navigator import _nav_volume_zone

        work = pd.DataFrame(
            [
                {
                    "date": "20260901",
                    "open": 10,
                    "high": 12,
                    "low": 9,
                    "close": 11,
                    "volume": 50000,
                    "is_halt": False,
                    "source": "biaoke_stock_day",
                },
                {
                    "date": "20260902",
                    "open": 11,
                    "high": 13,
                    "low": 10,
                    "close": 12,
                    "volume": 8000,
                    "is_halt": False,
                    "source": "tpex",
                },
            ]
        )
        zone = _nav_volume_zone(work, lookback=40)
        self.assertEqual(zone["i"], 1)
        self.assertEqual(zone["volume"], 8000)

    def test_nav_arrows_are_short_markers_without_outline(self):
        import inspect

        from wayne_navigator import _nav_arrow, _nav_legend_key, _sig_arrow

        for fn in (_nav_arrow, _sig_arrow, _nav_legend_key):
            src = inspect.getsource(fn)
            self.assertNotIn("withStroke", src, fn.__name__)
            self.assertNotIn("#000000", src, fn.__name__)
            self.assertNotIn("000000", src, fn.__name__)
        src = inspect.getsource(_nav_arrow)
        self.assertIn("head_h", src)
        self.assertIn("shaft_h", src)
        self.assertNotIn("_fill_triangle_gradient", src)


if __name__ == "__main__":
    unittest.main()
