# -*- coding: utf-8 -*-
"""圖文說明 9 頁：寬度、禁 emoji、與真實按鈕用詞對齊。"""
from __future__ import annotations

import os

from PIL import Image

from picture_guide import (
    BODY_SIZE,
    CACHE_VER,
    MARGIN,
    MAX_BODY_SIZE,
    MIN_BODY_SIZE,
    PAGE_SHOTS,
    PAGE_SLUGS,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PAGES,
    SHOT_TOP_RATIO,
    TEXT_SHOT_GAP,
    TITLE_SIZE,
    asset_dir,
    page_copy_blob,
    render_page,
    render_picture_guide,
    ensure_page,
    _is_caption_fill,
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
    assert "紅圈" in blob
    assert "連買區　說明　回報" in blob
    assert "如何賣" in blob
    assert "最高價＝20日高" in blob
    assert "06:30 早報" in blob
    assert "20:00 AI倉模擬" in blob
    assert "原因" in blob
    assert "三條槓" in blob
    assert CACHE_VER == "v16"
    assert "一張圖卡" in blob
    assert "跑馬燈" in blob
    assert "細項小框" in blob
    assert PAGE_WIDTH == 1080
    assert PAGE_HEIGHT == 1920
    assert PAGE_WIDTH / PAGE_HEIGHT == 1080 / 1920
    assert TITLE_SIZE >= 72
    assert BODY_SIZE >= 50
    assert MIN_BODY_SIZE >= 48
    assert MARGIN <= 40
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
    """配圖卡左右貼齊內文寬；貼在下半，不要佔滿到跟字黏在一起。"""
    slug, title, body = PAGES[1]
    out = str(tmp_path / "menu.png")
    render_page(slug, title, body, out)
    with Image.open(out) as im:
        bg = (18, 26, 38)

        def _near(c, t, tol=18):
            return all(abs(a - b) <= tol for a, b in zip(c, t))

        card_top = None
        for y in range(im.height - 12, int(im.height * 0.45), -1):
            xs = [x for x in range(MARGIN, im.width - MARGIN) if not _near(im.getpixel((x, y)), bg)]
            if xs:
                card_top = y
            elif card_top is not None:
                break
        assert card_top is not None, "lower half should have a screenshot card"
        assert card_top >= int(PAGE_HEIGHT * 0.48)
        y = min(im.height - 40, card_top + 20)
        xs = [x for x in range(im.width) if not _near(im.getpixel((x, y)), bg)]
        assert xs, "shot card should have ink"
        assert xs[0] <= MARGIN + 12
        assert xs[-1] >= PAGE_WIDTH - MARGIN - 12
        assert (xs[-1] - xs[0]) >= PAGE_WIDTH - 2 * MARGIN - 24


def test_keyboard_shot_trimmed_to_buttons():
    path = os.path.join(asset_dir(), "cover_menu.png")
    im = Image.open(path)
    trimmed = _trim_guide_shot("cover_menu.png", im.convert("RGB"))
    assert trimmed.width < im.width
    assert trimmed.height < im.height
    assert trimmed.width / trimmed.height < 5.0
    # 右側要留到「回報／AI倉」，不要裁掉第二排最右。
    assert trimmed.width / im.width >= 0.75
    cream = 0
    tw, th = trimmed.size
    px = trimmed.load()
    for y in range(max(0, th - 24), th):
        for x in range(0, tw, 5):
            if _is_caption_fill(px[x, y]):
                cream += 1
    assert cream < 8, cream


def test_guide_assets_caption_bar_stripped():
    for name in set(PAGE_SHOTS.values()):
        path = os.path.join(asset_dir(), name)
        im = Image.open(path).convert("RGB")
        trimmed = _trim_guide_shot(name, im)
        tw, th = trimmed.size
        px = trimmed.load()
        cream = 0
        n = 0
        for y in range(max(0, int(th * 0.92)), th):
            for x in range(0, tw, 6):
                n += 1
                if _is_caption_fill(px[x, y]):
                    cream += 1
        assert n, name
        assert cream / n < 0.04, f"{name} leftover caption {cream}/{n}"


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
    assert any("第 2 張 →" in t for t in labels)
    assert not any("← 第" in t for t in labels)


def test_picture_guide_keyboard_middle_and_last():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    mid = bot._picture_guide_keyboard(4, 9)
    labels = [b.text for row in mid.inline_keyboard for b in row]
    assert any("← 第 4 張" in t for t in labels)
    assert any("第 6 張 →" in t for t in labels)
    last = bot._picture_guide_keyboard(8, 9)
    labels = [b.text for row in last.inline_keyboard for b in row]
    assert any("← 第 8 張" in t for t in labels)
    assert not any("→" in t for t in labels if "第 9 張" in t or t.startswith("第"))


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
    assert any("← 第 1 張" in t for t in labels)
    assert any("第 3 張 →" in t for t in labels)


def test_pages_navy_white_and_utf8(tmp_path):
    dest = str(tmp_path / "navy")
    paths = render_picture_guide(dest, force=True)
    blob = page_copy_blob()
    assert "�" not in blob
    assert "图文" not in blob
    assert "说明书" not in blob
    beige = (246, 241, 232)
    for p in paths:
        with Image.open(p) as im:
            corner = im.getpixel((24, PAGE_HEIGHT - 12))
            assert all(abs(a - b) <= 22 for a, b in zip(corner, (18, 26, 38))), corner
            assert not all(abs(a - b) <= 18 for a, b in zip(corner, beige))
            left = im.getpixel((4, 200))
            assert left[2] >= 180  # 左側青條


def test_ensure_page_does_not_render_all_nine(tmp_path):
    dest = str(tmp_path / "lazy")
    one = ensure_page("cover", dest)
    names = {n for n in os.listdir(dest) if n.endswith(".png")}
    assert os.path.basename(one).endswith("cover.png")
    assert names == {f"{CACHE_VER}-cover.png"}


def test_flip_gif_then_photo_when_from_page_known(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import WayneTelegramBot
    from picture_guide import ensure_page

    dest = str(tmp_path / "flip")
    ensure_page("cover", dest)
    ensure_page("menu", dest)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.charts_dir = dest
    msg = MagicMock()
    msg.edit_media = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.delete = AsyncMock()

    async def _run():
        with patch("asyncio.sleep", new=AsyncMock()):
            await bot._show_picture_guide_page(msg, 1, edit=True, from_page=0)

    asyncio.run(_run())
    assert msg.edit_media.await_count == 2
    first = msg.edit_media.await_args_list[0].kwargs["media"]
    last = msg.edit_media.await_args_list[1].kwargs["media"]
    assert type(first).__name__ == "InputMediaAnimation"
    assert type(last).__name__ == "InputMediaPhoto"
    msg.reply_photo.assert_not_called()


def test_parse_guide_callback_old_and_new():
    from picture_guide import parse_guide_callback

    assert parse_guide_callback("pg:3") == (None, 3)
    assert parse_guide_callback("pg:2-3") == (2, 3)
    assert parse_guide_callback("pg:3-2") == (3, 2)


def test_wrapped_lines_stay_inside_and_keep_menu_token():
    from PIL import Image, ImageDraw

    from picture_guide import MAX_BODY_SIZE, _layout_body, _load_font, _text_w

    max_w = PAGE_WIDTH - 2 * MARGIN
    probe = Image.new("RGB", (200, 200))
    draw = ImageDraw.Draw(probe)
    font = _load_font(MAX_BODY_SIZE)
    blob_lines = []
    for slug, _title, body in PAGES:
        rows = _layout_body(draw, body, font, max_w)
        for row in rows:
            if row is None:
                continue
            indent, line = row
            right = MARGIN + indent + _text_w(draw, line, font)
            assert right <= PAGE_WIDTH - MARGIN + 2.0, f"{slug} {right:.1f} {line!r}"
            blob_lines.append(line)
            assert line.strip() not in ("/", "menu")
            assert not line.rstrip().endswith("打 /")
    joined = "\n".join(blob_lines)
    assert "/menu" in joined


def _near_rgb(c, t, tol=18):
    return all(abs(a - b) <= tol for a, b in zip(c[:3], t))


def test_cover_and_menu_title_centered_shot_in_lower_half(tmp_path):
    """主標題置中；配圖在下半；文圖中間留空；底欄不得出現半截「見就打/menu）」。"""
    dest = str(tmp_path / "layout")
    os.makedirs(dest, exist_ok=True)
    bg = (18, 26, 38)
    for slug in ("cover", "menu"):
        title, body = next((t, b) for s, t, b in PAGES if s == slug)
        out = os.path.join(dest, f"{slug}.png")
        render_page(slug, title, body, out)
        with Image.open(out) as im:
            # 標題列約在頂欄底下。找高亮度墨水的水平重心。
            y0, y1 = 78, 168
            xs = []
            for y in range(y0, y1):
                for x in range(MARGIN + 20, PAGE_WIDTH - MARGIN - 20):
                    r, g, b = im.getpixel((x, y))[:3]
                    if r + g + b >= 540 and abs(r - g) < 40:
                        xs.append(x)
            assert xs, slug
            cx = sum(xs) / len(xs)
            assert abs(cx - PAGE_WIDTH / 2) <= 36, (slug, cx)

            cream = 0
            n = 0
            px = im.load()
            for y in range(PAGE_HEIGHT - 36, PAGE_HEIGHT):
                for x in range(0, PAGE_WIDTH, 4):
                    n += 1
                    if _is_caption_fill(px[x, y]):
                        cream += 1
            assert cream / n < 0.02, f"{slug} caption leftover {cream}/{n}"

            card_top = None
            for y in range(PAGE_HEIGHT - 16, int(PAGE_HEIGHT * 0.40), -2):
                row = [
                    x
                    for x in range(MARGIN, PAGE_WIDTH - MARGIN, 3)
                    if not _near_rgb(im.getpixel((x, y)), bg)
                ]
                if row:
                    card_top = y
                elif card_top is not None:
                    break
            assert card_top is not None, slug
            assert card_top >= int(PAGE_HEIGHT * SHOT_TOP_RATIO) - 24
            gap_ink = 0
            for y in range(card_top - 56, card_top - 12):
                for x in range(MARGIN + 80, PAGE_WIDTH - MARGIN - 80, 6):
                    if not _near_rgb(im.getpixel((x, y)), bg, 28):
                        gap_ink += 1
            assert gap_ink < 80, (slug, gap_ink, card_top)
            assert card_top - 280 >= TEXT_SHOT_GAP
