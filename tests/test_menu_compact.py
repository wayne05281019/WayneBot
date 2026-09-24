# -*- coding: utf-8 -*-
"""主選單順序：完整兩排、沒有精簡鍵盤、持倉改去持股。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot_servers import (
    MENU_BTN_AI,
    MENU_BTN_BIAOKE_FACE,
    MENU_BTN_FLOW,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_MARKET,
    MENU_BTN_DONGZHU,
    MENU_BTN_STREAK,
    MENU_LAYOUT_VERSION,
    MENU_ROW1,
    MENU_ROW2,
    WayneTelegramBot,
)
from intent_router import parse_intent
from wayne_db import init_database


def test_full_menu_is_two_rows_no_compact():
    assert MENU_LAYOUT_VERSION == "30"
    assert MENU_ROW1 == ("海選", "持股", "觀察", MENU_BTN_BIAOKE_FACE, MENU_BTN_MARKET, MENU_BTN_FLOW)
    assert MENU_ROW2 == ("當沖", "隔日沖", MENU_BTN_AI, MENU_BTN_STREAK, MENU_BTN_LEAVE_ZERO, MENU_BTN_DONGZHU)
    assert "刷新" not in MENU_ROW1 + MENU_ROW2
    assert "回報" not in MENU_ROW1 + MENU_ROW2
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert [b.text for b in kb.keyboard[0]] == list(MENU_ROW1)
    assert [b.text for b in kb.keyboard[1]] == list(MENU_ROW2)


def test_old_compact_flag_cannot_shrink_keyboard(tmp_path):
    db = str(tmp_path / "m.db")
    init_database(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot._set_menu_compact("9", True)
    kb = bot._reply_menu("9")
    assert len(kb.keyboard) == 2
    labels = [b.text for row in kb.keyboard for b in row]
    assert labels == list(MENU_ROW1) + list(MENU_ROW2)
    assert "當沖" in labels
    assert MENU_BTN_AI in labels
    assert bot._menu_compact_on("9") is False


def test_holdings_intent_not_ai():
    assert parse_intent("持倉").kind == "portfolio"
    assert parse_intent("持股").kind == "portfolio"
    assert parse_intent("持倉報告").kind == "ai"
    assert parse_intent("模擬持倉").kind == "ai"
    assert parse_intent("模擬持倉報告").kind == "ai"
    assert parse_intent("台股大盤").kind == "market"
    assert parse_intent("大盤").kind == "market"
    assert parse_intent("資金輪動").kind == "flow"
    assert parse_intent("資金").kind == "flow"


def test_typed_compact_alias_still_hangs_full_keyboard(tmp_path):
    db = str(tmp_path / "m.db")
    init_database(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot._pending = {}
    bot._touch_user = MagicMock()
    bot._actor_key = MagicMock(return_value="9:9")
    bot._dismiss_menu_transients = AsyncMock()
    bot._force_reply_menu = AsyncMock()
    user = SimpleNamespace(id=9, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.chat_id = 9
    msg.text = "精簡選單"
    msg.reply_text = AsyncMock(return_value=MagicMock())
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)

    asyncio.run(bot.on_text(upd, MagicMock()))
    bot._force_reply_menu.assert_awaited()
    assert bot._menu_compact_on("9") is False
