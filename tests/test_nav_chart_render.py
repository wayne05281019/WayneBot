# -*- coding: utf-8 -*-
"""導航圖產出回歸（圖例 ncol 等）。"""
import os
import tempfile
import unittest

from config import get_db_path


class NavChartRenderTests(unittest.TestCase):
    def test_generate_chart_writes_png(self):
        from wayne_navigator import generate_chart

        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "2421.png")
            path = generate_chart("2421", "", db, out)
            self.assertTrue(path and os.path.isfile(path))
            self.assertGreater(os.path.getsize(path), 8000)


if __name__ == "__main__":
    unittest.main()
