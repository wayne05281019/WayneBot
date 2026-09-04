# -*- coding: utf-8 -*-
"""海選只收股票／KY，不收 ETF（含槓桿、反向、主動）。"""
import os
import sqlite3
import tempfile
import unittest

from wayne_db import ensure_core_schema


class ScreenExcludesEtfTests(unittest.TestCase):
    def test_load_market_data_keeps_stock_and_ky_drops_etf(self):
        from screening_engine import ScreeningEngine

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            uni = [
                ("4915", "致伸", "TW", "STOCK"),
                ("3711", "日月光投控", "TW", "KY"),
                ("00706L", "期元大S&P日圓正2", "TW", "ETF_LEVERAGED"),
                ("00962", "台新AI優息動能", "TW", "ETF_PASSIVE"),
                ("00990A", "主動元大AI新經濟", "TW", "ETF_ACTIVE"),
            ]
            conn.executemany(
                "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?, '', 1, 't')",
                uni,
            )
            q = "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            for sid, name, _m, _a in uni:
                conn.execute(
                    q,
                    ("20260904", sid, name, "TW", 10, 11, 9, 10, 5000, 80000, 1.0, 10, 0, 0, 0),
                )
            conn.commit()
            conn.close()
            dfs = ScreeningEngine(path).load_market_data("20260904", min_volume=1000, min_turnover_k=30000)
            self.assertIn("4915", dfs)
            self.assertIn("3711", dfs)
            self.assertNotIn("00706L", dfs)
            self.assertNotIn("00962", dfs)
            self.assertNotIn("00990A", dfs)
        finally:
            os.remove(path)

    def test_is_screen_equity_keeps_stock_ky_drops_etf_codes(self):
        from universe import is_screen_equity

        self.assertTrue(is_screen_equity("4915", "致伸"))
        self.assertTrue(is_screen_equity("7717", "萊德光電-KY"))
        self.assertTrue(is_screen_equity("3711", "日月光投控", "KY"))
        self.assertFalse(is_screen_equity("00706L", "期元大S&P日圓正2"))
        self.assertFalse(is_screen_equity("00962", "台新AI優息動能"))
        self.assertFalse(is_screen_equity("00990A", "主動元大AI新經濟"))
        self.assertFalse(is_screen_equity("00411A", "主動統一前沿科技"))
        self.assertFalse(is_screen_equity("2330", "台積電", "ETF_PASSIVE"))

    def test_format_payload_and_cache_drop_etf(self):
        from screening_engine import drop_non_equity_picks, format_screening_payload
        from screen_review import save_screen_picks
        from screen_sessions import load_bucket_rows, save_screen_session

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            mixed = {
                "day_trade": [
                    {"stock_id": "00962", "stock_name": "台新AI優息動能", "close": 15.66},
                    {"stock_id": "1597", "stock_name": "直得", "close": 155.0},
                ],
                "select_01": [
                    {"stock_id": "00706L", "stock_name": "期元大S&P日圓正2", "close": 19.59},
                    {"stock_id": "3591", "stock_name": "艾笛森", "close": 24.9},
                ],
            }
            cleaned = drop_non_equity_picks(mixed)
            self.assertEqual([x["stock_id"] for x in cleaned["day_trade"]], ["1597"])
            self.assertEqual([x["stock_id"] for x in cleaned["select_01"]], ["3591"])
            html = "\n".join(p["html"] for p in format_screening_payload(mixed, "20260904"))
            self.assertIn("3591", html)
            self.assertIn("艾笛森", html)
            self.assertNotIn("00962", html)
            self.assertNotIn("00706L", html)
            self.assertNotIn("日圓正2", html)
            self.assertEqual(save_screen_picks(path, "20260904", mixed), 2)
            conn = sqlite3.connect(path)
            saved = [r[0] for r in conn.execute("SELECT stock_id FROM screen_picks ORDER BY stock_id")]
            conn.close()
            self.assertEqual(saved, ["1597", "3591"])
            save_screen_session(path, "20260904", "morning", mixed)
            rows = load_bucket_rows(path, "day_trade", "20260904")
            self.assertEqual([r["stock_id"] for r in rows], ["1597"])
            conn = sqlite3.connect(path)
            conn.execute(
                """
                INSERT OR REPLACE INTO screen_picks(
                    as_of, bucket, stock_id, stock_name, pick_close
                ) VALUES (?,?,?,?,?)
                """,
                ("20260904", "select_01", "00706L", "期元大S&P日圓正2", 19.59),
            )
            conn.commit()
            conn.close()
            save_screen_picks(
                path,
                "20260904",
                {"select_01": [{"stock_id": "3591", "stock_name": "艾笛森", "close": 24.9}]},
            )
            conn = sqlite3.connect(path)
            left = [r[0] for r in conn.execute("SELECT stock_id FROM screen_picks WHERE as_of='20260904'")]
            conn.close()
            self.assertEqual(left, ["3591"])
            self.assertNotIn("00706L", left)
            self.assertNotIn("1597", left)
        finally:
            os.remove(path)

    def test_load_bucket_rows_skips_etf_only_morning_uses_evening(self):
        from screen_sessions import ensure_screen_session_table, load_bucket_rows, save_screen_session

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            ensure_screen_session_table(path)
            conn = sqlite3.connect(path)
            conn.execute(
                """
                INSERT INTO screen_sessions(
                    as_of, session, bucket, stock_id, stock_name, pick_close
                ) VALUES (?,?,?,?,?,?)
                """,
                ("20260904", "morning", "day_trade", "00962", "台新AI優息動能", 15.66),
            )
            conn.commit()
            conn.close()
            save_screen_session(
                path,
                "20260904",
                "evening",
                {"day_trade": [{"stock_id": "1597", "stock_name": "直得", "close": 155.0}]},
            )
            rows = load_bucket_rows(path, "day_trade", "20260904")
            self.assertEqual([r["stock_id"] for r in rows], ["1597"])
        finally:
            os.remove(path)

    def test_review_stats_ignore_etf_next_pct(self):
        from screen_review import _bucket_stats, format_review_html

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            conn.execute(
                """
                INSERT INTO screen_picks(
                    as_of, bucket, stock_id, stock_name, pick_close, next_date, next_close, next_pct
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                ("20260903", "select_01", "3591", "艾笛森", 24.0, "20260904", 24.9, 3.75),
            )
            conn.execute(
                """
                INSERT INTO screen_picks(
                    as_of, bucket, stock_id, stock_name, pick_close, next_date, next_close, next_pct
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                ("20260903", "select_01", "00706L", "期元大S&P日圓正2", 19.0, "20260904", 28.5, 50.0),
            )
            conn.commit()
            conn.close()
            stats = {k: (n, avg) for k, n, avg, _h in _bucket_stats(path)}
            n, avg = stats["select_01"]
            self.assertEqual(n, 1)
            self.assertAlmostEqual(avg, 3.75, places=2)
            html = format_review_html(path)
            self.assertIn("3591", html)
            self.assertNotIn("00706L", html)
            self.assertNotIn("日圓正2", html)
        finally:
            os.remove(path)

    def test_ai_fill_stats_and_persist_skip_etf(self):
        from screen_review import (
            _ai_fill_stats,
            format_ai_review_html,
            persist_ai_fill,
        )

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            persist_ai_fill(
                path,
                as_of="20260901",
                stock_id="00892",
                action="BUY",
                price=20.0,
                shares=1000,
                stock_name="富邦台灣半導體",
                bucket="overnight",
            )
            persist_ai_fill(
                path,
                as_of="20260901",
                stock_id="2330",
                action="BUY",
                price=100.0,
                shares=1000,
                stock_name="台積電",
                bucket="leave_zero",
            )
            conn = sqlite3.connect(path)
            ids = [r[0] for r in conn.execute("SELECT stock_id FROM ai_fills")]
            self.assertEqual(ids, ["2330"])
            conn.execute(
                """
                INSERT INTO ai_fills(
                    user_id, as_of, stock_id, stock_name, action, price, shares, amount,
                    reason, bucket, next_date, next_close, next_pct, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "wayne_ai",
                    "20260901",
                    "00892",
                    "富邦台灣半導體",
                    "BUY",
                    20,
                    1000,
                    20000,
                    "",
                    "overnight",
                    "20260902",
                    24,
                    20.0,
                    "t",
                ),
            )
            conn.execute(
                "UPDATE ai_fills SET next_date='20260902', next_close=102, next_pct=2.0 WHERE stock_id='2330'"
            )
            conn.commit()
            conn.close()
            stats = {k: (n, avg) for k, n, avg, _h in _ai_fill_stats(path, user_id="wayne_ai")}
            self.assertEqual(stats["overnight"][0], 0)
            self.assertEqual(stats["leave_zero"][0], 1)
            self.assertAlmostEqual(stats["leave_zero"][1], 2.0, places=1)
            html = format_ai_review_html(path)
            self.assertIn("2330", html)
            self.assertNotIn("00892", html)
            self.assertNotIn("富邦台灣半導體", html)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
