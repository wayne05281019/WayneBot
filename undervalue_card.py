# -*- coding: utf-8 -*-
"""低估名單最終結果 PNG（話筒出圖）。只排版，不重算選股／買訊。
規格：最終結果顯示的排版（4:5），對齊 industry_card 深底語彙。
"""
from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

# 版面（邏輯 px）
PAD_X = 44
PAD_Y = 40
TITLE_H = 56
LEGEND_H = 40
HEAD_H = 40
HEAD_AFTER = 10
MAIN_H = 52
REASON_LINE_H = 44
ROW_GAP = 8
FOOT_H = 44
# 數字欄之間至少留這麼寬，避免「980 22.4 28.1」糊成一串
COL_GAP = 26
REASON_MAX_LINES = 3
# 數字欄最小寬（邏輯 px）；內容更寬時自動撐開
COL_MIN = {"close": 104, "pe": 72, "med": 88, "dist": 118, "flow": 120}
EST_MARK = "推"
EST_FOOTNOTE = "推＝推估值，不是官方已公告數"


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


def _fit_name(
    fonts: Sequence[ImageFont.ImageFont], text: str, max_w: float
) -> Tuple[str, ImageFont.ImageFont]:
    """股名先降字級塞進欄寬，真的塞不下才截；不准一開始就把股名切掉。"""
    s = str(text or "").strip() or "—"
    for f in fonts:
        if f.getlength(s) <= max_w:
            return s, f
    return _truncate(fonts[-1], s, max_w), fonts[-1]


# 數字／英文詞整塊不拆（12,345、31.2%、PE、IET-KY）；其餘逐字
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9,.\-+%]*|\s+|.", re.S)
_BREAK_AFTER = set("，、；。：！？）」』,;:!? ")
_NO_LINE_START = set("，、；。：！？）」』%,.;:!?")


def _wrap_reason(
    font: ImageFont.ImageFont, text: str, max_w: float, max_lines: int = REASON_MAX_LINES
) -> List[str]:
    """理由能一行就一行；排不下才在標點處換行，數字與英文詞不切斷。"""
    s = " ".join(str(text or "").split())
    if not s:
        return ["—"]
    if font.getlength(s) <= max_w:
        return [s]
    tokens = _TOKEN_RE.findall(s)
    lines: List[str] = []
    cur: List[str] = []
    for tok in tokens:
        if not cur and tok.isspace():
            continue
        if not cur or font.getlength("".join(cur) + tok) <= max_w:
            cur.append(tok)
            continue
        if tok in _NO_LINE_START and len(cur) > 1:
            # 行首禁則：標點不准開新行，連前一塊一起帶下去
            carry = cur.pop()
            lines.append("".join(cur).rstrip())
            cur = [carry, tok]
            continue
        cut = len(cur)
        for i in range(len(cur) - 1, 0, -1):
            if cur[i] in _BREAK_AFTER:
                cut = i + 1
                break
        if font.getlength("".join(cur[:cut])) < max_w * 0.55:
            cut = len(cur)
        lines.append("".join(cur[:cut]).rstrip())
        cur = cur[cut:] + [tok]
        while cur and cur[0].isspace():
            cur.pop(0)
    if cur:
        lines.append("".join(cur).rstrip())
    # 末行只剩一個字：往上一行借一塊（遇標點多借），不留孤字
    if len(lines) >= 2 and len(lines[-1]) <= 1:
        prev = _TOKEN_RE.findall(lines[-2])
        take = 1
        while take < len(prev) and prev[-take] in _NO_LINE_START:
            take += 1
        if take < len(prev):
            lines[-1] = "".join(prev[-take:]).lstrip() + lines[-1]
            lines[-2] = "".join(prev[:-take]).rstrip()
    if len(lines) > max_lines:
        keep = lines[: max_lines - 1]
        last_tokens = _TOKEN_RE.findall(lines[max_lines - 1])
        ell = "…"
        while last_tokens and font.getlength("".join(last_tokens) + ell) > max_w:
            last_tokens.pop()
        keep.append("".join(last_tokens).rstrip() + ell)
        lines = keep
    return lines


def _finite(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _fmt_num(v: Any, digits: int = 1) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    if digits == 0:
        return f"{x:.0f}"
    return f"{x:.{digits}f}"


def _fmt_close(v: Any) -> str:
    """官方收盤照原檔位顯示（21.35 不准印成 21.4）；整數不補 .0。"""
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _fmt_pct(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:+.1f}%"


def _fmt_flow(v: Any) -> str:
    """流動張一律整數千分位，上下行尾數對齊（不混「1.2萬」與「8,200」）。"""
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:,.0f}"


def _as_of_label(as_of: Optional[str]) -> str:
    """只認呼叫端給的資料日；沒給就不印日期，不拿現在時間冒充資料日。"""
    raw = (as_of or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}（台北）"
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw[:10]}（台北）"
    return ""


