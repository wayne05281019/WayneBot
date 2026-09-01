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
        self.assertEqual(fuse_end_date(mid), "20260828")
        almost = datetime(2026, 8, 31, 16, 29, tzinfo=ZoneInfo("Asia/Taipei"))
        self.assertEqual(fuse_end_date(almost), "20260828")
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
        self.assertNotIn("＝＝當沖", blob)
        self.assertIn("今日無符合條件標的", blob)
        line = format_line_share_text({"day_trade": [item]}, "20260828")
        self.assertIn("主選單", line)
        self.assertIn("當沖", line)
        self.assertNotIn("保險進場", line)
        self.assertNotIn("＝＝當沖＝＝", line)
        self.assertNotIn("整則複製", line)
        snap = {
            "regime": "caution",
            "us_phase": "post",
            "dji_pct": -0.8,
            "spx_pct": -1.0,
            "ixic_pct": -1.3,
            "sox_pct": -2.1,
            "nq_f_pct": -0.4,
            "es_f_pct": -0.2,
            "ym_f_pct": -0.1,
            "tsm_pct": -1.0,
            "tsm_post_pct": -2.2,
            "nvda_pct": -0.5,
            "nvda_post_pct": -1.8,
            "vix": 19.0,
            "vix_pct": 4.0,
        }
        night_line = format_line_share_text(
            {"day_trade": [item]},
            "20260828",
            session_plain="今早 06:30　昨收名單",
            us_snap=snap,
        )
        self.assertIn("電子夜盤", night_line)
        self.assertIn("＝＝夜盤判斷＝＝", night_line)
        from screening_engine import split_line_share_chunks

        chunks = split_line_share_chunks(night_line)
        self.assertTrue(chunks)
        self.assertIn("轉寄稿", chunks[0])
        self.assertIn("長按這一則", chunks[0])

    def test_screen_push_omits_daytrade_and_overnight(self):
        from screening_engine import SCREEN_PUSH_SPECS, format_screening_payload

        keys = {s[0] for s in SCREEN_PUSH_SPECS}
        self.assertNotIn("day_trade", keys)
        self.assertNotIn("overnight", keys)
        item = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100,
            "volume": 8000,
            "pct_change": 2,
            "q60r": 2.1,
            "ma20": 98,
            "ma60": 95,
            "foreign_net": 0,
            "trust_net": 0,
            "dealer_net": 0,
        }
        payload = format_screening_payload(
            {"leave_zero": [item], "day_trade": [item], "overnight": [item]},
            "20260828",
        )
        blob = "\n".join(p["html"] for p in payload)
        self.assertIn("起漲", blob)
        self.assertNotIn("＝＝當沖", blob)
        self.assertNotIn("＝＝隔日沖", blob)
        self.assertNotIn("主選單", blob)

    def test_leave_zero_is_first_screening_section(self):
        from screening_engine import format_line_share_text, format_screening_payload

        leave = {"stock_id": "2610", "stock_name": "華航", "close": 20, "pct_change": 1.2, "volume": 8000}
        hot = {"stock_id": "2330", "stock_name": "台積電", "close": 100, "pct_change": 2.0, "volume": 50000}
        payload = format_screening_payload(
            {"leave_zero": [leave] * 9, "revenue_cross": [hot]},
            "20260828",
        )
        keys = [p.get("mark_key") for p in payload]
        self.assertEqual(keys[0], "leave_zero")
        self.assertIn("revenue_cross", keys)
        self.assertLess(keys.index("leave_zero"), keys.index("revenue_cross"))
        self.assertIn("起漲｜", payload[0]["html"])
        line = format_line_share_text(
            {"leave_zero": [leave], "revenue_cross": [hot]},
            "20260828",
        )
        self.assertLess(line.find("＝＝起漲｜"), line.find("＝＝優先看｜"))
        from config import scheduled_job_kind
        from line_hop import line_share_href, render_line_hop_html
        from screening_engine import format_line_share_packs

        self.assertEqual(scheduled_job_kind("30 22 * * 0-4"), "morning_screen")
        self.assertEqual(scheduled_job_kind("30 8 * * 1-5"), "increment")
        packs = format_line_share_packs(
            {"leave_zero": [leave], "day_trade": [hot]},
            "20260828",
            session_plain="今早 06:30",
            us_snap={"regime": "ok", "us_phase": "post", "sox_pct": -2.0, "tsm_pct": -2.1, "nvda_pct": -1.5},
        )
        ids = [p["id"] for p in packs]
        self.assertEqual(ids, ["night", "layout", "trade"])
        self.assertIn("電子夜盤", packs[0]["text"])
        self.assertIn("＝＝起漲｜", packs[1]["text"])
        self.assertIn("說明：", packs[1]["text"])
        self.assertIn("主選單", packs[2]["text"])
        self.assertNotIn("＝＝當沖＝＝", packs[2]["text"])
        href = line_share_href("測試")
        self.assertTrue(href.startswith("https://line.me/R/share?text="))
        page = render_line_hop_html("開 LINE・起漲", packs[1]["text"])
        self.assertIn("line.me/R/share", page)
        self.assertNotIn("哥哥", page)
        self.assertNotIn("自己選要傳給誰", page)

    def test_format_line_share_packs_ignores_us_regime_metadata(self):
        from screening_engine import format_line_share_packs

        item = {"stock_id": "2330", "stock_name": "台積電", "both_sessions": True}
        packs = format_line_share_packs(
            {"leave_zero": [item], "_us_regime": "risk_off"},
            "20260831",
            session_plain="今早 06:30",
        )
        self.assertEqual([p["id"] for p in packs], ["night", "layout", "trade"])
        self.assertIn("雙時段", packs[1]["text"])
        self.assertIn("2330", packs[1]["text"])

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
            self.assertIn("＝＝半導體業＝＝", html)
            self.assertIn("＝＝鋼鐵工業＝＝", html)
            self.assertIn("★ 買超最多", html)
            self.assertIn("★ 賣超最多", html)
            self.assertNotIn("分點不抓", html)
            self.assertNotIn("instant", html)
            self.assertNotIn("官方法人張數＋價量才進這張表", html)
            self.assertIn("2330", html)
            self.assertNotIn("元大台灣50", html)
            self.assertIn("tw.stock.yahoo.com/quote/2330", html)
            self.assertIn("┈┈┈", html)
            self.assertIn("較前日", html)
            for line in html.split("\n"):
                if "半導體業" in line or "鋼鐵工業" in line:
                    self.assertNotIn("張", line, line)
            self.assertIn("+9,970張", html)
            self.assertIn("+8,450張", html)
            self.assertNotIn("</code>張", html)
            flow = format_flow_html(path, yyyymmdd="20260828")
            self.assertIn("盤後資金輪動", flow)
            self.assertIn("個股資金", flow)
            self.assertIn("外資買超", flow)
            self.assertIn("1. ", flow)
            self.assertIn("2. ", flow)
            self.assertIn("tw.stock.yahoo.com/quote/", flow)
            self.assertIn("┈┈┈", flow)
            self.assertNotIn("分點不抓", flow)
            self.assertNotIn("instant", flow)
            self.assertGreaterEqual(flow.count("┈┈┈"), 3)
            self.assertNotIn("你的持股 vs", flow)
            self.assertNotIn("觀察清單", flow)
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


