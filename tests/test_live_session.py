# -*- coding: utf-8 -*-
"""盤中 K：開盤至查詢當下之開高低收量（MIS 合併，不寫庫）。"""
import unittest

import pandas as pd

from live_quote import append_live_bar, session_bar_from_mis


class LiveSessionTests(unittest.TestCase):
    def test_session_bar_from_mis_full_ohlc(self):
        rt = {
            "open": 4450.0,
            "high": 4565.0,
            "low": 4285.0,
            "close": 4320.0,
            "volume": 18265,
            "pct_change": 0.12,
            "yesterday_close": 4314.82,
            "update_time": "12:30:00",
        }
        bar = session_bar_from_mis(rt)
        self.assertAlmostEqual(bar["open"], 4450.0)
        self.assertAlmostEqual(bar["high"], 4565.0)
        self.assertAlmostEqual(bar["low"], 4285.0)
        self.assertAlmostEqual(bar["close"], 4320.0)
        self.assertEqual(bar["volume"], 18265)

    def test_append_live_bar_appends_today_with_session_ohlc(self):
        df = pd.DataFrame(
            [
                {
                    "date": "20260901",
                    "open": 4315.0,
                    "high": 4315.0,
                    "low": 4315.0,
                    "close": 4315.0,
                    "volume": 1000,
                    "change_pct": 0.0,
                }
            ]
        )
        rt = {
            "stock_name": "聯發科",
            "open": 4450.0,
            "high": 4565.0,
            "low": 4285.0,
            "close": 4320.0,
            "volume": 18265,
            "pct_change": 0.12,
            "yesterday_close": 4315.0,
            "update_time": "12:30:00",
        }

        class _Fake:
            @staticmethod
            def today():
                return "20260902"

        import live_quote as lq

        old_today = lq.taipei_today_str
        old_win = lq.is_live_merge_window
        try:
            lq.taipei_today_str = staticmethod(lambda: "20260902")
            lq.is_live_merge_window = staticmethod(lambda now=None: True)
            out = append_live_bar(df, "2454", merge_live=True, live_quote=rt)
        finally:
            lq.taipei_today_str = old_today
            lq.is_live_merge_window = old_win

        last = out.iloc[-1]
        self.assertEqual(str(last["date"]).replace("-", ""), "20260902")
        self.assertAlmostEqual(float(last["open"]), 4450.0)
        self.assertAlmostEqual(float(last["high"]), 4565.0)
        self.assertAlmostEqual(float(last["low"]), 4285.0)
        self.assertAlmostEqual(float(last["close"]), 4320.0)
        self.assertEqual(int(last["volume"]), 18265)


if __name__ == "__main__":
    unittest.main()
