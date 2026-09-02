# -*- coding: utf-8 -*-
"""決策卡數值正確性：漲跌幅、高低點、獲利欄。"""
import os
import unittest

from config import get_db_path
from decision_card_signals import resolve_daily_change_pct


class CardDataAccuracyTests(unittest.TestCase):
    def test_resolve_daily_change_prefers_yesterday_close(self):
        self.assertAlmostEqual(
            resolve_daily_change_pct(4320.0, yesterday_close=4314.82),
            0.12,
            places=2,
        )

    def test_2454_db_profit_and_h60_match_carybot(self):
        """庫內最後完整日：決策卡獲利／高低應自洽、兩次呼叫一致。"""
        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        import sqlite3

        from wayne_navigator import NavigatorEngine

        conn = sqlite3.connect(db)
        row = conn.execute(
            """
            SELECT replace(date,'-','') FROM daily_quotes
            WHERE stock_id='2454' ORDER BY replace(date,'-','') DESC LIMIT 1
            """
        ).fetchone()
        conn.close()
        if not row:
            self.skipTest("no 2454 quotes")
        latest = str(row[0])
        eng = NavigatorEngine(db)
        card = eng.get_decision_card("2454", merge_live=False)
        again = eng.get_decision_card("2454", merge_live=False)
        self.assertEqual(str(card.get("latest_date")), latest)
        self.assertEqual(card.get("gain_pct"), again.get("gain_pct"))
        self.assertEqual(card.get("h60"), again.get("h60"))
        self.assertGreater(float(card["h60"]), float(card["cal60_low"]))
        self.assertIn("gain_pct", card)

    def test_2454_live_headline_matches_carybot(self):
        """盤中 MIS 併入後：4320 / +0.12% / 37.1%（CaryBot 9/2 截圖）。"""
        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        from unittest.mock import patch

        from wayne_navigator import NavigatorEngine

        rt = {
            "stock_id": "2454",
            "stock_name": "聯發科",
            "open": 4450.0,
            "high": 4565.0,
            "low": 4285.0,
            "close": 4320.0,
            "volume": 18265,
            "pct_change": 0.12,
            "yesterday_close": 4314.82,
            "update_time": "12:00:00",
        }
        with patch("live_quote.fetch_mis_quote", return_value=rt), patch(
            "live_quote.is_live_merge_window", return_value=True
        ):
            card = NavigatorEngine(db).get_decision_card("2454", merge_live=True)
        self.assertAlmostEqual(float(card["close"]), 4320.0, places=0)
        self.assertAlmostEqual(float(card["change_pct"]), 0.12, places=2)
        self.assertAlmostEqual(float(card["gain_pct"]), 37.1, places=1)


if __name__ == "__main__":
    unittest.main()
