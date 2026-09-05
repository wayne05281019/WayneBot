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

    def test_nav_chart_hi_dpi_and_narrow_arrows(self):
        import inspect

        from PIL import Image

        from wayne_navigator import NAV_CHART_DPI, draw_from_ohlc, generate_chart

        self.assertGreaterEqual(NAV_CHART_DPI, 180)
        src = inspect.getsource(draw_from_ohlc)
        self.assertIn("arrow_hw = 0.48", src)
        self.assertNotIn("arrow_hw = 1.15", src)
        db = get_db_path()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nav.png")
            path = generate_chart("2330", "", db, out)
            self.assertTrue(path)
            with Image.open(path) as im:
                self.assertGreaterEqual(im.size[0], 2400)

    def test_nav_arrows_have_no_black_outline(self):
        import inspect

        from wayne_navigator import _fill_triangle_gradient, _nav_arrow, _nav_legend_key, _sig_arrow

        for fn in (_nav_arrow, _sig_arrow, _nav_legend_key):
            src = inspect.getsource(fn)
            self.assertNotIn("withStroke", src, fn.__name__)
            self.assertNotIn("#000000", src, fn.__name__)
            self.assertNotIn("000000", src, fn.__name__)
        self.assertIn("_fill_triangle_gradient", inspect.getsource(_nav_arrow))
        self.assertIn("LinearSegmentedColormap", inspect.getsource(_fill_triangle_gradient))
        self.assertIn("set_clip_path", inspect.getsource(_fill_triangle_gradient))


if __name__ == "__main__":
    unittest.main()
