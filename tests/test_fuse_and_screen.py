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
        chased = dict(item)
        chased["chase_warning"] = True
        self.assertIn("少追", _stock_card_html(chased, 1))
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

    def test_release_publish_requires_complete_day(self):
        from import_health import can_publish_release, release_publish_blockers
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            reasons = release_publish_blockers(path, cap="20260831", min_quote_rows=100)
            self.assertTrue(reasons)
            self.assertFalse(can_publish_release(path, cap="20260831")["ok"])
            blob = " ".join(reasons)
            self.assertTrue("日K" in blob or "都齊" in blob or "月營收" in blob)
        finally:
            os.remove(path)

    def test_etf_blank_industry_defaults_to_etf(self):
        from universe import default_industry

        self.assertEqual(default_industry("ETF_PASSIVE", ""), "ETF")
        self.assertEqual(default_industry("STOCK", "半導體業"), "半導體業")
        self.assertEqual(default_industry("STOCK", ""), "")

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

    def test_industry_brief_plain_language(self):
        from fundamentals import ensure_fundamentals_tables
        from industry_brief import format_industry_html
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            ensure_fundamentals_tables(path)
            conn = sqlite3.connect(path)
            now = "2026-08-31T00:00:00"
            univ = [
                ("2330", "台積電", "TWSE", "STOCK", "半導體業"),
                ("2454", "聯發科", "TWSE", "STOCK", "半導體業"),
                ("2303", "聯電", "TWSE", "STOCK", "半導體業"),
                ("2002", "中鋼", "TWSE", "STOCK", "鋼鐵工業"),
                ("2027", "大成鋼", "TWSE", "STOCK", "鋼鐵工業"),
                ("0050", "元大台灣50", "TWSE", "ETF_PASSIVE", "ETF"),
            ]
            for sid, name, mkt, atype, ind in univ:
                conn.execute(
                    "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
                    (sid, name, mkt, atype, ind, now),
                )
            month = "202607"
            for sid, name, yoy, mom in (
                ("2330", "台積電", 40.0, 5.0),
                ("2454", "聯發科", 8.0, 1.0),
                ("2303", "聯電", 5.0, 0.0),
                ("2002", "中鋼", -10.0, -2.0),
                ("2027", "大成鋼", -8.0, 0.0),
            ):
                conn.execute(
                    "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, month, name, "TW", "半導體業" if sid[0] == "2" and sid != "2002" and sid != "2027" else "鋼鐵工業", 1000, mom, yoy, yoy),
                )
            conn.execute(
                "INSERT INTO quarterly_income(stock_id,year,season,stock_name,market,revenue,gross_profit,gross_margin_pct,operating_income,net_income,eps) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("2330", 2026, 2, "台積電", "TW", 10000, 5800, 58.0, 4000, 3500, 10.0),
            )
            conn.execute(
                "INSERT INTO quarterly_income(stock_id,year,season,stock_name,market,revenue,gross_profit,gross_margin_pct,operating_income,net_income,eps) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("2454", 2026, 2, "聯發科", "TW", 5000, 1000, 20.0, 400, 300, 2.0),
            )
            conn.execute(
                "INSERT INTO quarterly_income(stock_id,year,season,stock_name,market,revenue,gross_profit,gross_margin_pct,operating_income,net_income,eps) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("2303", 2026, 2, "聯電", "TW", 4000, 800, 20.0, 200, 150, 1.0),
            )
            q = (
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            )
            for sid, name, fn in (("2330", "台積電", 8000), ("2454", "聯發科", 1200), ("2303", "聯電", 500)):
                conn.execute(q, ("20260828", sid, name, "TW", 100, 101, 99, 100, 10000, 50000, 1.0, 100, fn, 0, 0))
            for sid, name, fn in (("2002", "中鋼", -3000), ("2027", "大成鋼", -500)):
                conn.execute(q, ("20260828", sid, name, "TW", 30, 31, 29, 30, 8000, 20000, -1.0, 30, fn, 0, 0))
            conn.commit()
            conn.close()
            html = format_industry_html("2330", path)
            self.assertIn("產業說明", html)
            self.assertIn("半導體業", html)
            self.assertIn("比同業明顯較強", html)
            self.assertIn("高低卡", html)
            self.assertIn("不是內幕", html)
            self.assertIn("<code>", html)
            self.assertIn("張", html)
            etf = format_industry_html("0050", path)
            self.assertIn("ETF", etf)
        finally:
            os.remove(path)


class TelegramAlignTest(unittest.TestCase):
    def test_html_qty_same_width_so_zhang_aligns(self):
        import re
        from tg_layout import html_qty, html_pct

        a = html_qty(12)
        b = html_qty(-1234)
        c = html_qty(10000, signed=False)
        self.assertTrue(a.endswith("張"))
        self.assertTrue(b.endswith("張"))
        self.assertTrue(c.endswith("張"))

        def body(s: str) -> str:
            m = re.search(r"<code>(.*?)</code>", s)
            self.assertIsNotNone(m)
            return m.group(1)

        self.assertEqual(len(body(a)), len(body(b)))
        self.assertEqual(len(body(c)), 9)
        p1 = html_pct(1.2)
        p2 = html_pct(-12.5)
        self.assertTrue(p1.endswith("%"))
        self.assertEqual(len(body(p1)), len(body(p2)))

    def test_chip_html_does_not_escape_code_tags(self):
        from screening_engine import _chip_html, _stock_card_html

        item = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100,
            "volume": 12345,
            "pct_change": 1.2,
            "foreign_net": 8000,
            "trust_net": -200,
            "dealer_net": 0,
        }
        chips = _chip_html(item)
        self.assertIn("<code>", chips)
        self.assertIn("張", chips)
        card = _stock_card_html(item, 1)
        self.assertIn("<code>", card)
        self.assertNotIn("&lt;code&gt;", card)


if __name__ == "__main__":
    unittest.main()
