# -*- coding: utf-8 -*-
"""飆客個股文拆出的可量化規則：只測有接入的旗標與同業價對照。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

import pandas as pd

from peer_setup import (
    flags_from_ohlc_df,
    layout_spike_notice,
    liquid_peer_snapshot,
    setup_note_lines,
)
from wayne_db import ensure_core_schema


def _ohlc(*, n=80, close=None, high=None, low=None, volume=None):
    close = pd.Series(close if close is not None else [100.0] * n)
    high = pd.Series(high if high is not None else (close * 1.01))
    low = pd.Series(low if low is not None else (close * 0.99))
    volume = pd.Series(volume if volume is not None else [2000.0] * n)
    return pd.DataFrame({"close": close, "high": high, "low": low, "volume": volume})


class PeerSetupFlagTests(unittest.TestCase):
    def test_spike_watch_needs_volume_near_high_and_run(self):
        n = 70
        close = [100.0] * n
        close[-61] = 100.0
        close[-1] = 140.0
        for i in range(n - 20, n):
            close[i] = 130.0 + (i - (n - 20)) * 0.5
        close[-1] = 140.0
        vol = [1000.0] * n
        vol[-1] = 5000.0
        flags = flags_from_ohlc_df(_ohlc(n=n, close=close, volume=vol), q60r=2.4)
        self.assertTrue(flags["spike_watch"])
        self.assertGreaterEqual(flags["ret60"], 30.0)

    def test_spike_watch_skips_small_60d_gain(self):
        n = 70
        close = [100.0] * (n - 1) + [102.0]
        vol = [1000.0] * (n - 1) + [5000.0]
        flags = flags_from_ohlc_df(_ohlc(n=n, close=close, volume=vol), q60r=2.5)
        self.assertFalse(flags["spike_watch"])

    def test_pullback_band_after_double(self):
        n = 120
        close = [50.0] * 20 + [120.0] * 40 + [72.0] * 60
        high = [c * 1.02 for c in close]
        high[30] = 130.0
        low = [c * 0.98 for c in close]
        low[0] = 50.0
        flags = flags_from_ohlc_df(_ohlc(n=n, close=close, high=high, low=low))
        self.assertTrue(flags["pullback_band"])
        self.assertGreaterEqual(flags["dd120"], 35.0)
        self.assertLessEqual(flags["dd120"], 52.0)

    def test_dry_near_low_is_not_a_buy_flag(self):
        n = 80
        close = [100.0] * n
        close[-1] = 90.0
        vol = [2000.0] * n
        vol[-1] = 400.0
        flags = flags_from_ohlc_df(_ohlc(n=n, close=close, volume=vol), q60r=0.2)
        self.assertFalse(flags["spike_watch"])
        self.assertNotIn("dry_support", flags)

    def test_layout_spike_notice_skips_intraday_buckets(self):
        item = {"spike_watch": True, "entry_price": 100.0}
        self.assertFalse(layout_spike_notice(item))
        self.assertTrue(layout_spike_notice({"spike_watch": True}))
        self.assertFalse(layout_spike_notice({"spike_watch": True, "buy_range": "99~100"}))

    def test_setup_notes_are_not_buy_signals(self):
        lines = setup_note_lines(
            {"spike_watch": True, "setup_q60r": 2.3, "ret60": 40.0, "pullback_band": True, "dd120": 43.0}
        )
        blob = " ".join(lines)
        self.assertIn("觀望", blob)
        self.assertIn("不是買點", blob)

    def test_screen_card_shows_spike_only_on_layout(self):
        from screening_engine import _stock_card_html

        layout = {
            "stock_id": "3081",
            "stock_name": "聯亞",
            "close": 2000.0,
            "pct_change": 2.0,
            "q60r": 2.2,
            "volume": 5000,
            "ma20": 1800,
            "ma60": 1600,
            "spike_watch": True,
        }
        html = _stock_card_html(layout, 1)
        self.assertIn("爆量貼月高", html)
        day = dict(layout)
        day["entry_price"] = 2000.0
        day["target_1"] = 2060.0
        day["target_2"] = 2120.0
        day["stop_loss"] = 1980.0
        self.assertNotIn("爆量貼月高", _stock_card_html(day, 1))


class PeerTapeTests(unittest.TestCase):
    def test_liquid_peer_ranks_20d_return(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            names = [
                ("2330", "台積電", 140.0),
                ("2454", "聯發科", 110.0),
                ("2303", "聯電", 90.0),
                ("2344", "華邦電", 105.0),
                ("2408", "南亞科", 100.0),
            ]
            for sid, name, _ in names:
                conn.execute(
                    "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
                    (sid, name, "TWSE", "STOCK", "半導體業", "t"),
                )
            q = (
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            )
            dates = [f"202608{d:02d}" for d in range(1, 32) if d not in (8, 9, 15, 16, 22, 23, 29, 30)]
            dates = dates[:22]
            self.assertGreaterEqual(len(dates), 21)
            for sid, name, last in names:
                for i, d in enumerate(dates):
                    close = 100.0 if i < len(dates) - 1 else last
                    if i == 0:
                        close = 100.0
                    conn.execute(
                        q,
                        (d, sid, name, "TW", close, close, close, close, 8000, 50000, 0, close, 0, 0, 0),
                    )
            conn.commit()
            conn.close()
            as_of = dates[-1]
            tape = liquid_peer_snapshot(path, "2330", as_of=as_of)
            self.assertTrue(tape["ok"])
            self.assertEqual(tape["rank"], 1)
            self.assertGreaterEqual(tape["rank_of"], 5)
            self.assertEqual(tape["stronger"], [])
            weak_ids = {x["stock_id"] for x in tape["weaker"]}
            self.assertIn("2303", weak_ids)
            from industry_brief import format_industry_html

            html = format_industry_html("2330", path)
            self.assertIn("同業價現況", html)
            self.assertIn("只對照", html)
            self.assertIn("不改海選", html)
            self.assertIn("不拿來追", html)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