class ScreenReviewTest(unittest.TestCase):
    def test_next_day_score_and_weak_bucket_weight(self):
        from screen_review import (
            adapt_bucket_weights,
            bucket_weight,
            format_review_html,
            save_screen_picks,
            score_screen_picks,
        )
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260828", "2330", "台積電", "TW", 100, 101, 99, 102, 1000, 1000, 2.0, 100, 0, 0, 0),
            )
            conn.commit()
            conn.close()
            results = {
                "day_trade": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}],
                "select_01": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}],
            }
            self.assertEqual(save_screen_picks(path, "20260827", results), 2)
            n = score_screen_picks(path, "20260828")
            self.assertEqual(n, 2)
            html = format_review_html(path)
            self.assertIn("海選復盤", html)
            self.assertIn("+2.0%", html)
            conn = sqlite3.connect(path)
            for i in range(5):
                as_of = f"2026082{i}"
                conn.execute(
                    "INSERT OR REPLACE INTO screen_picks(as_of,bucket,stock_id,stock_name,pick_close,next_date,next_close,next_pct) VALUES (?,?,?,?,?,?,?,?)",
                    (as_of, "day_trade", f"1{i:03d}", "弱", 100, "20260828", 97, -3.0),
                )
            conn.commit()
            conn.close()
            adapt_bucket_weights(path)
            self.assertEqual(bucket_weight(path, "day_trade"), 0.0)
            self.assertGreater(bucket_weight(path, "select_01"), 0)
        finally:
            os.remove(path)


