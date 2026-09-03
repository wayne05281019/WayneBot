# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PIL import Image

from index_kline_chart import fetch_twii_ohlc, render_index_kline_png


class IndexKlineChartTests(unittest.TestCase):
    def test_render_writes_png(self):
        df = pd.DataFrame(
            {
                "date": [f"2026010{i}" for i in range(1, 8)],
                "open": [100, 101, 102, 101, 103, 104, 105],
                "high": [101, 103, 103, 102, 105, 106, 107],
                "low": [99, 100, 101, 100, 102, 103, 104],
                "close": [100.5, 102, 101.5, 101, 104, 105.5, 106],
                "volume": [1e6] * 7,
            }
        )
        df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "twii.png")
            path = render_index_kline_png(df, out)
            self.assertTrue(path and os.path.isfile(path))
            self.assertGreater(os.path.getsize(path), 5000)
            with Image.open(path) as img:
                w, h = img.size
                self.assertGreaterEqual(w, 1100)
                self.assertGreaterEqual(h, 1500)
                r, g, b = img.convert("RGB").getpixel((5, 5))
            self.assertGreater(r, 200)
            self.assertGreater(g, 200)
            self.assertGreater(b, 200)

    def test_render_uses_taiwan_prev_close_color(self):
        import inspect

        src = inspect.getsource(render_index_kline_png)
        self.assertIn("candle_up_taiwan", src)
        self.assertNotIn("cl >= op", src)

    @patch("index_kline_chart._SESSION.get")
    def test_fetch_parses_yahoo(self, mock_get):
        mock_get.return_value.json.return_value = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1_700_000_000, 1_700_086_400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [18000.0, 18100.0],
                                    "high": [18150.0, 18200.0],
                                    "low": [17950.0, 18050.0],
                                    "close": [18100.0, 18150.0],
                                    "volume": [1e9, 1.1e9],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        mock_get.return_value.raise_for_status = lambda: None
        df = fetch_twii_ohlc(days=60)
        self.assertEqual(len(df), 2)
        self.assertIn("open", df.columns)


class FakeChartDisabledTests(unittest.TestCase):
    def test_random_ohlc_chart_generator_raises(self):
        from wayne_navigator import ChartGenerator

        with self.assertRaises(RuntimeError) as ctx:
            ChartGenerator.draw_180d_chart()
        self.assertIn("假資料", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
