# -*- coding: utf-8 -*-
"""使用者傳的 CaryBot／作者卡截圖驗收：同一交易日列，逐格鎖死。

lookback=40：截圖日（8/10 等）不會在 20 日表滾出後消失。
溫度／量排名是先前只鎖價格／獲利／預警時還沒鎖的格子。
"""
import unittest

import pytest

from config import get_db_path
from decision_card_signals import display_alert_cell
from wayne_navigator import NavigatorEngine

pytestmark = pytest.mark.production_db


class CaryBotUserFixtureTests(unittest.TestCase):
    def _card(self, code: str):
        from wayne_navigator import NavigatorEngine

        return NavigatorEngine(get_db_path()).get_decision_card(
            code, lookback=40, merge_live=False
        )

    def _row(self, card, date_yyyymmdd: str):
        tbl = card["table"]
        hit = tbl[tbl["date"].astype(str) == str(date_yyyymmdd)]
        self.assertEqual(len(hit), 1, f"missing date {date_yyyymmdd}")
        return hit.iloc[0]

    def _shown_alert(self, row) -> str:
        return display_alert_cell(str(row["預警"]), str(row["高低"]))

    def _temp(self, row) -> float:
        return float(row["temp_num"])

    def test_8234_20260810_matches_carybot_peak(self):
        """CaryBot 截圖：8/10 高點列應完全一致。"""
        row = self._row(self._card("8234"), "20260810")
        self.assertAlmostEqual(float(row["close"]), 73.8, places=1)
        self.assertEqual(row["獲利"], "32.3%")
        self.assertEqual(row["預警"], "K20高")
        self.assertEqual(self._shown_alert(row), "20高")
        self.assertEqual(str(row["溫度計"]), "76.9 °C")
        self.assertAlmostEqual(self._temp(row), 76.9, places=1)
        self.assertEqual(str(row["升降"]), "最高溫")
        self.assertAlmostEqual(float(row["bias_monthly"]), 15.1, places=1)
        self.assertEqual(str(row["120日量"]), "第12名")
        self.assertEqual(int(row["vol_rank_120"]), 12)

    def test_2421_20260831_price_alert_vol_match_carybot(self):
        """CaryBot：8/31 價格、K20高、月乖離、量排名一致；獲利/溫度尺度不同（見對照說明）。"""
        row = self._row(self._card("2421"), "20260831")
        self.assertAlmostEqual(float(row["close"]), 179.5, places=1)
        self.assertEqual(row["預警"], "K20高")
        self.assertEqual(self._shown_alert(row), "20高")
        self.assertAlmostEqual(float(row["bias_monthly"]), 19.8, places=1)
        self.assertEqual(str(row["120日量"]), "第2名")
        self.assertEqual(int(row["vol_rank_120"]), 2)
        self.assertEqual(str(row["升降"]), "最高溫")
        # 建準溫度尺度與 Cary 截圖不完全同一把尺；只鎖量／預警／月乖離／升降。

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
        self.assertEqual(self._shown_alert(row), "20高")
        self.assertEqual(str(row["溫度計"]), "77.5 °C")
        self.assertAlmostEqual(self._temp(row), 77.5, places=1)
        self.assertEqual(str(row["升降"]), "最高溫")
        self.assertAlmostEqual(float(row["bias_monthly"]), 17.4, places=1)
        self.assertEqual(str(row["120日量"]), "第3名")
        self.assertEqual(int(row["vol_rank_120"]), 3)
        self.assertAlmostEqual(float(card["cal60_low"]), 33.75, places=2)

    def test_2324_high_low_summary_matches_carybot(self):
        """CaryBot 高低摘要：截圖日 9/2 收 39.7；20／60 高 43.2、10 高 41.6、60曆日低 33.75。

        摘要高低釘在截圖日 as_of；最新收盤列會隨盤後日滾動，不鎖在截圖價。
        """
        card = NavigatorEngine(get_db_path()).get_decision_card(
            "2324", lookback=40, merge_live=False, as_of="20260902"
        )
        row = self._row(card, "20260902")
        self.assertAlmostEqual(float(row["close"]), 39.7, places=1)
        self.assertAlmostEqual(float(card["h10"]), 41.6, places=1)
        self.assertAlmostEqual(float(card["h20"]), 43.2, places=1)
        self.assertAlmostEqual(float(card["h60"]), 43.2, places=1)
        self.assertAlmostEqual(float(card["l20"]), 36.3, places=1)
        self.assertAlmostEqual(float(card["cal60_low"]), 33.75, places=2)

    def test_2324_profit_floor_carybot_uses_cal60_only(self):
        """CaryBot 9/1 列獲利 18.2%＝只用 60曆日低 33.75（未貼 20 日低時與 CaryBot 一致）。"""
        card = self._card("2324")
        row = self._row(card, "20260901")
        self.assertAlmostEqual(float(row["close"]), 39.9, places=1)
        self.assertEqual(row["獲利"], "18.2%")
        pure_cal = (39.9 - 33.75) / 33.75 * 100.0
        self.assertAlmostEqual(pure_cal, 18.2, places=1)
        self.assertEqual(str(row["溫度計"]), "44.5 °C")
        self.assertEqual(str(row["120日量"]), "第42名")
        self.assertEqual(self._shown_alert(row), "No")

    def test_2324_20260902_temp_vol_low_cells(self):
        """仁寶 9/2 列：5低＋最低溫＋價未新低；溫度／量排名一起鎖。"""
        row = self._row(self._card("2324"), "20260902")
        self.assertAlmostEqual(float(row["close"]), 39.7, places=1)
        self.assertEqual(self._shown_alert(row), "5低")
        self.assertEqual(str(row["溫度計"]), "42.5 °C")
        self.assertEqual(str(row["升降"]), "最低溫")
        self.assertIn("價未新低", str(row.get("升降註") or ""))
        self.assertEqual(str(row["120日量"]), "第30名")
        self.assertAlmostEqual(float(row["bias_monthly"]), 0.4, places=1)

    def test_4915_author_card_sep4_cells(self):
        """致伸作者卡 9/4：2.4% 白底紅、20高、最高溫 69.3°C、量第102名。"""
        from wayne_navigator import _CARD, bias_cell_style, profit_cell_style, temp_cell_style

        row = self._row(self._card("4915"), "20260904")
        self.assertAlmostEqual(float(row["close"]), 60.8, places=1)
        self.assertEqual(row["獲利"], "2.4%")
        self.assertEqual(self._shown_alert(row), "20高")
        self.assertEqual(str(row["溫度計"]), "69.3 °C")
        self.assertEqual(str(row["升降"]), "最高溫")
        self.assertAlmostEqual(float(row["bias_monthly"]), 1.1, places=1)
        self.assertEqual(str(row["120日量"]), "第102名")
        bg, fg = profit_cell_style(float(row["profit_pct"]), None, _CARD["white"])
        self.assertEqual(bg, _CARD["white"])
        self.assertEqual(fg, _CARD["up"])
        tbg, _ = temp_cell_style(self._temp(row), _CARD["white"])
        self.assertEqual(tbg, _CARD["temp_warm_bg"])
        self.assertEqual(bias_cell_style(float(row["bias_monthly"]), _CARD["white"])[1], _CARD["up"])

    def test_4915_author_card_sep3_leave_zero_green(self):
        """致伸作者卡 9/3：0.3% 實綠底紅字、60低、降溫。"""
        from wayne_navigator import _CARD, bias_cell_style, profit_cell_style

        row = self._row(self._card("4915"), "20260903")
        self.assertAlmostEqual(float(row["close"]), 59.6, places=1)
        self.assertEqual(row["獲利"], "0.3%")
        self.assertEqual(self._shown_alert(row), "60低")
        self.assertEqual(str(row["溫度計"]), "19.3 °C")
        self.assertEqual(str(row["升降"]), "降溫")
        self.assertAlmostEqual(float(row["bias_monthly"]), -0.8, places=1)
        self.assertEqual(str(row["120日量"]), "第99名")
        bg, fg = profit_cell_style(float(row["profit_pct"]), 0.0, _CARD["white"])
        self.assertEqual(bg, _CARD["lo_hit_fill"])
        self.assertEqual(fg, _CARD["up"])
        self.assertEqual(bias_cell_style(float(row["bias_monthly"]), _CARD["white"])[1], _CARD["down"])

    def test_4915_author_card_aug31_zero_green(self):
        """致伸作者卡 8/31：0.0% 綠底白字、60低。"""
        from wayne_navigator import _CARD, profit_cell_style

        row = self._row(self._card("4915"), "20260831")
        self.assertAlmostEqual(float(row["close"]), 59.4, places=1)
        self.assertEqual(row["獲利"], "0.0%")
        self.assertEqual(self._shown_alert(row), "60低")
        self.assertEqual(str(row["溫度計"]), "9.5 °C")
        self.assertEqual(str(row["120日量"]), "第112名")
        bg, fg = profit_cell_style(float(row["profit_pct"]), None, _CARD["white"])
        self.assertEqual(bg, _CARD["lo_fill"])
        self.assertEqual(fg, _CARD["white"])

    def test_2408_20260903_ten_low_min_temp_vol(self):
        """南亞科 9/3 作者卡：貼 10 低、最低溫＋價未新低；鎖溫度／量。"""
        row = self._row(self._card("2408"), "20260903")
        self.assertAlmostEqual(float(row["close"]), 477.5, places=1)
        self.assertEqual(str(row["高低"]), "10低")
        self.assertEqual(self._shown_alert(row), "10低")
        self.assertEqual(str(row["升降"]), "最低溫")
        self.assertIn("價未新低", str(row.get("升降註") or ""))
        self.assertEqual(str(row["溫度計"]), "24.7 °C")
        self.assertEqual(str(row["120日量"]), "第15名")
        self.assertAlmostEqual(float(row["bias_monthly"]), -6.3, places=1)

    def test_2383_20260903_min_temp_vol(self):
        """台光電 9/3：最低溫＋價未新低；鎖溫度／量排名。"""
        row = self._row(self._card("2383"), "20260903")
        self.assertAlmostEqual(float(row["close"]), 5290.0, places=0)
        self.assertEqual(str(row["升降"]), "最低溫")
        self.assertIn("價未新低", str(row.get("升降註") or ""))
        self.assertEqual(str(row["溫度計"]), "11.7 °C")
        self.assertEqual(str(row["120日量"]), "第99名")
        self.assertEqual(self._shown_alert(row), "10低")

    def test_3105_20260901_peak_temp_vol(self):
        """穩懋 9/1：20高、最高溫 79.6°C、120日量第5名（表頭量能徽章用）。"""
        row = self._row(self._card("3105"), "20260901")
        self.assertAlmostEqual(float(row["close"]), 492.0, places=1)
        self.assertEqual(self._shown_alert(row), "20高")
        self.assertEqual(str(row["溫度計"]), "79.6 °C")
        self.assertEqual(str(row["升降"]), "最高溫")
        self.assertEqual(str(row["120日量"]), "第5名")
        self.assertAlmostEqual(float(row["bias_monthly"]), 25.2, places=1)

    def test_3105_20260902_k20_high_temp_vol(self):
        """穩懋 9/2：收 469.5／20高 492 → K20高；鎖溫度／量。"""
        row = self._row(self._card("3105"), "20260902")
        self.assertAlmostEqual(float(row["close"]), 469.5, places=1)
        self.assertEqual(row["預警"], "K20高")
        self.assertEqual(self._shown_alert(row), "K20高")
        self.assertEqual(str(row["溫度計"]), "67.8 °C")
        self.assertEqual(str(row["升降"]), "降溫")
        self.assertEqual(str(row["120日量"]), "第22名")

    def test_2530_20260831_zero_temp_vol(self):
        """華建 8/31 獲利 0.0% 起漲故事：鎖溫度／量排名。"""
        row = self._row(self._card("2530"), "20260831")
        self.assertEqual(row["獲利"], "0.0%")
        self.assertEqual(self._shown_alert(row), "20低")
        self.assertEqual(str(row["溫度計"]), "7.2 °C")
        self.assertEqual(str(row["升降"]), "最低溫")
        self.assertEqual(str(row["120日量"]), "第1名")

    def test_1314_20260820_dumped_chop_not_mid_hot(self):
        """中石化 8/20：Cary VAM 0.5。跌破季線盤整不該沿用舊高走到 40°C。"""
        card = NavigatorEngine(get_db_path()).get_decision_card(
            "1314", lookback=40, merge_live=False, as_of="20260820"
        )
        row = self._row(card, "20260820")
        self.assertAlmostEqual(float(row["close"]), 7.82, places=2)
        self.assertLess(self._temp(row), 12.0)
        self.assertNotEqual(str(row["升降"]), "最高溫")

    def test_2603_20260730_below_ma60_not_mid_hot(self):
        """長榮 7/30：Cary VAM 3.5。季線下還沒貼 20 高，不該 50°C+。"""
        card = NavigatorEngine(get_db_path()).get_decision_card(
            "2603", lookback=40, merge_live=False, as_of="20260730"
        )
        row = self._row(card, "20260730")
        self.assertAlmostEqual(float(row["close"]), 201.0, places=1)
        self.assertLess(self._temp(row), 16.0)

    def test_3008_20260902_price_high_not_cary_temp_scale(self):
        """大立光 9/2 截圖價 7810、20高。Cary 溫度 90.4 是另一把尺，不鎖成回歸。"""
        row = self._row(self._card("3008"), "20260902")
        self.assertAlmostEqual(float(row["close"]), 7810.0, places=0)
        self.assertEqual(self._shown_alert(row), "20高")
        self.assertEqual(str(row["120日量"]), "第14名")
        self.assertGreater(self._temp(row), 70.0)
        self.assertLess(self._temp(row), 90.0)

    def test_6770_20260910_matches_carybot_official_closes(self):
        """力積電 9/10 Cary 截圖：股價用官方收盤，不要把 8/27 除息 0.23 元還原進表。"""
        card = NavigatorEngine(get_db_path()).get_decision_card(
            "6770", lookback=20, merge_live=False, as_of="20260910"
        )
        self.assertAlmostEqual(float(card["close"]), 73.5, places=1)
        self.assertAlmostEqual(float(card["h10"]), 73.5, places=1)
        self.assertAlmostEqual(float(card["h20"]), 78.4, places=1)
        self.assertAlmostEqual(float(card["h60"]), 85.7, places=1)
        self.assertAlmostEqual(float(card["l10"]), 67.8, places=1)
        self.assertAlmostEqual(float(card["l20"]), 66.6, places=1)
        self.assertAlmostEqual(float(card["l60"]), 49.55, places=2)
        self.assertEqual(card["space_20"], 18)
        self.assertEqual(card["space_60"], 73)
        badges = card.get("badges") or []
        self.assertFalse(any("已除權還原" in str(b) for b in badges))
        row = self._row(card, "20260910")
        self.assertAlmostEqual(float(row["close"]), 73.5, places=1)
        self.assertEqual(row["獲利"], "48.3%")
        self.assertEqual(self._shown_alert(row), "10高")
        self.assertEqual(str(row["高低"]), "10高")
        r26 = self._row(card, "20260826")
        self.assertAlmostEqual(float(r26["close"]), 70.2, places=1)
        r14 = self._row(card, "20260814")
        self.assertAlmostEqual(float(r14["close"]), 78.4, places=1)
        self.assertEqual(self._shown_alert(r14), "20高")
        r07 = self._row(card, "20260907")
        self.assertAlmostEqual(float(r07["close"]), 72.9, places=1)
        self.assertEqual(self._shown_alert(r07), "5高")
        r04 = self._row(card, "20260904")
        self.assertEqual(self._shown_alert(r04), "No")
        r03 = self._row(card, "20260903")
        self.assertEqual(self._shown_alert(r03), "10低")


if __name__ == "__main__":
    unittest.main()
