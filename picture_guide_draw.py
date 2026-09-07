# -*- coding: utf-8 -*-
"""圖文說明下半：依該頁內文畫對得上的按鈕示意，不用錯截圖硬套。"""
from __future__ import annotations

from typing import Sequence, Tuple

_BG = (255, 255, 255)
_INK = (26, 36, 51)
_MUTED = (90, 98, 110)
_ACCENT = (196, 92, 38)
_LINE = (214, 204, 188)
_KEY = (248, 250, 252)
_KEY_LINE = (176, 196, 214)
_PINK = (255, 228, 232)
_PINK_INK = (176, 48, 64)
_GREEN = (46, 140, 90)
_CHAT = (246, 241, 232)

ROW1 = ["決策卡", "當沖", "持股", "觀察", "海選", "AI倉"]
ROW2 = ["隔日沖", "大盤", "資金", "連買區", "說明", "回報"]

# 測試用：每頁示意必須出現的字，對得上內文。
PANEL_MARKS = {
    "cover": ("四格", "決策卡", "/menu"),
    "menu": tuple(ROW1 + ROW2),
    "charts": ("介紹圖", "決策卡", "導航圖"),
    "hub": ("籌碼", "營收", "產業", "觀察", "記買入"),
    "discipline": ("不是買訊", "20 日表"),
    "screen": ("開 LINE・傳這檔", "一鍵傳 LINE"),
    "lists": ("觀察", "持股", "AI倉", "買入", "賣出", "AI操盤"),
    "streak": ("外資", "投信", "外資+投信"),
    "oops": ("決策卡", "回報", "/menu"),
}


def _text_w(draw, text: str, font) -> float:
    try:
        return float(draw.textlength(text, font=font))
    except Exception:
        return len(text or "") * (getattr(font, "size", 24) * 0.9)


def _center_text(draw, box, text: str, font, fill) -> None:
    x0, y0, x1, y1 = box
    tw = _text_w(draw, text, font)
    th = font.size
    draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2 - 2), text, font=font, fill=fill)


def _btn(draw, box, text: str, font, *, fill=_KEY, outline=_KEY_LINE, ink=_INK, width=3, rad=14):
    draw.rounded_rectangle(box, rad, fill=fill, outline=outline, width=width)
    if text:
        _center_text(draw, box, text, font, ink)


def _ring(draw, box, pad: int = 8, width: int = 6):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        (x0 - pad, y0 - pad, x1 + pad, y1 + pad),
        18,
        outline=_ACCENT,
        width=width,
    )


def _caption(draw, xy, text: str, font, fill=_ACCENT):
    draw.text(xy, text, font=font, fill=fill)


def _grid(draw, origin, cell_w, cell_h, gap, rows: Sequence[Sequence[str]], font, *, ring=None, ring_cells=None):
    """rows = list of button labels. ring_cells = {(r,c), ...}."""
    ox, oy = origin
    boxes = []
    for ri, row in enumerate(rows):
        row_boxes = []
        for ci, label in enumerate(row):
            x0 = ox + ci * (cell_w + gap)
            y0 = oy + ri * (cell_h + gap)
            box = (x0, y0, x0 + cell_w, y0 + cell_h)
            _btn(draw, box, label, font)
            if ring_cells and (ri, ci) in ring_cells:
                _ring(draw, box, pad=6, width=5)
            row_boxes.append(box)
        boxes.append(row_boxes)
    if ring == "all" and boxes:
        x0 = boxes[0][0][0]
        y0 = boxes[0][0][1]
        x1 = boxes[-1][-1][2]
        y1 = boxes[-1][-1][3]
        _ring(draw, (x0, y0, x1, y1), pad=10, width=6)
    return boxes