class USOvernightTest(unittest.TestCase):
    def test_classify_vix_and_index_drop(self):
        from us_overnight import classify_us_regime

        self.assertEqual(classify_us_regime({"vix": 15.0, "ixic_pct": 0.2, "spx_pct": 0.1, "dji_pct": 0.0, "sox_pct": 0.3}), "ok")
        self.assertEqual(classify_us_regime({"vix": 19.0, "ixic_pct": -0.4, "spx_pct": -0.2, "dji_pct": 0.0, "sox_pct": -0.5}), "caution")
        self.assertEqual(classify_us_regime({"vix": 14.0, "ixic_pct": -1.3, "spx_pct": -0.8, "dji_pct": -0.5, "sox_pct": -1.0}), "caution")
        self.assertEqual(classify_us_regime({"vix": 26.0, "ixic_pct": -0.5, "spx_pct": -0.4, "dji_pct": -0.2, "sox_pct": -0.3}), "risk_off")
        self.assertEqual(classify_us_regime({"vix": 16.0, "ixic_pct": -1.0, "spx_pct": -0.8, "dji_pct": -0.5, "sox_pct": -3.2}), "ok")
        self.assertEqual(classify_us_regime({}), "unknown")
        self.assertEqual(
            classify_us_regime({"vix": 15.0, "ixic_pct": 0.1, "spx_pct": 0.0, "dji_pct": 0.1, "nq_f_pct": -4.0}),
            "ok",
        )

    def test_electronics_night_side_and_plain(self):
        from us_overnight import electronics_night_side, format_night_plain

        self.assertEqual(electronics_night_side({}), "")
        self.assertEqual(
            electronics_night_side({"sox_pct": -2.0, "tsm_pct": -2.5, "nvda_pct": -1.5}),
            "跌",
        )
        self.assertEqual(
            electronics_night_side({"sox_pct": 1.5, "tsm_pct": 2.0, "nvda_pct": 1.2}),
            "漲",
        )
        self.assertEqual(
            electronics_night_side({"sox_pct": 0.2, "tsm_pct": -0.3, "nvda_pct": 0.1}),
            "平",
        )
        snap = {
            "regime": "caution",
            "us_phase": "post",
            "dji_pct": -0.8,
            "spx_pct": -1.0,
            "ixic_pct": -1.3,
            "sox_pct": -2.0,
            "nq_f_pct": -0.4,
            "es_f_pct": -0.2,
            "ym_f_pct": -0.1,
            "tsm_pct": -1.0,
            "tsm_post_pct": -2.2,
            "nvda_pct": -0.5,
            "nvda_post_pct": -1.8,
            "vix": 19.0,
            "vix_pct": 4.0,
        }
        night = format_night_plain(snap)
        self.assertIn("＝＝夜盤判斷＝＝", night)
        self.assertIn("電子夜盤", night)
        self.assertIn("跌", night)
        self.assertIn("盤後續勢", night)
        self.assertIn("台指期", night)

    def test_line_share_persists_for_forward_button(self):
        from screen_sessions import load_line_share, save_line_share
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            save_line_share(path, "20260828", "WayneBot 海選　2026/08/28\n1. 2330 台積電")
            self.assertIn("2330", load_line_share(path, "20260828"))
            self.assertIn("2330", load_line_share(path))
        finally:
            os.remove(path)

    def test_risk_off_clears_intraday_and_tags_chips(self):
        from screening_engine import format_screening_payload
        from us_overnight import apply_us_overnight, format_us_html

        chip = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "industry": "半導體業",
            "chase_warning": False,
            "q60r": 2.0,
            "close": 100,
            "volume": 5000,
        }
        steel = {
            "stock_id": "2002",
            "stock_name": "中鋼",
            "industry": "鋼鐵工業",
            "chase_warning": False,
            "q60r": 2.2,
            "close": 30,
            "volume": 8000,
        }
        results = {
            "day_trade": [dict(chip), dict(steel)],
            "overnight": [dict(chip)],
            "select_01": [dict(chip), dict(steel)],
        }
        snap = {"regime": "risk_off", "vix": 28.0, "sox_pct": -3.5, "ixic_pct": -2.8, "us_session": "20260829"}
        apply_us_overnight(results, snap)
        self.assertEqual(results["day_trade"], [])
        self.assertEqual(results["overnight"], [])
        by_id = {x["stock_id"]: x for x in results["select_01"]}
        self.assertTrue(by_id["2330"].get("us_peer_headwind"))
        self.assertFalse(by_id["2002"].get("us_peer_headwind"))
        self.assertEqual(results["select_01"][0]["stock_id"], "2002")
        html = format_us_html(snap)
        self.assertIn("VIX", html)
        self.assertNotIn("當沖／隔日沖今日不列", html)
        payload = format_screening_payload(results, "20260828")
        blob = "\n".join(p["html"] for p in payload)
        self.assertNotIn("美股收盤", blob)
        self.assertNotIn("＝＝當沖", blob)
        self.assertIn("隔夜逆風", blob)

    def test_caution_drops_chase_and_chip_headwind(self):
        from us_overnight import apply_us_overnight

        results = {
            "day_trade": [
                {"stock_id": "2330", "industry": "半導體業", "chase_warning": False, "q60r": 3},
                {"stock_id": "2303", "industry": "半導體業", "chase_warning": True, "q60r": 4},
                {"stock_id": "2002", "industry": "鋼鐵工業", "chase_warning": False, "q60r": 2},
            ]
        }
        apply_us_overnight(results, {"regime": "caution", "sox_pct": -1.8, "vix": 19})
        ids = [x["stock_id"] for x in results["day_trade"]]
        self.assertEqual(ids, ["2002"])

    def test_sox_dump_filters_chips_only(self):
        from us_overnight import apply_us_overnight, classify_us_regime

        snap = {"regime": "ok", "vix": 15.2, "ixic_pct": -0.5, "sox_pct": -3.5, "tsm_pct": -2.3}
        self.assertEqual(classify_us_regime(snap), "ok")
        results = {
            "day_trade": [
                {"stock_id": "2330", "industry": "半導體業", "chase_warning": False, "q60r": 3},
                {"stock_id": "2002", "industry": "鋼鐵工業", "chase_warning": False, "q60r": 2},
            ],
            "select_01": [
                {"stock_id": "2330", "industry": "半導體業", "chase_warning": False, "q60r": 3},
                {"stock_id": "2002", "industry": "鋼鐵工業", "chase_warning": False, "q60r": 2},
            ],
        }
        apply_us_overnight(results, snap)
        self.assertEqual([x["stock_id"] for x in results["day_trade"]], ["2002"])
        self.assertTrue(results["select_01"][1].get("us_peer_headwind") or results["select_01"][0].get("us_peer_headwind"))
        by_id = {x["stock_id"]: x for x in results["select_01"]}
        self.assertTrue(by_id["2330"].get("us_peer_headwind"))
        self.assertFalse(by_id["2002"].get("us_peer_headwind"))

    def test_tape_phase_ignores_futures_during_cash(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from us_overnight import classify_us_regime, us_tape_phase

        ny = ZoneInfo("America/New_York")
        self.assertEqual(us_tape_phase(datetime(2026, 8, 31, 11, 30, tzinfo=ny)), "regular")
        self.assertEqual(us_tape_phase(datetime(2026, 8, 31, 17, 15, tzinfo=ny)), "post")
        self.assertEqual(us_tape_phase(datetime(2026, 8, 31, 21, 0, tzinfo=ny)), "overnight")
        self.assertEqual(us_tape_phase(datetime(2026, 8, 30, 18, 30, tzinfo=ny)), "overnight")
        tw = datetime(2026, 9, 1, 6, 30, tzinfo=ZoneInfo("Asia/Taipei"))
        self.assertEqual(us_tape_phase(tw), "post")
        self.assertEqual(
            classify_us_regime({"vix": 15.0, "ixic_pct": 0.1, "spx_pct": 0.0, "dji_pct": 0.1, "nq_f_pct": -4.0}),
            "ok",
        )
        self.assertEqual(
            classify_us_regime(
                {
                    "vix": 15.0,
                    "ixic_pct": 0.1,
                    "spx_pct": 0.0,
                    "dji_pct": 0.1,
                    "nq_f_pct": -1.4,
                    "us_phase": "post",
                }
            ),
            "caution",
        )
        self.assertEqual(
            classify_us_regime(
                {
                    "vix": 15.0,
                    "ixic_pct": 0.1,
                    "spx_pct": 0.0,
                    "dji_pct": 0.1,
                    "nq_f_pct": -2.8,
                    "us_phase": "post",
                }
            ),
            "risk_off",
        )

    def test_post_tsm_dump_tags_chips(self):
        from us_overnight import apply_us_overnight

        results = {
            "day_trade": [
                {"stock_id": "2330", "industry": "半導體業", "chase_warning": False, "q60r": 3},
                {"stock_id": "2002", "industry": "鋼鐵工業", "chase_warning": False, "q60r": 2},
            ]
        }
        apply_us_overnight(
            results,
            {
                "regime": "ok",
                "vix": 14.0,
                "ixic_pct": 0.2,
                "tsm_pct": 0.3,
                "tsm_post_pct": -2.4,
                "us_phase": "post",
            },
        )
        self.assertEqual([x["stock_id"] for x in results["day_trade"]], ["2002"])

    def test_drop_alert_only_when_weak(self):
        from us_overnight import format_us_drop_alert, format_us_html, should_alert_us_drop

        flat = {"regime": "ok", "vix": 15.0, "ixic_pct": 0.2, "spx_pct": 0.1, "dji_pct": 0.0}
        self.assertFalse(should_alert_us_drop(flat))
        self.assertFalse(
            should_alert_us_drop({"regime": "caution", "vix": 19.0, "ixic_pct": 0.1, "spx_pct": 0.0, "dji_pct": 0.2})
        )
        dump = {
            "regime": "risk_off",
            "vix": 27.0,
            "ixic_pct": -2.8,
            "spx_pct": -2.1,
            "dji_pct": -1.9,
            "sox_pct": -3.0,
            "nq_f_pct": -3.1,
            "tsm_post_pct": -2.4,
            "us_phase": "post",
            "us_session": "20260831",
        }
        self.assertTrue(should_alert_us_drop(dump))
        html = format_us_drop_alert(dump)
        self.assertIn("一早提醒", html)
        self.assertIn("那斯達克", html)
        self.assertIn("盤後", html)
        self.assertIn("盤後", format_us_html(dump))
        self.assertTrue(
            should_alert_us_drop(
                {"regime": "ok", "vix": 14.0, "ixic_pct": 0.1, "tsm_pct": 0.2, "tsm_post_pct": -2.2, "us_phase": "post"}
            )
        )

    def test_last_post_bar_skips_cash_session(self):
        from us_overnight import last_post_from_block

        block = {
            "meta": {
                "previousClose": 100.0,
                "currentTradingPeriod": {
                    "regular": {"start": 1000, "end": 2000},
                    "post": {"start": 2000, "end": 3000},
                },
            },
            "timestamp": [1500, 1999, 2000, 2500, 3100],
            "indicators": {"quote": [{"close": [101.0, 102.0, 99.0, 97.5, 50.0]}]},
        }
        got = last_post_from_block(block)
        self.assertAlmostEqual(got["price"], 97.5)
        self.assertAlmostEqual(got["pct"], -2.5)
        cash_only = {
            "meta": {
                "previousClose": 100.0,
                "currentTradingPeriod": {
                    "regular": {"start": 1000, "end": 2000},
                    "post": {"start": 2000, "end": 3000},
                },
            },
            "timestamp": [1500, 1800],
            "indicators": {"quote": [{"close": [101.0, 102.0]}]},
        }
        self.assertIsNone(last_post_from_block(cash_only))


class LiveQuoteLabelTest(unittest.TestCase):
    def test_1330_is_close_not_intraday(self):
        from live_quote import format_mis_clock_line, live_clock_suffix, mis_session_label

        self.assertEqual(mis_session_label("13:30:00"), "收盤")
        self.assertEqual(mis_session_label("13:30"), "收盤")
        self.assertEqual(mis_session_label("14:00:00"), "收盤")
        self.assertEqual(mis_session_label("13:25:18"), "盤中")
        self.assertEqual(mis_session_label("09:01:00"), "盤中")
        self.assertEqual(mis_session_label("08:50:00"), "收盤")
        line = format_mis_clock_line("13:30:00")
        self.assertTrue(line.startswith("收盤"))
        self.assertIn("13:30:00", line)
        self.assertIn("證交所 MIS", line)
        self.assertNotIn("盤中", line)
        self.assertIn("收盤 13:30", live_clock_suffix(True, "13:30:00"))
        self.assertIn("盤中 13:25", live_clock_suffix(True, "13:25:18"))
        self.assertEqual(live_clock_suffix(False, "13:30:00"), "")


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

    def test_html_qty_tight_keeps_zhang_in_same_tag(self):
        from tg_layout import html_pct_tight, html_qty_tight, join_dashed

        q = html_qty_tight(89001)
        self.assertEqual(q, "<code>+89,001張</code>")
        self.assertNotIn("</code>張", q)
        self.assertEqual(html_pct_tight(2.2), "<code>+2.2%</code>")
        dashed = join_dashed("上", "下")
        self.assertIn("┈┈┈", dashed)
        self.assertTrue(dashed.startswith("上"))
        self.assertTrue(dashed.endswith("下"))

    def test_html_price_and_money_align(self):
        import re
        from tg_layout import html_money, html_price

        def body(s: str) -> str:
            m = re.search(r"<code>(.*?)</code>", s)
            self.assertIsNotNone(m)
            return m.group(1)

        self.assertEqual(len(body(html_price(12.5))), len(body(html_price(1234.5))))
        self.assertEqual(len(body(html_money(500000, signed=False))), len(body(html_money(12, signed=False))))

    def test_num_paren_aligns_and_stays_one_code(self):
        import re
        from tg_layout import html_last_move, html_num_paren, section_eq

        a = html_num_paren("+0", 0.0)
        b = html_num_paren("18.18", -7.0)
        c = html_num_paren("21.11", 8.0)
        self.assertEqual(a.count("<code>"), 1)
        self.assertNotIn("</code>（", a)
        self.assertIn("（+0.0%）", a)
        self.assertIn("（-7.0%）", b)
        ia, ib, ic = a.index("（"), b.index("（"), c.index("（")
        self.assertEqual(ia, ib)
        self.assertEqual(ib, ic)
        move = html_last_move(19.55, 0.15, 0.77)
        self.assertEqual(move.count("<code>"), 1)
        self.assertIn("▲0.15（+0.77%）", move)
        self.assertEqual(section_eq("AI 模擬帳戶"), "<b>== AI 模擬帳戶 ==</b>")
        self.assertEqual(section_eq("我的持股（手記）"), "<b>== 我的持股（手記） ==</b>")

    def test_holdings_and_ai_titles_use_eq(self):
        from ai_trader import format_ai_desk_html
        from portfolio_engine import PortfolioEngine
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            eng = PortfolioEngine(path)
            mine = eng.format_holdings_html([])
            self.assertIn("== 我的持股（手記） ==", mine)
            ai = format_ai_desk_html(eng)
            self.assertIn("== AI 模擬帳戶 ==", ai)
            filled = eng.format_holdings_html(
                [{"stock_code": "3703", "stock_name": "欣陸", "shares": 8, "cost_price": 19.55}]
            )
            self.assertIn("== 我的持股（手記） ==", filled)
            self.assertIn("<code>", filled)
            self.assertNotIn("</code>（", filled)
        finally:
            os.remove(path)

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


class DualSessionTest(unittest.TestCase):
    def test_overlap_marks_and_line_share(self):
        from screen_sessions import mark_both_sessions, overlap_ids, save_screen_session
        from screening_engine import format_line_share_text
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            eve = {
                "day_trade": [
                    {"stock_id": "2330", "stock_name": "台積電", "close": 100, "hi20_close": 110},
                    {"stock_id": "2002", "stock_name": "中鋼", "close": 30, "hi20_close": 32},
                ]
            }
            morn = {
                "day_trade": [
                    {"stock_id": "2330", "stock_name": "台積電", "close": 100, "hi20_close": 110, "chase_warning": False},
                    {"stock_id": "2303", "stock_name": "聯電", "close": 50, "hi20_close": 51, "chase_warning": True},
                ]
            }
            save_screen_session(path, "20260828", "evening", eve)
            save_screen_session(path, "20260828", "morning", morn)
            both = overlap_ids(path, "20260828")
            self.assertEqual(both, {"2330"})
            mark_both_sessions(morn, both)
            self.assertTrue(morn["day_trade"][0].get("both_sessions"))
            self.assertEqual(morn["day_trade"][0]["stock_id"], "2330")
            line = format_line_share_text(morn, "20260828", session_plain="今早 06:30")
            self.assertIn("雙時段", line)
            self.assertIn("2330", line)
            self.assertNotIn("tw.stock.yahoo.com/quote/2330", line)
        finally:
            os.remove(path)

    def test_midday_classify_uses_high_low_card(self):
        from midday_review import classify_row, format_midday_line

        row = {"hi20_close": 120.0, "entry_price": 99.0}
        self.assertEqual(classify_row(row, {"close": 97}), "ok")
        self.assertEqual(classify_row(row, {"close": 119}), "chase")
        self.assertEqual(classify_row(row, {"close": 100}), "above_entry")
        text = format_midday_line("20260828", {"ok": ["2330 台積電 現97"], "chase": [], "above_entry": [], "no_quote": []})
        self.assertIn("建議切入", text)
        self.assertIn("06:30", text)

    def test_job_kind_evening_and_midday(self):
        from config import job_kind

        old = os.environ.get("WAYNE_JOB")
        try:
            os.environ["WAYNE_JOB"] = "midday_review"
            self.assertEqual(job_kind([]), "midday_review")
            os.environ["WAYNE_JOB"] = "evening_screen"
            self.assertEqual(job_kind([]), "evening_screen")
        finally:
            if old is None:
                os.environ.pop("WAYNE_JOB", None)
            else:
                os.environ["WAYNE_JOB"] = old


class LookupCardTest(unittest.TestCase):
    def test_horizon_low_cells_order(self):
        from wayne_navigator import horizon_low_cells

        cells = horizon_low_cells(
            {
                "l120": 70,
                "dist_l120": 1.0,
                "l240": 60,
                "dist_l240": 10.0,
                "l480": 50,
                "dist_l480": 20.0,
            }
        )
        self.assertEqual([c[0] for c in cells], ["120低", "240低", "480低"])
        self.assertEqual(cells[0][1], 70.0)

    def test_label_and_value_never_collide_on_one_row(self):
        import matplotlib

        matplotlib.use("Agg")
        from wayne_navigator import _text_w, fit_label_value

        row_w, fig_w, gap = 91.6, 4.62, 5.5
        cases = [
            (["距120／240／480低", "距長期低"], "+237.0%　+563.0%　+836.3%"),
            (["距120／240／480低", "距長期低"], "+1237.0%　+5563.0%　+8836.3%"),
            ("距20日高（賣壓）", "+0.0%"),
            ("月／季空間", "42%　／　157%"),
        ]
        for labels, value in cases:
            with self.subTest(value=value):
                label, fa, fb = fit_label_value(labels, value, row_w, fig_w, gap=gap)
                used = (_text_w(label, fa, fig_w, 800)
                        + _text_w(value, fb, fig_w, 800))
                self.assertLessEqual(used + gap, row_w + 0.01)
                self.assertGreaterEqual(fb, 9.5)

    def test_nav_arrow_darkens_on_same_hue_band(self):
        from wayne_navigator import _NAV_TONE, _nav_tone, _wcag

        h20, l20 = 100.0, 60.0
        # 高點箭頭飄到粉紅區、低點箭頭掉到綠區時要換深色，否則融進背景。
        self.assertEqual(_nav_tone("h20_near", 105.0, h20, l20), _NAV_TONE["h20_near"][1])
        self.assertEqual(_nav_tone("h20_near", 80.0, h20, l20), _NAV_TONE["h20_near"][0])
        self.assertEqual(_nav_tone("l20_near", 55.0, h20, l20), _NAV_TONE["l20_near"][1])
        self.assertEqual(_nav_tone("l20_near", 80.0, h20, l20), _NAV_TONE["l20_near"][0])
        for kind, band in (("h20_near", "#F8BBD0"), ("l20_near", "#C8E6C9")):
            with self.subTest(kind=kind):
                light, dark = _NAV_TONE[kind]
                self.assertGreater(_wcag(dark, band), _wcag(light, band))

    def test_card_white_text_backgrounds_have_enough_contrast(self):
        from wayne_navigator import _CARD, _wcag

        for key in ("pill_hi", "pill_lo", "tag", "navy"):
            with self.subTest(key=key):
                self.assertGreaterEqual(_wcag("#FFFFFF", _CARD[key]), 4.5)

    def test_profit_cell_uses_low_palette_not_hardcoded_pink(self):
        import inspect

        from wayne_navigator import (
            _CARD,
            alert_cell_style,
            bias_cell_style,
            hl_cell_style,
            price_cell_style,
            profit_cell_style,
            render_decision_card_png,
            temp_cell_style,
            vol_rank_cell_style,
        )

        bg0, fg0 = profit_cell_style(0.0, None, _CARD["white"])
        self.assertEqual(bg0, _CARD["lo_fill"])
        self.assertEqual(fg0, _CARD["lo_ink"])
        bg_leave, fg_leave = profit_cell_style(0.9, 0.0, _CARD["white"])
        self.assertEqual(bg_leave, _CARD["lo_hit_fill"])
        bg_run, fg_run = profit_cell_style(1.5, 0.9, _CARD["white"])
        self.assertEqual(bg_run, _CARD["white"])
        self.assertNotEqual(bg_run, _CARD["hi_fill"])
        self.assertEqual(hl_cell_style("20低", _CARD["white"])[0], _CARD["lo_fill"])
        self.assertEqual(hl_cell_style("10高", _CARD["white"])[0], _CARD["hi_fill"])
        self.assertEqual(alert_cell_style("K20低", _CARD["white"])[0], _CARD["lo_fill"])
        self.assertEqual(temp_cell_style(76, _CARD["white"])[0], _CARD["temp_hot_bg"])
        self.assertEqual(vol_rank_cell_style(5, _CARD["white"])[0], _CARD["pill_hi"])
        self.assertEqual(bias_cell_style(1.2, _CARD["white"])[0], _CARD["hi_fill"])
        self.assertEqual(price_cell_style("5低", _CARD["white"])[0], _CARD["lo_fill"])
        src = inspect.getsource(render_decision_card_png)
        self.assertIn("profit_cell_style", src)
        self.assertIn("hl_cell_style", src)
        self.assertNotIn("#FBEAF1", src)

    def test_card_bold_and_body_use_different_font_weights(self):
        from wayne_navigator import _weight_step

        self.assertGreater(_weight_step("heavy" and 900), _weight_step(500))
        self.assertEqual(_weight_step(800), _weight_step(900))
        self.assertEqual(_weight_step(700), _weight_step(500))
        # 可變字型預設是 Thin，實際畫圖要用壓出來的靜態字重，不能落回 100。
        self.assertGreaterEqual(_weight_step(500), 400)

    def test_chips_table_cols_share_font_and_fit_span(self):
        import matplotlib

        matplotlib.use("Agg")
        from chips import fit_table_cols
        from wayne_navigator import _CARD, _text_w

        headers = ["日期", "收盤", "量", "外資", "投信", "自營", "合計", "超比", "10日累"]
        col_vals = [
            ["8/31", "8/28"],
            ["1,234.00", "12.50"],
            ["169,523", "12"],
            ["+10,702", "+4"],
            ["+1,266", "0"],
            ["-974,321", "+1"],
            ["+13,009", "-6"],
            ["+7.7%", "-0.1%"],
            ["+63,634", "+12"],
        ]
        fig_w, span = 7.2, 95.2
        xs, body_fs, _hdr_fs = fit_table_cols(headers, col_vals, fig_w, span)
        self.assertEqual(len(xs), 10)
        self.assertAlmostEqual(xs[-1], span, delta=0.05)
        self.assertGreaterEqual(body_fs, 9.0)
        # 最寬那欄（自營 -974,321）仍放得進自己的格子，不會吃隔壁。
        i = headers.index("自營")
        w = xs[i + 1] - xs[i]
        self.assertLessEqual(_text_w("-974,321", body_fs, fig_w, 800) + 2.4, w + 0.05)
        for key in ("hi_fill", "lo_fill", "tbl_hdr", "navy"):
            self.assertIn(key, _CARD)

    def test_chips_png_from_rows(self):
        import os
        import tempfile

        import matplotlib

        matplotlib.use("Agg")
        from chips import render_chips_png

        rows = [
            {
                "date": "20260831",
                "stock_name": "南亞",
                "close": 242.5,
                "volume": 169523,
                "foreign_net": 10702,
                "trust_net": 1266,
                "dealer_net": 1041,
                "three_net": 13009,
                "ratio_pct": 7.7,
                "acc_10d": 63634,
            },
            {
                "date": "20260828",
                "stock_name": "南亞",
                "close": 220.5,
                "volume": 12,
                "foreign_net": -10,
                "trust_net": 0,
                "dealer_net": 4,
                "three_net": -6,
                "ratio_pct": -0.1,
                "acc_10d": 12,
            },
        ]
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            out = render_chips_png(rows, path, stock_id="1303")
            self.assertTrue(out)
            self.assertGreater(os.path.getsize(out), 8000)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_decision_card_png_with_long_lows(self):
        import tempfile

        import matplotlib

        matplotlib.use("Agg")
        import pandas as pd

        from wayne_navigator import render_decision_card_png

        table = pd.DataFrame(
            [
                {
                    "date": "20260828",
                    "close": 51.0,
                    "獲利": "2.0%",
                    "高低": "No",
                    "預警": "No",
                    "溫度計": "55.0 °C",
                    "月乖離": "+1.0%",
                    "profit_pct": 2.0,
                    "bias_monthly": 1.0,
                    "vol_rank_120": 20,
                    "120日量": "第 20 名",
                }
            ]
        )
        card = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 51.0,
            "change_pct": 1.2,
            "h10": 55,
            "dist_h10": -7.3,
            "h20": 56,
            "dist_h20": -8.9,
            "h60": 60,
            "dist_h60": -15.0,
            "l10": 50,
            "dist_l10": 2.0,
            "l20": 49,
            "dist_l20": 4.1,
            "l60": 48,
            "dist_l60": 6.3,
            "l120": 50.5,
            "dist_l120": 1.0,
            "l240": 45,
            "dist_l240": 13.3,
            "l480": 40,
            "dist_l480": 27.5,
            "space_20": 14,
            "space_60": 25,
            "ma60s": 0.5,
            "qty60": 20000,
            "badges": ["近120日低"],
            "table": table,
        }
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            out = render_decision_card_png(card, path)
            self.assertTrue(out)
            self.assertGreater(os.path.getsize(out), 8000)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_decision_card_png_one_row_not_stretched(self):
        import tempfile

        import matplotlib

        matplotlib.use("Agg")
        import pandas as pd
        from PIL import Image

        from wayne_navigator import render_decision_card_png

        def row(date):
            return {
                "date": date,
                "close": 51.0,
                "獲利": "2.0%",
                "高低": "No",
                "預警": "No",
                "溫度計": "55.0 °C",
                "月乖離": "+1.0%",
                "profit_pct": 2.0,
                "bias_monthly": 1.0,
                "vol_rank_120": 20,
                "120日量": "第 20 名",
            }

        card = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 51.0,
            "change_pct": 1.2,
            "h10": 55,
            "dist_h10": -7.3,
            "h20": 56,
            "dist_h20": -8.9,
            "h60": 60,
            "dist_h60": -15.0,
            "l10": 50,
            "dist_l10": 2.0,
            "l20": 49,
            "dist_l20": 4.1,
            "l60": 48,
            "dist_l60": 6.3,
            "l120": 50.5,
            "dist_l120": 1.0,
            "l240": 45,
            "dist_l240": 13.3,
            "l480": 40,
            "dist_l480": 27.5,
            "space_20": 14,
            "space_60": 25,
            "ma60s": 0.5,
            "qty60": 20000,
            "badges": ["近120日低"],
        }
        dates = [
            "20260819",
            "20260820",
            "20260821",
            "20260822",
            "20260825",
            "20260826",
            "20260827",
            "20260828",
        ]
        long_dates = [f"202607{d:02d}" for d in range(1, 21)]
        paths, heights = [], []
        try:
            for tbl in (
                pd.DataFrame([row("20260828")]),
                pd.DataFrame([row(d) for d in dates]),
                pd.DataFrame([row(d) for d in long_dates]),
            ):
                fd, path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                paths.append(path)
                card["table"] = tbl
                render_decision_card_png(card, path)
                with Image.open(path) as im:
                    heights.append(im.size[1])
            h1, h8, h20 = heights
            # 列高固定：加幾列就長幾列的高度，1 列不會被拉滿整頁。
            per_row = (h8 - h1) / 7.0
            self.assertGreater(per_row, 20)
            self.assertLess(per_row, 120)
            self.assertAlmostEqual((h20 - h8) / 12.0, per_row, delta=2.0)
            overhead = h1 - per_row
            self.assertGreater(overhead, per_row * 8)
        finally:
            for path in paths:
                if os.path.exists(path):
                    os.remove(path)

    def test_mis_quote_cache_hits_once(self):
        import live_quote

        calls = []

        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "msgArray": [
                        {
                            "c": "2330",
                            "n": "台積電",
                            "z": "100",
                            "y": "99",
                            "o": "99",
                            "h": "101",
                            "l": "98",
                            "v": "1",
                            "t": "13:00",
                            "b": "",
                            "a": "",
                        }
                    ]
                }

        def fake_get(*_a, **_k):
            calls.append(1)
            return FakeResp()

        old = live_quote._SESSION.get
        live_quote._SESSION.get = fake_get
        with live_quote._QUOTE_LOCK:
            live_quote._QUOTE_CACHE.clear()
        try:
            a = live_quote.fetch_mis_quote("2330", "TW")
            b = live_quote.fetch_mis_quote("2330", "TW")
            self.assertEqual(len(calls), 1)
            self.assertEqual(a["close"], b["close"])
            self.assertEqual(float(a["close"]), 100.0)
            self.assertEqual(a["change"], 1.0)
        finally:
            live_quote._SESSION.get = old
            with live_quote._QUOTE_LOCK:
                live_quote._QUOTE_CACHE.clear()

    def test_stock_btn_shows_code_and_name(self):
        from tg_layout import stock_btn_label

        self.assertEqual(stock_btn_label("2330", "台積電"), "2330 台積電")
        self.assertNotIn("看這檔", stock_btn_label("2303", "聯電"))

    def test_html_move_shows_dollars_like_yahoo(self):
        from tg_layout import html_move, price_change

        down = html_move(-5.50, -3.05)
        self.assertIn("▼", down)
        self.assertIn("5.50", down)
        self.assertIn("-3.05%", down)
        up = html_move(5.50, 3.05)
        self.assertIn("▲", up)
        self.assertIn("+3.05%", up)
        self.assertEqual(price_change(175.0, -3.05, yesterday=180.5), -5.5)
        self.assertAlmostEqual(price_change(175.0, -3.05), -5.5, places=1)

    def test_chips_image_does_not_fetch_t86(self):
        import chips

        seen = {}

        def fake_load(*_a, **k):
            seen.update(k)
            return []

        old = chips.load_major_player_rows
        chips.load_major_player_rows = fake_load
        try:
            out = chips.generate_chips_image("2330", "missing.db", "/tmp/no_chips.png")
            self.assertEqual(out, "")
            self.assertIs(seen.get("allow_fetch"), False)
        finally:
            chips.load_major_player_rows = old

    def test_screen_ma60_cross_and_bounce(self):
        import pandas as pd
        from screening_engine import ScreeningEngine, format_line_share_text

        def bars(closes):
            from datetime import datetime, timedelta

            rows = []
            start = datetime(2026, 1, 5)
            for i, c in enumerate(closes):
                prev = closes[i - 1] if i else c
                pct = round((c - prev) / prev * 100.0, 2) if prev else 0
                d = (start + timedelta(days=i)).strftime("%Y%m%d")
                rows.append(
                    {
                        "date": d,
                        "stock_id": "2330",
                        "stock_name": "台積電",
                        "market": "TW",
                        "open": c - 0.2,
                        "high": c + 1,
                        "low": c - 1,
                        "close": c,
                        "volume": 8000,
                        "turnover_k": 80000,
                        "pct_change": pct,
                        "avg_price": c,
                        "foreign_net": 0,
                        "trust_net": 0,
                        "dealer_net": 0,
                    }
                )
            return pd.DataFrame(rows)

        engine = ScreeningEngine(db_path=":memory:")
        # 前段在季線下，最後一根站上
        cross = [90.0] * 68 + [88.0, 96.0]
        out = engine.execute_all_strategies({"2330": bars(cross)})
        self.assertTrue(out["select_02"])
        line = format_line_share_text(out, "20260828")
        self.assertIn("站上季線", line)
        self.assertNotIn("半年高", line)
        self.assertNotIn("兩年高", line)

        bounce = [100.0] * 50 + [88.0] * 18 + [90.0]
        out2 = engine.execute_all_strategies({"2330": bars(bounce)})
        self.assertTrue(out2["select_03"])

        # 高低卡獲利：昨收貼近 60 曆日低，今日剛離開 0
        leave = [50.0] * 40 + [50.2, 52.0]
        out3 = engine.execute_all_strategies({"2330": bars(leave)})
        self.assertTrue(out3["leave_zero"])
        self.assertGreaterEqual(out3["leave_zero"][0].get("profit") or 0, 0.4)

    def test_leave_zero_excludes_obvious_downtrend(self):
        from screening_engine import ScreeningEngine, _leave_zero_trend_ok

        self.assertTrue(
            _leave_zero_trend_ok(
                {"close": 100, "ma20": 95, "ma60": 90, "low20": 88, "d20": 5, "pct_change": 2.0}
            )
        )
        self.assertFalse(
            _leave_zero_trend_ok(
                {"close": 80, "ma20": 95, "ma60": 100, "low20": 79, "d20": 3, "pct_change": 1.0}
            )
        )
        self.assertFalse(
            _leave_zero_trend_ok(
                {"close": 50, "ma20": 55, "ma60": 60, "low20": 50.2, "d20": 0.5, "pct_change": 0.8}
            )
        )

        import pandas as pd
        from datetime import datetime, timedelta

        def bars(closes):
            rows = []
            start = datetime(2026, 1, 5)
            for i, c in enumerate(closes):
                prev = closes[i - 1] if i else c
                pct = round((c - prev) / prev * 100.0, 2) if prev else 0
                d = (start + timedelta(days=i)).strftime("%Y%m%d")
                rows.append(
                    {
                        "date": d,
                        "stock_id": "2330",
                        "stock_name": "台積電",
                        "market": "TW",
                        "open": c - 0.2,
                        "high": c + 1,
                        "low": c - 1,
                        "close": c,
                        "volume": 12000,
                        "turnover_k": 120000,
                        "pct_change": pct,
                        "avg_price": c,
                        "foreign_net": 0,
                        "trust_net": 0,
                        "dealer_net": 0,
                    }
                )
            return pd.DataFrame(rows)

        # 長跌後小反彈：可能剛離零但仍在月線、季線下 → 不進起漲
        slide = [100.0 - i * 0.8 for i in range(70)]
        bounce = slide + [slide[-1] * 1.004, slide[-1] * 1.012]
        out = ScreeningEngine(db_path=":memory:").execute_all_strategies({"2330": bars(bounce)})
        self.assertEqual(out["leave_zero"], [])

    def test_half_and_two_year_highs_excluded_from_all_push_buckets(self):
        import pandas as pd
        from screening_engine import ScreeningEngine, _skip_long_term_high_push

        def bars(closes, *, last_vol=8000):
            from datetime import datetime, timedelta

            rows = []
            start = datetime(2026, 1, 5)
            for i, c in enumerate(closes):
                prev = closes[i - 1] if i else c
                pct = round((c - prev) / prev * 100.0, 2) if prev else 0
                d = (start + timedelta(days=i)).strftime("%Y%m%d")
                vol = last_vol if i == len(closes) - 1 else 3000
                rows.append(
                    {
                        "date": d,
                        "stock_id": "2330",
                        "stock_name": "台積電",
                        "market": "TW",
                        "open": c - 0.2,
                        "high": c + 1,
                        "low": c - 1,
                        "close": c,
                        "volume": vol,
                        "turnover_k": vol * c,
                        "pct_change": pct,
                        "avg_price": c,
                        "foreign_net": 0,
                        "trust_net": 0,
                        "dealer_net": 0,
                    }
                )
            return pd.DataFrame(rows)

        engine = ScreeningEngine(db_path=":memory:")
        # 半年高改獨立分類；兩年高仍整檔排除
        half_year = [100.0] * 130 + [100.0, 100.0, 100.0, 101.0, 110.0]
        out_hi120 = engine.execute_all_strategies({"2330": bars(half_year, last_vol=20000)})
        self.assertEqual(out_hi120["select_01"], [])
        self.assertEqual(out_hi120["day_trade"], [])
        self.assertTrue(out_hi120["half_year_high"])
        info = engine.calculate_indicators(bars(half_year, last_vol=20000))
        from screening_engine import _is_half_year_high_break

        self.assertTrue(_is_half_year_high_break(info))

        # 創高但量不夠／漲幅小：不算舊版半年高，周帶量仍可推
        mild = [100.0] * 130 + [100.0, 100.0, 100.0, 101.0, 102.0]
        out_mild = engine.execute_all_strategies({"2330": bars(mild, last_vol=8000)})
        self.assertFalse(_skip_long_term_high_push(engine.calculate_indicators(bars(mild, last_vol=8000))))
        self.assertTrue(out_mild["select_01"])


