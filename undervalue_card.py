# -*- coding: utf-8 -*-
"""低估名單 D3 PNG（話筒出圖）。只排版，不重算選股／買訊。

畫布固定 1080×1920（9:16）；頂安全 140／底安全 180；每頁最多 4 卡。
排序 ★可買 → ☆等止穩 → ⚠️量小／興櫃。估值≠買訊。
"""
from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

# --- 畫布（Telegram 面向 1080×1920）---
BASE_W = 1080
BASE_H = 1920
SCALE = 1
SAFE_TOP = 140
SAFE_BOTTOM = 180
CARDS_PER_PAGE = 4

BG = (11, 17, 32)  # #0B1120
CARD = (17, 24, 39)  # #111827
GRID = (51, 65, 85)  # #334155
TEXT = (236, 242, 248)
HEAD = (132, 208, 255)
MUTED = (154, 163, 173)  # #9AA3AD 次要字（美編）
ROW_A = (28, 42, 58)
ROW_B = (22, 34, 48)
NEG = (120, 220, 168)
POS = (255, 160, 140)
DIV = (42, 50, 60)  # 十字線淡（美編 #2A323C 系）
GREEN = (61, 220, 151)  # #3DDC97
GREEN_EDGE = (16, 185, 129)
AMBER = (251, 191, 36)
AMBER_EDGE = (245, 158, 11)
PURPLE = (196, 181, 253)
PURPLE_EDGE = (167, 139, 250)
PILL_BG = (30, 41, 59)
CYAN = (56, 189, 248)  # 撐／目標條
ORANGE = (251, 146, 60)
RED_CHIP = (240, 113, 120)  # #F07178 壓
GRID_LINE = (42, 50, 60)
SUPPORT_COL = (61, 220, 151)
RESIST_COL = (240, 113, 120)

# 版面（邏輯 px）— 舊列表測試仍用
PAD_X = 36
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
    # 小 EPS（如 5.99）保留兩位，不准四捨成 6.0 對不上範本
    if digits == 1 and 0 < abs(x) < 10 and abs(x * 100 - round(x * 100)) < 1e-6:
        if abs(x * 100 - round(x * 10) * 10) > 1e-6:
            return f"{x:.2f}".rstrip("0").rstrip(".")
    return f"{x:.{digits}f}"


def _fmt_eps(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    if abs(x) >= 100:
        return f"{x:.0f}"
    if abs(x) >= 10:
        return f"{x:.1f}".rstrip("0").rstrip(".") if abs(x - round(x)) > 1e-6 else f"{x:.0f}"
    # <10：最多兩位
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _fmt_close(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _fmt_price(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    # 範本 481.5 元：有小數就留一位，不准四捨成 482
    has_dec = abs(x - round(x)) > 1e-6
    if abs(x) >= 1000:
        return f"{x:,.1f}".rstrip("0").rstrip(".") if has_dec else f"{x:,.0f}"
    if has_dec:
        return f"{x:.1f}"
    if abs(x) >= 100:
        return f"{x:.0f}"
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _fmt_pct(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:+.0f}%" if abs(x) >= 10 else f"{x:+.1f}%"


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
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]} 收盤"
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw[:10]} 收盤"
    return ""


def _is_star(mark: Any) -> bool:
    return str(mark or "").strip().lower() in ("star", "true", "★", "*")


def _is_emerging(mark: Any) -> bool:
    return str(mark or "").strip().lower() in ("emerging", "emerge", "⚠️", "warn")


def _mark_glyph(mark: str) -> Tuple[str, Tuple[int, int, int], Tuple[int, int, int], str]:
    """回傳 (glyph, 字色, 邊框色, 標籤)。標籤不含 glyph；表頭用『★ 可買』空一格。"""
    if _is_star(mark):
        return "★", GREEN, GREEN_EDGE, "可買"
    if _is_emerging(mark):
        return "⚠", PURPLE, PURPLE_EDGE, "量小"
    return "☆", AMBER, AMBER_EDGE, "等止穩"


def _split_chip_pills(chip: str) -> List[str]:
    """籌碼膠囊。範本『投信連買・外資調節』＝一顆橘膠囊，不准拆兩顆。"""
    s = str(chip or "").strip()
    if not s:
        return []
    # 中點・保留在同一膠囊（對齊範本）；只允許頓號／斜線拆
    for sep in ("、", "/", "|"):
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) >= 2:
                return parts[:3]
    return [s]


