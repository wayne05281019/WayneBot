# -*- coding: utf-8 -*-
"""選單隔離：按 A 只出 A，不連帶 B；pending 不被子字串誤觸發。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _msg(chat_id: int, uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=chat_id)
    message = MagicMock()
    message.chat_id = chat_id
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._enter_main_menu = AsyncMock(side_effect=lambda m, u, **kw: f"{m.chat_id}:{u}")
    return bot


@pytest.mark.parametrize(
    "text",
    ("我的自選股清單", "今日海選名單", "模擬持倉報告", "海選結果"),
)
def test_substring_does_not_trigger_menu(text):
    """含「自選／海選／模擬持倉」等字樣的普通文字不應觸發選單。"""
    bot = _bot()
    bot.screen_cmd = AsyncMock()
    bot.portfolio_cmd = AsyncMock()
    bot.watch_cmd = AsyncMock()

    async def run():
        with patch("wayne_db.lookup_stocks", return_value=[]):
            await bot.on_text(_update(_msg(1, 1, text)), MagicMock())

    asyncio.run(run())
    bot.screen_cmd.assert_not_awaited()
    bot.portfolio_cmd.assert_not_awaited()
    bot.watch_cmd.assert_not_awaited()


def test_buy_pending_not_lost_on_unrelated_text():
    bot = _bot()
    bot._enter_main_menu = AsyncMock(side_effect=lambda m, u, **kw: f"{1}:{u}")
    bot._pending["1:42"] = "buy:2330"

    async def run():
        with patch("wayne_db.lookup_stocks", return_value=[]):
            await bot.on_text(_update(_msg(1, 42, "随便乱打")), MagicMock())

    asyncio.run(run())
    assert bot._pending.get("1:42") == "buy:2330"


def test_market_cmd_dismisses_before_content():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot.charts_dir = "data/charts"
    bot._menu_fade_msgs = {}
    bot._menu_fade_gen = {}
    bot._pending = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot._enter_main_menu = AsyncMock()
    msg = _msg(5, 50, "大盤")
    upd = _update(msg)

    async def run():
        with patch("taiwan_market.format_taiwan_market_page_html", return_value="<b>台股大盤</b>"):
            await bot.market_cmd(upd, MagicMock())

    asyncio.run(run())
    bot._enter_main_menu.assert_awaited_once()
    msg.reply_html.assert_awaited()
