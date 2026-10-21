# -*- coding: utf-8 -*-
"""圖文說明已取消：模組／assets 不在；話筒靜音 stub 仍在。"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
from unittest.mock import AsyncMock, MagicMock

from bot_servers import WayneTelegramBot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_picture_guide_module_and_assets_gone():
    assert importlib.util.find_spec("picture_guide") is None
    assert not os.path.isdir(os.path.join(ROOT, "picture_guide_assets"))
    assert not os.path.isfile(os.path.join(ROOT, "picture_guide.py"))
    assert not os.path.isfile(os.path.join(ROOT, "scripts", "render_picture_guide.py"))
    assert not os.path.isfile(os.path.join(ROOT, "scripts", "build_picture_guide_shots.py"))


def test_send_picture_guide_stub_is_noop():
    src = inspect.getsource(WayneTelegramBot._send_picture_guide)
    assert "reply_media_group" not in src
    assert "reply_photo" not in src
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    msg.reply_media_group = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.edit_media = AsyncMock()

    async def _run():
        await bot._send_picture_guide(msg)

    asyncio.run(_run())
    msg.reply_photo.assert_not_awaited()
    msg.reply_text.assert_not_awaited()
    msg.reply_html.assert_not_awaited()
    msg.reply_media_group.assert_not_called()


def test_picture_guide_keyboard_is_empty():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    mid = bot._picture_guide_keyboard(4, 9)
    last = bot._picture_guide_keyboard(8, 9)
    assert not mid.inline_keyboard
    assert not last.inline_keyboard


def test_show_picture_guide_page_stub_is_noop():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    msg = MagicMock()
    msg.edit_media = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.delete = AsyncMock()

    async def _run():
        await bot._show_picture_guide_page(msg, 1, edit=True, from_page=0)

    asyncio.run(_run())
    msg.edit_media.assert_not_awaited()
    msg.reply_photo.assert_not_called()
    show = inspect.getsource(WayneTelegramBot._show_picture_guide_page)
    assert "ensure_flip_gif" not in show
    assert "InputMediaAnimation" not in show


def test_bot_still_silences_pg_callback_and_typed_guide():
    src = open(os.path.join(ROOT, "bot_servers.py"), encoding="utf-8").read()
    assert 'startswith("pg:")' in src
    assert 'text == "圖文"' in src
    assert "async def _send_picture_guide" in src
    assert "async def _show_picture_guide_page" in src
    assert "圖文說明已取消" in src