def _is_star(mark: Any) -> bool:
    return str(mark or "").strip().lower() in ("star", "true", "★", "*")


def _mark_glyph(mark: str) -> Tuple[str, Tuple[int, int, int]]:
    if _is_star(mark):
        return "★", STAR
    return "☆", WATCH


def _order_rows(rows: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """★ 在前、☆ 在後；組內維持呼叫端順序（圖例 ★3 ☆2 一眼對得上）。"""
    return sorted(list(rows or []), key=lambda r: 0 if _is_star(r.get("mark")) else 1)


def _cells(row: Dict[str, Any]) -> Dict[str, str]:
    pe_s = _fmt_num(row.get("pe"), 1)
    if row.get("pe_est") and pe_s != "—":
        pe_s = f"{EST_MARK} {pe_s}"
    return {
        "close": _fmt_close(row.get("close")),
        "pe": pe_s,
        "med": _fmt_num(row.get("peer_pe_median"), 1),
        "dist": _fmt_pct(row.get("dist_to_floor_pct")),
        "flow": _fmt_flow(row.get("flow_shares")),
    }


def _column_widths(
    cells: Sequence[Dict[str, str]],
    headers_txt: Dict[str, str],
    col_f: ImageFont.ImageFont,
    cell_f: ImageFont.ImageFont,
) -> Dict[str, int]:
    """數字欄寬＝max(最小寬, 表頭／最寬內容＋欄距)；右對齊時相鄰欄字不會互壓。"""
    cols: Dict[str, int] = {}
    for key, min_w in COL_MIN.items():
        need = col_f.getlength(headers_txt[key])
        for c in cells:
            need = max(need, cell_f.getlength(c[key]))
        cols[key] = max(_px(min_w), int(math.ceil(need)) + _px(COL_GAP))
    return cols


def render_undervalue_png(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    title: str = "低估名單",
    pe_label: str = "PE",
    empty_note: Optional[str] = None,
) -> str:
    """把已算好的低估／觀察列畫成話筒 PNG。回傳 save_path。

    列內 pe_est 為真＝PE 用推估 EPS，數字前標「推」並在卡底註明（推估必標）。
    ★ 列排在 ☆ 前，組內維持呼叫端順序。
    empty_note：空名單副句，呼叫端分清「盤後還沒算完」與「已算完 0 檔」。
    """
    rows = _order_rows(rows)
    W = _px(BASE_W)
    pad_x, pad_y = _px(PAD_X), _px(PAD_Y)
    content_l = pad_x
    content_r = W - pad_x

    title_f = _font(48, bold=True)
    date_f = _font(26)
    legend_f = _font(26, bold=True)
    col_f = _font(22, bold=True)
    cell_f = _font(30, bold=True)
    name_fonts = [_font(28), _font(24), _font(22)]
    reason_f = _font(24)
    empty_f = _font(36, bold=True)
    empty_sub_f = _font(26)
    foot_f = _font(22)

    cells = [_cells(r) for r in rows]
    headers_txt = {"close": "收盤", "pe": pe_label, "med": "中位", "dist": "距下緣％", "flow": "流動張"}
    cols = _column_widths(cells, headers_txt, col_f, cell_f)
    x_flow_r = content_r
    x_dist_r = x_flow_r - cols["flow"]
    x_med_r = x_dist_r - cols["dist"]
    x_pe_r = x_med_r - cols["med"]
    x_close_r = x_pe_r - cols["pe"]
    x_mark = content_l
    x_sid = x_mark + _px(52)
    x_name = x_sid + _px(100)
    name_max = max(_px(40), x_close_r - cols["close"] - x_name - _px(8))
    reason_max = content_r - x_name

    reasons = [_wrap_reason(reason_f, str(r.get("reason") or ""), reason_max) for r in rows]
    row_hs = [_px(MAIN_H) + _px(REASON_LINE_H) * len(lines) for lines in reasons]
    has_est = any(r.get("pe_est") and _finite(r.get("pe")) is not None for r in rows)

    top_block = pad_y + _px(TITLE_H + LEGEND_H + HEAD_H + HEAD_AFTER)
    body_h = sum(h + _px(ROW_GAP) for h in row_hs) if rows else _px(220)
    foot_h = _px(FOOT_H) if has_est else 0
    H = max(_px(BASE_H), top_block + body_h + foot_h + pad_y + _px(14))

    im = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(im)
    card_box = (_px(18), _px(14), W - _px(18), H - _px(14))
    dr.rounded_rectangle(card_box, radius=_px(28), fill=CARD, outline=CARD_EDGE, width=max(1, _px(2)))

    y = pad_y
    _text_left_mid(dr, (content_l, y, content_r, y + _px(52)), title, title_f, TEXT)
    date_s = _as_of_label(as_of)
    if date_s:
        _text_right_mid(dr, (content_l, y + _px(8), content_r, y + _px(52)), date_s, date_f, MUTED)
    y += _px(TITLE_H)

    n_star = sum(1 for r in rows if _is_star(r.get("mark")))
    n_watch = len(rows) - n_star
    leg = f"★真低估 {n_star}　☆觀察 {n_watch}　　共 {len(rows)} 檔"
    _text_left_mid(dr, (content_l, y, content_r, y + _px(32)), leg, legend_f, HEAD)
    y += _px(LEGEND_H)

    head_h = _px(HEAD_H)
    headers = [
        ("★☆", x_mark, x_mark + _px(52), "c"),
        ("代號", x_sid, x_sid + _px(100), "l"),
        ("股名", x_name, x_name + name_max, "l"),
        (headers_txt["close"], x_close_r - cols["close"], x_close_r, "r"),
        (headers_txt["pe"], x_pe_r - cols["pe"], x_pe_r, "r"),
        (headers_txt["med"], x_med_r - cols["med"], x_med_r, "r"),
        (headers_txt["dist"], x_dist_r - cols["dist"], x_dist_r, "r"),
        (headers_txt["flow"], x_flow_r - cols["flow"], x_flow_r, "r"),
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
    y += _px(HEAD_AFTER)

    main_h = _px(MAIN_H)
    line_h = _px(REASON_LINE_H)

    if not rows:
        mid_y = y + (H - pad_y - y) // 2
        _text_center_mid(
            dr,
            (content_l, mid_y - _px(40), content_r, mid_y),
            "無低估／觀察名單",
            empty_f,
            TEXT,
        )
        _text_center_mid(
            dr,
            (content_l, mid_y + _px(8), content_r, mid_y + _px(48)),
            str(empty_note or "有資料再顯示 ★真低估／☆觀察"),
            empty_sub_f,
            MUTED,
        )
    else:
        for i, row in enumerate(rows):
            top = y
            bot = y + row_hs[i]
            bg = ROW_A if i % 2 == 0 else ROW_B
            dr.rounded_rectangle(
                (content_l - _px(6), top, content_r + _px(6), bot),
                radius=_px(10),
                fill=bg,
            )
            glyph, gfill = _mark_glyph(row.get("mark"))
            m0, m1 = top, top + main_h
            c = cells[i]

            _text_center_mid(dr, (x_mark, m0, x_mark + _px(52), m1), glyph, cell_f, gfill)
            _text_left_mid(
                dr,
                (x_sid, m0, x_sid + _px(100), m1),
                str(row.get("stock_id") or "—"),
                cell_f,
                TEXT,
            )
            name, name_f = _fit_name(name_fonts, str(row.get("name") or ""), name_max)
            _text_left_mid(dr, (x_name, m0, x_name + name_max, m1), name, name_f, TEXT)
            _text_right_mid(dr, (x_close_r - cols["close"], m0, x_close_r, m1), c["close"], cell_f, TEXT)
            _text_right_mid(dr, (x_pe_r - cols["pe"], m0, x_pe_r, m1), c["pe"], cell_f, TEXT)
            _text_right_mid(dr, (x_med_r - cols["med"], m0, x_med_r, m1), c["med"], cell_f, TEXT)
            dv = _finite(row.get("dist_to_floor_pct"))
            dist_fill = MUTED if dv is None else (NEG if dv < 0 else (POS if dv > 0 else TEXT))
            _text_right_mid(dr, (x_dist_r - cols["dist"], m0, x_dist_r, m1), c["dist"], cell_f, dist_fill)
            _text_right_mid(dr, (x_flow_r - cols["flow"], m0, x_flow_r, m1), c["flow"], cell_f, TEXT)

            ry = top + main_h
            for line in reasons[i]:
                _text_left_mid(dr, (x_name, ry, content_r, ry + line_h), line, reason_f, MUTED)
                ry += line_h
            y = bot + _px(ROW_GAP)

    if has_est:
        fy = H - _px(14) - pad_y - _px(FOOT_H) + _px(12)
        _text_left_mid(dr, (content_l, fy, content_r, fy + _px(FOOT_H)), EST_FOOTNOTE, foot_f, MUTED)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    im.save(save_path, format="PNG", optimize=True)
    return save_path


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
    # 示範列是假數字：只准標「排版示意」、不帶資料日，不准當名單送話筒
    p1 = render_undervalue_png(
        _DEMO_ROWS,
        os.path.join(out_dir, "undervalue_list_demo_filled.png"),
        title="排版示意（非名單）",
    )
    p2 = render_undervalue_png(
        [],
        os.path.join(out_dir, "undervalue_list_demo_empty.png"),
        title="排版示意（非名單）",
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
