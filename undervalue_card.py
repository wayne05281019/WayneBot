# -*- coding: utf-8 -*-
"""低估名單最終結果 PNG（話筒出圖）。只排版，不重算選股／買訊。
規格：最終結果顯示的排版（4:5），對齊 industry_card 深底語彙。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

# --- 畫布（邏輯 px；實渲 × SCALE）---
BASE_W = 1080
BASE_H = 1350
SCALE = 2

BG = (12, 18, 28)
CARD = (22, 34, 48)
CARD_EDGE = (78, 118, 158)
TEXT = (236, 242, 248)
HEAD = (132, 208, 255)
MUTED = (168, 186, 204)
ROW_A = (28, 42, 58)
ROW_B = (22, 34, 48)
STAR = (255, 196, 72)
WATCH = (180, 198, 216)
NEG = (120, 220, 168)
POS = (255, 160, 140)
DIV = (48, 68, 88)

_TAIPEI = ZoneInfo("Asia/Taipei")


def _px(n: float) -> int:
    return int(round(n * SCALE))


def _font(size_logic: float, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """與 industry_card 同一套字型路徑（含 wayne_navigator 權重檔＋系統 Noto），CI 才找得到。"""
    from industry_card import _card_font

    return _card_font(_px(size_logic), bold=bold)


def _ink(font: ImageFont.ImageFont, text: str) -> Tuple[int, int, int, int]:
    return font.getbbox(str(text or ""))


def _text_left_mid(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float, float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill,
) -> None:
    x0, y0, _x1, y1 = xy
    l, t, r, b = _ink(font, text)
    ty = y0 + ((y1 - y0) - (b - t)) / 2.0 - t
    draw.text((x0 - l, ty), str(text), font=font, fill=fill)


def _text_right_mid(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float, float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill,
) -> None:
    _x0, y0, x1, y1 = xy
    l, t, r, b = _ink(font, text)
    tw = r - l
    tx = x1 - tw - l
    ty = y0 + ((y1 - y0) - (b - t)) / 2.0 - t
    draw.text((tx, ty), str(text), font=font, fill=fill)


def _text_center_mid(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float, float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill,
) -> None:
    x0, y0, x1, y1 = xy
    l, t, r, b = _ink(font, text)
    tw, th = r - l, b - t
    draw.text(
        (x0 + (x1 - x0 - tw) / 2.0 - l, y0 + (y1 - y0 - th) / 2.0 - t),
        str(text),
        font=font,
        fill=fill,
    )


def _truncate(font: ImageFont.ImageFont, text: str, max_w: float) -> str:
    s = str(text or "").strip()
    if not s:
        return "—"
    if font.getlength(s) <= max_w:
        return s
    ell = "…"
    while s and font.getlength(s + ell) > max_w:
        s = s[:-1]
    return (s + ell) if s else ell


def _fmt_num(v: Any, digits: int = 1) -> str:
    if v is None or v == "":
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if digits == 0:
        return f"{x:.0f}"
    return f"{x:.{digits}f}"


def _fmt_pct(v: Any) -> str:
    if v is None or v == "":
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{x:+.1f}%"


def _fmt_flow(v: Any) -> str:
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 10000:
        return f"{n / 10000:.1f}萬"
    if abs(n) >= 1000:
        return f"{n:,.0f}"
    return f"{n:.0f}"


def _as_of_label(as_of: Optional[str]) -> str:
    raw = (as_of or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}（台北）"
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw[:10]}（台北）"
    now = datetime.now(_TAIPEI)
    return f"{now:%Y-%m-%d}（台北）"


def _mark_glyph(mark: str) -> Tuple[str, Tuple[int, int, int]]:
    m = str(mark or "").strip().lower()
    if m in ("star", "true", "★", "*"):
        return "★", STAR
    return "☆", WATCH


def _measure_h(n_rows: int) -> int:
    """邏輯高度；至少 BASE_H。"""
    pad_y = 40
    header_block = 48 + 12 + 26 + 16 + 26 + 16 + 40 + 12
    row_h = 96
    gap = 8
    body = n_rows * (row_h + gap) if n_rows else 220
    footer = 36
    need = pad_y + header_block + body + footer + pad_y
    return max(BASE_H, int(need))


def render_undervalue_png(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    title: str = "低估名單",
) -> str:
    """把已算好的低估／觀察列畫成話筒 PNG。回傳 save_path。"""
    rows = list(rows or [])
    H_logic = _measure_h(len(rows))
    W, H = _px(BASE_W), _px(H_logic)
    pad_x, pad_y = _px(44), _px(40)

    im = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(im)

    # 卡面
    card_box = (_px(18), _px(14), W - _px(18), H - _px(14))
    dr.rounded_rectangle(card_box, radius=_px(28), fill=CARD, outline=CARD_EDGE, width=max(1, _px(2)))

    title_f = _font(48, bold=True)
    date_f = _font(26)
    legend_f = _font(26, bold=True)
    col_f = _font(22, bold=True)
    cell_f = _font(30, bold=True)
    name_f = _font(28)
    reason_f = _font(24)
    empty_f = _font(36, bold=True)
    empty_sub_f = _font(26)

    content_l = pad_x
    content_r = W - pad_x
    y = pad_y

    # 標題列
    _text_left_mid(dr, (content_l, y, content_r, y + _px(52)), title, title_f, TEXT)
    date_s = _as_of_label(as_of)
    _text_right_mid(dr, (content_l, y + _px(8), content_r, y + _px(52)), date_s, date_f, MUTED)
    y += _px(56)

    # 圖例
    n_star = sum(1 for r in rows if _mark_glyph(r.get("mark"))[0] == "★")
    n_watch = len(rows) - n_star
    leg = f"★真低估 {n_star}　☆觀察 {n_watch}　　共 {len(rows)} 檔"
    _text_left_mid(dr, (content_l, y, content_r, y + _px(32)), leg, legend_f, HEAD)
    y += _px(40)

    # 欄寬（實像素）
    # 標記 代號 股名 | 收盤 PE 中位 距下緣 流動
    cols = {
        "mark": _px(52),
        "sid": _px(100),
        "name": _px(150),
        "close": _px(104),
        "pe": _px(72),
        "med": _px(88),
        "dist": _px(118),
        "flow": _px(120),
    }
    # 右緣對齊：從右往左堆數字欄
    x_flow_r = content_r
    x_dist_r = x_flow_r - cols["flow"]
    x_med_r = x_dist_r - cols["dist"]
    x_pe_r = x_med_r - cols["med"]
    x_close_r = x_pe_r - cols["pe"]
    x_mark = content_l
    x_sid = x_mark + cols["mark"]
    x_name = x_sid + cols["sid"]
    # 股名右緣不得撞收盤欄
    name_max = max(_px(40), x_close_r - cols["close"] - x_name - _px(8))

    # 表頭
    head_h = _px(40)
    headers = [
        ("★☆", x_mark, x_mark + cols["mark"], "c"),
        ("代號", x_sid, x_sid + cols["sid"], "l"),
        ("股名", x_name, x_name + name_max, "l"),
        ("收盤", x_close_r - cols["close"], x_close_r, "r"),
        ("PE", x_pe_r - cols["pe"], x_pe_r, "r"),
        ("中位", x_med_r - cols["med"], x_med_r, "r"),
        ("距下緣％", x_dist_r - cols["dist"], x_dist_r, "r"),
        ("流動張", x_flow_r - cols["flow"], x_flow_r, "r"),
    ]
    for lab, x0, x1, align in headers:
        box = (x0, y, x1, y + head_h)
        if align == "r":
            _text_right_mid(dr, box, lab, col_f, MUTED)
        elif align == "c":
            _text_center_mid(dr, box, lab, col_f, MUTED)
        else:
            _text_left_mid(dr, box, lab, col_f, MUTED)
    y += head_h
    dr.line([(content_l, y), (content_r, y)], fill=DIV, width=max(1, _px(1)))
    y += _px(10)

    row_h = _px(96)
    gap = _px(8)
    main_h = _px(52)
    reason_h = _px(44)

    if not rows:
        mid_y = y + (H - pad_y - y) // 2
        _text_center_mid(
            dr,
            (content_l, mid_y - _px(40), content_r, mid_y),
            "今日無低估／觀察名單",
            empty_f,
            TEXT,
        )
        _text_center_mid(
            dr,
            (content_l, mid_y + _px(8), content_r, mid_y + _px(48)),
            "有資料再顯示 ★真低估／☆觀察",
            empty_sub_f,
            MUTED,
        )
    else:
        for i, row in enumerate(rows):
            top = y
            bot = y + row_h
            bg = ROW_A if i % 2 == 0 else ROW_B
            dr.rounded_rectangle(
                (content_l - _px(6), top, content_r + _px(6), bot),
                radius=_px(10),
                fill=bg,
            )
            glyph, gfill = _mark_glyph(row.get("mark"))
            main_box_y0, main_box_y1 = top, top + main_h

            _text_center_mid(
                dr, (x_mark, main_box_y0, x_mark + cols["mark"], main_box_y1), glyph, cell_f, gfill
            )
            _text_left_mid(
                dr,
                (x_sid, main_box_y0, x_sid + cols["sid"], main_box_y1),
                str(row.get("stock_id") or "—"),
                cell_f,
                TEXT,
            )
            name = _truncate(name_f, str(row.get("name") or ""), name_max)
            _text_left_mid(dr, (x_name, main_box_y0, x_name + name_max, main_box_y1), name, name_f, TEXT)

            _text_right_mid(
                dr,
                (x_close_r - cols["close"], main_box_y0, x_close_r, main_box_y1),
                _fmt_num(row.get("close"), 1 if _needs_decimal(row.get("close")) else 0),
                cell_f,
                TEXT,
            )
            _text_right_mid(
                dr,
                (x_pe_r - cols["pe"], main_box_y0, x_pe_r, main_box_y1),
                _fmt_num(row.get("pe"), 1),
                cell_f,
                TEXT,
            )
            _text_right_mid(
                dr,
                (x_med_r - cols["med"], main_box_y0, x_med_r, main_box_y1),
                _fmt_num(row.get("peer_pe_median"), 1),
                cell_f,
                TEXT,
            )
            dist = row.get("dist_to_floor_pct")
            dist_s = _fmt_pct(dist)
            dist_fill = MUTED
            try:
                dv = float(dist)
                dist_fill = NEG if dv < 0 else (POS if dv > 0 else TEXT)
            except (TypeError, ValueError):
                pass
            _text_right_mid(
                dr,
                (x_dist_r - cols["dist"], main_box_y0, x_dist_r, main_box_y1),
                dist_s,
                cell_f,
                dist_fill,
            )
            _text_right_mid(
                dr,
                (x_flow_r - cols["flow"], main_box_y0, x_flow_r, main_box_y1),
                _fmt_flow(row.get("flow_shares")),
                cell_f,
                TEXT,
            )

            reason = str(row.get("reason") or "").strip() or "—"
            reason = _truncate(reason_f, reason, content_r - x_name)
            _text_left_mid(
                dr,
                (x_name, top + main_h, content_r, top + main_h + reason_h),
                reason,
                reason_f,
                MUTED,
            )
            y = bot + gap

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    im.save(save_path, format="PNG", optimize=True)
    return save_path


def _needs_decimal(v: Any) -> bool:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return abs(x - round(x)) > 1e-9


# --- 本機樣張（假資料僅示範排版；非產品買訊）---
_DEMO_ROWS: List[Dict[str, Any]] = [
    {
        "mark": "star",
        "stock_id": "2330",
        "name": "台積電",
        "close": 980,
        "pe": 22.4,
        "peer_pe_median": 28.1,
        "dist_to_floor_pct": -18.2,
        "flow_shares": 12345,
        "reason": "同鏈 PE 低於中位近兩成，量能仍在",
    },
    {
        "mark": "star",
        "stock_id": "2317",
        "name": "鴻海",
        "close": 168.5,
        "pe": 14.2,
        "peer_pe_median": 18.0,
        "dist_to_floor_pct": -12.5,
        "flow_shares": 8200,
        "reason": "距同鏈下緣仍有空間，流動張數夠",
    },
    {
        "mark": "watch",
        "stock_id": "2454",
        "name": "聯發科",
        "close": 1285,
        "pe": 19.8,
        "peer_pe_median": 21.0,
        "dist_to_floor_pct": -4.1,
        "flow_shares": 5600,
        "reason": "接近中位，先列觀察不當真低估",
    },
    {
        "mark": "watch",
        "stock_id": "2308",
        "name": "台達電",
        "close": 412,
        "pe": 26.5,
        "peer_pe_median": 24.0,
        "dist_to_floor_pct": 3.2,
        "flow_shares": 3100,
        "reason": "PE 略高於同鏈中位，僅觀察",
    },
    {
        "mark": "star",
        "stock_id": "2383",
        "name": "台光電",
        "close": 529.5,
        "pe": 16.8,
        "peer_pe_median": 22.5,
        "dist_to_floor_pct": -21.0,
        "flow_shares": 4500,
        "reason": "同鏈低估幅度深，流動尚可",
    },
]


def main() -> None:
    out_dir = "/opt/cursor/artifacts"
    as_of = "2026-11-14"
    p1 = render_undervalue_png(
        _DEMO_ROWS,
        os.path.join(out_dir, "undervalue_list_demo_filled.png"),
        as_of=as_of,
    )
    p2 = render_undervalue_png(
        [],
        os.path.join(out_dir, "undervalue_list_demo_empty.png"),
        as_of=as_of,
    )
    print(p1)
    print(p2)
    # 順便存一份縮圖可讀性檢查（寬 540）
    for src, name in (
        (p1, "undervalue_list_demo_filled_thumb540.png"),
        (p2, "undervalue_list_demo_empty_thumb540.png"),
    ):
        im = Image.open(src)
        w = 540
        h = int(round(im.height * (w / im.width)))
        im.resize((w, h), Image.Resampling.LANCZOS).save(os.path.join(out_dir, name))


if __name__ == "__main__":
    main()
