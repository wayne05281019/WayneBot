# -*- coding: utf-8 -*-
import unittest

from us_overnight import _fmt_move, _fmt_pct, format_us_drop_alert, format_us_html


class UsAlertFormatTests(unittest.TestCase):
    def test_pct_two_decimals(self):
        self.assertEqual(_fmt_pct(-0.8), "-0.80%")
        self.assertEqual(_fmt_pct(1.234), "+1.23%")

    def test_move_shows_pct_and_points(self):
        self.assertEqual(_fmt_move(-0.8, -142.15), "-0.80%（-142.15點）")

    def test_drop_alert_layout(self):
        snap = {
            "regime": "caution",
            "vix": 16.3,
            "vix_pct": 4.5,
            "vix_chg": 0.7,
            "dji_pct": -0.8,
            "dji_chg": -142.15,
            "spx_pct": -0.7,
            "spx_chg": -38.42,
            "ixic_pct": -1.0,
            "ixic_chg": -198.32,
            "sox_pct": -2.1,
            "sox_chg": -125.4,
            "nq_f_pct": -0.2,
            "nq_f_chg": -45.0,
            "tsm_post_pct": -0.3,
            "tsm_post_chg": -0.75,
            "nvda_post_pct": -1.4,
            "nvda_post_chg": -2.1,
            "us_phase": "post",
            "us_session": "20260901",
        }
        html = format_us_drop_alert(snap)
        self.assertIn("美股收盤偏弱", html)
        self.assertIn("一早提醒", html)
        self.assertIn("== 現金收盤 ==", html)
        self.assertIn("道瓊", html)
        self.assertIn("-0.80%（-142.15點）", html)
        self.assertIn("16.30（+4.50%）", html)
        self.assertIn("== 盤後續勢 ==", html)
        self.assertIn("NQ", html)
        self.assertNotIn("｜", html)
        # 每個指數獨立一行，那斯達克不應被拆成兩行（標籤與數值同列）
        self.assertIn("那斯達克", html)
        self.assertLess(html.index("道瓊"), html.index("標普"))
        self.assertLess(html.index("標普"), html.index("那斯達克"))

    def test_us_html_block_layout(self):
        snap = {
            "regime": "ok",
            "vix": 15.0,
            "vix_pct": 0.0,
            "dji_pct": 0.1,
            "dji_chg": 10.0,
            "spx_pct": 0.0,
            "spx_chg": 0.0,
            "ixic_pct": 0.2,
            "ixic_chg": 20.0,
            "sox_pct": -0.5,
            "sox_chg": -5.0,
            "us_phase": "regular",
            "us_session": "20260901",
        }
        html = format_us_html(snap)
        self.assertIn("== 現金收盤 ==", html)
        self.assertIn("+0.10%（+10.00點）", html)
        self.assertNotIn("｜", html)


if __name__ == "__main__":
    unittest.main()