def _order_rows(rows: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """★→☆→⚠；同階維持輸入順序（對齊範本 Top4 列序，不准同階再按空間重排）。"""
    tagged = list(enumerate(rows or []))

    def key(item: Tuple[int, Dict[str, Any]]) -> Tuple[int, int]:
        i, r = item
        m = str(r.get("mark") or "").lower()
        if m in ("star", "true", "★", "*"):
            tier = 0
        elif m in ("emerging", "emerge", "⚠️", "warn"):
            tier = 2
        else:
            tier = 1
        return (tier, i)

    return [r for _, r in sorted(tagged, key=key)]


def _sanitize_paint_rows(
    rows: Optional[Sequence[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """出圖硬閘：黑名單／無收／示意列不准上卡；股名＝代號則留空不重複印。

    缺欄顯示「—」，不准發明數字。DEMO／示意只准本機 demo 入口。
    """
    try:
        from undervalue_growth import HARD_EXCLUDE_SIDS, format_core_ratio
    except Exception:
        HARD_EXCLUDE_SIDS = frozenset({"3006", "6265"})

        def format_core_ratio(v):  # type: ignore
            x = _finite(v)
            if x is None:
                return "—"
            return "純本業" if x >= 100 else f"{x:.0f}%"

    out: List[Dict[str, Any]] = []
    for raw in rows or []:
        r = dict(raw or {})
        sid = str(r.get("stock_id") or "").strip()
        if not sid or sid in HARD_EXCLUDE_SIDS:
            continue
        if str(r.get("reason") or "").strip() == "示意":
            # 明示意列只給本地 DEMO；話筒路徑不該進來
            continue
        if _finite(r.get("close")) is None:
            continue
        name = str(r.get("name") or "").strip()
        if not name or name == sid or name.isdigit():
            r["name"] = ""
        if not str(r.get("core_ratio_label") or "").strip():
            r["core_ratio_label"] = format_core_ratio(r.get("core_ratio_pct"))
        # 今年／明年目標若相等且明年空間為 0 → 清掉明年目標，不准複製今年價冒充
        fy = _finite(r.get("fair_year"))
        tn = _finite(r.get("target_next"))
        if fy is not None and tn is not None and abs(fy - tn) < 0.05:
            ups = _finite(r.get("ups_tgt_pct"))
            if ups is None or abs(ups) < 0.05:
                r["target_next"] = None
                r["ups_tgt_pct"] = None
        out.append(r)
    return out


def _display_name(row: Dict[str, Any]) -> str:
    sid = str(row.get("stock_id") or "").strip()
    name = str(row.get("name") or "").strip()
    if not name or name == sid or name.isdigit():
        return ""
    return name


def _core_label(row: Dict[str, Any]) -> str:
    lab = str(row.get("core_ratio_label") or "").strip()
    if lab:
        return lab
    try:
        from undervalue_growth import format_core_ratio

        return format_core_ratio(row.get("core_ratio_pct"))
    except Exception:
        v = _finite(row.get("core_ratio_pct"))
        if v is None:
            return "—"
        if v >= 100:
            return "純本業"
        return f"{v:.0f}%"


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


def _chip_colors(chip: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """膠囊底／字色。範本：外投同買橘底深字、投信連買紅底、興櫃紫、投信＋調節橘。"""
    s = str(chip or "")
    if "同賣" in s:
        return (120, 40, 48), (20, 8, 8)
    if "同買" in s:
        return (232, 160, 72), (20, 12, 4)  # 外投同買：橘底深字
    # 範本：投信連買・外資調節 → 單顆橘膠囊深字
    if "調節" in s and ("投信" in s or "外資" in s):
        return (220, 150, 60), (24, 14, 4)
    if "投信連買" in s or (s.startswith("投信") and "買" in s):
        return (176, 48, 56), (255, 236, 236)
    if "外資連買" in s or (s.startswith("外資") and "買" in s):
        return (36, 72, 120), (220, 236, 255)
    if "興櫃" in s:
        return (120, 100, 180), (18, 10, 28)
    if "調節" in s:
        return (200, 140, 56), (24, 14, 4)
    return PILL_BG, MUTED


def _header_fill(mark: Any) -> Tuple[int, int, int]:
    """表頭實心底（對齊範本：可買深綠／等止穩琥珀／量小紫）。"""
    if _is_star(mark):
        return (6, 48, 36)
    if _is_emerging(mark):
        return (40, 28, 64)
    return (64, 44, 12)


def _pe_dot_ruler(
    dr: ImageDraw.ImageDraw,
    x0: float,
    x1: float,
    y: float,
    pe_now: Optional[float],
    fair_lo: Optional[float],
    fair_hi: Optional[float],
    *,
    accent: Tuple[int, int, int],
) -> None:
    """本益比尺：細軸＋小點＋小把手（美編：不准玩具大球）。"""
    lo = _finite(fair_lo)
    hi = _finite(fair_hi)
    now = _finite(pe_now)
    vals = [v for v in (lo, hi, now) if v is not None and v > 0]
    n_dots = 5
    span = max(x1 - x0, 1.0)
    cy = y
    dr.line([(x0, cy), (x1, cy)], fill=(55, 62, 72), width=max(2, _px(2)))
    for i in range(n_dots):
        cx = x0 + (i + 0.5) / n_dots * span
        r = _px(3)
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(70, 78, 90))
    if len(vals) < 1 or now is None:
        return
    span_lo = min(vals) * 0.85
    span_hi = max(vals) * 1.15
    den = max(span_hi - span_lo, 1e-9)
    frac = max(0.0, min(1.0, (float(now) - span_lo) / den))
    cx = x0 + frac * span
    r = _px(7)
    dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=accent)


def _inline_bar(
    dr: ImageDraw.ImageDraw,
    x0: float,
    x1: float,
    y_mid: float,
    frac: float,
    *,
    fill,
) -> None:
    """目標空間右側全圓角進度條（對齊範本高度）。"""
    bar_h = _px(16)
    yy0 = y_mid - bar_h / 2.0
    yy1 = yy0 + bar_h
    if x1 - x0 < _px(28):
        return
    rad = bar_h // 2
    dr.rounded_rectangle((x0, yy0, x1, yy1), radius=rad, fill=(28, 34, 44))
    f = max(0.0, min(1.0, float(frac)))
    if f <= 0:
        return
    dr.rounded_rectangle(
        (x0, yy0, x0 + max(_px(8), (x1 - x0) * f), yy1),
        radius=rad,
        fill=fill,
    )


def _eps_ratio_bar(
    dr: ImageDraw.ImageDraw,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    pct: Optional[float],
    *,
    fill,
    font: ImageFont.ImageFont,
) -> None:
    """EPS％＝小綠膠囊＋深字（美編：貼在明年後，高≈32）。"""
    if pct is None:
        return
    lab = f"{int(round(pct))}%"
    tw = font.getlength(lab)
    ph = min(_px(32), max(_px(26), y1 - y0 - _px(6)))
    pw = max(tw + _px(18), _px(52))
    # 若呼叫端給了較寬 x1，膠囊靠左貼字，不拉滿
    px0 = x0
    px1 = min(x1, px0 + pw)
    cy0 = (y0 + y1 - ph) / 2.0
    cy1 = cy0 + ph
    rad = ph // 2
    dr.rounded_rectangle((px0, cy0, px1, cy1), radius=rad, fill=fill)
    _text_center_mid(dr, (px0, cy0, px1, cy1), lab, font, (12, 18, 14))


def _draw_d3_card(
    dr: ImageDraw.ImageDraw,
    box: Tuple[float, float, float, float],
    row: Dict[str, Any],
) -> None:
    """對齊範本實測：表頭高77／字高≈38–40／膠囊≈140×47／2×2 等分。"""
    x0, y0, x1, y1 = box
    glyph, gfill, edge, glabel = _mark_glyph(row.get("mark"))
    emerging = _is_emerging(row.get("mark"))
    star = _is_star(row.get("mark"))
    dr.rounded_rectangle(box, radius=_px(14), fill=CARD, outline=edge, width=_px(2))

    # 範本字高：表頭≈38→font34；格標題／主數≈40→font42；次要≈22→font20
    head_f = _font(34, bold=True)
    cell_title_f = _font(40, bold=True)
    cell_f = _font(36, bold=True)
    cell_b = _font(40, bold=True)
    small_f = _font(22, bold=True)
    micro_f = _font(20)
    pill_f = _font(22, bold=True)
    pad = _px(16)
    head_h = _px(76)
    hx0, hy0 = x0 + pad, y0 + _px(10)
    hx1, hy1 = x1 - pad, y0 + head_h - _px(10)

    # 實心表頭底（範本）
    dr.rounded_rectangle(
        (x0 + _px(2), y0 + _px(2), x1 - _px(2), y0 + head_h - _px(1)),
        radius=_px(12),
        fill=_header_fill(row.get("mark")),
    )

    sid = str(row.get("stock_id") or "—")
    name = _display_name(row)
    close_s = _fmt_price(row.get("close"))
    gm = _fmt_num(row.get("gross_margin"), 1)
    yoy = _fmt_pct(row.get("yoy_pct"))
    pills = _split_chip_pills(str(row.get("chip_note") or ""))

    # 右膠囊：範本 ≈140×47
    pill_gap = _px(8)
    cursor_r = hx1
    pill_h = _px(46)
    for chip in reversed(pills):
        cbg, cfg = _chip_colors(chip)
        pw = min(_px(160), max(_px(120), pill_f.getlength(chip) + _px(28)))
        cx1p = cursor_r
        cx0p = cx1p - pw
        cy0p = (hy0 + hy1 - pill_h) / 2.0
        cy1p = cy0p + pill_h
        dr.rounded_rectangle((cx0p, cy0p, cx1p, cy1p), radius=_px(12), fill=cbg)
        _text_center_mid(dr, (cx0p, cy0p, cx1p, cy1p), chip, pill_f, cfg)
        cursor_r = cx0p - pill_gap
    left_max = cursor_r - _px(10) if pills else hx1

    # 表頭單行同字級（範本）
    accent_h = gfill
    pipe = (120, 140, 130) if star else MUTED
    name_bit = f"{sid} {name}".strip() if name else sid
    segs: List[Tuple[str, Tuple[int, int, int]]] = [
        (f"{glyph} {glabel}", accent_h),
        (" | ", pipe),
        (name_bit, TEXT),
        (" | ", pipe),
        (f"{close_s}元", TEXT),
    ]
    if gm != "—":
        segs += [(" | ", pipe), (f"毛利{gm}%", accent_h)]
    if yoy != "—":
        segs += [(" | ", pipe), (f"年增{yoy}", accent_h)]

    def _with_pipe(pipe_s: str) -> List[Tuple[str, Tuple[int, int, int]]]:
        out: List[Tuple[str, Tuple[int, int, int]]] = []
        for s, col in segs:
            if s.strip() == "|":
                if pipe_s:
                    out.append((pipe_s, col))
            else:
                out.append((s, col))
        return out

    trial: List[Tuple[str, Tuple[int, int, int]]] = []
    for pipe_s in (" | ", " |", "|", ""):
        cand = _with_pipe(pipe_s)
        if head_f.getlength("".join(s for s, _ in cand)) <= left_max - hx0:
            trial = cand
            break
    if not trial:
        trial = _with_pipe("|")
        while len(trial) > 5 and head_f.getlength("".join(s for s, _ in trial)) > left_max - hx0:
            trial.pop()
            if trial and trial[-1][0].strip() in ("|", ""):
                trial.pop()
    full = "".join(s for s, _ in trial)
    if head_f.getlength(full) > left_max - hx0:
        _text_left_mid(
            dr, (hx0, hy0, left_max, hy1),
            _truncate(head_f, full, left_max - hx0), head_f, TEXT,
        )
    else:
        tx = hx0
        for s, col in trial:
            if not s:
                continue
            _text_left_mid(dr, (tx, hy0, left_max, hy1), s, head_f, col)
            tx += head_f.getlength(s)

    # 2×2 等分（範本十字線淡灰）
    grid_top = y0 + head_h
    grid_bot = y1 - _px(4)
    mid_x = (x0 + x1) / 2.0
    mid_y = (grid_top + grid_bot) / 2.0
    gpad = _px(14)
    dr.line(
        [(mid_x, grid_top + _px(6)), (mid_x, grid_bot - _px(6))],
        fill=GRID_LINE, width=max(1, _px(1)),
    )
    dr.line(
        [(x0 + gpad, mid_y), (x1 - gpad, mid_y)],
        fill=GRID_LINE, width=max(1, _px(1)),
    )

    cells = [
        (x0 + gpad, grid_top + _px(8), mid_x - _px(10), mid_y - _px(6), "tl"),
        (mid_x + _px(10), grid_top + _px(8), x1 - gpad, mid_y - _px(6), "tr"),
        (x0 + gpad, mid_y + _px(6), mid_x - _px(10), grid_bot - _px(6), "bl"),
        (mid_x + _px(10), mid_y + _px(6), x1 - gpad, grid_bot - _px(6), "br"),
    ]

    eps_e = _finite(row.get("eps_earned"))
    eps_y = _finite(row.get("eps_2026"))
    eps_n = _finite(row.get("eps_2027"))
    pe_now = _finite(row.get("pe"))
    pe_fwd = _finite(row.get("pe_fwd"))
    pe_year = _finite(row.get("pe_year"))
    pe_next = _finite(row.get("pe_next"))
    fair = _finite(row.get("fair_year"))
    tgt = _finite(row.get("target_next"))
    ups_f = _finite(row.get("ups_fair_pct"))
    ups_t = _finite(row.get("ups_tgt_pct"))
    thr = _finite(row.get("rev_threshold_yi"))
    oct_r = _finite(row.get("rev_oct_yi"))
    support = _finite(row.get("support"))
    resist = _finite(row.get("resistance"))
    broken = bool(row.get("tech_broken")) or (
        "破撐" in str(row.get("tech_status") or "") or "破撐" in str(row.get("reason") or "")
    )
    accent = PURPLE if emerging else CYAN
    pill_fill = (150, 120, 210) if emerging else (45, 190, 150)
    support_col = PURPLE if emerging else GREEN
    resist_col = PURPLE if emerging else RESIST_COL

    earned_pct = None
    if eps_e is not None and eps_n is not None and eps_n > 0:
        earned_pct = max(0.0, min(999.0, eps_e / eps_n * 100.0))
    climb_pct = None
    if eps_y is not None and eps_n is not None and eps_n > 0:
        climb_pct = max(0.0, min(100.0, eps_y / eps_n * 100.0))

    def _sr_badge(
        label: str,
        price: Optional[float],
        *,
        fg,
        bg,
        x: float,
        ya: float,
        yb: float,
    ) -> float:
        """範本：撐／壓小色塊＋價。回傳下一段起點 x。"""
        bw = _px(30)
        bh = min(_px(30), max(_px(24), yb - ya - _px(4)))
        by0 = (ya + yb - bh) / 2.0
        dr.rounded_rectangle((x, by0, x + bw, by0 + bh), radius=_px(4), fill=bg)
        _text_center_mid(dr, (x, by0, x + bw, by0 + bh), label, small_f, TEXT)
        px = x + bw + _px(6)
        lab = _fmt_price(price)
        _text_left_mid(dr, (px, ya, cx1, yb), lab, cell_f, fg)
        return px + cell_f.getlength(lab)

    for cx0, cy0, cx1, cy1, kind in cells:
        ch = max(1.0, cy1 - cy0)
        if kind == "tl":
            # 三行：標題／已賺／今年｜明年＋76%膠囊
            bands = [
                (cy0, cy0 + ch * 0.30),
                (cy0 + ch * 0.30, cy0 + ch * 0.62),
                (cy0 + ch * 0.62, cy1),
            ]
            _text_left_mid(dr, (cx0, bands[0][0], cx1, bands[0][1]), "【EPS爬坡】", cell_title_f, TEXT)
            e_s = f"已賺 {_fmt_eps(eps_e)}"
            _text_left_mid(dr, (cx0, bands[1][0], cx1, bands[1][1]), e_s, cell_b, TEXT)
            if earned_pct is not None:
                ex = cx0 + cell_b.getlength(e_s) + _px(8)
                _text_left_mid(
                    dr, (ex, bands[1][0], cx1, bands[1][1]),
                    f"{int(round(earned_pct))}%", micro_f, MUTED,
                )
            n_raw = row.get("eps_2027_label")
            n_s = str(n_raw) if n_raw else _fmt_eps(eps_n)
            y_s = _fmt_eps(eps_y)
            if eps_y is not None and abs(eps_y - round(eps_y)) < 1e-9 and abs(eps_y) < 100:
                y_s = f"{eps_y:.1f}"
            if not n_raw and eps_n is not None and abs(eps_n - round(eps_n)) < 1e-9 and abs(eps_n) < 100:
                n_s = f"{eps_n:.1f}"
            n_lab = "明" if (n_raw or (eps_n is not None and eps_n >= 100)) else "明年"
            line2 = f"今年 {y_s} | {n_lab} {n_s}"
            max_txt = max(0.0, (cx1 - cx0) - _px(70))
            line2s = _truncate(cell_f, line2, max_txt)
            _text_left_mid(dr, (cx0, bands[2][0], cx1, bands[2][1]), line2s, cell_f, TEXT)
            bar_x0 = cx0 + cell_f.getlength(line2s) + _px(8)
            _eps_ratio_bar(
                dr, bar_x0, cx1, bands[2][0], bands[2][1], climb_pct,
                fill=pill_fill, font=small_f,
            )
        elif kind == "tr":
            fair_lo = pe_next if pe_next is not None else pe_year
            fair_hi = pe_year if pe_year is not None else pe_next
            if fair_lo is not None and fair_hi is not None and fair_lo > fair_hi:
                fair_lo, fair_hi = fair_hi, fair_lo
            pe_s = _fmt_num(pe_now, 1)
            if pe_s != "—" and pe_now is not None and abs(pe_now - round(pe_now)) < 0.05:
                pe_s = f"{pe_now:.0f}"
            bands = [
                (cy0, cy0 + ch * 0.28),
                (cy0 + ch * 0.28, cy0 + ch * 0.54),
                (cy0 + ch * 0.54, cy0 + ch * 0.78),
            ]
            _text_left_mid(dr, (cx0, bands[0][0], cx1, bands[0][1]), "【本益比位階】", cell_title_f, TEXT)
            pe_bit = f"今年 {pe_s}x" if pe_s != "—" else "今年 —"
            _text_left_mid(dr, (cx0, bands[1][0], cx1, bands[1][1]), pe_bit, cell_b, TEXT)
            fwd_s = _fmt_num(pe_fwd, 1)
            if fwd_s != "—" and pe_fwd is not None and abs(pe_fwd - round(pe_fwd)) < 0.05:
                fwd_s = f"{pe_fwd:.0f}"
            band = "—"
            if (not emerging) and fair_lo is not None and fair_hi is not None:
                band = f"{fair_lo:.0f}-{fair_hi:.0f}x"
            fwd_bit = f"前瞻 {fwd_s}x" if fwd_s != "—" else "前瞻 —"
            _text_left_mid(dr, (cx0, bands[2][0], cx1, bands[2][1]), fwd_bit, cell_f, TEXT)
            if band != "—":
                bx = cx0 + cell_f.getlength(fwd_bit) + _px(6)
                _text_left_mid(
                    dr, (bx, bands[2][0], cx1, bands[2][1]),
                    f"(合理 {band})", micro_f, MUTED,
                )
            _pe_dot_ruler(
                dr, cx0, cx1, cy0 + ch * 0.90, pe_now, fair_lo, fair_hi, accent=accent,
            )
        elif kind == "bl":
            title = "【目標空間】"
            bar_w = _px(110)
            rows_tgt: List[Tuple[str, bool, Optional[float], Tuple[int, int, int]]] = []
            if emerging and fair is not None and tgt is not None:
                rows_tgt.append(
                    (f"明年看 {_fmt_price(fair)}-{_fmt_price(tgt)}", False, ups_t, accent)
                )
            else:
                if fair is not None:
                    rows_tgt.append((f"今年看 {_fmt_price(fair)}", True, ups_f, CYAN))
                if tgt is not None:
                    rows_tgt.append((f"明年看 {_fmt_price(tgt)}", True, ups_t, accent))
            t0, t1 = cy0, cy0 + ch * 0.28
            _text_left_mid(dr, (cx0, t0, cx1, t1), title, cell_title_f, TEXT)
            body_top, body_bot = t1, cy1
            n_lines = max(1, len(rows_tgt[:2]))
            line_h = (body_bot - body_top) / n_lines
            for i, (lab, show_pct, ups, bar_col) in enumerate(rows_tgt[:2]):
                ly0 = body_top + i * line_h
                ly1 = ly0 + line_h
                bar_x0 = cx1 - bar_w
                text_right = bar_x0 - _px(6)
                _text_left_mid(dr, (cx0, ly0, text_right, ly1), lab, cell_f, TEXT)
                tw = cell_f.getlength(lab)
                if show_pct and ups is not None:
                    _text_left_mid(
                        dr, (cx0 + tw + _px(4), ly0, text_right, ly1),
                        f"({_fmt_pct(ups)})", small_f, GREEN if not emerging else PURPLE,
                    )
                frac = max(0.0, min(1.0, float(ups) / 100.0)) if ups is not None else 0.0
                _inline_bar(dr, bar_x0, cx1, (ly0 + ly1) / 2.0, frac, fill=bar_col)
        else:  # br
            if emerging:
                title = "【對帳防線】"
                thr_line = f"明年門檻 {_fmt_num(thr, 2 if (thr is not None and thr < 10) else 1)}億/月"
            else:
                title = "【對帳與撐壓】"
                thr_line = f"月門檻 {_fmt_num(thr, 1)}億"
                if oct_r is not None:
                    mon = str(row.get("rev_month_label") or "最新").strip() or "最新"
                    thr_line = f"{thr_line} ({mon}{_fmt_num(oct_r, 1)})"
            bands = [
                (cy0, cy0 + ch * 0.28),
                (cy0 + ch * 0.28, cy0 + ch * 0.58),
                (cy0 + ch * 0.60, cy1),
            ]
            _text_left_mid(dr, (cx0, bands[0][0], cx1, bands[0][1]), title, cell_title_f, TEXT)
            # 門檻白字＋括號灰
            if "(" in thr_line:
                main, rest = thr_line.split("(", 1)
                _text_left_mid(dr, (cx0, bands[1][0], cx1, bands[1][1]), main.rstrip(), cell_f, TEXT)
                mx = cx0 + cell_f.getlength(main.rstrip()) + _px(4)
                _text_left_mid(
                    dr, (mx, bands[1][0], cx1, bands[1][1]),
                    "(" + rest, micro_f, MUTED,
                )
            else:
                _text_left_mid(
                    dr, (cx0, bands[1][0], cx1, bands[1][1]),
                    _truncate(cell_f, thr_line, cx1 - cx0), cell_f, TEXT,
                )
            ya, yb = bands[2]
            if (not emerging) and broken and support is not None:
                warn = f"▲破撐 {_fmt_price(support)}"
                _text_left_mid(dr, (cx0, ya, cx1, yb), warn, cell_f, ORANGE)
                mid = cx0 + cell_f.getlength(warn)
                _text_left_mid(dr, (mid, ya, cx1, yb), " | ", cell_f, MUTED)
                mid2 = mid + cell_f.getlength(" | ")
                nx = _sr_badge("壓", resist, fg=resist_col, bg=(80, 32, 36), x=mid2, ya=ya, yb=yb)
                _ = nx
            else:
                nx = _sr_badge(
                    "撐", support,
                    fg=support_col, bg=(20, 72, 52) if not emerging else (60, 40, 90),
                    x=cx0, ya=ya, yb=yb,
                )
                _text_left_mid(dr, (nx, ya, cx1, yb), " | ", cell_f, MUTED)
                nx2 = nx + cell_f.getlength(" | ")
                _sr_badge(
                    "壓", resist,
                    fg=resist_col, bg=(80, 32, 36) if not emerging else (60, 40, 90),
                    x=nx2, ya=ya, yb=yb,
                )


def _page_count(n: int) -> int:
    if n <= 0:
        return 1
    return int(math.ceil(n / float(CARDS_PER_PAGE)))


def _render_d3_page(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    page_i: int = 0,
    page_n: int = 1,
    title: str = "版本 D3 終極版｜2×2 矩陣 · 籌碼撐壓整合",
    empty_note: Optional[str] = None,
) -> str:
    rows = _sanitize_paint_rows(rows)
    W = _px(BASE_W)
    H = _px(BASE_H)
    im = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(im)

    # 範本卡左右約 30px
    content_l = _px(30)
    content_r = W - _px(30)
    top = _px(SAFE_TOP)
    bot = H - _px(SAFE_BOTTOM)

    title_f = _font(32, bold=True)
    sub_f = _font(20)
    page_f = _font(18)
    empty_f = _font(34, bold=True)
    empty_sub_f = _font(22)
    foot_f = _font(18)

    y = top
    head = f"{title}（Top {CARDS_PER_PAGE}）"
    # 範本標題置中；多頁頁碼副標右
    _text_center_mid(dr, (content_l, y, content_r, y + _px(36)), head, title_f, TEXT)
    y += _px(38)
    date_s = _as_of_close_label(as_of)
    sub = "已整合外資／投信連買賣與大量區撐壓"
    if date_s:
        sub = f"{date_s}｜{sub}"
    page_bit = f"第{page_i + 1}/{max(1, page_n)}頁"
    _text_center_mid(
        dr, (content_l, y, content_r, y + _px(24)),
        _truncate(sub_f, sub, content_r - content_l - _px(90)), sub_f, MUTED,
    )
    if page_n > 1:
        _text_right_mid(dr, (content_l, y, content_r, y + _px(24)), page_bit, page_f, MUTED)
    y += _px(26)

    foot_reserve = _px(26)
    avail = bot - y - foot_reserve
    gap = _px(12)
    if not rows:
        mid_y = y + avail // 2
        _text_center_mid(
            dr, (content_l, mid_y - _px(36), content_r, mid_y),
            "無真成長低估名單", empty_f, TEXT,
        )
        _text_center_mid(
            dr, (content_l, mid_y + _px(8), content_r, mid_y + _px(40)),
            str(empty_note or "已剔除假低估陷阱；有資料再顯示"), empty_sub_f, MUTED,
        )
    else:
        n = len(rows)
        card_h = int((avail - gap * max(0, n - 1)) / max(1, n))
        # 範本單卡高≈408；在安全區內盡量貼近
        card_h = max(_px(360), min(card_h, _px(420)))
        for i, row in enumerate(rows):
            top_c = y + i * (card_h + gap)
            _draw_d3_card(dr, (content_l, top_c, content_r, top_c + card_h), row)

    fy = bot - foot_reserve
    _text_center_mid(
        dr, (content_l, fy, content_r, fy + foot_reserve),
        "估值≠買訊｜★可買仍須對齊黃金買點才切入", foot_f, MUTED,
    )

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    im.save(save_path, format="PNG", optimize=True)
    return save_path


def render_undervalue_pages(
    picks: Sequence[Dict[str, Any]],
    out_dir: str,
    *,
    as_of: Optional[str] = None,
    title: str = "版本 D3 終極版｜2×2 矩陣 · 籌碼撐壓整合",
    empty_note: Optional[str] = None,
    prefix: str = "uv_d3",
) -> List[str]:
    """渲全部頁面；每頁最多 4 卡。回傳 PNG 路徑列表（至少 1）。"""
    rows = _order_rows(_sanitize_paint_rows(picks))
    os.makedirs(out_dir or ".", exist_ok=True)
    n_pages = _page_count(len(rows)) if rows else 1
    paths: List[str] = []
    if not rows:
        p = os.path.join(out_dir, f"{prefix}_p1.png")
        paths.append(
            _render_d3_page(
                [], p, as_of=as_of, page_i=0, page_n=1, title=title, empty_note=empty_note
            )
        )
        return paths
    for i in range(n_pages):
        chunk = rows[i * CARDS_PER_PAGE : (i + 1) * CARDS_PER_PAGE]
        p = os.path.join(out_dir, f"{prefix}_p{i + 1}.png")
        paths.append(
            _render_d3_page(
                chunk,
                p,
                as_of=as_of,
                page_i=i,
                page_n=n_pages,
                title=title,
                empty_note=empty_note,
            )
        )
    return paths


def render_undervalue_png(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    title: str = "版本 D3 終極版｜2×2 矩陣 · 籌碼撐壓整合",
    pe_label: str = "PE",
    empty_note: Optional[str] = None,
) -> str:
    """相容入口：有成長欄→D3 第 1 頁；否則舊列表（測試／舊快取）。"""
    _ = pe_label
    rows_l = _sanitize_paint_rows(rows)
    if not rows_l or _has_growth_fields(rows_l):
        ordered = _order_rows(rows_l)
        page_n = _page_count(len(ordered)) if ordered else 1
        return _render_d3_page(
            ordered[:CARDS_PER_PAGE],
            save_path,
            as_of=as_of,
            page_i=0,
            page_n=page_n,
            title=title,
            empty_note=empty_note,
        )
    # --- 舊列表相容（無 fair_year 的單元測試／舊庫）---
    rows_l = _order_rows(rows_l)
    W = _px(BASE_W)
    pad_x, pad_y = _px(PAD_X), _px(SAFE_TOP)
    content_l = pad_x
    content_r = W - pad_x

    title_f = _font(36, bold=True)
    date_f = _font(22)
    legend_f = _font(22, bold=True)
    col_f = _font(18, bold=True)
    cell_f = _font(24, bold=True)
    name_fonts = [_font(22), _font(20), _font(18)]
    reason_f = _font(20)
    empty_f = _font(32, bold=True)
    empty_sub_f = _font(22)
    foot_f = _font(18)

    cells = [_cells(r) for r in rows_l]
    headers_txt = {"close": "收盤", "pe": pe_label, "med": "中位", "dist": "距下緣％", "flow": "流動張"}
    cols = _column_widths(cells, headers_txt, col_f, cell_f)
    x_flow_r = content_r
    x_dist_r = x_flow_r - cols["flow"]
    x_med_r = x_dist_r - cols["dist"]
    x_pe_r = x_med_r - cols["med"]
    x_close_r = x_pe_r - cols["pe"]
    x_mark = content_l
    x_sid = x_mark + _px(44)
    x_name = x_sid + _px(90)
    name_max = max(_px(40), x_close_r - cols["close"] - x_name - _px(8))
    reason_max = content_r - x_name

    reasons = [_wrap_reason(reason_f, str(r.get("reason") or ""), reason_max) for r in rows_l]
    row_hs = [_px(MAIN_H) + _px(REASON_LINE_H) * len(lines) for lines in reasons]
    has_est = any(r.get("pe_est") and _finite(r.get("pe")) is not None for r in rows_l)

    top_block = pad_y + _px(TITLE_H + LEGEND_H + HEAD_H + HEAD_AFTER)
    body_h = sum(h + _px(ROW_GAP) for h in row_hs) if rows_l else _px(220)
    foot_h = _px(FOOT_H) if has_est else 0
    H = max(_px(BASE_H), top_block + body_h + foot_h + _px(SAFE_BOTTOM) + _px(14))

    im = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(im)
    card_box = (_px(18), _px(14), W - _px(18), H - _px(14))
    dr.rounded_rectangle(card_box, radius=_px(28), fill=CARD, outline=(78, 118, 158), width=max(1, _px(2)))

    y = pad_y
    _text_left_mid(dr, (content_l, y, content_r, y + _px(40)), title, title_f, TEXT)
    date_s = _as_of_label(as_of)
    if date_s:
        _text_right_mid(dr, (content_l, y + _px(4), content_r, y + _px(40)), date_s, date_f, MUTED)
    y += _px(TITLE_H)

    n_star = sum(1 for r in rows_l if _is_star(r.get("mark")))
    n_watch = len(rows_l) - n_star
    leg = f"★真低估 {n_star}　☆觀察 {n_watch}　　共 {len(rows_l)} 檔"
    _text_left_mid(dr, (content_l, y, content_r, y + _px(28)), leg, legend_f, HEAD)
    y += _px(LEGEND_H)

    head_h = _px(HEAD_H)
    headers = [
        ("★☆", x_mark, x_mark + _px(44), "c"),
        ("代號", x_sid, x_sid + _px(90), "l"),
        ("股名", x_name, x_name + name_max, "l"),
        (headers_txt["close"], x_close_r - cols["close"], x_close_r, "r"),
        (headers_txt["pe"], x_pe_r - cols["pe"], x_pe_r, "r"),
        (headers_txt["med"], x_med_r - cols["med"], x_med_r, "r"),
        (headers_txt["dist"], x_dist_r - cols["dist"], x_dist_r, "r"),
        (headers_txt["flow"], x_flow_r - cols["flow"], x_flow_r, "r"),
    ]
    for lab, xa, xb, align in headers:
        box = (xa, y, xb, y + head_h)
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
        mid_y = y + (H - _px(SAFE_BOTTOM) - y) // 2
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
            glyph, gfill, _edge, _lab = _mark_glyph(row.get("mark"))
            m0, m1 = top, top + main_h
            c = cells[i]
            _text_center_mid(dr, (x_mark, m0, x_mark + _px(44), m1), glyph, cell_f, gfill)
            _text_left_mid(
                dr, (x_sid, m0, x_sid + _px(90), m1),
                str(row.get("stock_id") or "—"), cell_f, TEXT,
            )
            name, name_f = _fit_name(name_fonts, _display_name(row) or "—", name_max)
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
        fy = H - _px(SAFE_BOTTOM) - _px(FOOT_H) + _px(8)
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
        "pe": 20.1,
        "pe_fwd": 15.2,
        "pe_year": 28,
        "pe_next": 22,
        "gross_margin": 59.3,
        "core_ratio_pct": 94,
        "core_ratio_label": "94%",
        "yoy_pct": 83,
        "eps_earned": 34.9,
        "eps_2026": 52.0,
        "eps_2027": 68.0,
        "fair_year": 1350,
        "target_next": 1625,
        "ups_fair_pct": 29,
        "ups_tgt_pct": 55,
        "rev_threshold_yi": 20.5,
        "rev_oct_yi": 18.4,
        "rev_month_label": "10月",
        "support": 1045,
        "resistance": 1210,
        "tech_status": "站回支撐區",
        "tech_broken": False,
        "chip_note": "外投同買",
        "peer_pe_median": 26,
        "dist_to_floor_pct": -23,
        "flow_shares": 5000,
        "reason": "",
    },
    {
        "mark": "star",
        "stock_id": "7711",
        "name": "永擎",
        "industry": "先進封裝",
        "close": 481.5,
        "pe": 13.4,
        "pe_fwd": 10.5,
        "pe_year": 18,
        "pe_next": 14,
        "gross_margin": 21.1,
        "core_ratio_pct": 105,
        "core_ratio_label": "純本業",
        "yoy_pct": 57,
        "eps_earned": 24.5,
        "eps_2026": 36.0,
        "eps_2027": 48.0,
        "fair_year": 620,
        "target_next": 780,
        "ups_fair_pct": 29,
        "ups_tgt_pct": 62,
        "rev_threshold_yi": 28.0,
        "rev_oct_yi": 24.0,
        "support": 465,
        "resistance": 520,
        "tech_broken": False,
        "chip_note": "投信連買5日",
        "reason": "",
    },
    {
        "mark": "watch",
        "stock_id": "2383",
        "name": "台光電",
        "industry": "高階CCL",
        "close": 3460,
        "pe": 26.8,
        "pe_fwd": 20.4,
        "pe_year": 30,
        "pe_next": 24,
        "gross_margin": 37.7,
        "core_ratio_pct": 92,
        "yoy_pct": 203,
        "eps_earned": 82.9,
        "eps_2026": 129.0,
        "eps_2027": 170.0,
        "fair_year": 4500,
        "target_next": 5800,
        "ups_fair_pct": 30,
        "ups_tgt_pct": 68,
        "rev_threshold_yi": 265.0,
        "rev_oct_yi": 220.0,
        "support": 4160,
        "resistance": 4475,
        "tech_status": "跌破大量區撐 4160，先看表等止穩",
        "tech_broken": True,
        "chip_note": "投信連買・外資調節",
        "reason": "",
    },
    {
        "mark": "emerging",
        "stock_id": "3595",
        "name": "山太士",
        "industry": "興櫃",
        "close": 580,
        "pe": 61.0,
        "pe_fwd": 30.0,
        "pe_year": 28,
        "pe_next": 22,
        "gross_margin": 77.4,
        "core_ratio_pct": 90,
        "yoy_pct": 55,
        "eps_earned": 5.99,
        "eps_2026": 9.5,
        "eps_2027": 19.0,
        "eps_2027_label": "18-20",
        "fair_year": 630,
        "target_next": 800,
        "ups_fair_pct": 9,
        "ups_tgt_pct": 38,
        "rev_threshold_yi": 1.5,
        "rev_oct_yi": 1.2,
        "support": 561,
        "resistance": 636,
        "tech_status": "60日均量過小",
        "tech_broken": False,
        "chip_note": "興櫃無法人",
        "reason": "",
    },
]


def main() -> None:
    out_dir = "/opt/cursor/artifacts/uv-d3"
    os.makedirs(out_dir, exist_ok=True)
    paths = render_undervalue_pages(
        _DEMO_ROWS, out_dir, as_of="20261117", prefix="demo"
    )
    print(paths)
    p1 = render_undervalue_png(
        _DEMO_ROWS,
        os.path.join(out_dir, "page1.png"),
        as_of="20261117",
    )
    print(p1)


if __name__ == "__main__":
    main()
