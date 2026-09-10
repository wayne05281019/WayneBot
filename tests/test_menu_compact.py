# -*- coding: utf-8 -*-
"""第一週選單順序、精簡六顆、持倉改去持股。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot_servers import (
    MENU_BTN_AI,
    MENU_BTN_CARD,
    MENU_BTN_MARKET,
    MENU_BTN_REPORT,
    MENU_BTN_STREAK,
    MENU_COMPACT_ROWS,
    MENU_FULL_ALIASES,
    MENU_LAYOUT_VERSION,
    MENU_ROW1,
    MENU_ROW2,
    WayneTelegramBot,
)
from intent_router import parse_intent
from wayne_db import init_database


def test_compact_six_buttons_are_two_chars_no_wrap():
    from bot_servers import MENU_COMPACT_ROWS, MENU_BTN_CARD

    assert MENU_BTN_CARD == "刷新"
    for row in MENU_COMPACT_ROWS:
        assert len(row) == 3
        for t in row:
            assert len(t) == 2, t
    assert MENU_LAYOUT_VERSION == "15"
    assert MENU_ROW1 == ("說明", "海選", "持股", "觀察", MENU_BTN_CARD, MENU_BTN_REPORT, "飆客")
    assert MENU_ROW2[:6] == (MENU_BTN_MARKET, "資金", "當沖", "隔日沖", MENU_BTN_AI, MENU_BTN_STREAK)
    assert MENU_ROW2[6].strip() == ""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert [b.text for b in kb.keyboard[0]] == list(MENU_ROW1)
    assert [b.text for b in kb.keyboard[1]] == list(MENU_ROW2)


def test_compact_menu_is_six_first_week_buttons(tmp_path):
    db = str(tmp_path / "m.db")
    init_database(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot._set_menu_compact("9", True)
    kb = bot._reply_menu("9")
    assert len(kb.keyboard) == 2
    labels = [b.text for row in kb.keyboard for b in row]
    assert labels == [t for row in MENU_COMPACT_ROWS for t in row]
    assert "當沖" not in labels
    assert MENU_BTN_AI not in labels
    bot._set_menu_compact("9", False)
    kb2 = bot._reply_menu("9")
    assert [b.text for b in kb2.keyboard[0]] == list(MENU_ROW1)
    assert [b.text for b in kb2.keyboard[1]] == list(MENU_ROW2)


def test_holdings_intent_not_ai():
    assert parse_intent("持倉").kind == "portfolio"
    assert parse_intent("持股").kind == "portfolio"
    assert parse_intent("持倉報告").kind == "ai"
    assert parse_intent("模擬持倉").kind == "ai"
    assert parse_intent("模擬持倉報告").kind == "ai"


def test_compact_and_full_aliases_refresh_keyboard(tmp_path):
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
    assert bot._menu_compact_on("9") is True

    bot._force_reply_menu.reset_mock()
    msg.text = MENU_FULL_ALIASES[0]
    asyncio.run(bot.on_text(upd, MagicMock()))
    assert bot._menu_compact_on("9") is False
