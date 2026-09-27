# -*- coding: utf-8 -*-
"""導航圖產出回歸（圖例 ncol 等）。"""
import os
import tempfile
import unittest

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
        db = get_db_path()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nav.png")
            path = generate_chart("2330", "", db, out)
            self.assertTrue(path)
            with Image.open(path) as im:
                self.assertGreaterEqual(im.size[0], 2400)

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

    def test_nav_legend_covers_drawn_markers(self):
        """每個實際畫出的標都要進圖例，且色相可辨（勿近紫／近綠互撞）。"""
        import inspect

        from wayne_navigator import (
            _NAV_GHOST,
            _NAV_SIG,
            _NAV_TONE,
            _draw_nav_legend,
            _paint_nav_on_axes,
        )

        leg = inspect.getsource(_draw_nav_legend)
        for label in (
            "20高", "20高脫離", "20低", "20低脫離", "60低",
            "接近高（空心）", "接近低（空心）", "殘影（仍貼）",
            "量能異常", "警告", "警告底", "月波動低", "月波動低底",
            "買點↑藍", "賣點↓橙",
        ):
            self.assertIn(label, leg, label)
        paint = inspect.getsource(_paint_nav_on_axes)
        self.assertIn("_NAV_GHOST", paint)
        self.assertIn("_NAV_SIG", paint)
        self.assertIn("vol_low_band", paint)
        # 脫離／觸發墨水必須拉開色相（不要兩個近紫或兩個近綠）
        self.assertNotEqual(_NAV_TONE["h20"][1].upper(), _NAV_TONE["h20_leave"][1].upper())
        self.assertNotEqual(_NAV_TONE["l20"][1].upper()[:3], _NAV_TONE["l60"][1].upper()[:3])
        self.assertEqual(_NAV_GHOST[1].upper(), "#607D8B")
        self.assertEqual(_NAV_SIG["vol_low_band"].upper(), "#90CAF9")
        # 脫離不再用半透明糊成殘影
        self.assertNotIn('alpha = 0.34 if (hollow or kind.endswith("_leave"))', paint)


if __name__ == "__main__":
    unittest.main()
