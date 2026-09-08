#!/usr/bin/env python3
"""從話筒截圖裁聊天區、畫紅圈，產出圖文說明配圖。

個人資訊（側欄帳號／編號／姓名）整塊裁掉，不進說明書。
LINE 登入信箱同樣不進說明書。
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ACCENT = (196, 92, 38)
WHITE = (255, 255, 255)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.environ.get("WAYNE_GUIDE_SHOT_SRC", "/tmp/computer-use")
DEST = os.path.join(ROOT, "picture_guide_assets")

# Telegram Web A：1280×800 時聊天區起點（裁掉 Chrome 頂列＋左側聯絡人）
CHAT_LEFT_FRAC = 0.29
CHAT_TOP_FRAC = 0.097


def _font(size: int):
    path = os.path.join(ROOT, "fonts", "NotoSansTC-w860.ttf")
    if os.path.isfile(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _crop_chat(im: Image.Image) -> Image.Image:
    w, h = im.size
    left = int(w * CHAT_LEFT_FRAC)
    top = int(h * CHAT_TOP_FRAC)
    return im.crop((left, top, w - 8, h - 8))


SCALE = 2


def _up(im: Image.Image) -> Image.Image:
    if SCALE == 1:
        return im
    return im.resize((im.width * SCALE, im.height * SCALE), Image.Resampling.LANCZOS)


def _ring(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    rx: int,
    ry: int | None = None,
    width: int = 7,
) -> None:
    cx, cy, rx = cx * SCALE, cy * SCALE, rx * SCALE
    ry = (rx if ry is None else ry * SCALE)
    width = max(8, width * SCALE)
    # 白邊再套紅圈，綠底上也看得清
    draw.ellipse((cx - rx - 3, cy - ry - 3, cx + rx + 3, cy + ry + 3), outline=WHITE, width=width + 4)
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=ACCENT, width=width)


def _caption_bar(im: Image.Image, text: str) -> Image.Image:
    font = _font(40)
    pad = 22
    # 兩行以內
    lines = [text]
    if "　" in text and len(text) > 22:
        parts = text.split("　", 1)
        lines = [parts[0], parts[1]] if parts[1] else [text]
    bar_h = 52 * len(lines) + 28
    out = Image.new("RGB", (im.width, im.height + bar_h), WHITE)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    d.rectangle((0, im.height, im.width, im.height + bar_h), fill=(255, 246, 236))
    y = im.height + 12
    for ln in lines:
        d.text((pad, y), ln, font=font, fill=ACCENT)
        y += 50
    return out


def _save(im: Image.Image, name: str) -> str:
    os.makedirs(DEST, exist_ok=True)
    path = os.path.join(DEST, name)
    im.save(path, "PNG", compress_level=4)
    print(path, im.size, os.path.getsize(path))
    return path


def _kb_slice(chat: Image.Image) -> Image.Image:
    """兩排主選單＋輸入列（含右側四格鍵盤圖示）。"""
    return chat.crop((0, 480, chat.width, chat.height))


def _swap_row2_streak_help(kb: Image.Image) -> Image.Image:
    """舊截圖第二排是說明／連買區；對調成連買區／說明再畫圈。"""
    out = kb.copy()
    help_box = (453, 118, 493, 154)
    streak_box = (499, 118, 539, 154)
    a = kb.crop(help_box)
    b = kb.crop(streak_box)
    out.paste(b, help_box[:2])
    out.paste(a, streak_box[:2])
    return out


def build(src: str = SRC) -> list[str]:
    paths: list[str] = []

    kb_src = os.path.join(src, "76b1a.webp")
    if os.path.isfile(kb_src):
        chat = _crop_chat(Image.open(kb_src).convert("RGB"))
        kb = _swap_row2_streak_help(_kb_slice(chat))
        # 量過的座標（1 倍聊天區；畫圈前再放大 2 倍）
        sl = _up(kb)
        d = ImageDraw.Draw(sl)
        _ring(d, 450, 115, 165, 44, 8)
        _ring(d, 555, 172, 26, 20, 6)
        paths.append(
            _save(
                _caption_bar(sl, "大紅圈：兩排按鈕　小圈：輸入列右邊四格圖示（不見就打 /menu）"),
                "cover_menu.png",
            )
        )

        sl2 = _up(kb)
        d = ImageDraw.Draw(sl2)
        _ring(d, 425, 92, 28, 22, 6)  # 持股
        _ring(d, 475, 92, 28, 22, 6)  # 觀察
        _ring(d, 575, 92, 30, 22, 6)  # AI倉
        paths.append(_save(_caption_bar(sl2, "紅圈：持股／觀察／AI倉　三種清單不要搞混"), "lists.png"))

        sl3 = _up(kb)
        d = ImageDraw.Draw(sl3)
        _ring(d, 473, 138, 32, 22, 6)  # 連買區（資金右邊）
        paths.append(_save(_caption_bar(sl3, "紅圈：連買區（第二排資金右邊）　官方法人連買，不是下單"), "streak.png"))

        sl4 = _up(kb)
        d = ImageDraw.Draw(sl4)
        _ring(d, 575, 138, 32, 22, 6)  # 回報
        paths.append(_save(_caption_bar(sl4, "紅圈：回報（第二排最右）　畫面怪打字或傳截圖"), "oops.png"))

        sl5 = _up(kb)
        d = ImageDraw.Draw(sl5)
        _ring(d, 525, 92, 32, 22, 6)  # 海選
        paths.append(
            _save(
                _caption_bar(sl5, "紅圈：海選　按一次等 2～5 分鐘，不要連按"),
                "screen.png",
            )
        )

    help_src = os.path.join(src, "6cf9c.webp")
    if os.path.isfile(help_src):
        chat = _crop_chat(Image.open(help_src).convert("RGB"))
        sl = _up(chat.crop((0, 0, chat.width, 340)))
        d = ImageDraw.Draw(sl)
        _ring(d, 430, 100, 48, 28, 7)  # 圖文
        paths.append(_save(_caption_bar(sl, "紅圈：說明頁「圖文」＝九張長圖說明書"), "help_pics.png"))

    alb_src = os.path.join(src, "99a09.webp")
    if os.path.isfile(alb_src):
        chat = _crop_chat(Image.open(alb_src).convert("RGB"))
        sl = _up(chat.crop((0, 0, chat.width, 500)))
        d = ImageDraw.Draw(sl)
        _ring(d, 360, 410, 180, 48, 8)  # 介紹／決策卡縮圖
        paths.append(
            _save(
                _caption_bar(sl, "紅圈：介紹／決策卡縮圖　點開放大；一次兩張"),
                "charts.png",
            )
        )

        bot = _up(chat.crop((0, 400, chat.width, chat.height)))
        d = ImageDraw.Draw(bot)
        _ring(d, 325, 155, 160, 52, 8)  # 籌碼／營收／產業（兩排都圈）
        paths.append(
            _save(
                _caption_bar(bot, "紅圈：圖下面這一排（籌碼／營收／產業），不在右側四格鍵盤"),
                "hub.png",
            )
        )

    card_src = os.path.join(src, "20cc7.webp")
    if os.path.isfile(card_src):
        im = Image.open(card_src).convert("RGB")
        sl = _up(im.crop((420, 55, 940, 720)))
        d = ImageDraw.Draw(sl)
        _ring(d, 260, 195, 200, 58, 8)  # 今日態度
        paths.append(
            _save(
                _caption_bar(sl, "紅圈：今日態度／粉紅紀律　不是買訊，進場只認下面的表"),
                "discipline.png",
            )
        )

    return paths


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    paths = build(src)
    print("n", len(paths))
    return 0 if paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
