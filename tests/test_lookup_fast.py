# -*- coding: utf-8 -*-
"""查股快速路徑：出圖不等 MIS 重複打三次。"""
import time
import unittest

from config import get_db_path


class LookupFastTests(unittest.TestCase):
    def test_decision_card_without_live_merge_is_fast(self):
        import os

        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        from wayne_navigator import NavigatorEngine

        t0 = time.perf_counter()
        card = NavigatorEngine(db).get_decision_card("2330", merge_live=False)
        elapsed = time.perf_counter() - t0
        self.assertNotIn("error", card)
        self.assertLess(elapsed, 5.0, f"card build too slow: {elapsed:.1f}s")


if __name__ == "__main__":
    unittest.main()
