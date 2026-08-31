# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo


class FuseAndScreenTest(unittest.TestCase):
    def test_should_not_commit_half_day(self):
        from import_health import should_commit_quote_fetch, sides_complete

        self.assertTrue(sides_complete(1318, 840))
        self.assertFalse(sides_complete(1318, 0))
        self.assertFalse(
            should_commit_quote_fetch(existing_tw=0, existing_two=0, new_tw=1318, new_two=0)
        )
        self.assertFalse(
            should_commit_quote_fetch(existing_tw=1318, existing_two=840, new_tw=1318, new_two=0)
        )
        self.assertTrue(
            should_commit_quote_fetch(existing_tw=1318, existing_two=0, new_tw=1318, new_two=840)
        )

    def test_fuse_end_before_1630_is_yesterday(self):
        from config import fuse_end_date

        mid = datetime(2026, 8, 31, 14, 35, tzinfo=ZoneInfo("Asia/Taipei"))
        self.assertEqual(fuse_end_date(mid), "20260830")
        almost = datetime(2026, 8, 31, 16, 29, tzinfo=ZoneInfo("Asia/Taipei"))
        self.assertEqual(fuse_end_date(almost), "20260830")
        closed = datetime(2026, 8, 31, 16, 30, tzinfo=ZoneInfo("Asia/Taipei"))
        self.assertEqual(fuse_end_date(closed), "20260831")

    def test_job_kind_env_beats_once_flag(self):
        from config import job_kind

        old_job = os.environ.get("WAYNE_JOB")
        old_mode = os.environ.get("WAYNE_MODE")
        os.environ["WAYNE_JOB"] = "morning_screen"
        os.environ.pop("WAYNE_MODE", None)
        try:
            self.assertEqual(job_kind(["--once"]), "morning_screen")
        finally:
            if old_job is None:
                os.environ.pop("WAYNE_JOB", None)
            else:
                os.environ["WAYNE_JOB"] = old_job
            if old_mode is None:
                os.environ.pop("WAYNE_MODE", None)
            else:
                os.environ["WAYNE_MODE"] = old_mode

    def test_latest_complete_skips_otc_zero(self):
        from import_health import latest_complete_quote_date
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260828", "2330", "台積電", "TW", 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0),
            )
            for i in range(800):
                conn.execute(
                    "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("20260827", f"1{i:03d}", "測", "TW", 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0),
                )
            for i in range(600):
                conn.execute(
                    "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("20260827", f"8{i:03d}", "櫃", "TWO", 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0),
                )
            for i in range(800):
                conn.execute(
                    "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("20260831", f"2{i:03d}", "半", "TW", 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0),
                )
            conn.commit()
            conn.close()
            self.assertEqual(latest_complete_quote_date(path), "20260827")
        finally:
            os.remove(path)

    def test_daytrade_copy_has_safety_prices(self):
        from screening_engine import _stock_card_html, format_line_share_text, format_screening_payload

        item = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "pct_change": 3.2,
            "q60r": 2.4,
            "volume": 5000,
            "turnover_k": 80000,
            "ma20": 98.0,
            "ma60": 95.0,
            "entry_price": 100.0,
            "target_1": 103.0,
            "target_2": 106.0,
            "stop_loss": 99.2,
            "foreign_net": 120,
            "trust_net": 30,
            "dealer_net": -10,
        }
        html = _stock_card_html(item, 1)
        self.assertIn("保險進場", html)
        self.assertIn("第一停利", html)
        self.assertIn("保險停損", html)
        self.assertIn("103", html)
        payload = format_screening_payload({"day_trade": [item] * 12}, "20260828")
        blob = "\n".join(p["html"] for p in payload)
        self.assertNotIn("expandable", blob)
        self.assertIn("其餘", blob)
        self.assertIn("保險進", blob)
        line = format_line_share_text({"day_trade": [item]}, "20260828")
        self.assertIn("保險進場", line)
        self.assertIn("第一停利", line)
        self.assertIn("均價", line)

    def test_inventory_payload_shape(self):
        from import_health import inventory_payload
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            inv = inventory_payload(path)
            self.assertIn("quotes", inv)
            self.assertIn("monthly_revenue", inv)
            self.assertIn("quarterly_income", inv)
            self.assertIn("gaps", inv)
            self.assertIn("latest_complete", inv)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
