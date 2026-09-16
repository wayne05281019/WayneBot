# -*- coding: utf-8 -*-
"""查股介紹圖／決策卡：產業法人 overlay。不改溫度／買賣格。"""
from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile
import unittest

from money_flow import (
    attach_industry_flow,
    industry_flow_overlay,
    industry_flow_tag,
)
from wayne_db import ensure_core_schema


def _flow_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    ensure_core_schema(path)
    conn = sqlite3.connect(path)
    now = "2026-08-31T00:00:00"
    univ = [
        ("2330", "台積電", "TWSE", "STOCK", "半導體業"),
        ("2454", "聯發科", "TWSE", "STOCK", "半導體業"),
        ("2382", "廣達", "TWSE", "STOCK", "電腦及週邊設備業"),
        ("3231", "緯創", "TWSE", "STOCK", "電腦及週邊設備業"),
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

    # 8/27：電腦流入、半導體流出；8/28：半導體剛輪進、電腦續流入、鋼鐵流出。
    q("20260827", "2330", "台積電", "TW", -0.5, 40000, -500, -100, 0)
    q("20260827", "2454", "聯發科", "TW", -0.2, 8000, -80, -20, 0)
    q("20260827", "2382", "廣達", "TW", 0.4, 20000, 400, 80, 0)
    q("20260827", "3231", "緯創", "TW", 0.3, 9000, 90, 20, 0)
    q("20260827", "2002", "中鋼", "TW", -0.3, 20000, -200, -50, 0)
    q("20260827", "2027", "大成鋼", "TW", -0.1, 5000, -40, -10, 0)
    q("20260828", "2330", "台積電", "TW", 1.2, 50000, 8000, 400, 50)
    q("20260828", "2454", "聯發科", "TW", 0.8, 9000, 1200, 300, 20)
    q("20260828", "2382", "廣達", "TW", 0.5, 18000, 600, 90, 10)
    q("20260828", "3231", "緯創", "TW", 0.4, 8000, 120, 30, 5)
    q("20260828", "2002", "中鋼", "TW", -1.5, 18000, -3000, -400, -50)
    q("20260828", "2027", "大成鋼", "TW", -0.8, 4000, -500, -80, -10)
    q("20260828", "0050", "元大台灣50", "TW", 0.4, 20000, 90000, 0, 0)
    conn.commit()
    conn.close()
    return path


class LookupIndustryFlowTests(unittest.TestCase):
    def setUp(self):
        self.path = _flow_db()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_overlay_just_inflow_outflow_and_stamp(self):
        just = industry_flow_overlay(self.path, "半導體業", "20260828")
        self.assertIn("半導體業剛輪進", just)
        self.assertIn("官方法人 overlay", just)
        self.assertIn("不改溫度／買賣格", just)
        self.assertIn("2026/08/28（五）", just)
        stay = industry_flow_overlay(self.path, "電腦及週邊設備業", "20260828")
        self.assertIn("電腦及週邊設備業在流入前段", stay)
        out = industry_flow_overlay(self.path, "鋼鐵工業", "20260828")
        self.assertIn("鋼鐵工業在流出前段", out)
        self.assertEqual(industry_flow_overlay(self.path, "ETF", "20260828"), "")
        self.assertEqual(industry_flow_overlay(self.path, "未分類", "20260828"), "")
        self.assertEqual(industry_flow_overlay(self.path, "", "20260828"), "")

    def test_tag_short_and_empty(self):
        self.assertEqual(industry_flow_tag("官方法人 overlay：半導體業剛輪進（截至 x）。"), "剛輪進")
        self.assertEqual(industry_flow_tag("…在流出前段…"), "流出前段")
        self.assertEqual(industry_flow_tag("…在流入前段…"), "流入前段")
        self.assertEqual(industry_flow_tag(""), "")

    def test_attach_does_not_change_temp_or_stance(self):
        card = {
            "stock_id": "2330",
            "industry": "半導體業",
            "temp_c": "36.0 °C",
            "stance": "今天先看表，先等",
            "stance_kind": "wait",
            "table": [{"高低": "No", "升降": "—"}],
        }
        table_before = card["table"]
        out = attach_industry_flow(card, self.path, ymd="20260828")
        self.assertIs(out, card)
        self.assertIn("半導體業剛輪進", card["industry_flow"])
        self.assertEqual(card["temp_c"], "36.0 °C")
        self.assertEqual(card["stance"], "今天先看表，先等")
        self.assertEqual(card["stance_kind"], "wait")
        self.assertIs(card["table"], table_before)
        self.assertEqual(card["table"][0]["高低"], "No")

    def test_attach_skips_etf_and_keeps_existing(self):
        etf = {"etf_kind": "被動", "industry": "半導體業", "temp_c": "12.0 °C"}
        attach_industry_flow(etf, self.path, ymd="20260828")
        self.assertNotIn("industry_flow", etf)
        self.assertEqual(etf["temp_c"], "12.0 °C")
        kept = {"industry": "鋼鐵工業", "industry_flow": "已有"}
        attach_industry_flow(kept, self.path, ymd="20260828")
        self.assertEqual(kept["industry_flow"], "已有")
        err = {"error": "no", "industry": "半導體業"}
        attach_industry_flow(err, self.path, ymd="20260828")
        self.assertNotIn("industry_flow", err)

    def test_html_and_png_sources_carry_overlay(self):
        from wayne_navigator import (
            generate_decision_card,
            render_decision_card_png,
            render_first_glance_png,
        )

        html_src = inspect.getsource(generate_decision_card)
        glance_src = inspect.getsource(render_first_glance_png)
        card_src = inspect.getsource(render_decision_card_png)
        engine_src = inspect.getsource(
            __import__("wayne_navigator", fromlist=["NavigatorEngine"]).NavigatorEngine.get_decision_card
        )
        self.assertIn('card.get("industry_flow")', html_src)
        self.assertIn("chip_block", html_src)
        self.assertIn("industry_flow_tag", glance_src)
        self.assertIn("industry_flow_tag", card_src)
        self.assertIn("attach_industry_flow", engine_src)
        flow_bit = html_src.split("industry_flow", 1)[1][:280]
        self.assertIn("chip_block", flow_bit)
        self.assertNotIn("pink_warning", flow_bit)
        self.assertNotIn("sell_action", flow_bit)


if __name__ == "__main__":
    unittest.main()
