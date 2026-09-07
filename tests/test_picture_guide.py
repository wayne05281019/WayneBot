# -*- coding: utf-8 -*-
"""圖文說明 9 頁：寬度、禁 emoji、與真實按鈕用詞對齊。"""
from __future__ import annotations

import os

from PIL import Image

from picture_guide import (
    CACHE_VER,
    PAGE_SLUGS,
    PAGE_WIDTH,
    PAGES,
    page_copy_blob,
    render_page,
    render_picture_guide,
)


def test_nine_pages_1080_and_no_emoji(tmp_path):
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
    for p in paths:
        assert os.path.getsize(p) > 8_000
        with Image.open(p) as im:
            assert im.size[0] == PAGE_WIDTH
            assert im.size[1] >= 1200


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


def test_send_picture_guide_media_group_no_caption_none(tmp_path):
    import asyncio
    import inspect
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_picture_guide)
    assert "caption=None" not in src
    dest = str(tmp_path / "g")
    paths = render_picture_guide(dest, force=True)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.charts_dir = dest
    msg = MagicMock()
    status = MagicMock()
    status.delete = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)
    msg.reply_html = AsyncMock()
    msg.reply_media_group = AsyncMock(return_value=[MagicMock()])
    msg.reply_photo = AsyncMock()

    async def _run():
        with patch("picture_guide.render_picture_guide", return_value=paths):
            await bot._send_picture_guide(msg)

    asyncio.run(_run())
    msg.reply_media_group.assert_awaited()
    media = msg.reply_media_group.await_args.kwargs.get("media") or msg.reply_media_group.await_args.args[0]
    assert len(media) == 9
    assert media[0].caption
