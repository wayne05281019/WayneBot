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
            self.assertIn("daily_sector_flow", inv)
        finally:
            os.remove(path)

    def test_sector_rotation_uses_official_chips(self):
        from money_flow import (
            annotate_items_with_sector_flow,
            format_flow_html,
            format_sector_rotation_html,
            recompute_sector_flow,
        )
        from screening_engine import _stock_card_html
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            now = "2026-08-31T00:00:00"
            univ = [
                ("2330", "台積電", "TWSE", "STOCK", "半導體業"),
                ("2454", "聯發科", "TWSE", "STOCK", "半導體業"),
                ("2002", "中鋼", "TWSE", "STOCK", "鋼鐵工業"),
                ("2027", "大成鋼", "TWSE", "STOCK", "鋼鐵工業"),
                ("0050", "元大台灣50", "TWSE", "ETF_PASSIVE", "ETF"),
            ]
            for sid, name, mkt, atype, ind in univ:
                conn.execute(
                    "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
                    (sid, name, mkt, atype, ind, now),
                )

            def q(date, sid, name, market, pct, vol, fn, tn, dn):
                conn.execute(
                    "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (date, sid, name, market, 100, 101, 99, 100, vol, 50000, pct, 100, fn, tn, dn),
                )

            q("20260827", "2330", "台積電", "TW", 0.5, 40000, 500, 100, 0)
            q("20260827", "2454", "聯發科", "TW", 0.2, 8000, 80, 20, 0)
            q("20260827", "2002", "中鋼", "TW", -0.3, 20000, 200, 50, 0)
            q("20260827", "2027", "大成鋼", "TW", -0.1, 5000, 40, 10, 0)
            q("20260828", "2330", "台積電", "TW", 1.2, 50000, 8000, 400, 50)
            q("20260828", "2454", "聯發科", "TW", 0.8, 9000, 1200, 300, 20)
            q("20260828", "2002", "中鋼", "TW", -1.5, 18000, -3000, -400, -50)
            q("20260828", "2027", "大成鋼", "TW", -0.8, 4000, -500, -80, -10)
            q("20260828", "0050", "元大台灣50", "TW", 0.4, 20000, 90000, 0, 0)
            conn.commit()
            conn.close()

            n = recompute_sector_flow(path, "20260828")
            self.assertGreaterEqual(n, 2)
            html = format_sector_rotation_html(path, "20260828")
            self.assertIn("盤後資金輪動", html)
            self.assertIn("半導體業", html)
            self.assertIn("鋼鐵工業", html)
            self.assertIn("2330", html)
            self.assertNotIn("元大台灣50", html)
            flow = format_flow_html(path, yyyymmdd="20260828")
            self.assertIn("盤後資金輪動", flow)
            self.assertIn("個股資金", flow)
            items = [{"stock_id": "2330", "stock_name": "台積電", "close": 100, "pct_change": 1.2, "volume": 50000}]
            annotate_items_with_sector_flow(path, "20260828", items)
            self.assertTrue(items[0].get("sector_inflow"))
            self.assertIn("半導體", items[0].get("sector_flow_label") or "")
            card = _stock_card_html({**items[0], "ma20": 98, "ma60": 95}, 1)
            self.assertIn("輪動進", card)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
