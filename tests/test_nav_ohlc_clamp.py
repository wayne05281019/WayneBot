# -*- coding: utf-8 -*-
"""導航圖畫 K 前夾住 Op>Hi，避免影線包不住實體。"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import pandas as pd

from live_quote import sanitize_ohlc_frame


class NavOhlcClampTests(unittest.TestCase):
    def test_draw_from_ohlc_clamps_last_bar_open_above_high(self):
        from wayne_navigator import draw_from_ohlc

        start = datetime(2026, 8, 3)
        rows = []
        for i in range(25):
            day = start + timedelta(days=i)
            rows.append(
                {
                    "date": day.strftime("%Y%m%d"),
                    "stock_name": "台光電",
                    "open": 5300.0,
                    "high": 5350.0,
                    "low": 5250.0,
                    "close": 5320.0,
                    "volume": 1000,
                }
            )
        rows[-1].update(open=5590.0, high=5515.0, low=5255.0, close=5350.0)
        df = pd.DataFrame(rows)
        clamped = sanitize_ohlc_frame(df)
        self.assertAlmostEqual(float(clamped.iloc[-1]["high"]), 5590.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "2383.png")
            out = draw_from_ohlc(df, "2383", "台光電", path)
            self.assertTrue(out and os.path.isfile(out))
            self.assertGreater(os.path.getsize(out), 8000)

    def test_default_font_lookup_does_not_warn_missing_weight(self):
        import warnings

        import matplotlib.font_manager as fm

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fm.findfont(fm.FontProperties(), fallback_to_default=True)
        msgs = [str(w.message) for w in caught]
        self.assertFalse(any("Failed to find font weight" in m for m in msgs), msgs)
