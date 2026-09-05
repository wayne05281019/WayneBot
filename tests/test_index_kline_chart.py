# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PIL import Image

from index_kline_chart import (
    build_market_kline_chart,
    fetch_twii_ohlc,
    load_index_daily_ohlc,
    render_index_kline_png,
)


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


class IndexDailyOfficialChartTests(unittest.TestCase):
    def test_load_index_daily_ohlc_and_title_matches_official_change(self):
        import sqlite3
        import tempfile

        from PIL import Image

        db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        try:
            con = sqlite3.connect(db)
            con.execute(
                """
                CREATE TABLE index_daily (
                    date TEXT, symbol TEXT, close REAL, volume REAL, pct_change REAL,
                    ma20 REAL, ma60 REAL, regime TEXT, updated_at TEXT,
                    open REAL, high REAL, low REAL,
                    PRIMARY KEY (date, symbol)
                )
                """
            )
            con.execute(
                "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "20260903",
                    "TWII",
                    45857.66,
                    11201668,
                    -0.67,
                    None,
                    None,
                    "",
                    "",
                    46325.48,
                    46517.45,
                    45839.36,
                ),
            )
            con.execute(
                "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "20260904",
                    "TWII",
                    46551.13,
                    9267047,
                    1.51,
                    None,
                    None,
                    "",
                    "",
                    45991.28,
                    46620.96,
                    45966.86,
                ),
            )
            con.commit()
            con.close()
            df = load_index_daily_ohlc(db, days=30)
            self.assertEqual(len(df), 2)
            self.assertAlmostEqual(float(df.iloc[-1]["close"]), 46551.13, places=2)
            chg = float(df.iloc[-1]["close"]) - float(df.iloc[-2]["close"])
            self.assertAlmostEqual(chg, 693.47, places=2)
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "official.png")
                path = build_market_kline_chart(out, db_path=db)
                self.assertTrue(path and os.path.isfile(path))
                with Image.open(path) as img:
                    self.assertGreaterEqual(img.size[0], 800)
        finally:
            os.unlink(db)

    def test_build_skips_yahoo_when_db_empty(self):
        import inspect

        src = inspect.getsource(build_market_kline_chart)
        self.assertIn("load_index_daily_ohlc", src)
        self.assertNotIn("fetch_twii_ohlc", src)


class FakeChartDisabledTests(unittest.TestCase):
    def test_random_ohlc_chart_generator_raises(self):
        from wayne_navigator import ChartGenerator

        with self.assertRaises(RuntimeError) as ctx:
            ChartGenerator.draw_180d_chart()
        self.assertIn("假資料", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
