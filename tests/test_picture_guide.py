# -*- coding: utf-8 -*-
"""圖文說明 9 頁：寬度、禁 emoji、與真實按鈕用詞對齊。"""
from __future__ import annotations

import os

from PIL import Image

from picture_guide import (
    CACHE_VER,
    PAGE_SHOTS,
    PAGE_SLUGS,
    PAGE_WIDTH,
    PAGES,
    asset_dir,
    page_copy_blob,
    render_page,
    render_picture_guide,
)


def test_nine_pages_large_type_and_no_emoji(tmp_path):
    dest = str(tmp_path / "guide")
    paths = render_picture_guide(dest, force=True)
    assert [os.path.basename(p).split("-", 1)[-1].replace(".png", "") for p in paths] == list(PAGE_SLUGS)
    assert len(paths) == 9
    blob = page_copy_blob()
    assert "⌨️" not in blob
    assert "➕" not in blob
    assert "①" not in blob
    assert "黃金買點" in blob
    assert "開 LINE・傳這檔" in blob
    assert "一鍵傳 LINE" in blob
    assert "回報" in blob
    assert "記買入" in blob
    assert "外資+投信" in blob
    assert "四格" in blob
    assert "第 2 張" in blob
    assert "月K還在往上" in blob
    assert CACHE_VER == "v7"
    assert PAGE_WIDTH >= 1440
    for p in paths:
        assert os.path.getsize(p) > 20_000
        with Image.open(p) as im:
            assert im.size[0] == PAGE_WIDTH
            assert im.size[1] >= 1600


def test_assets_crop_sidebar_and_no_pii():
    banned = (b"8528875978", b"wei72152", b"Weichuan", b"gmail.com")
    names = set(PAGE_SHOTS.values()) | {"help_pics.png"}
    for name in names:
        path = os.path.join(asset_dir(), name)
        assert os.path.isfile(path), name
        raw = open(path, "rb").read()
        assert len(raw) > 8_000, name
        for needle in banned:
            assert needle not in raw, f"{name} leaked {needle!r}"


def test_cache_reuse(tmp_path):
    dest = str(tmp_path / "g")
    a = render_picture_guide(dest, force=True)
    mtime = os.path.getmtime(a[0])
    b = render_picture_guide(dest, force=False)
    assert a == b
    assert os.path.getmtime(b[0]) == mtime
    assert CACHE_VER in os.path.basename(a[0])


def test_page_render_roundtrip(tmp_path):
    out = str(tmp_path / "one.png")
    slug, title, body = PAGES[0]
    render_page(slug, title, body, out)
    with Image.open(out) as im:
        assert im.size[0] == PAGE_WIDTH


def test_send_picture_guide_one_page_with_next_button(tmp_path):
    import asyncio
    import inspect
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_picture_guide)
    assert "caption=None" not in src
    assert "reply_media_group" not in src
    dest = str(tmp_path / "g")
    paths = render_picture_guide(dest, force=True)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.charts_dir = dest
    msg = MagicMock()
    status = MagicMock()
    status.delete = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)
    msg.reply_html = AsyncMock()
    msg.reply_media_group = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.edit_media = AsyncMock()

    async def _run():
        with patch("picture_guide.render_picture_guide", return_value=paths):
            await bot._send_picture_guide(msg)

    asyncio.run(_run())
    msg.reply_photo.assert_awaited()
    msg.reply_media_group.assert_not_called()
    kwargs = msg.reply_photo.await_args.kwargs
    assert "圖文 1／" in str(kwargs.get("caption") or "")
    labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert "第 2 張 →" in labels
    assert not any(t.startswith("←") for t in labels)


def test_picture_guide_keyboard_middle_and_last():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    mid = bot._picture_guide_keyboard(4, 9)
    labels = [b.text for row in mid.inline_keyboard for b in row]
    assert "← 第 4 張" in labels
    assert "第 6 張 →" in labels
    last = bot._picture_guide_keyboard(8, 9)
    labels = [b.text for row in last.inline_keyboard for b in row]
    assert "← 第 8 張" in labels
    assert not any("→" in t for t in labels if t.startswith("第"))


def test_picture_guide_flip_edits_same_message(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import WayneTelegramBot

    dest = str(tmp_path / "g")
    paths = render_picture_guide(dest, force=True)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.charts_dir = dest
    msg = MagicMock()
    msg.edit_media = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.delete = AsyncMock()

    async def _run():
        with patch("picture_guide.render_picture_guide", return_value=paths):
            await bot._show_picture_guide_page(msg, 1, edit=True)

    asyncio.run(_run())
    msg.edit_media.assert_awaited()
    msg.reply_photo.assert_not_called()
    media = msg.edit_media.await_args.kwargs["media"]
    assert "圖文 2／" in str(media.caption or "")
    labels = [b.text for row in msg.edit_media.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
    assert "← 第 1 張" in labels
    assert "第 3 張 →" in labels
