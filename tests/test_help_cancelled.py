# -*- coding: utf-8 -*-
"""說明／圖文／介紹已取消：話筒不再送說明鈕與圖文頁。舊氣泡靜音。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot_servers import HELP_TOPICS, WayneTelegramBot


def _src() -> str:
    return open("bot_servers.py", encoding="utf-8").read()


def _bot():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._help_msgs = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._actor_key = MagicMock(return_value="1:1")
    bot._keyboard = MagicMock(return_value=None)
    bot._reply_help_topic = AsyncMock()
    bot._send_picture_guide = AsyncMock()
    bot._show_picture_guide_page = AsyncMock()
    bot.help_cmd = AsyncMock()
    bot.screen_cmd = AsyncMock()
    return bot


def _msg(text: str = ""):
    user = SimpleNamespace(id=1, first_name="w")
    chat = SimpleNamespace(id=1)
    message = MagicMock()
    message.chat_id = 1
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    message.reply_photo = AsyncMock()
    message.edit_text = AsyncMock()
    message.edit_media = AsyncMock()
    message.delete = AsyncMock()
    message.photo = None
    return message


def test_help_topics_empty():
    assert HELP_TOPICS == {}


def test_bot_source_has_no_inline_help_button():
    src = _src()
    assert 'InlineKeyboardButton("說明"' not in src
    assert "HELP_TOPICS = {}" in src
    assert 'callback_data=f"n:{c}"' in src


def test_help_nav_and_picture_send_are_noop():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._help_nav_keyboard()
    assert not kb.inline_keyboard
    assert bot._q("stock") is None
    assert not bot._picture_guide_keyboard(0, 9).inline_keyboard

    msg = _msg()

    async def run():
        await WayneTelegramBot._reply_help_topic(bot, msg, "guide")
        await WayneTelegramBot._send_picture_guide(bot, msg)
        await WayneTelegramBot._show_picture_guide_page(bot, msg, 1, edit=True, from_page=0)

    asyncio.run(run())
    msg.reply_html.assert_not_awaited()
    msg.reply_photo.assert_not_awaited()
    msg.reply_text.assert_not_awaited()
    msg.edit_media.assert_not_awaited()


def test_old_pg_and_help_callbacks_are_silent():
    bot = _bot()
    for data in ("pg:0", "pg:2-3", "?:stock", "?:pics", "?:guide"):
        bot._show_picture_guide_page.reset_mock()
        bot._reply_help_topic.reset_mock()
        msg = _msg()
        q = SimpleNamespace(
            data=data,
            from_user=SimpleNamespace(id=1),
            message=msg,
            answer=AsyncMock(),
        )
        upd = SimpleNamespace(callback_query=q, effective_user=q.from_user)

        async def run():
            await bot.on_callback(upd, MagicMock())

        asyncio.run(run())
        q.answer.assert_awaited()
        bot._show_picture_guide_page.assert_not_awaited()
        bot._reply_help_topic.assert_not_awaited()
        msg.reply_photo.assert_not_awaited()


def test_typed_help_picture_and_pick_are_silent():
    bot = _bot()
    bot._pending["1:1"] = "x"
    for text in ("說明", "圖文", "選股", "/help"):
        bot._pending["1:1"] = "x"
        bot._send_picture_guide.reset_mock()
        bot._reply_help_topic.reset_mock()
        bot.help_cmd.reset_mock()
        bot.screen_cmd.reset_mock()
        msg = _msg(text)
        upd = SimpleNamespace(
            message=msg,
            effective_user=msg.from_user,
            effective_chat=msg.chat,
        )

        async def run():
            await bot.on_text(upd, MagicMock())

        asyncio.run(run())
        assert "1:1" not in bot._pending
        msg.reply_html.assert_not_awaited()
        msg.reply_photo.assert_not_awaited()
        bot._send_picture_guide.assert_not_awaited()
        bot._reply_help_topic.assert_not_awaited()
        bot.help_cmd.assert_not_awaited()
        bot.screen_cmd.assert_not_awaited()
