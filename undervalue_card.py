# -*- coding: utf-8 -*-
"""低估名單最終結果 PNG（話筒出圖）。只排版，不重算選股／買訊。

真成長低估＝三段卡片：★現在可買／☆等止穩／⚠️興櫃量小。
估值≠買訊；切入仍只認高低卡黃金買點。
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

BG = (15, 23, 42)  # #0F172A
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
GREEN = (52, 211, 153)
GREEN_EDGE = (16, 185, 129)
AMBER = (251, 191, 36)
AMBER_EDGE = (245, 158, 11)
PURPLE = (196, 181, 253)
PURPLE_EDGE = (167, 139, 250)
PILL_BG = (30, 41, 59)

# 版面（邏輯 px）— 舊列表測試仍用
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
COL_GAP = 26
REASON_MAX_LINES = 3
COL_MIN = {"close": 104, "pe": 72, "med": 88, "dist": 118, "flow": 120}
EST_MARK = "推"
EST_FOOTNOTE = "推＝推估值，不是官方已公告數｜估值≠買訊"


def _px(n: float) -> int:
    return int(round(n * SCALE))


def _font(size_logic: float, *, bold: bool = False) -> ImageFont.FreeTypeFont:
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
    s = str(text or "").strip() or "—"
    for f in fonts:
        if f.getlength(s) <= max_w:
            return s, f
    return _truncate(fonts[-1], s, max_w), fonts[-1]


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9,.\-+%]*|\s+|.", re.S)
_BREAK_AFTER = set("，、；。：！？）」』,;:!? ")
_NO_LINE_START = set("，、；。：！？）」』%,.;:!?")


def _wrap_reason(
    font: ImageFont.ImageFont, text: str, max_w: float, max_lines: int = REASON_MAX_LINES
) -> List[str]:
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


def _as_of_close_label(as_of: Optional[str]) -> str:
    raw = (as_of or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]} 收盤基準"
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw[:10]} 收盤基準"
    return ""


def _is_star(mark: Any) -> bool:
    return str(mark or "").strip().lower() in ("star", "true", "★", "*")


def _is_emerging(mark: Any) -> bool:
    return str(mark or "").strip().lower() in ("emerging", "emerge", "⚠️", "warn")


def _mark_glyph(mark: str) -> Tuple[str, Tuple[int, int, int]]:
    if _is_star(mark):
        return "★", GREEN
    if _is_emerging(mark):
        return "⚠️", PURPLE
    return "☆", AMBER


def _order_rows(rows: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    def key(r: Dict[str, Any]) -> int:
        m = str(r.get("mark") or "").lower()
        if m in ("star", "true", "★", "*"):
            return 0
        if m in ("emerging", "emerge", "⚠️", "warn"):
            return 2
        return 1

    return sorted(list(rows or []), key=key)


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
    cols: Dict[str, int] = {}
    for key, min_w in COL_MIN.items():
        need = col_f.getlength(headers_txt[key])
        for c in cells:
            need = max(need, cell_f.getlength(c[key]))
        cols[key] = max(_px(min_w), int(math.ceil(need)) + _px(COL_GAP))
    return cols


def _has_growth_fields(rows: Sequence[Dict[str, Any]]) -> bool:
    return any(_finite(r.get("fair_year")) is not None for r in rows)


def _zone_split(
    rows: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    stars, watches, emerg = [], [], []
    for r in rows:
        if _is_star(r.get("mark")):
            stars.append(r)
        elif _is_emerging(r.get("mark")):
            emerg.append(r)
        else:
            watches.append(r)
    return stars, watches, emerg


def _draw_progress(
    dr: ImageDraw.ImageDraw,
    x0: float,
    x1: float,
    y: float,
    close: float,
    fair: float,
    tgt: float,
    font: ImageFont.ImageFont,
) -> float:
    """雙軌目標價進度條；回傳佔用高度。"""
    h = _px(36)
    track_y = y + _px(8)
    track_h = _px(10)
    vals = [v for v in (close, fair, tgt) if _finite(v) and float(v) > 0]
    if len(vals) < 2:
        return h
    lo = min(vals) * 0.92
    hi = max(vals) * 1.05
    span = max(hi - lo, 1e-9)

    def xp(v: float) -> float:
        return x0 + (float(v) - lo) / span * (x1 - x0)

    dr.rounded_rectangle(
        (x0, track_y, x1, track_y + track_h),
        radius=_px(4),
        fill=(51, 65, 85),
    )
    # 現價→今年→明年
    cx, fx, tx = xp(close), xp(fair), xp(tgt)
    dr.line([(cx, track_y + track_h / 2), (fx, track_y + track_h / 2)], fill=POS, width=_px(3))
    dr.line([(fx, track_y + track_h / 2), (tx, track_y + track_h / 2)], fill=HEAD, width=_px(3))
    for px, col in ((cx, TEXT), (fx, POS), (tx, HEAD)):
        r = _px(5)
        dr.ellipse((px - r, track_y + track_h / 2 - r, px + r, track_y + track_h / 2 + r), fill=col)
    return h


def _render_growth_png(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    title: str = "真成長低估掃描｜今明兩年目標價與買點導航",
    empty_note: Optional[str] = None,
) -> str:
    rows = _order_rows(rows)
    stars, watches, emerg = _zone_split(rows)
    W = _px(BASE_W)
    pad_x, pad_y = _px(PAD_X), _px(PAD_Y)
    content_l = pad_x
    content_r = W - pad_x

    title_f = _font(36, bold=True)
    sub_f = _font(22)
    zone_f = _font(28, bold=True)
    line1_f = _font(26, bold=True)
    line2_f = _font(22)
    line3_f = _font(20)
    empty_f = _font(36, bold=True)
    empty_sub_f = _font(26)
    foot_f = _font(20)

    card_h = _px(168)
    zone_gap = _px(18)
    card_gap = _px(12)
    zone_head = _px(44)

    n_cards = len(stars) + len(watches) + len(emerg)
    n_zones = sum(1 for z in (stars, watches, emerg) if z) or (0 if rows else 1)
    top_h = pad_y + _px(88)
    body_h = 0
    for z in (stars, watches, emerg):
        if not z:
            continue
        body_h += zone_head + len(z) * (card_h + card_gap) + zone_gap
    if not rows:
        body_h = _px(220)
    H = max(_px(BASE_H), int(top_h + body_h + _px(FOOT_H) + pad_y))

    im = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(im)

    y = pad_y
    _text_left_mid(dr, (content_l, y, content_r, y + _px(40)), title, title_f, TEXT)
    y += _px(42)
    date_s = _as_of_close_label(as_of)
    sub = "已自動剔除：景氣循環 / 營建入帳 / 業外灌水 / 毛利<20%"
    if date_s:
        sub = f"{date_s}｜{sub}"
    _text_left_mid(dr, (content_l, y, content_r, y + _px(28)), sub, sub_f, MUTED)
    y += _px(36)

    def _section(
        label: str,
        zone_rows: List[Dict[str, Any]],
        edge: Tuple[int, int, int],
        dashed: bool = False,
    ) -> None:
        nonlocal y
        if not zone_rows:
            return
        _text_left_mid(dr, (content_l, y, content_r, y + _px(34)), label, zone_f, edge)
        y += zone_head
        for row in zone_rows:
            top = y
            bot = y + card_h
            box = (content_l - _px(4), top, content_r + _px(4), bot)
            dr.rounded_rectangle(box, radius=_px(14), fill=CARD, outline=edge, width=_px(3))
            if dashed:
                # 虛線感：再畫一層淡邊
                dr.rounded_rectangle(
                    (box[0] + _px(4), box[1] + _px(4), box[2] - _px(4), box[3] - _px(4)),
                    radius=_px(12),
                    outline=PURPLE,
                    width=_px(1),
                )
            glyph, gfill = _mark_glyph(row.get("mark"))
            sid = str(row.get("stock_id") or "—")
            name = str(row.get("name") or "")
            ind = str(row.get("industry") or "")
            close_s = _fmt_close(row.get("close"))
            gm = _fmt_num(row.get("gross_margin"), 1)
            core = _fmt_num(row.get("core_ratio_pct"), 0)
            yoy = _fmt_pct(row.get("yoy_pct"))
            pe_s = _fmt_num(row.get("pe"), 1)
            fair = _finite(row.get("fair_year"))
            tgt = _finite(row.get("target_next"))
            ups_f = _fmt_pct(row.get("ups_fair_pct"))
            ups_t = _fmt_pct(row.get("ups_tgt_pct"))
            thr = _fmt_num(row.get("rev_threshold_yi"), 1)
            oct_r = _fmt_num(row.get("rev_oct_yi"), 1)
            tech = str(row.get("tech_status") or row.get("reason") or "—")
            chip = str(row.get("chip_note") or "")

            # 行1
            head = f"{glyph} {sid} {name}"
            if ind:
                head = f"{head}（{ind}）"
            head = _truncate(line1_f, head, content_r - content_l - _px(200))
            _text_left_mid(
                dr, (content_l + _px(16), top + _px(10), content_r - _px(16), top + _px(42)),
                head, line1_f, gfill,
            )
            _text_right_mid(
                dr, (content_l + _px(16), top + _px(10), content_r - _px(16), top + _px(42)),
                f"收盤 {close_s}", line1_f, TEXT,
            )
            metrics = f"Q3毛利 {gm}%｜本業比 {core}%｜營收YoY {yoy}"
            _text_left_mid(
                dr, (content_l + _px(16), top + _px(44), content_r - _px(16), top + _px(70)),
                _truncate(line2_f, metrics, content_r - content_l - _px(32)), line2_f, MUTED,
            )
            # 行2 進度
            bar_top = top + _px(74)
            if fair is not None and tgt is not None and _finite(row.get("close")):
                _draw_progress(
                    dr,
                    content_l + _px(16),
                    content_r - _px(16),
                    bar_top,
                    float(row["close"]),
                    float(fair),
                    float(tgt),
                    line2_f,
                )
                track = (
                    f"現價 {close_s} ({pe_s}x) → 今年合理 {_fmt_num(fair, 0)} ({ups_f})"
                    f" → 明年目標 {_fmt_num(tgt, 0)} ({ups_t})"
                )
            else:
                track = (
                    f"現價 {close_s} PE {pe_s}｜中位 {_fmt_num(row.get('peer_pe_median'), 1)}"
                    f"｜距下緣 {_fmt_pct(row.get('dist_to_floor_pct'))}"
                )
            _text_left_mid(
                dr, (content_l + _px(16), bar_top + _px(28), content_r - _px(16), bar_top + _px(52)),
                _truncate(line2_f, track, content_r - content_l - _px(32)), line2_f, TEXT,
            )
            # 行3 pill
            pill = f"明年達標月均營收門檻：{thr}億/月（目前：{oct_r}億）｜{tech}"
            if chip:
                pill = f"{pill}｜{chip}"
            pill_box = (
                content_l + _px(16),
                bot - _px(44),
                content_r - _px(16),
                bot - _px(12),
            )
            dr.rounded_rectangle(pill_box, radius=_px(10), fill=PILL_BG)
            _text_left_mid(
                dr, pill_box, _truncate(line3_f, pill, content_r - content_l - _px(48)),
                line3_f, MUTED if not _is_star(row.get("mark")) else NEG,
            )
            y = bot + card_gap

    if not rows:
        mid_y = y + (H - pad_y - y) // 2
        _text_center_mid(
            dr, (content_l, mid_y - _px(40), content_r, mid_y),
            "無真成長低估名單", empty_f, TEXT,
        )
        _text_center_mid(
            dr, (content_l, mid_y + _px(8), content_r, mid_y + _px(48)),
            str(empty_note or "已剔除假低估陷阱；有資料再顯示"), empty_sub_f, MUTED,
        )
    else:
        _section("★ 現在可買（基本面低估＋站穩大量區撐）", stars, GREEN_EDGE)
        _section("☆ 真低估但等止穩（先看表）", watches, AMBER_EDGE)
        _section("⚠️ 高波動興櫃／量小觀察池", emerg, PURPLE_EDGE, dashed=True)

    fy = H - pad_y - _px(28)
    _text_left_mid(
        dr, (content_l, fy, content_r, fy + _px(28)),
        "估值≠買訊｜進場只認高低卡黃金買點", foot_f, MUTED,
    )

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    im.save(save_path, format="PNG", optimize=True)
    return save_path


def render_undervalue_png(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    title: str = "真成長低估掃描｜今明兩年目標價與買點導航",
    pe_label: str = "PE",
    empty_note: Optional[str] = None,
) -> str:
    """把已算好的低估列畫成話筒 PNG。回傳 save_path。

    有今明目標價欄→三段成長卡；否則仍走相容列表（測試／舊快取）。
    """
    _ = pe_label
    rows_l = list(rows or [])
    if not rows_l or _has_growth_fields(rows_l):
        return _render_growth_png(
            rows_l, save_path, as_of=as_of, title=title, empty_note=empty_note
        )
    # --- 舊列表相容（無 fair_year 的單元測試／舊庫）---
    rows_l = _order_rows(rows_l)
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

    cells = [_cells(r) for r in rows_l]
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

    reasons = [_wrap_reason(reason_f, str(r.get("reason") or ""), reason_max) for r in rows_l]
    row_hs = [_px(MAIN_H) + _px(REASON_LINE_H) * len(lines) for lines in reasons]
    has_est = any(r.get("pe_est") and _finite(r.get("pe")) is not None for r in rows_l)

    top_block = pad_y + _px(TITLE_H + LEGEND_H + HEAD_H + HEAD_AFTER)
    body_h = sum(h + _px(ROW_GAP) for h in row_hs) if rows_l else _px(220)
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

    n_star = sum(1 for r in rows_l if _is_star(r.get("mark")))
    n_watch = len(rows_l) - n_star
    leg = f"★真低估 {n_star}　☆觀察 {n_watch}　　共 {len(rows_l)} 檔"
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

    if not rows_l:
        mid_y = y + (H - pad_y - y) // 2
        _text_center_mid(
            dr, (content_l, mid_y - _px(40), content_r, mid_y),
            "無低估／觀察名單", empty_f, TEXT,
        )
        _text_center_mid(
            dr, (content_l, mid_y + _px(8), content_r, mid_y + _px(48)),
            str(empty_note or "有資料再顯示 ★真低估／☆觀察"), empty_sub_f, MUTED,
        )
    else:
        for i, row in enumerate(rows_l):
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
                dr, (x_sid, m0, x_sid + _px(100), m1),
                str(row.get("stock_id") or "—"), cell_f, TEXT,
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


_DEMO_ROWS: List[Dict[str, Any]] = [
    {
        "mark": "star",
        "stock_id": "6442",
        "name": "光聖",
        "industry": "光通訊/CPO",
        "close": 1045,
        "pe": 20.0,
        "gross_margin": 59.3,
        "core_ratio_pct": 94,
        "yoy_pct": 83,
        "fair_year": 1300,
        "target_next": 1625,
        "ups_fair_pct": 24,
        "ups_tgt_pct": 55,
        "rev_threshold_yi": 20.5,
        "rev_oct_yi": 18.2,
        "tech_status": "站回支撐區",
        "chip_note": "投信近5日買超",
        "peer_pe_median": 26,
        "dist_to_floor_pct": -23,
        "flow_shares": 5000,
        "reason": "示意",
    },
    {
        "mark": "star",
        "stock_id": "7711",
        "name": "永擎",
        "industry": "AI伺服器",
        "close": 481.5,
        "pe": 13.4,
        "gross_margin": 21.1,
        "core_ratio_pct": 88,
        "yoy_pct": 57,
        "fair_year": 620,
        "target_next": 780,
        "ups_fair_pct": 29,
        "ups_tgt_pct": 62,
        "rev_threshold_yi": 28.0,
        "rev_oct_yi": 22.0,
        "tech_status": "投信連買",
        "chip_note": "投信近5日買超",
        "peer_pe_median": 16,
        "dist_to_floor_pct": -16,
        "flow_shares": 4200,
        "reason": "示意",
    },
    {
        "mark": "watch",
        "stock_id": "2383",
        "name": "台光電",
        "industry": "高階CCL",
        "close": 3795,
        "pe": 18.0,
        "gross_margin": 37.7,
        "core_ratio_pct": 92,
        "yoy_pct": 203,
        "fair_year": 4800,
        "target_next": 6120,
        "ups_fair_pct": 26,
        "ups_tgt_pct": 61,
        "rev_threshold_yi": 95.0,
        "rev_oct_yi": 80.0,
        "tech_status": "跌破大量區撐 4160，先看表等止穩",
        "chip_note": "外資近5日賣超",
        "peer_pe_median": 26,
        "dist_to_floor_pct": -30,
        "flow_shares": 8000,
        "reason": "示意",
    },
    {
        "mark": "emerging",
        "stock_id": "3595",
        "name": "山太士",
        "industry": "興櫃",
        "close": 580,
        "pe": 25.0,
        "gross_margin": 77.4,
        "core_ratio_pct": 90,
        "yoy_pct": 40,
        "fair_year": 700,
        "target_next": 900,
        "ups_fair_pct": 20,
        "ups_tgt_pct": 55,
        "rev_threshold_yi": 1.5,
        "rev_oct_yi": 1.2,
        "tech_status": "60日均量過小",
        "chip_note": "",
        "peer_pe_median": 28,
        "dist_to_floor_pct": -10,
        "flow_shares": 200,
        "reason": "示意",
    },
]


def main() -> None:
    out_dir = "/opt/cursor/artifacts"
    p1 = render_undervalue_png(
        _DEMO_ROWS,
        os.path.join(out_dir, "undervalue_growth_demo.png"),
        as_of="20261116",
        title="真成長低估掃描｜今明兩年目標價與買點導航",
    )
    p2 = render_undervalue_png(
        [],
        os.path.join(out_dir, "undervalue_growth_demo_empty.png"),
        as_of="20261116",
    )
    print(p1)
    print(p2)
    for src, name in (
        (p1, "undervalue_growth_demo_thumb540.png"),
        (p2, "undervalue_growth_demo_empty_thumb540.png"),
    ):
        im = Image.open(src)
        w = 540
        h = int(round(im.height * (w / im.width)))
        im.resize((w, h), Image.Resampling.LANCZOS).save(os.path.join(out_dir, name))


if __name__ == "__main__":
    main()
