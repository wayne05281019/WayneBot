# -*- coding: utf-8 -*-
"""使用者傳的 CaryBot 截圖驗收（2421 建準、8234 新漢、2324 仁寶）。"""
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

    def test_2421_profit_matches_carybot_cal60_floor(self):
        """CaryBot 9/1 列獲利 46.9%＝只用 60曆日低 120.5。"""
        card = self._card("2421")
        self.assertAlmostEqual(float(card["cal60_low"]), 120.5, places=1)
        row = self._row(card, "20260901")
        self.assertEqual(row["獲利"], "46.9%")
        pure_cal = (177.0 - 120.5) / 120.5 * 100.0
        self.assertAlmostEqual(pure_cal, 46.9, places=1)

    def test_2324_20260814_matches_carybot_peak(self):
        """CaryBot 截圖：8/14 高點列價格、獲利、預警、月乖離一致。"""
        card = self._card("2324")
        row = self._row(card, "20260814")
        self.assertAlmostEqual(float(row["close"]), 43.2, places=1)
        self.assertEqual(row["獲利"], "28.0%")
        self.assertEqual(row["預警"], "K20高")
        self.assertAlmostEqual(float(row["bias_monthly"]), 17.4, places=1)
        self.assertIn("第 3", str(row["120日量"]))
        self.assertAlmostEqual(float(card["cal60_low"]), 33.75, places=2)

    def test_2324_high_low_summary_matches_carybot(self):
        """CaryBot／WayneBot 高低摘要區：10/20/60 高低與距現價 % 一致。"""
        card = self._card("2324")
        self.assertAlmostEqual(float(card["close"]), 39.9, places=1)
        self.assertAlmostEqual(float(card["h10"]), 41.6, places=1)
        self.assertAlmostEqual(float(card["h20"]), 43.2, places=1)
        self.assertAlmostEqual(float(card["h60"]), 43.2, places=1)
        self.assertAlmostEqual(float(card["l10"]), 38.5, places=1)
        self.assertAlmostEqual(float(card["l20"]), 36.3, places=1)
        self.assertAlmostEqual(float(card["cal60_low"]), 33.75, places=2)

    def test_2324_profit_floor_carybot_uses_cal60_only(self):
        """CaryBot 9/2 列獲利 18.2%＝只用 60曆日低 33.75；WayneBot 用 max(60曆日,20日)。"""
        card = self._card("2324")
        row = self._row(card, "20260901")
        self.assertAlmostEqual(float(row["close"]), 39.9, places=1)
        # floor ≈ 20日低 36.3 → (39.9-36.3)/36.3 ≈ 9.9%
        self.assertEqual(row["獲利"], "9.9%")
        pure_cal = (39.9 - 33.75) / 33.75 * 100.0
        self.assertAlmostEqual(pure_cal, 18.2, places=1)


if __name__ == "__main__":
    unittest.main()
