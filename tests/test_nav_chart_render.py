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


if __name__ == "__main__":
    unittest.main()
