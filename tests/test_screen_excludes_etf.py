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


if __name__ == "__main__":
    unittest.main()
