# -*- coding: utf-8 -*-
"""查股快速路徑：出圖不等 MIS 重複打、圖表不重算 normalize。"""
import time
import unittest

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


class LookupFastTests(unittest.TestCase):
    def test_decision_card_without_live_merge_is_fast(self):
        db = get_db_path()
        from wayne_navigator import NavigatorEngine

        t0 = time.perf_counter()
        card = NavigatorEngine(db).get_decision_card("2330", merge_live=False)
        elapsed = time.perf_counter() - t0
        self.assertNotIn("error", card)
        self.assertLess(elapsed, 5.0, f"card build too slow: {elapsed:.1f}s")

    def test_chart_reuses_normalized_ohlc(self):
        import os
        import tempfile

        db = get_db_path()
        from unittest.mock import patch

        from wayne_navigator import NavigatorEngine, generate_chart

        engine = NavigatorEngine(db)
        card = engine.get_decision_card("2330", merge_live=False)
        ohlc = card.get("_ohlc")
        self.assertIsNotNone(ohlc)
        self.assertIn("is_halt", ohlc.columns)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "2330.png")
            with patch("wayne_navigator.normalize_ohlc") as mock_norm:
                path = generate_chart(
                    "2330",
                    db_path=db,
                    save_path=out,
                    df=ohlc,
                    already_normalized=True,
                )
                mock_norm.assert_not_called()
            self.assertTrue(path and os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
