# -*- coding: utf-8 -*-
"""決策卡數值正確性：漲跌幅、高低點、獲利欄。"""
import os
import unittest

import pytest

from config import get_db_path
from decision_card_signals import resolve_daily_change_pct


class CardDataAccuracyTests(unittest.TestCase):
    def test_resolve_daily_change_prefers_yesterday_close(self):
        self.assertAlmostEqual(
            resolve_daily_change_pct(4320.0, yesterday_close=4314.82),
            0.12,
            places=2,
        )

    @pytest.mark.production_db
    def test_2454_db_profit_and_h60_match_carybot(self):
        """庫內最後完整日：決策卡獲利／高低應自洽、兩次呼叫一致。"""
        db = get_db_path()
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

    @pytest.mark.production_db
    def test_2454_live_headline_matches_carybot(self):
        """盤中 MIS 併入後：4320 / +0.12% / 37.1%（CaryBot 9/2 截圖）。"""
        db = get_db_path()
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


    @pytest.mark.production_db
    def test_3105_official_20260903_matches_db_and_carybot_levels(self):
        """穩懋 20260903 官方：漲跌對昨收、高低摘要、60日量前十、預警露出 10低。"""
        db = get_db_path()
        import sqlite3

        from decision_card_signals import candle_up_taiwan, display_alert_cell, volume_headline_rank
        from wayne_navigator import NavigatorEngine

        conn = sqlite3.connect(db)
        row = conn.execute(
            """
            SELECT replace(date,'-',''), open, high, low, close, volume, pct_change
            FROM daily_quotes WHERE stock_id='3105' AND replace(date,'-','')='20260903'
            """
        ).fetchone()
        prev = conn.execute(
            """
            SELECT close FROM daily_quotes
            WHERE stock_id='3105' AND replace(date,'-','') < '20260903'
            ORDER BY replace(date,'-','') DESC LIMIT 1
            """
        ).fetchone()
        conn.close()
        if not row:
            self.skipTest("no 3105 20260903")
        o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
        self.assertAlmostEqual(o, 478.0, places=1)
        self.assertAlmostEqual(h, 490.0, places=1)
        self.assertAlmostEqual(l, 440.0, places=1)
        self.assertAlmostEqual(c, 446.5, places=1)
        prev_c = float(prev[0]) if prev else 0.0
        self.assertAlmostEqual(prev_c, 469.5, places=1)
        self.assertFalse(candle_up_taiwan(c, prev_c, o))

        card = NavigatorEngine(db).get_decision_card("3105", merge_live=False)
        tbl = card["table"]
        r903 = tbl[tbl["date"].astype(str) == "20260903"]
        self.assertFalse(r903.empty, "20 日表應含 20260903")
        self.assertAlmostEqual(float(r903.iloc[0]["close"]), 446.5, places=1)
        latest = str(card.get("latest_date")).replace("-", "")[:8]
        if latest == "20260903":
            self.assertAlmostEqual(float(card["close"]), 446.5, places=1)
            self.assertAlmostEqual(float(card["change_pct"]), -4.90, places=2)
            self.assertAlmostEqual(float(card["h10"]), 492.0, places=1)
            self.assertAlmostEqual(float(card["h20"]), 492.0, places=1)
            self.assertAlmostEqual(float(card["l10"]), 355.0, places=0)
            self.assertAlmostEqual(float(card["l60"]), 268.0, places=0)
            self.assertAlmostEqual(float(card["gain_pct"]), 66.6, places=1)
            lab, n = volume_headline_rank(
                card.get("vol_rank_480") or 99,
                card.get("vol_rank") or 99,
                card.get("vol_rank_60") or 99,
            )
            self.assertEqual(lab, "60日量")
            self.assertLessEqual(int(n), 10)
            self.assertTrue(any("60日量" in str(b) for b in (card.get("badges") or [])))

        r824 = tbl[tbl["date"].astype(str) == "20260824"]
        if not r824.empty:
            shown = display_alert_cell(str(r824.iloc[0]["預警"]), str(r824.iloc[0]["高低"]))
            self.assertEqual(shown, "10低")
        r901 = tbl[tbl["date"].astype(str) == "20260901"]
        if not r901.empty:
            shown = display_alert_cell(str(r901.iloc[0]["預警"]), str(r901.iloc[0]["高低"]))
            self.assertEqual(shown, "20高")


if __name__ == "__main__":
    unittest.main()