def draw_page_panel(slug: str, width: int, height: int):
    """畫滿 width×height 的示意面板。"""
    from PIL import Image, ImageDraw

    from picture_guide import _load_font

    img = Image.new("RGB", (max(1, width), max(1, height)), _CHAT)
    draw = ImageDraw.Draw(img)
    pad = 16
    draw.rounded_rectangle((4, 4, width - 5, height - 5), 22, fill=_BG, outline=_LINE, width=3)
    title_f = _load_font(max(28, int(width * 0.034)), bold=True)
    body_f = _load_font(max(24, int(width * 0.030)))
    small_f = _load_font(max(22, int(width * 0.026)))
    cap_f = _load_font(max(26, int(width * 0.032)), bold=True)
    fn = {
        "cover": _draw_cover,
        "menu": _draw_menu,
        "charts": _draw_charts,
        "hub": _draw_hub,
        "discipline": _draw_discipline,
        "screen": _draw_screen,
        "lists": _draw_lists,
        "streak": _draw_streak,
        "oops": _draw_oops,
    }.get(slug, _draw_menu)
    fn(draw, width, height, pad, title_f, body_f, small_f, cap_f)
    return img


def _draw_cover(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 10
    _caption(draw, (pad + 8, y), "輸入列右邊這一顆", cap_f)
    y += 48
    bar_h = 70
    x0, x1 = pad + 8, w - pad - 8
    draw.rounded_rectangle((x0, y, x1, y + bar_h), 18, fill=_KEY, outline=_KEY_LINE, width=3)
    burger = (x0 + 10, y + 12, x0 + 64, y + bar_h - 12)
    _btn(draw, burger, "選", small_f, fill=(230, 236, 242))
    draw.text((x0 + 78, y + 18), "打股名／代號，或按「決策卡」", font=small_f, fill=_MUTED)
    four = (x1 - 78, y + 10, x1 - 12, y + bar_h - 10)
    _btn(draw, four, "四格", small_f, fill=(255, 246, 236), outline=_ACCENT, ink=_ACCENT)
    _ring(draw, four, pad=7, width=5)
    y += bar_h + 28
    _caption(draw, (pad + 8, y), "展開後是這兩排（不見就打 /menu）", cap_f)
    y += 50
    inner = w - 2 * pad - 16
    gap = 8
    cell_w = (inner - 5 * gap) // 6
    cell_h = 56
    _grid(draw, (pad + 8, y), cell_w, cell_h, gap, [ROW1, ROW2], small_f, ring="all")


def _draw_menu(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 8
    _caption(draw, (pad + 8, y), "第一排", cap_f)
    y += 44
    inner = w - 2 * pad - 16
    gap = 8
    cell_w = (inner - 5 * gap) // 6
    cell_h = 64
    _grid(draw, (pad + 8, y), cell_w, cell_h, gap, [ROW1], small_f)
    y += cell_h + 28
    _caption(draw, (pad + 8, y), "第二排：連買區在說明左邊", cap_f)
    y += 44
    boxes = _grid(draw, (pad + 8, y), cell_w, cell_h, gap, [ROW2], small_f)
    # 圈 連買區、說明
    if boxes:
        _ring(draw, boxes[0][3], pad=6, width=5)
        _ring(draw, boxes[0][4], pad=6, width=5)
    y += cell_h + 24
    _caption(draw, (pad + 8, y), "畫面怪 → 最右「回報」", body_f)


def _draw_charts(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 8
    _caption(draw, (pad + 8, y), "打 2330 一次出這三張，點開放大", cap_f)
    y += 52
    labels = ("介紹圖", "決策卡", "導航圖")
    notes = ("熱不熱、獲利", "高低卡表", "近半年走勢")
    inner = w - 2 * pad - 16
    gap = 12
    cw = (inner - 2 * gap) // 3
    ch = min(280, h - y - 90)
    x = pad + 8
    for i, (lab, note) in enumerate(zip(labels, notes)):
        box = (x, y, x + cw, y + ch)
        fill = (255, 252, 246) if i != 1 else (255, 244, 238)
        _btn(draw, box, "", small_f, fill=fill, rad=18)
        _center_text(draw, (x, y + ch * 0.28, x + cw, y + ch * 0.52), lab, title_f, _INK)
        _center_text(draw, (x, y + ch * 0.52, x + cw, y + ch * 0.72), note, small_f, _MUTED)
        x += cw + gap
    _ring(draw, (pad + 8, y, w - pad - 8, y + ch), pad=6, width=5)
    y += ch + 20
    _caption(draw, (pad + 8, y), "進場只認決策卡的表，不認紅箭頭", cap_f)


def _draw_hub(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 8
    _caption(draw, (pad + 8, y), "查完圖，下面才出現這一排", cap_f)
    y += 48
    thumb = (pad + 8, y, w - pad - 8, y + 90)
    _btn(draw, thumb, "2330 介紹圖／決策卡／導航圖", body_f, fill=(236, 242, 248), rad=16)
    y += 110
    inner = w - 2 * pad - 16
    gap = 10
    cw = (inner - 2 * gap) // 3
    ch = 64
    r1 = ["籌碼", "營收", "產業"]
    r2 = ["觀察", "記買入", "說明"]
    boxes1 = _grid(draw, (pad + 8, y), cw, ch, gap, [r1], body_f)
    _ring(draw, (boxes1[0][0][0], boxes1[0][0][1], boxes1[0][2][2], boxes1[0][2][3]), pad=8, width=6)
    y += ch + 18
    _grid(draw, (pad + 8, y), cw, ch, gap, [r2], body_f)
    y += ch + 22
    _caption(draw, (pad + 8, y), "找不到產業：在這裡，不在右側四格鍵盤", cap_f)


def _draw_discipline(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 8
    _caption(draw, (pad + 8, y), "粉紅句子只講現在怎樣", cap_f)
    y += 46
    box = (pad + 8, y, w - pad - 8, y + 120)
    draw.rounded_rectangle(box, 18, fill=_PINK, outline=_PINK_INK, width=4)
    _center_text(draw, (box[0], box[1] + 8, box[2], box[1] + 64), "漲多了，今天別追", title_f, _PINK_INK)
    _center_text(draw, (box[0], box[1] + 64, box[2], box[3] - 8), "不是買訊，也不改海選", body_f, _MUTED)
    y += 140
    _caption(draw, (pad + 8, y), "進場只認下面這張 20日表", cap_f)
    y += 44
    table = (pad + 8, y, w - pad - 8, min(h - pad - 12, y + 220))
    _btn(draw, table, "", small_f, fill=(255, 252, 248), rad=16)
    headers = ("日期", "收盤", "獲利", "溫度")
    cols = 4
    tw = table[2] - table[0]
    cw = tw / cols
    hf = small_f
    for i, hd in enumerate(headers):
        _center_text(draw, (table[0] + i * cw, table[1] + 10, table[0] + (i + 1) * cw, table[1] + 48), hd, hf, _MUTED)
    rows = (("9/4", "60.8", "2.4%", "41°"), ("9/3", "59.6", "0.3%", "38°"), ("9/2", "59.4", "0.0%", "35°"))
    for ri, rec in enumerate(rows):
        yy0 = table[1] + 54 + ri * 44
        for ci, val in enumerate(rec):
            ink = _PINK_INK if ci == 2 and rec[2].startswith("2") else _INK
            if ci == 2 and rec[2].startswith("0.0"):
                ink = _GREEN
            _center_text(draw, (table[0] + ci * cw, yy0, table[0] + (ci + 1) * cw, yy0 + 40), val, hf, ink)


def _draw_screen(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 8
    _caption(draw, (pad + 8, y), "海選名單：左看圖、右加觀察", cap_f)
    y += 46
    inner = w - 2 * pad - 16
    gap = 10
    picks = (("2330 台積電", "+"), ("4915 致伸", "+"))
    name_w = int(inner * 0.72)
    plus_w = inner - name_w - gap
    ch = 52
    for name, plus in picks:
        _btn(draw, (pad + 8, y, pad + 8 + name_w, y + ch), name, body_f)
        _btn(draw, (pad + 8 + name_w + gap, y, pad + 8 + inner, y + ch), plus, title_f, ink=_GREEN)
        y += ch + 8
        link = (pad + 8, y, pad + 8 + name_w, y + 44)
        _btn(draw, link, "開 LINE・傳這檔", small_f, fill=(232, 255, 240), outline=_GREEN, ink=_GREEN)
        _ring(draw, link, pad=5, width=4)
        y += 54
    y += 4
    _caption(draw, (pad + 8, y), "區底才是一次傳好幾檔", cap_f)
    y += 42
    pack = (pad + 8, y, w - pad - 8, y + 58)
    _btn(draw, pack, "一鍵傳 LINE", title_f, fill=(232, 255, 240), outline=_GREEN, ink=_GREEN)
    _ring(draw, pack, pad=6, width=5)


def _draw_lists(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 6
    inner = w - 2 * pad - 16
    gap = 8
    # 三欄
    cw = (inner - 2 * gap) // 3
    panels = (
        ("觀察＝還沒買", (("2330 台積電", "籌碼"), ("買入", "刪"))),
        ("持股＝手記的", (("2330 台積電", "賣出"), ("成交／復盤／AI倉", ""))),
        ("AI倉＝假錢", (("留現金", "1／3"), ("AI操盤", ""))),
    )
    x = pad + 8
    for title, rows in panels:
        _caption(draw, (x, y), title, cap_f)
        py = y + 42
        ph = min(h - py - pad, 260)
        _btn(draw, (x, py, x + cw, py + ph), "", small_f, fill=(252, 250, 246), rad=16)
        by = py + 16
        bw = (cw - 24 - 8) // 2
        bh = 48
        for r in rows:
            bx = x + 12
            for lab in r:
                if lab:
                    _btn(draw, (bx, by, bx + bw, by + bh), lab, small_f)
                bx += bw + 8
            by += bh + 10
        x += cw + gap
    y = y + 42 + min(h - (y + 42) - pad, 260) + 12
    if y < h - 40:
        _caption(draw, (pad + 8, min(y, h - 48)), "三種清單不要搞混", cap_f)


def _draw_streak(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 8
    _caption(draw, (pad + 8, y), "先選誰在買", cap_f)
    y += 46
    inner = w - 2 * pad - 16
    gap = 10
    cw = (inner - gap) // 2
    ch = 64
    b1 = (pad + 8, y, pad + 8 + cw, y + ch)
    b2 = (pad + 8 + cw + gap, y, pad + 8 + inner, y + ch)
    _btn(draw, b1, "外資", body_f)
    _btn(draw, b2, "投信", body_f)
    _ring(draw, b1, pad=6, width=5)
    y += ch + 12
    both = (pad + 8, y, w - pad - 8, y + ch)
    _btn(draw, both, "外資+投信", body_f)
    y += ch + 24
    _caption(draw, (pad + 8, y), "再點天數（上市櫃一起列）", cap_f)
    y += 46
    days = ["3", "5", "10", "20", "30"]
    dw = (inner - 4 * gap) // 5
    dh = 58
    boxes = _grid(draw, (pad + 8, y), dw, dh, gap, [days], body_f)
    if boxes:
        _ring(draw, boxes[0][2], pad=6, width=5)
    y += dh + 22
    _caption(draw, (pad + 8, y), "不是下單訊號。按錯就改按別顆。", cap_f)


def _draw_oops(draw, w, h, pad, title_f, body_f, small_f, cap_f):
    y = pad + 8
    _caption(draw, (pad + 8, y), "一打開別先按決策卡", cap_f)
    y += 44
    inner = w - 2 * pad - 16
    gap = 8
    cell_w = (inner - 5 * gap) // 6
    cell_h = 56
    boxes = _grid(draw, (pad + 8, y), cell_w, cell_h, gap, [ROW1, ROW2], small_f)
    # 決策卡 = (0,0) 畫紅叉感：圈＋「別先按」
    bad = boxes[0][0]
    _ring(draw, bad, pad=6, width=6)
    _caption(draw, (bad[0] - 4, bad[3] + 8), "別先按", cap_f)
    good = boxes[1][5]
    _ring(draw, good, pad=6, width=6)
    y2 = boxes[1][0][3] + 48
    _caption(draw, (pad + 8, y2), "畫面怪、數字怪 → 最右「回報」", cap_f)
    y2 += 48
    _caption(draw, (pad + 8, y2), "主選單不見：點四格，或打 /menu", body_f)
