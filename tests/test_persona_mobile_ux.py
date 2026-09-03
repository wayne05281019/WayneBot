# -*- coding: utf-8 -*-
"""十人格 UX：雅虎連結、按鈕密度、hub 精簡。"""
from __future__ import annotations

import re

from bot_servers import MAX_PICK_INLINE_ROWS, WayneTelegramBot
from stock_links import html_stock_anchor


def test_hub_keyboard_mobile_compact():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._hub_keyboard("2330")
    rows = kb.inline_keyboard
    assert len(rows) == 2
    assert all(len(r) <= 3 for r in rows)
    texts = [b.text for r in rows for b in r]
    assert "籌碼" in texts and "記買入" in texts
    assert "導航圖" not in texts


def test_picks_keyboard_caps_rows():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = "data/wayne_market.db"
    picks = [(str(2300 + i), f"股{i}") for i in range(20)]
    kb = bot._picks_keyboard(picks, line_pack_id="day_trade")
    stock_rows = [r for r in kb.inline_keyboard if any("k:" in (b.callback_data or "") for b in r)]
    assert len(stock_rows) <= MAX_PICK_INLINE_ROWS


def test_yahoo_anchor_opens_quote_page_for_app():
    html = html_stock_anchor("2330", "台積電", "data/wayne_market.db")
    assert re.search(r'href="https://tw\.stock\.yahoo\.com/quote/2330\.TW"', html)
    assert "technical-analysis" not in html


def test_hits_keyboard_two_buttons_per_row():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._hits_keyboard([{"stock_id": "2330", "stock_name": "台積電"}])
    row = kb.inline_keyboard[0]
    assert len(row) == 2
    assert row[1].text == "➕"
