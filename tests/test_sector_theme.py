# -*- coding: utf-8 -*-
"""今日最強族 + 代表股（資金輪動頂部 brief）。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from money_flow import (
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
            html = format_sector_rotation_html(path, "20260902")
            self.assertIn("金融", html)
            self.assertIn("撐盤", html)
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


if __name__ == "__main__":
    unittest.main()
