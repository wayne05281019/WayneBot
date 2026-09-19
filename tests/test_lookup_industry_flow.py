# -*- coding: utf-8 -*-
"""查股介紹圖／決策卡／持股：本鏈資金句，與產業卡／洞燭同一套。"""
from __future__ import annotations

import inspect
import json
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
    import datetime as _dt

    now = _dt.datetime.now().isoformat(timespec="seconds")
    univ = [
        ("2330", "台積電", "TWSE", "STOCK", "半導體業", "電子上游-IC-代工"),
        ("2454", "聯發科", "TWSE", "STOCK", "半導體業", "電子上游-IC-代工"),
        ("2002", "中鋼", "TWSE", "STOCK", "鋼鐵工業", "傳產-鋼鐵"),
        ("2027", "大成鋼", "TWSE", "STOCK", "鋼鐵工業", "傳產-鋼鐵"),
        ("1101", "台泥", "TWSE", "STOCK", "水泥工業", "傳產-水泥"),
        ("0050", "元大台灣50", "TWSE", "ETF_PASSIVE", "ETF", ""),
    ]
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_fine_industry (
            stock_id TEXT PRIMARY KEY,
            chain TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            cat_id TEXT DEFAULT '',
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    for sid, name, mkt, atype, ind, chain in univ:
        conn.execute(
            "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
            (sid, name, mkt, atype, ind, now),
        )
        if chain:
            tags = chain.split("-")
            conn.execute(
                "INSERT INTO stock_fine_industry(stock_id,chain,tags_json,cat_id,source,fetched_at) VALUES (?,?,?,?,?,?)",
                (sid, chain, json.dumps(tags, ensure_ascii=False), "", "test", now),
            )

    def q(date, sid, name, market, pct, vol, fn, tn, dn):
        conn.execute(
            "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (date, sid, name, market, 100, 101, 99, 100, vol, 50000, pct, 100, fn, tn, dn),
        )

    # 代工佔比連三日升；鋼鐵連三日退。
    q("20260826", "2330", "台積電", "TW", 0.2, 30000, 80, 20, 0)
    q("20260826", "2454", "聯發科", "TW", 0.1, 7000, 40, 10, 0)
    q("20260826", "2002", "中鋼", "TW", 0.1, 18000, 40, 10, 0)
    q("20260826", "2027", "大成鋼", "TW", 0.1, 4000, 20, 5, 0)
    q("20260826", "1101", "台泥", "TW", 0.2, 20000, 8000, 2000, 0)
    q("20260827", "2330", "台積電", "TW", 0.4, 35000, 160, 40, 0)
    q("20260827", "2454", "聯發科", "TW", 0.3, 8000, 80, 20, 0)
    q("20260827", "2002", "中鋼", "TW", -0.3, 20000, -200, -50, 0)
    q("20260827", "2027", "大成鋼", "TW", -0.1, 5000, -40, -10, 0)
    q("20260827", "1101", "台泥", "TW", 0.1, 18000, 3000, 500, 0)
    q("20260828", "2330", "台積電", "TW", 1.2, 50000, 320, 80, 10)
    q("20260828", "2454", "聯發科", "TW", 0.8, 9000, 160, 40, 5)
    q("20260828", "2002", "中鋼", "TW", -1.5, 18000, -3000, -400, -50)
    q("20260828", "2027", "大成鋼", "TW", -0.8, 4000, -500, -80, -10)
    q("20260828", "1101", "台泥", "TW", -0.2, 16000, 400, 100, 0)
    q("20260828", "0050", "元大台灣50", "TW", 0.4, 20000, 0, 0, 0)
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

    def test_overlay_uses_chain_not_twse_bucket(self):
        just = industry_flow_overlay(self.path, ymd="20260828", stock_id="2330")
        self.assertIn("本鏈", just)
        self.assertIn("資金流入", just)
        self.assertNotIn("半導體業", just)
        self.assertNotIn("官方法人 overlay", just)
        self.assertNotIn("不改溫度", just)
        self.assertNotIn("買賣格", just)
        out = industry_flow_overlay(self.path, ymd="20260828", stock_id="2002")
        self.assertIn("本鏈", out)
        self.assertIn("資金流出", out)
        self.assertNotIn("鋼鐵工業", out)
        self.assertEqual(industry_flow_overlay(self.path, "半導體業", "20260828"), "")
        self.assertEqual(industry_flow_overlay(self.path, ymd="20260828", stock_id="0050"), "")
        self.assertEqual(industry_flow_overlay(self.path, ymd="20260828", stock_id=""), "")

    def test_tag_short_and_empty(self):
        self.assertEqual(industry_flow_tag("本鏈（代工）法人合計買超。佔比在升＝資金流入。"), "資金流入")
        self.assertEqual(industry_flow_tag("佔比在退＝資金流出。"), "資金流出")
        self.assertEqual(industry_flow_tag("買超佔比還在。"), "佔比還在")
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
        self.assertIn("本鏈", card["industry_flow"])
        self.assertIn("資金流入", card["industry_flow"])
        self.assertNotIn("半導體業剛輪進", card["industry_flow"])
        self.assertNotIn("不改溫度", card["industry_flow"])
        self.assertNotIn("買賣格", card["industry_flow"])
        self.assertEqual(card["temp_c"], "36.0 °C")
        self.assertEqual(card["stance"], "今天先看表，先等")
        self.assertEqual(card["stance_kind"], "wait")
        self.assertIs(card["table"], table_before)
        self.assertEqual(card["table"][0]["高低"], "No")

    def test_attach_skips_etf_and_keeps_existing(self):
        etf = {"etf_kind": "被動", "stock_id": "0050", "industry": "半導體業", "temp_c": "12.0 °C"}
        attach_industry_flow(etf, self.path, ymd="20260828")
        self.assertNotIn("industry_flow", etf)
        self.assertEqual(etf["temp_c"], "12.0 °C")
        kept = {"stock_id": "2002", "industry": "鋼鐵工業", "industry_flow": "已有"}
        attach_industry_flow(kept, self.path, ymd="20260828")
        self.assertEqual(kept["industry_flow"], "已有")
        err = {"error": "no", "stock_id": "2330", "industry": "半導體業"}
        attach_industry_flow(err, self.path, ymd="20260828")
        self.assertNotIn("industry_flow", err)

    def test_same_sentence_on_peers_industry_and_lookup(self):
        from industry_brief import format_industry_html, stock_flow_overlay, stock_peer_plain_rows

        overlay = stock_flow_overlay("2330", self.path, ymd="20260828")
        rows = dict(stock_peer_plain_rows("2330", self.path))
        html = format_industry_html("2330", self.path, allow_fetch=False)
        self.assertTrue(overlay)
        self.assertEqual(rows.get("資金"), overlay.rstrip("。"))
        self.assertIn("資金：", html)
        self.assertIn(overlay.rstrip("。"), html)
        self.assertIn("本鏈", overlay)
        self.assertIn("資金流入", overlay)

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

    def test_holdings_html_overlay_not_in_discipline(self):
        from unittest.mock import patch

        from portfolio_engine import PortfolioEngine

        eng = PortfolioEngine(self.path)
        with patch("money_flow.resolve_flow_as_of", return_value=("20260828", None)):
            html = eng.format_holdings_html(
                [
                    {"stock_code": "2330", "stock_name": "台積電", "shares": 1, "cost_price": 100},
                    {"stock_code": "2002", "stock_name": "中鋼", "shares": 1, "cost_price": 30},
                    {"stock_code": "0050", "stock_name": "元大台灣50", "shares": 1, "cost_price": 150},
                ],
                quotes_map={
                    "2330": {"close": 110, "pct_change": 1.0},
                    "2002": {"close": 29, "pct_change": -1.0},
                    "0050": {"close": 151, "pct_change": 0.2},
                },
            )
        self.assertIn("資金：", html)
        self.assertIn("資金流入", html)
        self.assertIn("資金流出", html)
        self.assertNotIn("半導體業剛輪進", html)
        self.assertNotIn("官方法人 overlay", html)
        self.assertNotIn("不改溫度", html)
        self.assertNotIn("買賣格", html)
        self.assertIn("未實現", html)
        self.assertIn("市值", html)
        hold_src = inspect.getsource(PortfolioEngine.format_holdings_html)
        self.assertIn("industry_flows_for_stocks", hold_src)
        disc_idx = hold_src.find('kv_compact("紀律"')
        flow_idx = hold_src.find("industry_flows_for_stocks")
        self.assertGreater(disc_idx, 0)
        self.assertGreater(flow_idx, 0)
        self.assertLess(flow_idx, disc_idx)

    def test_flows_for_stocks_batch_and_skips_etf(self):
        from money_flow import industry_flows_for_stocks

        flows = industry_flows_for_stocks(
            self.path, ["2330", "2002", "0050", "2330"], ymd="20260828"
        )
        self.assertIn("資金流入", flows["2330"])
        self.assertIn("本鏈", flows["2330"])
        self.assertIn("資金流出", flows["2002"])
        self.assertNotIn("0050", flows)
        self.assertEqual(industry_flows_for_stocks("", ["2330"], ymd="20260828"), {})
        self.assertEqual(industry_flows_for_stocks(self.path, [], ymd="20260828"), {})

    def test_watch_html_overlay_same_sentence(self):
        from unittest.mock import patch

        from bot_servers import WayneTelegramBot

        bot = object.__new__(WayneTelegramBot)
        bot.db_path = self.path
        with patch("money_flow.resolve_flow_as_of", return_value=("20260828", None)):
            html, kb = bot._render_watch(
                [
                    {"stock_code": "2330", "stock_name": "台積電"},
                    {"stock_code": "2002", "stock_name": "中鋼"},
                    {"stock_code": "0050", "stock_name": "元大台灣50"},
                ]
            )
        self.assertIn("資金：", html)
        self.assertIn("資金流入", html)
        self.assertIn("資金流出", html)
        self.assertNotIn("官方法人 overlay", html)
        self.assertNotIn("不改溫度", html)
        self.assertNotIn("買賣格", html)
        self.assertIn("觀察清單", html)
        datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("k:2330", datas)
        self.assertIn("rw:2330", datas)
        empty, _ = bot._render_watch([])
        self.assertIn("目前是空的", empty)
        self.assertNotIn("資金：", empty)

    def test_ai_desk_overlay_before_discipline(self):
        from ai_trader import ensure_ai_user, format_ai_desk_html, format_ai_desk_pages
        from portfolio_engine import PortfolioEngine

        eng = PortfolioEngine(self.path)
        uid = "1001"
        user = ensure_ai_user(eng, uid)
        bought = eng.buy(user, "20260828", "2330", "台積電", 100.0, 1000, reason="黃金買點")
        self.assertTrue(bought.get("success"))
        from unittest.mock import patch

        with patch("money_flow.resolve_flow_as_of", return_value=("20260828", None)):
            html = format_ai_desk_html(eng, uid)
            pages = format_ai_desk_pages(eng, uid)
        self.assertIn("資金流入", html)
        self.assertNotIn("不改溫度", html)
        self.assertNotIn("買賣格", html)
        held = next(p for p in pages if "第 1 槽" in p)
        self.assertIn("資金流入", held)
        self.assertIn("資金：", held)
        self.assertLess(held.find("進場"), held.find("資金"))
        src = inspect.getsource(format_ai_desk_pages)
        flow_idx = src.find("industry_flows_for_stocks")
        disc_idx = src.find('sell_notes.get(sid)')
        self.assertGreater(flow_idx, 0)
        self.assertGreater(disc_idx, 0)
        self.assertLess(flow_idx, disc_idx)


if __name__ == "__main__":
    unittest.main()
