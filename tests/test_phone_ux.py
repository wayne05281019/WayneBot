# -*- coding: utf-8 -*-
"""精簡六顆在出錯後仍在；例外不上話筒。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot_servers import (
    MENU_COMPACT_ROWS,
    MENU_ROW1,
    MENU_ROW2,
    PHONE_BUSY,
    WayneTelegramBot,
    _ACTIVE_PHONE_UID,
)
from wayne_db import init_database


def _bot(tmp_path):
    db = str(tmp_path / "m.db")
    init_database(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot._pending = {}
    bot._last_card = {}
    bot._menu_pin_msgs = {}
    bot.charts_dir = str(tmp_path / "charts")
    return bot


def test_phone_busy_has_no_exception_placeholder():
    assert "{e}" not in PHONE_BUSY
    assert "Render" not in PHONE_BUSY
    assert "暫時沒跑完" in PHONE_BUSY


def test_context_uid_keeps_compact_keyboard_without_arg(tmp_path):
    bot = _bot(tmp_path)
    bot._set_menu_compact("9", True)
    token = _ACTIVE_PHONE_UID.set("9")
    try:
        kb = bot._keyboard()
        labels = [b.text for row in kb.keyboard for b in row]
        assert labels == [t for row in MENU_COMPACT_ROWS for t in row]
        assert "當沖" not in labels
        assert "大盤" not in labels
    finally:
        _ACTIVE_PHONE_UID.reset(token)
    kb2 = bot._keyboard()
    assert [b.text for b in kb2.keyboard[0]] == list(MENU_ROW1)
    assert [b.text for b in kb2.keyboard[1]] == list(MENU_ROW2)


def test_callback_bot_from_user_still_compact(tmp_path):
    """Inline 回調的 message.from_user 是機器人；精簡旗要認按的人。"""
    bot = _bot(tmp_path)
    bot._set_menu_compact("9001", True)
    bot_user = SimpleNamespace(id=555000, first_name="bot")
    msg = SimpleNamespace(from_user=bot_user, chat_id=9001)
    token = _ACTIVE_PHONE_UID.set("9001")
    try:
        assert bot._menu_uid_from_message(msg) == "9001"
        labels = [b.text for row in bot._reply_menu().keyboard for b in row]
        assert labels == [t for row in MENU_COMPACT_ROWS for t in row]
        actor = bot._actor_key(msg)
        assert actor.startswith("9001:")
        assert actor.endswith(":9001")
    finally:
        _ACTIVE_PHONE_UID.reset(token)


def test_restore_main_menu_compact_copy(tmp_path):
    bot = _bot(tmp_path)
    bot._set_menu_compact("9", True)
    msg = MagicMock()
    msg.chat_id = 9
    msg.from_user = SimpleNamespace(id=9)
    msg.reply_html = AsyncMock()
    asyncio.run(bot._restore_main_menu(msg, "9"))
    html = msg.reply_html.await_args.args[0]
    assert "精簡六顆" in html
    kb = msg.reply_html.await_args.kwargs["reply_markup"]
    labels = [b.text for row in kb.keyboard for b in row]
    assert labels == [t for row in MENU_COMPACT_ROWS for t in row]


def test_restore_main_menu_full_copy(tmp_path):
    bot = _bot(tmp_path)
    bot._set_menu_compact("9", False)
    msg = MagicMock()
    msg.chat_id = 9
    msg.from_user = SimpleNamespace(id=9)
    msg.reply_html = AsyncMock()
    asyncio.run(bot._restore_main_menu(msg, "9"))
    html = msg.reply_html.await_args.args[0]
    assert "兩排主選單" in html


def test_market_error_keeps_compact_and_hides_exception(tmp_path):
    from unittest.mock import patch

    bot = _bot(tmp_path)
    bot._set_menu_compact("9", True)
    bot._delete_message = AsyncMock()
    msg = MagicMock()
    msg.chat_id = 9
    msg.from_user = SimpleNamespace(id=9)
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()

    async def boom(coro, timeout=None):
        _ = timeout
        if hasattr(coro, "close"):
            coro.close()
        raise RuntimeError("secret traceback xyz")

    token = _ACTIVE_PHONE_UID.set("9")
    try:

        async def run():
            with patch("bot_servers.asyncio.wait_for", boom):
                await bot._send_market_page(msg, status=MagicMock())

        asyncio.run(run())
    finally:
        _ACTIVE_PHONE_UID.reset(token)
    text = msg.reply_text.await_args.args[0]
    assert text == PHONE_BUSY
    assert "secret" not in text
    kb = msg.reply_text.await_args.kwargs["reply_markup"]
    labels = [b.text for row in kb.keyboard for b in row]
    assert labels == [t for row in MENU_COMPACT_ROWS for t in row]


def test_source_hides_ops_and_tracebacks():
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "大盤讀取失敗：{e}" not in src
    assert "資金移動失敗：{e}" not in src
    assert "海選失敗：{e}" not in src
    assert "請到 Render Logs" not in src
    assert "PHONE_BUSY" in src
    assert "_ACTIVE_PHONE_UID" in src
    assert "self._reply_menu(str(chat_id))" in src
    assert "已回到主選單（精簡六顆）" in src


def test_start_mentions_compact():
    from bot_servers import WayneTelegramBot
    import inspect

    src = inspect.getsource(WayneTelegramBot.start_cmd)
    assert "精簡選單" in src
    assert "完整選單" in src
