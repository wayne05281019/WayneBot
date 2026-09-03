# -*- coding: utf-8 -*-
"""盤中／盤後最強族 + 代表股（資金輪動頂部 brief）。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from money_flow import (
    compute_live_sector_rows,
    format_sector_rotation_html,
    format_sector_theme_brief,
    recompute_sector_flow,
    sector_theme_headline,
)
from wayne_db import ensure_core_schema


class SectorThemeTests(unittest.TestCase):
    def test_headline_financial_bullish(self):
        h = sector_theme_headline(
            {"industry": "金融保險業", "three_net": 180000, "avg_pct": 0.8}
        )
        self.assertIn("金融", h)
        self.assertIn("撐盤", h)

    def test_headline_live_mode(self):
        h = sector_theme_headline(
            {"industry": "金融保險業", "mode": "live", "avg_pct": 0.35}
        )
        self.assertIn("金融", h)
        self.assertIn("撐盤", h)
        h2 = sector_theme_headline(
            {"industry": "半導體業", "mode": "live", "avg_pct": 0.1}
        )
        self.assertIn("走強", h2)

    def test_rotation_includes_theme_block(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            now = "2026-09-02T00:00:00"
            stocks = [
                ("2884", "玉山金", "金融保險業", 5000, 8000),
                ("2887", "台新新光金", "金融保險業", 3000, 5000),
                ("2890", "永豐金", "金融保險業", 2000, 2000),
                ("2330", "台積電", "半導體業", -1000, 9000),
                ("2454", "聯發科", "半導體業", -500, 1200),
            ]

            def ins(date, sid, name, ind, fn, tn):
                conn.execute(
                    """
                    INSERT INTO daily_quotes(
                        date, stock_id, stock_name, market, open, high, low, close, volume,
                        turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
                    ) VALUES (?, ?, ?, 'TW', 100, 101, 99, 100, 5000, 500000, 1.0, 100, ?, ?, 0)
                    """,
                    (date, sid, name, fn, tn),
                )

            for sid, name, ind, fn, tn in stocks:
                conn.execute(
                    """
                    INSERT INTO stock_universe(
                        stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
                    ) VALUES (?, ?, 'TWSE', 'STOCK', ?, 1, ?)
                    """,
                    (sid, name, ind, now),
                )
                ins("20260827", sid, name, ind, fn // 2, tn // 2)
                ins("20260902", sid, name, ind, fn, tn)
            conn.commit()
            conn.close()

            recompute_sector_flow(path, "20260902")
            with mock.patch("live_quote.is_live_merge_window", return_value=False):
                html = format_sector_rotation_html(path, "20260902")
            self.assertIn("金融", html)
            self.assertIn("撐盤", html)
            self.assertIn("盤後最強族", html)
            self.assertIn("2884", html)
            self.assertIn("獲利", html)
            self.assertIn("＝＝金融保險業＝＝", html)
        finally:
            os.remove(path)

    def test_theme_brief_skips_outflow_leader(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            conn.execute(
                """
                INSERT INTO stock_universe(
                    stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
                ) VALUES ('2002', '中鋼', 'TWSE', 'STOCK', '鋼鐵工業', 1, 't')
                """
            )
            conn.execute(
                """
                INSERT INTO daily_quotes(
                    date, stock_id, stock_name, market, open, high, low, close, volume,
                    turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
                ) VALUES ('20260902', '2002', '中鋼', 'TW', 30, 31, 29, 30, 8000, 240000, -1.0, 30, -500, -200, 0)
                """
            )
            conn.commit()
            conn.close()
            brief = format_sector_theme_brief(
                path,
                "20260902",
                {"industry": "鋼鐵工業", "three_net": -700, "avg_pct": -1.0},
            )
            self.assertEqual(brief, "")
        finally:
            os.remove(path)

    def test_live_theme_brief(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            now = "2026-09-02T00:00:00"
            for sid, name, ind, close, pct in [
                ("2884", "玉山金", "金融保險業", 30.0, 1.2),
                ("2887", "台新新光金", "金融保險業", 18.0, 0.8),
                ("2890", "永豐金", "金融保險業", 25.0, 0.5),
                ("2330", "台積電", "半導體業", 900.0, -0.3),
            ]:
                conn.execute(
                    """
                    INSERT INTO stock_universe(
                        stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
                    ) VALUES (?, ?, 'TWSE', 'STOCK', ?, 1, ?)
                    """,
                    (sid, name, ind, now),
                )
                conn.execute(
                    """
                    INSERT INTO daily_quotes(
                        date, stock_id, stock_name, market, open, high, low, close, volume,
                        turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
                    ) VALUES ('20260902', ?, ?, 'TW', ?, ?, ?, ?, 50000, 1500000, ?, ?, 0, 0, 0)
                    """,
                    (sid, name, close, close + 1, close - 1, close, pct, close),
                )
            conn.commit()
            conn.close()

            live_quotes = {
                "2884": {"close": 30.5, "pct": 1.5, "volume": 60000, "name": "玉山金"},
                "2887": {"close": 18.2, "pct": 1.0, "volume": 50000, "name": "台新新光金"},
                "2890": {"close": 25.1, "pct": 0.6, "volume": 40000, "name": "永豐金"},
                "2330": {"close": 895.0, "pct": -0.5, "volume": 80000, "name": "台積電"},
            }
            meta = {
                sid: {"stock_id": sid, "stock_name": q["name"], "industry": ind}
                for sid, q, ind in [
                    ("2884", live_quotes["2884"], "金融保險業"),
                    ("2887", live_quotes["2887"], "金融保險業"),
                    ("2890", live_quotes["2890"], "金融保險業"),
                    ("2330", live_quotes["2330"], "半導體業"),
                ]
            }
            top = {
                "industry": "金融保險業",
                "mode": "live",
                "avg_pct": 0.85,
                "sample_n": 3,
                "_live_meta": meta,
                "_live_quotes": live_quotes,
            }
            brief = format_sector_theme_brief(path, "20260902", top, mode="live")
            self.assertIn("盤中最強族", brief)
            self.assertIn("金融", brief)
            self.assertIn("MIS", brief)
            self.assertIn("2884", brief)
            self.assertIn("獲利", brief)

            with mock.patch("live_quote.is_live_merge_window", return_value=True), mock.patch(
                "midday_review.fetch_mis_batch", return_value=live_quotes
            ):
                rows = compute_live_sector_rows(path, now=datetime(2026, 9, 2, 10, 0))
            self.assertTrue(rows)
            self.assertEqual(rows[0]["industry"], "金融保險業")
            self.assertGreater(float(rows[0]["avg_pct"]), 0)
        finally:
            os.remove(path)

    def test_rotation_prefers_live_theme(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            now = "2026-09-02T00:00:00"
            stocks = [
                ("2884", "玉山金", "金融保險業", 5000, 8000),
                ("2887", "台新新光金", "金融保險業", 3000, 5000),
                ("2890", "永豐金", "金融保險業", 2000, 2000),
                ("2330", "台積電", "半導體業", -1000, 9000),
            ]

            def ins(date, sid, name, ind, fn, tn):
                conn.execute(
                    """
                    INSERT INTO daily_quotes(
                        date, stock_id, stock_name, market, open, high, low, close, volume,
                        turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
                    ) VALUES (?, ?, ?, 'TW', 100, 101, 99, 100, 5000, 500000, 1.0, 100, ?, ?, 0)
                    """,
                    (date, sid, name, fn, tn),
                )

            for sid, name, ind, fn, tn in stocks:
                conn.execute(
                    """
                    INSERT INTO stock_universe(
                        stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
                    ) VALUES (?, ?, 'TWSE', 'STOCK', ?, 1, ?)
                    """,
                    (sid, name, ind, now),
                )
                ins("20260902", sid, name, ind, fn, tn)
            conn.commit()
            conn.close()
            recompute_sector_flow(path, "20260902")

            live_quotes = {
                "2330": {"close": 101.0, "pct": 2.0, "volume": 60000, "name": "台積電"},
                "2884": {"close": 99.0, "pct": -0.5, "volume": 50000, "name": "玉山金"},
            }
            meta = {
                "2330": {"stock_id": "2330", "stock_name": "台積電", "industry": "半導體業"},
                "2884": {"stock_id": "2884", "stock_name": "玉山金", "industry": "金融保險業"},
            }
            with mock.patch("live_quote.is_live_merge_window", return_value=True), mock.patch(
                "money_flow.compute_live_sector_rows"
            ) as mock_live:
                mock_live.return_value = [
                    {
                        "industry": "半導體業",
                        "mode": "live",
                        "avg_pct": 1.5,
                        "sample_n": 5,
                        "_live_meta": meta,
                        "_live_quotes": live_quotes,
                    }
                ]
                html = format_sector_rotation_html(
                    path, "20260902", now=datetime(2026, 9, 2, 10, 0)
                )
            self.assertIn("盤中最強族", html)
            mock_live.assert_called_once()
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