class AIDeskTest(unittest.TestCase):
    def test_run_ai_desk_actually_buys(self):
        import os
        import tempfile
        from ai_trader import AI_USER, MAX_SLOTS, run_ai_desk
        from portfolio_engine import PortfolioEngine

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            results = {
                "leave_zero": [
                    {"stock_id": "2330", "stock_name": "台積電", "close": 100.0, "chase_warning": False}
                ],
                "overnight": [{"stock_id": "2303", "stock_name": "聯電", "close": 50.0}],
                "day_trade": [{"stock_id": "2317", "stock_name": "鴻海", "close": 80.0}],
                "select_01": [
                    {"stock_id": "2412", "stock_name": "中華電", "close": 120.0, "chase_warning": True}
                ],
                "select_04": [
                    {
                        "stock_id": "2308",
                        "stock_name": "台達電",
                        "close": 400.0,
                        "us_peer_headwind": True,
                    }
                ],
            }
            ai = run_ai_desk(path, results, "20260831")
            blob = " ".join(ai.get("bought") or [])
            self.assertIn("2330", blob)
            self.assertIn("2303", blob)
            self.assertNotIn("2317", blob)
            self.assertNotIn("2412", blob)
            self.assertNotIn("2308", blob)
            eng = PortfolioEngine(path)
            summary = eng.get_portfolio_summary(AI_USER)
            self.assertGreaterEqual(summary["positions_count"], 2)
            self.assertLess(summary["cash"], 500000)
            by_id = {p["stock_id"]: p for p in summary["positions"]}
            self.assertIn("2330", by_id)
            self.assertEqual(by_id["2330"]["shares"], 1000)
            self.assertEqual(by_id["2303"]["shares"], 3000)
            self.assertAlmostEqual(ai.get("slot") or 0, 500000.0 / MAX_SLOTS, delta=1)
            html = ai.get("html") or ""
            self.assertIn("AI 模擬帳戶", html)
            self.assertIn("已用槽", html)
            self.assertIn("每槽上限", html)
            self.assertIn("停損", html)
            self.assertIn("停利", html)
            self.assertIn("成交紀錄", html)
            conn = sqlite3.connect(path)
            fills = conn.execute("SELECT stock_id, action, shares, bucket FROM ai_fills ORDER BY id").fetchall()
            conn.close()
            self.assertGreaterEqual(len(fills), 2)
            self.assertEqual(fills[0][0], "2330")
            self.assertEqual(fills[0][1], "BUY")
            self.assertEqual(fills[0][2], 1000)
            self.assertEqual(fills[0][3], "leave_zero")
        finally:
            os.remove(path)

    def test_equal_slots_do_not_dump_remaining_cash(self):
        import os
        import tempfile
        from ai_trader import AI_USER, run_ai_desk
        from portfolio_engine import PortfolioEngine

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            eng = PortfolioEngine(path)
            eng.ensure_user_exists(AI_USER)
            conn = sqlite3.connect(path)
            for i, sid in enumerate(("1101", "1102"), 1):
                conn.execute(
                    """
                    INSERT INTO user_positions
                    (user_id, stock_id, stock_name, shares, cost_price, highest_price, buy_date, warning_days, strategy_type)
                    VALUES (?,?,?,?,?,?,?,0,'MOMENTUM')
                    """,
                    (AI_USER, sid, f"占槽{i}", 1000, 10.0, 10.0, "20260828"),
                )
            conn.commit()
            conn.close()
            ai = run_ai_desk(
                path,
                {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}]},
                "20260831",
            )
            self.assertTrue(ai.get("bought"))
            summary = eng.get_portfolio_summary(AI_USER)
            by_id = {p["stock_id"]: p for p in summary["positions"]}
            self.assertEqual(by_id["2330"]["shares"], 1000)
            self.assertGreater(summary["cash"], 350000)
        finally:
            os.remove(path)

    def test_ai_fill_next_day_scores_and_weakens_bucket(self):
        import os
        import tempfile
        from ai_trader import AI_USER, run_ai_desk
        from screen_review import bucket_weight, format_ai_review_html, score_ai_fills
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            run_ai_desk(
                path,
                {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}]},
                "20260827",
            )
            conn = sqlite3.connect(path)
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260828", "2330", "台積電", "TW", 100, 101, 99, 102, 1000, 1000, 2.0, 100, 0, 0, 0),
            )
            for i in range(3):
                conn.execute(
                    """
                    INSERT INTO ai_fills(as_of,stock_id,stock_name,action,price,shares,amount,reason,bucket,realized_pnl,pnl_pct,next_date,next_close,next_pct,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"2026082{i}",
                        f"1{i:03d}",
                        "弱",
                        "BUY",
                        100,
                        1000,
                        100000,
                        "起漲：獲利離零",
                        "leave_zero",
                        0,
                        0,
                        "20260828",
                        96,
                        -4.0,
                        "2026-08-28 16:00:00",
                    ),
                )
            conn.commit()
            conn.close()
            n = score_ai_fills(path, "20260828")
            self.assertGreaterEqual(n, 1)
            html = format_ai_review_html(path)
            self.assertIn("AI 成交復盤", html)
            self.assertIn("2330", html)
            self.assertEqual(bucket_weight(path, "leave_zero"), 0.0)
        finally:
            os.remove(path)

    def test_bundled_fonts_shipped_for_fast_lookup(self):
        from wayne_navigator import _WEIGHT_BOLD, _WEIGHT_TEXT, bundled_weight_path

        self.assertTrue(os.path.isfile(bundled_weight_path(_WEIGHT_TEXT)))
        self.assertTrue(os.path.isfile(bundled_weight_path(_WEIGHT_BOLD)))


class SpeedOptTest(unittest.TestCase):
    def test_chips_only_need_recent_window_for_acc(self):
        from datetime import date, timedelta
        from chips import major_player_rows
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            q = "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            start = date(2026, 7, 1)
            for i in range(40):
                d = (start + timedelta(days=i)).strftime("%Y%m%d")
                conn.execute(q, (d, "2330", "台積電", "TW", 100, 101, 99, 100, 1000, 1000, 0, 100, 10, 20, 30))
            conn.commit()
            conn.close()
            rows = major_player_rows(path, "2330", limit=15)
            self.assertEqual(len(rows), 15)
            self.assertEqual(rows[0]["three_net"], 60)
            self.assertEqual(rows[0]["acc_10d"], 600)
        finally:
            os.remove(path)

    def test_annotate_screen_computes_sector_once(self):
        import money_flow
        from money_flow import annotate_screen_results
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        orig = money_flow.compute_sector_rows
        calls = {"n": 0}

        def wrapped(conn, ymd):
            calls["n"] += 1
            return orig(conn, ymd)

        money_flow.compute_sector_rows = wrapped
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            conn.execute(
                "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,?,?)",
                ("2330", "台積電", "TW", "股票", "半導體業", 1, "x"),
            )
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260828", "2330", "台積電", "TW", 100, 101, 99, 100, 10000, 50000, 1.0, 100, 8000, 0, 0),
            )
            conn.commit()
            conn.close()
            results = {
                "leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100}],
                "select_01": [{"stock_id": "2330", "stock_name": "台積電", "close": 100}],
                "day_trade": [{"stock_id": "2330", "stock_name": "台積電", "close": 100}],
            }
            annotate_screen_results(path, "20260828", results)
            self.assertEqual(calls["n"], 1)
            self.assertEqual(results["leave_zero"][0].get("industry"), "半導體業")
        finally:
            money_flow.compute_sector_rows = orig
            os.remove(path)

    def test_schema_second_call_is_noop(self):
        from wayne_db import ensure_core_schema

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='daily_quotes'").fetchone()[0]
            conn.close()
            self.assertEqual(n, 1)
        finally:
            os.remove(path)


class WatchListTest(unittest.TestCase):
    def test_add_and_remove_watchlist(self):
        from wayne_db import (
            add_to_watchlist,
            get_user_watchlist,
            remove_from_watchlist,
            ensure_core_schema,
        )

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            add_to_watchlist(path, "u1", "2330", "台積電")
            add_to_watchlist(path, "u1", "2317", "鴻海")
            rows = get_user_watchlist(path, "u1")
            self.assertEqual({r["stock_code"] for r in rows}, {"2330", "2317"})
            self.assertTrue(remove_from_watchlist(path, "u1", "2330"))
            left = get_user_watchlist(path, "u1")
            self.assertEqual([r["stock_code"] for r in left], ["2317"])
            self.assertFalse(remove_from_watchlist(path, "u1", "2330"))
            self.assertFalse(remove_from_watchlist(path, "u1", ""))
        finally:
            os.remove(path)

    def test_watch_keyboard_has_delete(self):
        from bot_servers import WayneTelegramBot

        bot = object.__new__(WayneTelegramBot)
        kb = bot._watch_list_keyboard(
            [{"stock_code": "2330", "stock_name": "台積電"}, {"stock_code": "2317", "stock_name": "鴻海"}]
        )
        datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("rw:2330", datas)
        self.assertIn("rw:2317", datas)
        self.assertIn("刪", texts)
        self.assertIn("k:2330", datas)

    def test_line_stock_share_persists_and_hop(self):
        import os
        import tempfile
        from line_hop import hop_stock_response, render_line_hop_html
        from screening_engine import build_line_stock_bodies, format_stock_line_share_text
        from screen_sessions import load_line_stock, save_line_stocks

        item = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "pct_change": 2.5,
            "volume": 8000,
            "q60r": 2.1,
        }
        text = format_stock_line_share_text(item, "20260828", bucket_label="起漲")
        self.assertIn("2330", text)
        self.assertNotIn("開 LINE", text)
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            bodies = build_line_stock_bodies({"leave_zero": [item]}, "20260828")
            save_line_stocks(path, "20260828", bodies)
            self.assertIn("2330", load_line_stock(path, "2330")["text"])
            hop = hop_stock_response(path, "2330")
            self.assertTrue((hop.get("redirect") or "").startswith("https://line.me/R/share?text="))
            page = render_line_hop_html("傳 2330", load_line_stock(path, "2330")["text"])
            self.assertIn("line.me/R/share", page)
            self.assertIn("location.replace", page)
            self.assertNotIn("哥哥", page)
        finally:
            os.remove(path)

    def test_stock_card_inline_line_link_on_title_row(self):
        from screening_engine import _stock_card_html

        card = _stock_card_html(
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "close": 100,
                "volume": 8000,
                "pct_change": 1.2,
                "q60r": 2.0,
                "ma20": 98,
                "ma60": 95,
                "foreign_net": 0,
                "trust_net": 0,
                "dealer_net": 0,
            },
            1,
        )
        self.assertIn("<blockquote>", card)
        self.assertIn("開 LINE・傳這檔", card)
        self.assertIn("/line/stock/2330", card)
        slim = _stock_card_html(
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "close": 100,
                "volume": 8000,
                "pct_change": 1.2,
                "q60r": 2.0,
                "ma20": 98,
                "ma60": 95,
                "foreign_net": 0,
                "trust_net": 0,
                "dealer_net": 0,
            },
            1,
            show_line_link=False,
        )
        self.assertNotIn("開 LINE・傳這檔", slim)
        first = card.split("\n", 1)[0]
        self.assertIn("台積電", first)
        self.assertIn("開 LINE・傳這檔", first)

    def test_screen_keyboard_has_section_line_button(self):
        import inspect
        from bot_servers import WayneTelegramBot

        bot = object.__new__(WayneTelegramBot)
        bot.db_path = None
        kb = bot._screening_section_keyboard(line_pack_id="leave_zero", include_menu=True)
        datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(texts.count("生成完整圖文・傳LINE"), 1)
        self.assertTrue(any(d and d == "lp:leave_zero" for d in datas))
        self.assertFalse(any("2330" in (t or "") for t in texts))
        day_kb = bot._picks_keyboard(
            [("2330", "台積電")],
            include_menu=True,
            topic="daytrade",
            line_pack_id="day_trade",
        )
        day_urls = [getattr(btn, "url", None) for row in day_kb.inline_keyboard for btn in row]
        self.assertTrue(any(u and "/line/day_trade" in (u or "") for u in day_urls))
        send_src = inspect.getsource(WayneTelegramBot.send_screening_report)
        self.assertNotIn("_send_line_share(self.chat_id", send_src)
        payload_src = inspect.getsource(WayneTelegramBot._reply_screening_payload)
        self.assertIn("_remember_line_share", payload_src)
        self.assertIn("line_pack_id", payload_src)

    def test_watch_html_yahoo_link_and_send_disables_preview(self):
        import inspect
        from bot_servers import WayneTelegramBot

        bot = object.__new__(WayneTelegramBot)
        bot.db_path = None
        html, kb = bot._render_watch([{"stock_code": "2330", "stock_name": "台積電"}])
        self.assertIn("2330 台積電", html)
        self.assertIn("tw.stock.yahoo.com/quote/2330", html)
        self.assertIn("<a ", html)
        self.assertIn("刪", html)
        datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("rw:2330", datas)
        send_src = inspect.getsource(WayneTelegramBot._send_watch)
        self.assertIn("disable_web_page_preview=True", send_src)
        self.assertGreaterEqual(send_src.count("disable_web_page_preview=True"), 2)
        self.assertIn("_remove_watch_clicked", inspect.getsource(WayneTelegramBot.on_callback))


if __name__ == "__main__":
    unittest.main()
