# -*- coding: utf-8 -*-
"""使用者 2026-09-02 傳的 CaryBot 截圖驗收（2421 建準、8234 新漢）。"""
import os
import unittest

from config import get_db_path


class CaryBotUserFixtureTests(unittest.TestCase):
    def _card(self, code: str):
        from wayne_navigator import NavigatorEngine

        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        return NavigatorEngine(db).get_decision_card(code, merge_live=False)

    def _row(self, card, date_yyyymmdd: str):
        tbl = card["table"]
        hit = tbl[tbl["date"].astype(str) == str(date_yyyymmdd)]
        self.assertEqual(len(hit), 1, f"missing date {date_yyyymmdd}")
        return hit.iloc[0]

    def test_8234_20260810_matches_carybot_peak(self):
        """CaryBot 截圖：8/10 高點列應完全一致。"""
        row = self._row(self._card("8234"), "20260810")
        self.assertAlmostEqual(float(row["close"]), 73.8, places=1)
        self.assertEqual(row["獲利"], "32.3%")
        self.assertEqual(row["預警"], "K20高")
        self.assertIn("76.9", str(row["溫度計"]))
        self.assertAlmostEqual(float(row["bias_monthly"]), 15.1, places=1)

    def test_2421_20260831_price_alert_vol_match_carybot(self):
        """CaryBot：8/31 價格、K20高、月乖離、量排名一致；獲利/溫度尺度不同（見對照說明）。"""
        row = self._row(self._card("2421"), "20260831")
        self.assertAlmostEqual(float(row["close"]), 179.5, places=1)
        self.assertEqual(row["預警"], "K20高")
        self.assertAlmostEqual(float(row["bias_monthly"]), 19.8, places=1)
        self.assertIn("第 2", str(row["120日量"]))

    def test_2421_profit_floor_uses_max_cal20_not_cal_only(self):
        """CaryBot 9/2 列獲利 39.8%＝只用 60曆日低 120.5；WayneBot 用 max(60曆日,20日)。"""
        card = self._card("2421")
        self.assertAlmostEqual(float(card["cal60_low"]), 120.5, places=1)
        row = self._row(card, "20260901")
        # floor ≈ 20日低 140.5 → (177-140.5)/140.5 ≈ 26%
        self.assertEqual(row["獲利"], "26.0%")
        # CaryBot 同價若只用 120.5 → 46.9%；截圖 9/1 CaryBot 寫 46.9% 與此一致
        pure_cal = (177.0 - 120.5) / 120.5 * 100.0
        self.assertAlmostEqual(pure_cal, 46.9, places=1)


if __name__ == "__main__":
    unittest.main()
