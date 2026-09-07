# -*- coding: utf-8 -*-
"""圖文說明 9 頁：寬度、禁 emoji、與真實按鈕用詞對齊。"""
from __future__ import annotations

import os

from PIL import Image

from picture_guide import (
    BODY_SIZE,
    CACHE_VER,
    MARGIN,
    MIN_BODY_SIZE,
    PAGE_SHOTS,
    PAGE_SLUGS,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PAGES,
    TITLE_SIZE,
    asset_dir,
    page_copy_blob,
    render_page,
    render_picture_guide,
    _trim_guide_shot,
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
    assert "留現金" in blob
    assert "平常最多用 1 份" in blob
    assert "這波先當結束" in blob
    assert "官方收盤掃全市場" in blob
    assert "連買區　說明　回報" in blob
    assert "如何賣" in blob
    assert "最高價＝20日高" in blob
    assert "06:30 早報" in blob
    assert "20:00 AI倉模擬" in blob
    assert CACHE_VER == "v11"
    assert PAGE_WIDTH == 1080
    assert PAGE_HEIGHT == 1920
    assert PAGE_WIDTH / PAGE_HEIGHT == 1080 / 1920
    assert TITLE_SIZE >= 72
    assert BODY_SIZE >= 50
    assert MIN_BODY_SIZE >= 48
    assert MARGIN <= 32
    # 390 寬話筒點開：52px 內文 ≈ 19 點，不要再縮到看不清。
    assert BODY_SIZE * (390 / PAGE_WIDTH) >= 18
    sizes = set()
    for p in paths:
        assert os.path.getsize(p) > 20_000
        assert os.path.getsize(p) <= 9_800_000
        with Image.open(p) as im:
            assert im.size == (PAGE_WIDTH, PAGE_HEIGHT)
            sizes.add(im.size)
    assert len(sizes) == 1


def test_panel_marks_match_page_copy():
    """每頁示意的按鈕／入口必須出現在該頁內文，避免再文不對題。"""
    from picture_guide_draw import PANEL_MARKS

    by_slug = {slug: body for slug, _title, body in PAGES}
    for slug, marks in PANEL_MARKS.items():
        body = by_slug[slug]
        blob = by_slug[slug]
        for mark in marks:
            assert mark in blob, f"{slug} copy missing {mark!r}"
    assert "開 LINE・傳這檔" in by_slug["screen"]
    assert "一鍵傳 LINE" in by_slug["screen"]
    assert "外資+投信" in by_slug["streak"]
    assert "記買入" in by_slug["hub"]
    assert "連買區" in by_slug["menu"]


def test_page_panels_are_not_the_same_keyboard_crop(tmp_path):
    from hashlib import sha1

    from picture_guide_draw import draw_page_panel

    hashes = []
    for slug, _t, _b in PAGES:
        im = draw_page_panel(slug, 640, 480)
        hashes.append(sha1(im.tobytes()).hexdigest())
    assert len(set(hashes)) == 9


def test_shot_builder_swaps_help_and_streak():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "scripts", "build_picture_guide_shots.py"),
        encoding="utf-8",
    ).read()
    assert "_swap_row2_streak_help" in src
    assert "第二排資金右邊" in src
    assert "第二排右二" not in src


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
        assert im.size == (PAGE_WIDTH, PAGE_HEIGHT)


def test_shot_panel_fills_content_width(tmp_path):
    """下半截圖左右貼齊內文寬，不要再留大塊米色邊。"""
    slug, title, body = PAGES[1]
    out = str(tmp_path / "menu.png")
    render_page(slug, title, body, out)
    with Image.open(out) as im:
        y = int(im.height * 0.84)
        bg = (246, 241, 232)

        def _near(c, t, tol=18):
            return all(abs(a - b) <= tol for a, b in zip(c, t))

        xs = [x for x in range(im.width) if not _near(im.getpixel((x, y)), bg)]
        assert xs, "lower third should be the screenshot, not empty beige"
        assert xs[0] <= MARGIN + 12
        assert xs[-1] >= PAGE_WIDTH - MARGIN - 12
        assert (xs[-1] - xs[0]) >= PAGE_WIDTH - 2 * MARGIN - 24


def test_keyboard_shot_trimmed_to_buttons():
    path = os.path.join(asset_dir(), "cover_menu.png")
    from PIL import Image

    im = Image.open(path)
    trimmed = _trim_guide_shot("cover_menu.png", im.convert("RGB"))
    assert trimmed.width < im.width
    assert trimmed.height < im.height
    assert trimmed.width / trimmed.height < 5.0


def test_send_picture_guide_one_page_with_next_button(tmp_path):
    import asyncio
    import inspect
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_picture_guide)
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
    assert not (kwargs.get("caption") or "")
    assert "圖文 1／" not in str(kwargs)
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
    assert not (getattr(media, "caption", None) or "")
    labels = [b.text for row in msg.edit_media.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
    assert "← 第 1 張" in labels
    assert "第 3 張 →" in labels
