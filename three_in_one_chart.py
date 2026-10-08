#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查股三合一圖（T0118 產品路徑）。

①高低導航 180 日＋②飆大結構＋③大量壓力，合成一張。
規則鎖自 media/6526-三合一圖.png（T0118）。
官方 OHLC；③不准盤中假柱；買點只認藍▲紅框；紅箭頭不是買訊。
"""
from __future__ import annotations

import functools
import json
import os
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

from PIL import Image, ImageDraw, ImageFilter, ImageFont

MARK_COLOR = "#e65100"
MARK_LABEL = "③窗起"
# 爆大量連線改紫（跟橘窗起／測壓／橙賣點分開，一眼能分）
SPIKE_COLOR = "#6a1b9a"
SPIKE_DASH = (0, (3.5, 2.2))  # 爆大量連線＝虛線，不准實線
SPIKE_BAR_COLOR = "#f9a825"  # 量柱仍用琥珀，只換豎線色
# 測壓連線色（跟爆大量琥珀／窗起橘分開）
CEYA_LINE_COLOR = "#0277bd"
# 三圖 K／量柱同一套台股紅漲綠跌（①導航＝準）
CANDLE_UP = "#e53935"
CANDLE_DN = "#00897b"
WICK_UP = "#b71c1c"
WICK_DN = "#004d40"
# 三圖同一左右框（①為範本）；左界再往左＝圖寬變寬。壓撐標改貼框內左側（不准軸外被裁成半個數字）
FRAME_LEFT = 0.042
FRAME_RIGHT = 0.970
# 壓撐標：相對水平線左端，往右進框內（points；正＝框內）
VZ_TAG_X_OFFSET = 10

THREE_IN_ONE_CAPTION_HEAD = "三合一圖（導航＋結構＋大量壓力；非買訊）"
LOCK_KEY = "T0118"
# 過關＝話筒對話框點開，不是下載相簿。Telegram sendPhoto 會把「最長邊」再壓到
# 約 2560；源圖 2800×7000 點開寬只剩 ~1000，國字被二次 JPEG 抽糊。
# 合成直接對點開視窗：欄寬約 1480、整張最長邊 ≤2560，字級依這張設計。
CHROME_SCALE = 1.55
TG_CLICK_MAX_SIDE = 2560
TG_WH_BUDGET = 4200  # 寬+高；點開視窗約 1170×2532，不再衝 10000 讓 TG 砍最長邊
COMPOSE_INNER_W = 1480
THREE_IN_ONE_JPEG_QUALITY = 95
LOOKUP_STRUCTURE_CAPTION = "結構圖（非買訊）　買點只認藍▲紅框"
# 查股單張直式：對齊高低卡 4:5，220DPI → 1920×2400
LOOKUP_PORTRAIT_FIG = (1920 / 220.0, 2400 / 220.0)
LOOKUP_PORTRAIT_DPI = 220
# pane 仍 220DPI 再縮進合成欄＝超採樣，細 K／量柱點開比較不毛
PANE_DPI = 220
_HERE = os.path.dirname(os.path.abspath(__file__))
_BUNDLE_BOLD = os.path.join(_HERE, "fonts", "NotoSansTC-w860.ttf")
_BUNDLE_REG = os.path.join(_HERE, "fonts", "NotoSansTC-w560.ttf")


def _header_quote_bar(
    sid: str,
    db: str,
    official,
    card: Optional[dict],
) -> Tuple[dict, bool, str]:
    """表頭今K／查詢日戳用的價量。

    - 盤中有即時：跟①（`_load_ohlc`／card 合併列）同源，標 is_live。
    - 收盤後：最新官方完整柱（`load_official_ohlc` 末日），不准死釘舊日。
    ②③ 日K／壓撐仍只用 official，不准拿這根盤中假柱去改③。
    """
    official_as_of = ""
    official_bar: dict = {}
    if official is not None and not getattr(official, "empty", True):
        last = official.iloc[-1]
        official_as_of = _dk(last.get("date"))
        prev_close = None
        if len(official) >= 2:
            try:
                prev_close = float(official.iloc[-2].get("close") or 0) or None
            except Exception:
                prev_close = None
        close = float(last.get("close") or 0)
        chg = (close - prev_close) if prev_close else None
        pct = (
            (chg / prev_close * 100.0)
            if (prev_close and chg is not None and prev_close > 0)
            else None
        )
        official_bar = {
            "date": official_as_of,
            "open": float(last.get("open") or 0),
            "high": float(last.get("high") or 0),
            "low": float(last.get("low") or 0),
            "close": close,
            "volume": float(last.get("volume") or 0),
            "prev_close": prev_close,
            "change": chg,
            "pct": pct,
            "source": "official_as_of",
        }

    # 1) 決策卡已帶即時／最新價 → 表頭直接用（與話筒高低卡同源）
    if isinstance(card, dict) and not card.get("error"):
        try:
            close = float(card.get("close") or 0)
        except Exception:
            close = 0.0
        if close > 0:
            is_live = bool(card.get("is_live"))
            as_of = _dk(card.get("latest_date") or card.get("as_of") or "")
            if not as_of:
                as_of = official_as_of
            prev = None
            try:
                prev = float(card.get("prev_close") or 0) or None
            except Exception:
                prev = None
            if not prev and official_bar.get("close") and not is_live:
                prev = official_bar.get("close")
            chg = None
            pct = None
            try:
                if card.get("change") is not None:
                    chg = float(card.get("change"))
            except Exception:
                chg = None
            try:
                raw_pct = card.get("change_pct")
                if raw_pct is None:
                    raw_pct = card.get("pct_change")
                if raw_pct is not None:
                    pct = float(raw_pct)
            except Exception:
                pct = None
            # 盤中％以行情源為準；本地缺完整日柱時 prev 可能對不齊，改由％反推漲跌點
            if pct is not None and abs(float(pct) + 100.0) > 1e-9:
                implied_prev = close / (1.0 + float(pct) / 100.0)
                if chg is None or (
                    prev
                    and abs((prev * (1.0 + float(pct) / 100.0)) - close) / max(close, 1.0) > 0.015
                ):
                    chg = close - implied_prev
                    prev = implied_prev
            elif chg is None and prev and prev > 0:
                chg = close - float(prev)
                pct = chg / float(prev) * 100.0
            try:
                o = float(card.get("open") or 0)
                hi = float(card.get("high") or 0)
                lo = float(card.get("low") or 0)
                vol = float(card.get("volume") or 0)
            except Exception:
                o = hi = lo = vol = 0.0
            return (
                {
                    "date": as_of,
                    "open": o,
                    "high": hi,
                    "low": lo,
                    "close": close,
                    "volume": vol,
                    "prev_close": prev,
                    "change": chg,
                    "pct": pct,
                    "source": "card_live" if is_live else "card_as_of",
                },
                is_live,
                as_of or official_as_of,
            )

    # 2) 與①導航同一條 `_load_ohlc`（可含盤中合併列）
    try:
        from wayne_navigator import _load_ohlc

        nav_df = _load_ohlc(sid, db, 5)
        if nav_df is not None and not nav_df.empty:
            row = nav_df.iloc[-1]
            is_live = bool(row.get("is_live")) if "is_live" in nav_df.columns else False
            as_of = _dk(row.get("date"))
            close = float(row.get("close") or 0)
            prev = None
            if len(nav_df) >= 2:
                try:
                    for j in range(len(nav_df) - 2, -1, -1):
                        rj = nav_df.iloc[j]
                        if "is_live" in nav_df.columns and bool(rj.get("is_live")):
                            continue
                        prev = float(rj.get("close") or 0) or None
                        if prev:
                            break
                except Exception:
                    prev = None
            if not prev and official_bar.get("close"):
                prev = float(official_bar["close"])
            chg = (close - prev) if prev else None
            pct = (
                (chg / prev * 100.0)
                if (prev and chg is not None and prev > 0)
                else None
            )
            if close > 0 and as_of:
                return (
                    {
                        "date": as_of,
                        "open": float(row.get("open") or 0),
                        "high": float(row.get("high") or 0),
                        "low": float(row.get("low") or 0),
                        "close": close,
                        "volume": float(row.get("volume") or 0),
                        "prev_close": prev,
                        "change": chg,
                        "pct": pct,
                        "source": "nav_live" if is_live else "nav_ohlc",
                    },
                    is_live,
                    as_of,
                )
    except Exception:
        pass

    # 3) 退回官方完整柱末日
    return official_bar, False, official_as_of


def _dk(raw) -> str:
    return str(raw or "").replace("-", "")[:8]


def _md_slash(ymd: str) -> str:
    s = _dk(ymd)
    if len(s) >= 8:
        return f"{s[4:6]}/{s[6:8]}"
    return s


def _index_of_date(dates, target: str) -> int:
    t = _dk(target)
    for i, d in enumerate(dates):
        if _dk(d) == t:
            return i
    return -1


def _mark_axvline(ax, x: float, label: str) -> None:
    """Thin vertical marker + small top chip; keep off price digits."""
    from matplotlib.transforms import blended_transform_factory
    from wayne_navigator import _fp

    ax.axvline(x, color=MARK_COLOR, linewidth=1.6, alpha=0.90, zorder=9, linestyle=(0, (4, 2)))
    trans = blended_transform_factory(ax.transData, ax.transAxes)
    ax.text(
        x,
        0.985,
        label,
        transform=trans,
        ha="left",
        va="top",
        fontproperties=_fp(9.0, "bold"),
        color=MARK_COLOR,
        zorder=12,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.18",
            facecolor="#fff3e0",
            edgecolor=MARK_COLOR,
            linewidth=0.9,
            alpha=0.95,
        ),
    )


def _bars_from_official(df, sid: str, name: str) -> list[dict]:
    out: list[dict] = []
    for _, r in df.iterrows():
        halt = False
        try:
            halt = bool(r.get("is_halt"))
        except Exception:
            halt = False
        out.append(
            {
                "date": _dk(r.get("date")),
                "stock_id": sid,
                "stock_name": str(r.get("stock_name") or name),
                "open": float(r.get("open") or r.get("close") or 0),
                "high": float(r.get("high") or r.get("close") or 0),
                "low": float(r.get("low") or r.get("close") or 0),
                "close": float(r.get("close") or 0),
                "volume": float(r.get("volume") or 0),
                "is_halt": halt,
                "pct_change": float(r.get("pct_change") or 0)
                if r.get("pct_change") is not None
                else None,
            }
        )
    return out


def _dash_spike_vline(ax, x: float, *, lw: float = 1.7, z: int = 6) -> None:
    if ax is None:
        return
    ax.axvline(
        float(x),
        color=SPIKE_COLOR,
        linewidth=lw,
        linestyle=SPIKE_DASH,
        alpha=0.92,
        zorder=z,
    )


def _strip_left_edge_arrows(*axes, x_min: float = 0.35) -> int:
    """藏暖窗平移溢到可見窗左緣的箭頭／三角。回傳藏起件數。

    箭頭 tip＝Polygon 第一點（_nav_arrow／_sig_arrow）；用 tip／中心判定。
    """
    from matplotlib.collections import PathCollection
    from matplotlib.patches import Polygon

    xmin = float(x_min)
    n_hide = 0
    for ax in axes:
        if ax is None:
            continue
        for p in list(ax.patches):
            try:
                if not isinstance(p, Polygon):
                    continue
                if not bool(getattr(p, "get_visible", lambda: True)()):
                    continue
                xy = p.get_xy()
                if xy is None or len(xy) < 3:
                    continue
                tip_x = float(xy[0][0])
                xs = [float(v[0]) for v in xy]
                cx = sum(xs) / float(len(xs))
                # 柄／頭任一端還在左緣內都藏（暖窗溢箭）
                if tip_x < xmin or cx < xmin or max(xs) < xmin:
                    p.set_visible(False)
                    n_hide += 1
            except Exception:
                continue
        for coll in list(ax.collections):
            try:
                if not isinstance(coll, PathCollection):
                    continue
                offs = coll.get_offsets()
                if offs is None or len(offs) == 0:
                    continue
                keep = [i for i, (x, _y) in enumerate(offs) if float(x) >= xmin]
                if len(keep) == len(offs):
                    continue
                if not keep:
                    coll.set_visible(False)
                    n_hide += 1
                    continue
                n_hide += len(offs) - len(keep)
                coll.set_offsets(offs[keep])
            except Exception:
                continue
    return n_hide


def _card_emerging(card) -> bool:
    if not isinstance(card, dict):
        return False
    try:
        from wayne_navigator import _card_is_emerging

        return bool(_card_is_emerging(card))
    except Exception:
        return False


def _header_price_chip_style(
    close,
    prev_close=None,
    pct=None,
    *,
    emerging: bool = False,
) -> tuple[str, str, str, bool]:
    """表頭收盤色塊＝高低卡同一套：漲停紅底、跌停綠底；其餘白底＋漲跌字色。

    回傳 (fill, ink, outline, up)。
    """
    from wayne_navigator import quote_limit_chip_colors, quote_limit_side

    try:
        cl = float(close or 0)
    except (TypeError, ValueError):
        cl = 0.0
    prev = None
    try:
        if prev_close not in (None, "", 0, 0.0):
            prev = float(prev_close)
            if prev <= 0:
                prev = None
    except (TypeError, ValueError):
        prev = None
    up = True
    if prev is not None:
        up = cl >= prev
    tone = CANDLE_UP if up else CANDLE_DN
    side = quote_limit_side(cl, prev, pct, emerging=bool(emerging))
    chip = quote_limit_chip_colors(side)
    if chip:
        fill, ink = chip
        return str(fill), str(ink), str(fill), up
    return "#ffffff", tone, tone, up


def _fit_telegram_click_view(im: Image.Image) -> Image.Image:
    """點開用：最長邊 ≤2560，避免 sendPhoto 再壓一次把國字抽糊。"""
    w, h = im.size
    if w <= 0 or h <= 0:
        return im
    long = max(w, h)
    scale = 1.0
    if long > TG_CLICK_MAX_SIDE:
        scale = min(scale, TG_CLICK_MAX_SIDE / float(long))
    if w + h > TG_WH_BUDGET:
        scale = min(scale, TG_WH_BUDGET / float(w + h))
    if long <= TG_CLICK_MAX_SIDE and w + h <= TG_WH_BUDGET:
        return im
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    while max(nw, nh) > TG_CLICK_MAX_SIDE or nw + nh > TG_WH_BUDGET:
        if nw >= nh and nw > 1:
            nw -= 1
        elif nh > 1:
            nh -= 1
        else:
            break
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def _recolor_vol_bar(ax, idx: int, color: str = SPIKE_BAR_COLOR) -> float:
    """把第 idx 根量柱改色；回傳柱高（沒找到回 0）。"""
    if ax is None:
        return 0.0
    h = 0.0
    for p in ax.patches:
        try:
            cx = p.get_x() + p.get_width() / 2.0
            if abs(cx - float(idx)) < 0.45:
                p.set_facecolor(color)
                p.set_edgecolor("#ffffff")
                h = max(h, float(p.get_height()))
        except Exception:
            continue
    return h


def _hide_texts_matching(ax, pred) -> None:
    if ax is None:
        return
    for txt in list(ax.texts):
        try:
            if pred(str(txt.get_text() or "")):
                txt.set_visible(False)
        except Exception:
            continue



@functools.lru_cache(maxsize=48)
def _font(size: int, bold: bool = False):
    """表頭／圖例必須吃 repo 內 NotoSansTC（與高低卡同一套）。

    不准先走系統 TTC、也不准硬編碼 /workspace/assets（Render WORKDIR=/app，
    那條永遠不存在）。缺字會落到 Pillow load_default 點陣，話筒上看起來像亂碼。
    """
    size = max(10, int(size))
    cands: list[str] = []
    if bold:
        cands.append(_BUNDLE_BOLD)
    cands.append(_BUNDLE_REG)
    if bold:
        cands += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        ]
    cands += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in cands:
        if not (p and os.path.isfile(p)):
            continue
        if p.endswith(".ttc"):
            for idx in (3, 2, 0):
                try:
                    return ImageFont.truetype(p, size=size, index=idx)
                except (OSError, ValueError):
                    continue
        else:
            try:
                return ImageFont.truetype(p, size=size)
            except (OSError, ValueError):
                continue
    return ImageFont.load_default()


def _tw(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def _draw_chip(d, x, y, text, *, font, fill, ink, pad_x=16, pad_y=10, radius=8, outline=None, min_w=0, height=None, max_w=None):
    """數字／標籤畫在色塊正中（用 textbbox，不准字落到塊外）。max_w 擋溢欄。"""
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    w = max(int(min_w), int(tw + pad_x * 2))
    if max_w is not None and w > int(max_w):
        # 縮 pad；仍超就裁字尾加…（表頭四欄不准互壓）
        pad_x = max(8, int(pad_x * 0.7))
        w = max(int(min_w), int(tw + pad_x * 2))
        if w > int(max_w):
            w = int(max_w)
            # 二分找塞得進的字
            lo, hi = 1, len(text)
            fit = "…"
            while lo <= hi:
                mid = (lo + hi) // 2
                cand = text[:mid].rstrip() + ("…" if mid < len(text) else "")
                cw = d.textbbox((0, 0), cand, font=font)
                if (cw[2] - cw[0]) + pad_x * 2 <= w:
                    fit = cand
                    lo = mid + 1
                else:
                    hi = mid - 1
            text = fit
            bb = d.textbbox((0, 0), text, font=font)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
    h = int(height) if height else int(th + pad_y * 2)
    d.rounded_rectangle(
        [x, y, x + w, y + h],
        radius=radius,
        fill=fill,
        outline=outline or fill,
        width=2,
    )
    tx = x + (w - tw) / 2.0 - bb[0]
    ty = y + (h - th) / 2.0 - bb[1]
    d.text((tx, ty), text, fill=ink, font=font)
    return w, h


def _canon_candle_col(col: str) -> str:
    s = str(col or "").lower()
    if s in (CANDLE_UP, "#e53935", "#d32f2f", "#ef5350", "#c62828"):
        return CANDLE_UP
    if s in (CANDLE_DN, "#00897b", "#26a69a", "#00897b", "#43a047"):
        return CANDLE_DN
    # 偏紅＝漲、其餘當跌
    try:
        h = s[1:] if s.startswith("#") and len(s) >= 7 else ""
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return CANDLE_UP if r > g + 20 else CANDLE_DN
    except Exception:
        return CANDLE_DN


def _wick_col(body: str) -> str:
    return WICK_UP if _canon_candle_col(body) == CANDLE_UP else WICK_DN


def _unique(prefix: str) -> str:
    ts = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%dT%H%M%S")
    return os.path.join(tempfile.gettempdir(), f"{prefix}-{ts}.png")


def _crop_frac(im: Image.Image, top: float, bottom: float) -> Image.Image:
    w, h = im.size
    y0 = max(0, int(h * top))
    y1 = min(h, int(h * bottom))
    return im.crop((0, y0, w, y1)).convert("RGB")


def _crop_below_main_spine(im: Image.Image, *, min_top: float = 0.012) -> tuple[Image.Image, int]:
    """②裁掉結構縮圖／頭牌：從主 K 上框線裁。回傳 (圖, 裁掉的上緣像素)。"""
    import numpy as np

    arr = np.asarray(im.convert("RGB"))
    h, w = arr.shape[:2]
    lum = arr.astype(np.float32).mean(axis=2)
    x0, x1 = int(w * 0.12), int(w * 0.88)
    dark = (lum[:, x0:x1] < 90).mean(axis=1)
    y_start = int(h * float(min_top))
    for y in range(y_start, int(h * 0.55)):
        if dark[y] >= 0.35:
            top = max(0, y - 2)
            return im.crop((0, top, w, h)).convert("RGB"), top
    top = int(h * 0.348)
    return _crop_frac(im, 0.348, 1.0), top


def _crop_white_tail(im: Image.Image, *, pad: int = 10, keep_min: int = 28) -> Image.Image:
    """裁掉日期下方大片留白；保留刻度字。"""
    import numpy as np

    arr = np.asarray(im.convert("RGB"))
    h, w = arr.shape[:2]
    if h <= keep_min:
        return im
    lum = arr.astype(np.float32).mean(axis=2)
    content = (lum < 248).mean(axis=1) > 0.012
    ys = np.where(content)[0]
    if len(ys) == 0:
        return im
    last = min(h, int(ys[-1]) + int(pad))
    last = max(int(keep_min), last)
    if last >= h - 2:
        return im
    return im.crop((0, 0, w, last)).convert("RGB")


def _detect_plot_frames(im: Image.Image) -> list[tuple[int, int]]:
    """找出上下堆疊的 K／量能／成交量外框（top, bottom）像素列。"""
    import numpy as np

    arr = np.asarray(im.convert("RGB"))
    h, w = arr.shape[:2]
    lum = arr.astype(np.float32).mean(axis=2)
    x0, x1 = int(w * 0.12), int(w * 0.88)
    dark = (lum[:, x0:x1] < 90).mean(axis=1)
    ys = np.where(dark > 0.22)[0]
    lines: list[int] = []
    if len(ys):
        s = prev = int(ys[0])
        for y in ys[1:]:
            y = int(y)
            if y - prev > 3:
                if prev - s + 1 <= 8:
                    lines.append((s + prev) // 2)
                s = y
            prev = y
        if prev - s + 1 <= 8:
            lines.append((s + prev) // 2)
    frames: list[tuple[int, int]] = []
    i = 0
    while i < len(lines) - 1:
        top = lines[i]
        found = None
        for j in range(i + 1, len(lines)):
            bot = lines[j]
            hh = bot - top
            if hh < 55:
                continue
            if hh > 1800:
                break
            # 橫向框線已跨圖寬；中間短距是區隔，下一條夠高就是框底
            found = bot
            break
        if found is not None:
            frames.append((top, found))
            while i < len(lines) and lines[i] <= found:
                i += 1
        else:
            i += 1
    if len(frames) >= 4 and (frames[0][1] - frames[0][0]) < 80:
        frames = frames[1:]
    return frames


def _rebuild_zones(
    im: Image.Image,
    frames: list[tuple[int, int]],
    target_hs: list[int],
    *,
    gaps: list[int] | None = None,
) -> Image.Image:
    """只拉伸對應的 K／量能／成交量框，頭尾日期與留白不跟整張硬拉。"""
    if not frames or not target_hs or len(frames) < len(target_hs):
        return im
    frames = frames[-len(target_hs) :]
    w, h = im.size
    pieces: list[Image.Image] = []
    y = 0
    for idx, ((top, bot), th) in enumerate(zip(frames, target_hs)):
        if top > y:
            gap = im.crop((0, y, w, top))
            if gaps is not None and idx > 0 and (idx - 1) < len(gaps):
                gh = max(4, int(gaps[idx - 1]))
                if gap.height != gh:
                    gap = gap.resize((w, gh), Image.Resampling.LANCZOS)
            pieces.append(gap)
        band = im.crop((0, top, w, bot + 1))
        th = max(20, int(th))
        # 差不到 6% 就不拉：LANCZOS 微縮會把細 K／影線拉成殘破
        if band.height != th:
            if abs(band.height - th) / float(th) < 0.06:
                th = band.height
            else:
                band = band.resize((w, th), Image.Resampling.LANCZOS)
        pieces.append(band)
        y = bot + 1
    if y < h:
        pieces.append(_crop_white_tail(im.crop((0, y, w, h))))
    out_h = sum(p.height for p in pieces)
    out = Image.new("RGB", (w, out_h), "#ffffff")
    yy = 0
    for p in pieces:
        out.paste(p, (0, yy))
        yy += p.height
    return _crop_white_tail(out)


def _fit_w(im: Image.Image, width: int) -> Image.Image:
    if im.width == width:
        return im
    h = max(1, int(round(im.height * (width / im.width))))
    return im.resize((width, h), Image.Resampling.LANCZOS)


def _match_zone_heights_to_nav(
    fitted: list[Image.Image],
    zones: list[list[tuple[int, int]]] | None = None,
) -> list[Image.Image]:
    """對齊①三區外框高度：主K／量能訊號／日成交量。②沒有量能列，只對主K＋成交量，不准整張拉成跟①一樣高。"""
    if len(fitted) < 3:
        return fitted
    nav, st, vol = fitted[0], fitted[1], fitted[2]
    zlist = zones or [None, None, None]
    nf = sorted(list(zlist[0] or []), key=lambda t: t[0])
    sf = sorted(list(zlist[1] or []), key=lambda t: t[0])
    vf = sorted(list(zlist[2] or []), key=lambda t: t[0])
    if len(nf) < 3:
        nf = _detect_plot_frames(nav)
    if len(sf) < 2:
        sf = _detect_plot_frames(st)
    if len(vf) < 3:
        vf = _detect_plot_frames(vol)
    print(
        f"[zones] nav={[(a, b, b - a + 1) for a, b in nf]} "
        f"st={[(a, b, b - a + 1) for a, b in sf]} "
        f"vol={[(a, b, b - a + 1) for a, b in vf]}",
        flush=True,
    )
    if len(nf) < 3:
        return [nav, _crop_white_tail(st), _crop_white_tail(vol)]
    k_h = nf[0][1] - nf[0][0] + 1
    sig_h = nf[1][1] - nf[1][0] + 1
    vol_h = nf[2][1] - nf[2][0] + 1
    nav_gaps = [nf[1][0] - nf[0][1] - 1, nf[2][0] - nf[1][1] - 1]
    st2 = _rebuild_zones(st, sf, [k_h, vol_h]) if len(sf) >= 2 else _crop_white_tail(st)
    vol2 = (
        _rebuild_zones(vol, vf, [k_h, sig_h, vol_h], gaps=nav_gaps)
        if len(vf) >= 3
        else _crop_white_tail(vol)
    )
    print(
        f"[zones] target k/sig/vol=({k_h},{sig_h},{vol_h}) "
        f"out st={st2.size} vol={vol2.size} nav={nav.size}",
        flush=True,
    )
    return [nav, st2, vol2]


def _ax_spine_frac(ax) -> tuple[float, float] | None:
    """回傳主軸在 figure 裡的 left/right 比例（0–1）。"""
    if ax is None:
        return None
    try:
        pos = ax.get_position()
        return float(pos.x0), float(pos.x1)
    except Exception:
        return None


def _ax_box_frac(ax) -> dict | None:
    """軸在 figure 的比例框（y0 下／y1 上，原點在下）。"""
    if ax is None:
        return None
    try:
        pos = ax.get_position()
        return {
            "x0": float(pos.x0),
            "x1": float(pos.x1),
            "y0": float(pos.y0),
            "y1": float(pos.y1),
        }
    except Exception:
        return None


def _fracs_to_px(
    fracs: list[dict | None],
    img_h: int,
    crop_top: int,
    crop_bot: int,
) -> list[tuple[int, int]]:
    """figure 比例 → 裁切後影像的 (top, bottom)。"""
    out: list[tuple[int, int]] = []
    ch = max(1, int(crop_bot) - int(crop_top))
    for fr in fracs or []:
        if not fr:
            continue
        yt = int(round((1.0 - float(fr["y1"])) * img_h)) - int(crop_top)
        yb = int(round((1.0 - float(fr["y0"])) * img_h)) - int(crop_top)
        yt = max(0, min(ch - 8, yt))
        yb = max(yt + 20, min(ch, yb))
        out.append((yt, yb))
    return out


def _scale_zones(
    zones: list[tuple[int, int]], old_h: int, new_h: int
) -> list[tuple[int, int]]:
    if not zones or old_h <= 0 or new_h == old_h:
        return list(zones or [])
    r = float(new_h) / float(old_h)
    return [(int(round(a * r)), int(round(b * r))) for a, b in zones]


def _ax_frame_h_px(ax) -> float:
    """軸外框高度（像素）＝整條量能區框架，不是箭頭。"""
    if ax is None:
        return 0.0
    try:
        fig = ax.figure
        fig.canvas.draw()
        return float(ax.get_window_extent().height)
    except Exception:
        return 0.0


def _match_sig_frame_height(fig, target_px: float) -> dict:
    """把③量能訊號整框（ax_sig bbox）對到①同像素高；列高＋箭頭視覺一致。"""
    out = {"target_px": float(target_px or 0), "before": None, "after": None}
    if fig is None or not target_px or target_px < 20:
        return out
    ax1, ax_sig, ax2 = _pick_vol_axes(fig)
    if ax1 is None or ax_sig is None:
        return out
    try:
        fig.canvas.draw()
        pos = ax_sig.get_position()
        p1 = ax1.get_position()
        p2 = ax2.get_position() if ax2 is not None else None
        fig_h = float(fig.bbox.height) or 1.0
        before = float(ax_sig.get_window_extent().height)
        out["before"] = before
        # 至少跟①一樣高；若本來更矮就抬到 target
        need_px = max(float(target_px), before)
        new_h = need_px / fig_h
        old_h = float(pos.height)
        if new_h < 0.02:
            out["after"] = before
            return out
        if new_h <= old_h + 0.002 and before >= target_px - 2:
            out["after"] = before
            return out
        # 往上吃 K 區空間；量柱底邊不動
        grow = new_h - old_h
        ax_sig.set_position([pos.x0, pos.y0, pos.width, new_h])
        new_ax1_y0 = float(p1.y0) + grow
        new_ax1_h = float(p1.height) - grow
        if new_ax1_h > 0.18:
            ax1.set_position([p1.x0, new_ax1_y0, p1.width, new_ax1_h])
        fig.canvas.draw()
        out["after"] = float(ax_sig.get_window_extent().height)
        out["grew"] = grow
        if p2 is not None:
            out["vol_y0"] = float(p2.y0)
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _thin_stagger_date_ticks(
    ax, tick_pos, tick_labs, *, min_gap: float = 5.0, protect=()
) -> tuple[list, list]:
    """底軸日期去重＋錯層。窗起／爆大量／末日／演算不准被「×月」吃掉。"""
    from wayne_navigator import _set_staggered_month_ticks

    if ax is None or not tick_pos:
        return [], []
    prot = {str(x) for x in (protect or ()) if x}
    pairs = sorted(
        ((float(p), str(l)) for p, l in zip(tick_pos, tick_labs) if str(l)),
        key=lambda t: t[0],
    )
    kept: list[tuple[float, str]] = []
    for pos, lab in pairs:
        if not kept:
            kept.append((pos, lab))
            continue
        prev_p, prev_l = kept[-1]
        if abs(pos - prev_p) >= float(min_gap):
            kept.append((pos, lab))
            continue
        prev_prot = prev_l in prot or ("/" in prev_l and not prev_l.endswith("月"))
        cur_prot = lab in prot or ("/" in lab and not lab.endswith("月"))
        if cur_prot and not prev_prot:
            kept[-1] = (pos, lab)
        elif prev_prot and cur_prot:
            kept.append((pos, lab))  # 兩顆關鍵日都留，交給錯層
        elif prev_prot and not cur_prot:
            continue
        else:
            kept[-1] = (pos, lab)
    for txt in list(ax.texts):
        try:
            s = str(txt.get_text() or "")
            if s.endswith("月") or ("/" in s and len(s) <= 8) or s == "演算":
                if float(txt.get_position()[1]) < 0.25:
                    txt.set_visible(False)
        except Exception:
            continue
    ax.tick_params(axis="x", labelbottom=False)
    ax.set_xticklabels([])
    for t in ax.get_xticklabels():
        t.set_visible(False)
        try:
            t.set_text("")
        except Exception:
            pass
    pos_out = [p for p, _ in kept]
    lab_out = [l for _, l in kept]
    _set_staggered_month_ticks(ax, lab_out, pos_out, compact=False)
    return pos_out, lab_out


def _force_y_right_only(ax, *, ylabel: str | None = None) -> None:
    """成交量／價軸數字只留右手邊（不准左右兩邊都印）；框線加深跟①一致。"""
    if ax is None:
        return
    try:
        from wayne_navigator import _fp

        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.tick_params(
            axis="y",
            labelleft=False,
            labelright=True,
            left=False,
            right=True,
            length=5,
            width=0.8,
        )
        if ylabel is not None:
            ax.set_ylabel(ylabel, fontproperties=_fp(10.5, "bold"), color="#37474f")
        ax.yaxis.set_ticks_position("right")
        # 左右框線加粗加深，合成後跟①黑框同一視覺重量
        for side in ("left", "right", "top", "bottom"):
            sp = ax.spines.get(side)
            if sp is not None:
                sp.set_visible(True)
                sp.set_linewidth(1.35)
                sp.set_color("#212121")
    except Exception:
        pass


def _pane_spine_lr(im: Image.Image, *, top_skip: float = 0.12, bot_skip: float = 0.08):
    """偵測圖框左右豎線（matplotlib spine）。

    規則：左側先是大片白／淺底，再遇到連續深灰豎線，右側立刻有格線／K／量；
    不准把壓／撐色標、橘虛線、箭頭當成框線。
    """
    import numpy as np

    arr = np.asarray(im.convert("RGB"))
    h, w = arr.shape[:2]
    y0 = max(0, int(h * top_skip))
    y1 = min(h, int(h * (1.0 - bot_skip)))
    if y1 <= y0 + 20 or w < 80:
        return 0, w - 1
    band = arr[y0:y1]
    lum = band.astype(np.float32).mean(axis=2)
    # 框線＝深黑到中灰的豎線
    spine = ((lum < 145) & (lum > 20)).mean(axis=0)
    near_white = (lum > 242).mean(axis=0)
    R = band[:, :, 0].astype(int)
    G = band[:, :, 1].astype(int)
    B = band[:, :, 2].astype(int)
    # 真 K／量：紅漲／青綠跌；排除洋紅壓標（R、B 都高）
    candle = ((R > 170) & (G < 120) & (B < 120) & (R > B + 40) & (R > G + 40)) | (
        (G > 90) & (G > R + 20) & (B < 160) & (R < 140)
    )
    content = candle.any(axis=0) | ((lum < 230) & (lum > 150)).any(axis=0)

    def _left_spine() -> int | None:
        for x in range(36, max(37, w // 2)):
            if spine[x] < 0.28:
                continue
            left_white = float(near_white[max(0, x - 48) : x].mean()) if x > 8 else 0.0
            right_has = bool(content[x + 1 : min(w, x + 55)].any()) if x + 1 < w else False
            # 左白（或軸外標籤帶可略髒）＋右有圖
            if left_white >= 0.45 and right_has:
                return int(x)
            if spine[x] >= 0.55 and right_has and left_white >= 0.25:
                return int(x)
        return None

    def _right_spine() -> int | None:
        for x in range(w - 36, w // 2, -1):
            if spine[x] < 0.28:
                continue
            right_white = float(near_white[x + 1 : min(w, x + 48)].mean()) if x + 1 < w else 0.0
            left_has = bool(content[max(0, x - 55) : x].any())
            if right_white >= 0.35 and left_has:
                return int(x)
            if spine[x] >= 0.55 and left_has and right_white >= 0.20:
                return int(x)
        return None

    L = _left_spine()
    R = _right_spine()
    if L is None or R is None or R <= L + 40:
        xs = np.where(candle.any(axis=0))[0]
        # 略過最左色標帶
        xs = xs[xs > 100] if len(xs) else xs
        if len(xs) < 8:
            ink = ~((R > 246) & (G > 246) & (B > 246))
            xs = np.where(ink.any(axis=0))[0]
            xs = xs[xs > 80] if len(xs) else xs
        if len(xs) < 2:
            return 0, w - 1
        return int(xs[0]), int(xs[-1])
    return int(L), int(R)


def _candle_content_lr(im: Image.Image, x0: int, x1: int) -> tuple[int, int]:
    """框線內真 K／量柱左右緣（略過洋紅壓標）。"""
    import numpy as np

    arr = np.asarray(im.convert("RGB"))
    h, w = arr.shape[:2]
    x0 = max(0, min(w - 2, int(x0)))
    x1 = max(x0 + 2, min(w, int(x1)))
    y0 = max(0, int(h * 0.14))
    y1 = min(h, int(h * 0.92))
    band = arr[y0:y1, x0:x1]
    R = band[:, :, 0].astype(int)
    G = band[:, :, 1].astype(int)
    B = band[:, :, 2].astype(int)
    candle = ((R > 170) & (G < 120) & (B < 120) & (R > B + 40) & (R > G + 40)) | (
        (G > 90) & (G > R + 20) & (B < 160) & (R < 140)
    )
    xs = np.where(candle.any(axis=0))[0]
    if len(xs) < 8:
        lum = band.astype(np.float32).mean(axis=2)
        xs = np.where((lum < 235).any(axis=0))[0]
    if len(xs) < 2:
        return x0, x1 - 1
    return x0 + int(xs[0]), x0 + int(xs[-1])


def _align_panes_to_nav_frame(
    fitted: list[Image.Image],
    spine_fracs: dict | None = None,
) -> list[Image.Image]:
    """以①左右框線為範本：只對齊外框，框內整塊貼上。不准再把 K 柱橫向拉开（會殘破）。"""
    if len(fitted) < 3:
        return fitted
    ref = fitted[0]
    keys = ("nav", "struct", "vol")
    fracs = spine_fracs or {}

    def _spine_for(im: Image.Image, key: str) -> tuple[int, int]:
        fr = fracs.get(key) if isinstance(fracs, dict) else None
        fb = (int(round(im.width * FRAME_LEFT)), int(round(im.width * FRAME_RIGHT)))
        if fr and len(fr) == 2 and 0.02 < float(fr[0]) < float(fr[1]) < 0.99:
            return int(round(im.width * float(fr[0]))), int(round(im.width * float(fr[1])))
        det = _pane_spine_lr(im)
        L = det[0] if abs(det[0] - fb[0]) <= 100 else fb[0]
        R = det[1] if abs(det[1] - fb[1]) <= 100 else fb[1]
        return (fb if R <= L + 40 else (L, R))

    rl, rr = _spine_for(ref, keys[0])
    print(f"[align] ref spine=({rl},{rr}) (no content-stretch)", flush=True)
    out = [fitted[0]]
    for idx, (im, key) in enumerate(zip(fitted[1:], keys[1:]), start=2):
        if im.width != ref.width:
            im = _fit_w(im, ref.width)
        ml, mr = _spine_for(im, key)
        print(f"[align] pane{idx}/{key} spine=({ml},{mr})", flush=True)
        w, h = im.size
        canvas = Image.new("RGB", (w, h), "#ffffff")
        if ml > 0:
            left = im.crop((0, 0, ml, h)).resize((max(1, rl), h), Image.Resampling.LANCZOS)
            canvas.paste(left, (0, 0))
        if mr + 1 < w:
            right = im.crop((mr + 1, 0, w, h))
            r_w = max(1, w - rr - 1)
            right = right.resize((r_w, h), Image.Resampling.LANCZOS)
            canvas.paste(right, (rr + 1, 0))
        # 框內整塊等比貼到①框，不准只抓「有色柱」再拉開
        inner = im.crop((ml, 0, mr + 1, h)).resize(
            (max(1, rr - rl + 1), h), Image.Resampling.LANCZOS
        )
        canvas.paste(inner, (rl, 0))
        out.append(canvas)
    return out


def _mark_axvline_at(ax, x: float, label: str, y: float = 0.985) -> None:
    """③窗起 chip; y 可下移避開壓標。"""
    from matplotlib.transforms import blended_transform_factory
    from wayne_navigator import _fp

    ax.axvline(x, color=MARK_COLOR, linewidth=1.6, alpha=0.90, zorder=9, linestyle=(0, (4, 2)))
    trans = blended_transform_factory(ax.transData, ax.transAxes)
    ax.text(
        x + 0.8,
        y,
        label,
        transform=trans,
        ha="left",
        va="top",
        fontproperties=_fp(9.0, "bold"),
        color=MARK_COLOR,
        zorder=12,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.18",
            facecolor="#fff3e0",
            edgecolor=MARK_COLOR,
            linewidth=0.9,
            alpha=0.95,
        ),
    )


def _pick_vol_axes(fig):
    """price / momentum / volume：用上下位置，不准用 ymax>1500。

    高價股（台光電／大立光／聯亞）價軸 ymax 也 >1500，舊啟發式會把價軸
    當成量軸，③ 量柱區對錯框再被 crop_white_tail 當留白裁掉。
    """
    live = [ax for ax in list(getattr(fig, "axes", []) or []) if ax.axison]
    if not live:
        return None, None, None
    ordered = sorted(
        live,
        key=lambda ax: -float(ax.get_position().y0 + ax.get_position().height * 0.5),
    )
    sig = None
    price_vol: list = []
    for ax in ordered:
        try:
            pos_h = float(ax.get_position().height)
        except Exception:
            pos_h = 1.0
        if pos_h < 0.028:
            continue
        ymin, ymax = ax.get_ylim()
        span = float(ymax) - float(ymin)
        if ymin >= -1.5 and ymax <= 2.8 and span <= 4.5:
            sig = ax
            continue
        price_vol.append(ax)
    price = price_vol[0] if price_vol else None
    vol = price_vol[-1] if len(price_vol) >= 2 else None
    if price is None and live:
        price = max(
            live,
            key=lambda ax: abs((ax.bbox.y1 - ax.bbox.y0) * (ax.bbox.x1 - ax.bbox.x0)),
        )
    return price, sig, vol


def _polish_vol_figure(
    fig,
    *,
    first_i: int = 0,
    first_k: str,
    spike_i: int,
    spike_md: str,
    spike_lots: int,
    spike_hi: float,
    spike_lo: float,
    tick_labs=None,
    tick_pos=None,
    last_bar=None,
    bars=None,
    zone_date: str = "",
):
    """圖三：壓撐標移橘虛線左、爆大量張數、量柱日期刻度、當日走勢標（非死釘壓價）。"""
    from wayne_navigator import _fp, _fmt_price, _set_staggered_month_ticks
    import vol_zone_chart as vz

    ax1, ax_sig, ax2 = _pick_vol_axes(fig)
    if ax1 is None:
        return
    for ax in fig.axes:
        for txt in list(ax.texts):
            s = str(txt.get_text() or "")
            if (
                s.startswith("爆大量")
                or s.startswith("③窗起")
                or s.startswith("大量區壓")
                or s.startswith("大量區撐")
                or s.startswith("壓 ")
                or s.startswith("撐 ")
                or ("測壓" in s)
                or ("未過" in s and "高" in s)
            ):
                txt.set_visible(False)
    x0 = float(first_i if first_i is not None and first_i >= 0 else 0)
    # 左右框跟①：只微調 xlim，不准拉出大片空白（壓撐標改放軸外）
    x_right = ax1.get_xlim()[1]
    ax1.set_xlim(-0.55, x_right)
    for ax in (ax_sig, ax2):
        if ax is not None:
            ax.set_xlim(-0.55, x_right)

    lab = f"{MARK_LABEL} {first_k[4:6]}/{first_k[6:8]}" if len(first_k) >= 8 else f"{MARK_LABEL} {first_k}"
    _mark_axvline_at(ax1, x0, lab, y=0.90)
    for ax in (ax_sig, ax2):
        if ax is None:
            continue
        ax.axvline(x0, color=MARK_COLOR, lw=1.4, ls=(0, (4, 2)), zorder=9, alpha=0.8)

    # 壓／撐標：貼框內左側（連水平線）；框變寬後標籤在脊線右側，完整「壓／撐＋數字」
    tag_box = dict(boxstyle="round,pad=0.28", facecolor="#ffffff", linewidth=1.15, alpha=0.96)
    x_left = float(ax1.get_xlim()[0]) + 0.35
    for y_val, name, col in (
        (float(spike_hi), f"壓 {_fmt_price(spike_hi)}", vz._PRESS),
        (float(spike_lo), f"撐 {_fmt_price(spike_lo)}", vz._HOLD),
    ):
        ax1.annotate(
            name,
            xy=(x_left, y_val),
            xytext=(VZ_TAG_X_OFFSET, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontproperties=_fp(vz.VOL_ZONE_TAG_PT, "bold"),
            color=col,
            zorder=12,
            clip_on=False,
            alpha=1.0,
            arrowprops=dict(arrowstyle="-", color=col, lw=1.8, shrinkA=0, shrinkB=0),
            bbox={**tag_box, "edgecolor": col},
        )

    # 先藏產品實線爆大量豎線，改畫橘黃虛線（K／動能／量連起來）
    from matplotlib.colors import to_hex

    for ax in (ax1, ax_sig, ax2):
        if ax is None:
            continue
        for line in list(ax.lines):
            try:
                xd = line.get_xdata()
                if len(xd) < 2:
                    continue
                if abs(float(xd[0]) - float(spike_i)) > 0.08:
                    continue
                if abs(float(xd[0]) - float(xd[-1])) > 0.08:
                    continue
                try:
                    hx = to_hex(line.get_color()).lower()
                except Exception:
                    hx = str(line.get_color() or "").lower()
                # 凡是爆大量日那條豎線，一律改橘黃虛線（不准實線）
                if hx in ("#f9a825", "#ffc107", "#ffb300", str(vz._SPIKE).lower(), SPIKE_COLOR.lower()):
                    line.set_linestyle(SPIKE_DASH)
                    line.set_color(SPIKE_COLOR)
                    line.set_linewidth(1.85)
                    line.set_alpha(0.92)
                    continue
            except Exception:
                continue
        _dash_spike_vline(ax, spike_i, lw=1.85)

    # K 上：爆大量日標放在桃色帶中段、黃線左側，避開測壓與撐
    ax1.annotate(
        f"爆大量 {spike_md}",
        xy=(float(spike_i), float(spike_hi)),
        xytext=(float(spike_i) - 16.0, (float(spike_hi) + float(spike_lo)) / 2.0),
        textcoords="data",
        ha="right",
        va="center",
        fontproperties=_fp(11.5, "bold"),
        color="#5d4037",
        zorder=14,
        clip_on=False,
        arrowprops=dict(arrowstyle="->", color="#f9a825", lw=1.2, shrinkB=2),
        bbox=dict(
            boxstyle="round,pad=0.22",
            facecolor="#fffde7",
            edgecolor="#f9a825",
            linewidth=0.9,
            alpha=0.96,
        ),
    )

    if ax2 is not None:
        bar_h = None
        for p in ax2.patches:
            try:
                cx = p.get_x() + p.get_width() / 2.0
                if abs(cx - float(spike_i)) < 0.45:
                    bar_h = max(bar_h or 0.0, float(p.get_height()))
            except Exception:
                continue
        if bar_h and bar_h > 0:
            ax2.set_ylim(0, bar_h * 1.28)
            spike_h = bar_h
        else:
            ymax = ax2.get_ylim()[1]
            ax2.set_ylim(0, max(ymax / 1.30 * 1.12, 1.0))
            spike_h = ax2.get_ylim()[1] * 0.88
        ax2.annotate(
            f"爆大量 {spike_md}　{spike_lots:,}張",
            xy=(float(spike_i), float(spike_h)),
            xytext=(-28, 6),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontproperties=_fp(11.0, "bold"),
            color="#5d4037",
            zorder=15,
            clip_on=False,
            arrowprops=dict(arrowstyle="->", color="#f9a825", lw=1.15, shrinkB=1.5),
            bbox=dict(
                boxstyle="round,pad=0.20",
                facecolor="#fffde7",
                edgecolor="#f9a825",
                linewidth=0.95,
                alpha=0.97,
            ),
        )
        # 量軸數字／「日成交量（張）」只留右手邊（不准左右兩邊都印）
        _force_y_right_only(ax2, ylabel="日成交量（張）")
        ax2.tick_params(axis="y", labelsize=10, labelbottom=True)
        for lab_t in ax2.get_yticklabels():
            lab_t.set_fontproperties(_fp(10, "bold"))
            lab_t.set_visible(True)
        # 價軸也只留右邊，跟①同一讀法（避免左軸把框線擠歪）
        _force_y_right_only(ax1)
        fr = _ax_spine_frac(ax1)
        if fr:
            # 由呼叫端寫入 ctx；此函式無 ctx 時略過
            pass
        # 量柱下方日期：去重＋錯層（06/12／09/23／10/02 不准跟「×月」互壓）
        if tick_labs and tick_pos:
            for txt in list(ax2.texts):
                s = str(txt.get_text() or "")
                if s.endswith("月") or ("/" in s and len(s) <= 8):
                    try:
                        if float(txt.get_position()[1]) < 0.25:
                            txt.set_visible(False)
                    except Exception:
                        txt.set_visible(False)
            _thin_stagger_date_ticks(
                ax2, list(tick_pos), list(tick_labs), min_gap=6.0,
                protect=(tick_labs[0] if tick_labs else "", spike_md, tick_labs[-1] if tick_labs else ""),
            )
        ax1.tick_params(labelbottom=False)
        if ax_sig is not None:
            ax_sig.tick_params(labelbottom=False)

    for ax in fig.axes:
        for txt in list(ax.texts):
            s = str(txt.get_text() or "")
            # 月線／季線標必須留；先前誤藏
            if s in ("月線", "季線"):
                txt.set_visible(True)
                txt.set_alpha(1.0)

    # 再清一次左溢箭頭（overlay 之後可能還殘；掃整張 fig 所有軸）
    try:
        # 除錯：左緣可見箭 tip
        from matplotlib.patches import Polygon as _Poly

        tips = []
        for ax in list(fig.axes):
            for p in list(ax.patches):
                try:
                    if not isinstance(p, _Poly):
                        continue
                    if not bool(getattr(p, "get_visible", lambda: True)()):
                        continue
                    xy = p.get_xy()
                    if xy is None or len(xy) < 3:
                        continue
                    tip_x = float(xy[0][0])
                    if tip_x < 40:
                        tips.append(round(tip_x, 2))
                except Exception:
                    continue
        tips.sort()
        print(f"[strip-left] before tips<40={tips[:24]} n={len(tips)}", flush=True)
        # 只藏暖窗溢到 x<0 的箭；可見窗內量能紅底必須留紅三角
        n_hide = _strip_left_edge_arrows(ax1, ax_sig, x_min=-0.20)
        tips2 = []
        for ax in list(fig.axes):
            for p in list(ax.patches):
                try:
                    if not isinstance(p, _Poly):
                        continue
                    if not bool(getattr(p, "get_visible", lambda: True)()):
                        continue
                    xy = p.get_xy()
                    if xy is None or len(xy) < 3:
                        continue
                    tip_x = float(xy[0][0])
                    if tip_x < 40:
                        tips2.append(round(tip_x, 2))
                except Exception:
                    continue
        tips2.sort()
        print(
            f"[strip-left] hid={n_hide} x_min=-0.20 after tips<40={tips2[:24]} n={len(tips2)}",
            flush=True,
        )
    except Exception as exc:
        print(f"[strip-left] FAIL {exc!r}", flush=True)

    # 當日走勢標：官方／MIS 今開高低收對既有大量壓撐組句，不准死釘「10/05 壓 3,255」
    lb = last_bar or {}
    try:
        from matplotlib.patches import FancyArrowPatch
        from vol_zone_chart import vol_zone_day_path_label

        last_hi = float(lb.get("high") or 0)
        last_lo = float(lb.get("low") or 0)
        last_cl = float(lb.get("close") or 0)
        last_i = lb.get("_i")
        press = float(spike_hi)
        hold = float(spike_lo)
        msg = vol_zone_day_path_label(
            press, hold, lb, bars=bars, zone_date=zone_date
        )
        if last_i is not None and last_hi > 0 and press > 0 and msg:
            ymin, ymax = ax1.get_ylim()
            # 標放在壓／撐帶中段、最後一根左側，不准再釘右上角死標
            band_mid = (press + hold) / 2.0 if press > hold else (ymin + ymax) / 2.0
            y_lab = min(max(band_mid, ymin + (ymax - ymin) * 0.18), ymax - (ymax - ymin) * 0.12)
            x_lab = float(last_i) - 8.0
            x_lab = max(x_lab, float(ax1.get_xlim()[0]) + 5.0)
            bits = [p for p in msg.split("  ") if p]
            if len(bits) >= 3:
                shown = f"{bits[0]}  {bits[1]}\n{'  '.join(bits[2:])}"
            else:
                shown = "\n".join(bits) if bits else msg
            tag = "日說明"
            ax1.axvline(
                float(last_i),
                color=CEYA_LINE_COLOR,
                linewidth=1.55,
                linestyle=(0, (3.2, 2.0)),
                alpha=0.90,
                zorder=8,
            )
            ax1.text(
                x_lab,
                y_lab,
                shown,
                ha="right",
                va="center",
                fontproperties=_fp(11.0, "bold"),
                color=CEYA_LINE_COLOR,
                zorder=32,
                clip_on=False,
                linespacing=1.18,
                bbox=dict(
                    boxstyle="round,pad=0.30",
                    facecolor="#e3f2fd",
                    edgecolor=CEYA_LINE_COLOR,
                    linewidth=1.35,
                    alpha=0.99,
                ),
            )
            tip_y = float(last_lo) if "撐" in tag else float(min(last_hi, press - 1.0) if last_hi else last_cl)
            if tip_y <= 0:
                tip_y = last_cl or last_hi
            arr = FancyArrowPatch(
                (x_lab + 1.2, y_lab - (ymax - ymin) * 0.02),
                (float(last_i) - 0.45, tip_y),
                arrowstyle="->",
                mutation_scale=10,
                color=CEYA_LINE_COLOR,
                lw=1.35,
                zorder=31,
                clip_on=False,
            )
            ax1.add_patch(arr)
            print(
                f"[last-bar] {tag} i={last_i} hi={last_hi} lo={last_lo} cl={last_cl} "
                f"press={press} hold={hold} msg={msg}",
                flush=True,
            )
    except Exception as exc:
        print(f"[last-bar] FAIL {exc!r} lb={lb}", flush=True)

    # 強制重畫月線／季線標（產品左標常被藏／壓住／只剩一條）
    try:
        from matplotlib.colors import to_hex
        import vol_zone_chart as _vz

        for txt in list(ax1.texts):
            s = str(txt.get_text() or "")
            if s in ("月線", "季線"):
                txt.set_visible(False)
        ma20_y = ma60_y = None
        ma20_x = ma60_x = None
        for line in ax1.lines:
            try:
                xd = line.get_xdata()
                yd = line.get_ydata()
                if yd is None or len(yd) < 5:
                    continue
                col = to_hex(line.get_color()).lower()
                yv = None
                xv = None
                # 取左側 8%～28% 窗內第一個有限點（標要貼線左段）
                n = len(yd)
                i0 = max(0, int(n * 0.08))
                i1 = max(i0 + 1, int(n * 0.28))
                for i in range(i0, min(i1, n)):
                    try:
                        fv = float(yd[i])
                        fx = float(xd[i]) if xd is not None and i < len(xd) else float(i)
                    except Exception:
                        continue
                    if fv == fv and fv > 0:
                        yv, xv = fv, fx
                        break
                if yv is None:
                    for i in range(n - 1, -1, -1):
                        try:
                            fv = float(yd[i])
                            fx = float(xd[i]) if xd is not None and i < len(xd) else float(i)
                        except Exception:
                            continue
                        if fv == fv and fv > 0:
                            yv, xv = fv, fx
                            break
                if yv is None:
                    continue
                if col in (to_hex(_vz._MA20).lower(), "#f9a825"):
                    ma20_y, ma20_x = yv, xv
                elif col in (to_hex(_vz._MA60).lower(), "#5c6bc0"):
                    ma60_y, ma60_x = yv, xv
            except Exception:
                continue
        x_left = float(ax1.get_xlim()[0]) + 3.5
        if ma20_y is None and press:
            ma20_y = float(press) * 0.78
        if ma60_y is None and press:
            ma60_y = float(press) * 0.68
        if ma20_y:
            ax1.text(
                float(ma20_x) if ma20_x is not None else x_left,
                float(ma20_y),
                "月線",
                fontproperties=_fp(13.0, "bold"),
                color=_vz._MA20,
                ha="left",
                va="bottom",
                zorder=22,
                clip_on=False,
                bbox=dict(
                    boxstyle="round,pad=0.26",
                    facecolor="#fffde7",
                    edgecolor=_vz._MA20,
                    linewidth=1.2,
                    alpha=0.98,
                ),
            )
        if ma60_y:
            # 季線標略右、略下，不准跟月線盒互壓
            x60 = float(ma60_x) if ma60_x is not None else (x_left + 6.0)
            if ma20_x is not None and abs(x60 - float(ma20_x)) < 4.0:
                x60 = float(ma20_x) + 7.0
            ax1.text(
                x60,
                float(ma60_y),
                "季線",
                fontproperties=_fp(13.0, "bold"),
                color=_vz._MA60,
                ha="left",
                va="top",
                zorder=22,
                clip_on=False,
                bbox=dict(
                    boxstyle="round,pad=0.26",
                    facecolor="#e8eaf6",
                    edgecolor=_vz._MA60,
                    linewidth=1.2,
                    alpha=0.98,
                ),
            )
        print(
            f"[ma-label] forced ma20={ma20_y}@{ma20_x} ma60={ma60_y}@{ma60_x}",
            flush=True,
        )
    except Exception as exc:
        print(f"[ma-label] FAIL {exc!r}", flush=True)


def _apply_patches_and_render(sid: str, name: str, db: str, tmp: str, *, card: Optional[dict] = None):
    """Render three product panes with 01–08 presentation hooks."""
    import biaoke_chart as bc
    import vol_zone_chart as vz
    import wayne_navigator as wn
    from matplotlib.figure import Figure
    from matplotlib.gridspec import GridSpec
    from vol_zone_chart import (
        clear_vol_zone_render_cache,
        load_official_ohlc,
        prepare_volume_zone,
    )
    from wayne_navigator import NavigatorEngine, clear_lookup_render_cache, generate_chart
    from biaoke_chart import render_biaoke_structure_png, stock_nameplate

    clear_lookup_render_cache()
    clear_vol_zone_render_cache()
    official = load_official_ohlc(sid, db, 360)
    if official is None or official.empty:
        raise RuntimeError("no official OHLC")
    # ②③ 只用官方完整柱；表頭今K 另走 card／① 同源（可含盤中）
    if not isinstance(card, dict):
        card = None
        try:
            # 與話筒查股一致：盤中 merge_live，收盤後自然落到最新完整柱
            card = NavigatorEngine(db).get_decision_card(sid, lookback=20, merge_live=True)
            if isinstance(card, dict):
                card.pop("_ohlc", None)
        except Exception:
            card = None
    elif isinstance(card, dict):
        card = dict(card)
        card.pop("_ohlc", None)

    last_bar, is_live_quote, header_as_of = _header_quote_bar(sid, db, official, card)
    as_of = header_as_of or _dk(official["date"].iloc[-1])
    pack = prepare_volume_zone(sid, name, db, os.path.join(tmp, "prep.png"))
    first_k = _dk(pack["view"]["date"].iloc[0])
    last_k = _dk(pack["view"]["date"].iloc[-1])
    spike_i = int(pack["spike_i"])
    spike_date = _dk(pack.get("spike_date"))
    spike_md = _md_slash(spike_date)
    spike_vol = float(pack["view"]["volume"].iloc[spike_i] or 0)
    spike_lots = int(round(spike_vol))
    spike_hi = float(pack.get("hi") or 0)
    spike_lo = float(pack.get("lo") or 0)
    n_bars = int(pack.get("n") or len(pack["view"]))

    # 量柱底軸刻度資料（polish 重畫用）
    view0 = pack["view"]
    if "dt" not in view0.columns:
        import pandas as pd

        view0 = view0.copy()
        view0["dt"] = pd.to_datetime(view0["date"].astype(str), format="%Y%m%d", errors="coerce")
    tick_at = {}
    prev_m = None
    for i, dt in enumerate(view0["dt"]):
        if dt is None or (hasattr(dt, "month") is False):
            continue
        key = (int(dt.year), int(dt.month))
        if key != prev_m:
            tick_at[i] = f"{int(dt.month):02d}月"
            prev_m = key
    # 窗起／爆大量／末日用月日，量柱下才能對到日
    tick_at[0] = _md_slash(first_k)
    tick_at[spike_i] = spike_md
    tick_at[n_bars - 1] = _md_slash(last_k)
    tick_pos = sorted(tick_at)
    tick_labs = [tick_at[i] for i in tick_pos]

    # 表頭最右＝查詢當下戳（盤中 HH:MM／盤後收盤標籤）；日期＝今K 對應日（即時＝今日）
    from decision_card_signals import format_card_query_stamp

    query_now = datetime.now(ZoneInfo("Asia/Taipei"))
    stamp_date, stamp_clock = format_card_query_stamp(
        is_live=is_live_quote,
        latest_date=as_of,
        generated_at=query_now,
        stock_id=sid,
        db_path=db,
        quote_source=str((card or {}).get("quote_source") or ""),
        listing=str((card or {}).get("listing") or ""),
        market=str((card or {}).get("market") or ""),
    )
    ctx_stamp = {
        "date": stamp_date,
        "clock": stamp_clock,
        "query_wall": query_now.strftime("%m/%d %H:%M"),
        "generated_at": query_now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "is_live": is_live_quote,
    }

    # 買點對質：以① 180 日窗 `_nav_trade_marks` 為唯一準繩
    from wayne_navigator import _nav_trade_marks

    canon_work = official.tail(180).reset_index(drop=True).copy()
    canon_buy_is, canon_sell_i = _nav_trade_marks(canon_work, card=card)
    canon_buy_rows = []
    for i in canon_buy_is:
        d = _dk(canon_work["date"].iloc[i])
        canon_buy_rows.append(
            {
                "date": d,
                "low": float(canon_work["low"].iloc[i]),
                "high": float(canon_work["high"].iloc[i]),
                "close": float(canon_work["close"].iloc[i]),
                "nav_i": int(i),
                "after_window": d >= first_k,
            }
        )
    canon_buy_dates = {r["date"] for r in canon_buy_rows}
    canon_sell_date = (
        _dk(canon_work["date"].iloc[canon_sell_i]) if canon_sell_i is not None else None
    )
    # 短窗若自行重算會多畫：先記未對齊結果
    vz_raw_is, _ = _nav_trade_marks(pack["view"], card=card)
    vz_raw_dates = [_dk(pack["view"]["date"].iloc[i]) for i in vz_raw_is]
    buy_audit = {
        "rule": "藍▲紅框＝leave_zero 且過排除層；同源=_nav_trade_marks；紅箭頭不是買訊",
        "canon_window": "① generate_chart 180日",
        "first_k": first_k,
        "canon_buys_all": canon_buy_rows,
        "canon_buys_after_window": [r for r in canon_buy_rows if r["after_window"]],
        "vz_raw_before_align": vz_raw_dates,
        "vz_extra_removed": sorted(set(vz_raw_dates) - canon_buy_dates),
        "nav_missing_vs_raw_vz": sorted(
            set(d for d in vz_raw_dates if d >= first_k) - canon_buy_dates
        ),
        "fix": "③短窗重算 leave_zero 多畫；確認圖已把③買點對齊① 180日窗日期",
        "aligned": True,
        "card_buy_verdict": (card or {}).get("buy_verdict"),
        "card_sell_action": (card or {}).get("sell_action"),
        "card_gain_pct": (card or {}).get("gain_pct"),
        "sell_date": canon_sell_date,
        "note_buy": "藍▲紅框＝leave_zero；紅箭頭不是買訊；①③同源 _nav_trade_marks",
    }

    # ---- shared artist tweaks before save ----
    orig_fig_save = Figure.savefig
    orig_lookup_save = wn._savefig_lookup_png
    orig_gs = GridSpec
    orig_fig_h = vz.VOL_ZONE_FIG_H_NAV
    orig_legend = wn._draw_nav_legend
    orig_paint_nav = wn._paint_nav_on_axes
    orig_paint_vz = vz._paint_volume_zone
    orig_axhspan = None
    ctx = {"nav_i": -1, "st_i": -1, "vz_i": -1, "query_stamp": ctx_stamp}

    def _noop_legend(*a, **k):
        return None

    class _GS(GridSpec):
        def __init__(self, *a, **k):
            hr = k.get("height_ratios")
            try:
                hr_t = tuple(float(x) for x in (hr or ()))
            except (TypeError, ValueError):
                hr_t = ()
            # 量柱列縮回；量能訊號再縮，省下給量柱下方月份／日期刻度
            if hr_t in (
                (1.28, 3.38, 0.40, 0.98),
                (0.06, 2.55, 0.42, 2.15),
                (0.06, 3.27, 0.42, 0.72),
                (0.06, 3.55, 0.38, 0.50),
                (0.05, 3.52, 0.16, 0.72),
                (0.05, 2.95, 0.72, 0.78),
                (0.05, 3.05, 0.58, 0.72),
                (0.05, 3.22, 0.40, 0.72),
                (0.05, 3.28, 0.40, 0.72),
            ):
                # ① 範本：主圖／量能／成交量；量柱列加高，點開仍看得到日柱
                k["height_ratios"] = [0.04, 4.85, 0.42, 1.85]
                k["top"] = 0.995
                k["bottom"] = 0.118
                k["hspace"] = 0.050
                k["left"] = FRAME_LEFT
                k["right"] = FRAME_RIGHT
            elif hr_t in ((5.45, 1.45), (5.15, 1.45), (4.85, 1.85)):
                k["height_ratios"] = [4.85, 1.85]
                k.setdefault("hspace", 0.050)
            elif hr_t in ((5.15, 0.42, 1.45), (4.85, 0.42, 1.85)):
                k["height_ratios"] = [4.85, 0.42, 1.85]
                k.setdefault("hspace", 0.050)
            super().__init__(*a, **k)

    def _pre_save(fig):
        if fig is None:
            return
        # drop per-figure footer / stamp / long titles (dedupe to composite)
        for t in list(getattr(fig, "texts", []) or []):
            s = str(t.get_text() or "")
            if any(
                k in s
                for k in (
                    "桃色帶",
                    "高觸壓",
                    "K 線紅漲綠跌",
                    "量能列",
                    "13:30",
                    "收盤",
                    "WayneBot",
                )
            ):
                t.set_visible(False)
        for ax in list(fig.axes):
            title = ax.get_title() or ""
            if title:
                ax.set_title("")
            if ax.get_legend() is not None:
                try:
                    ax.get_legend().remove()
                except Exception:
                    pass
            # hide head-panel intro texts
            for txt in list(ax.texts):
                s = str(txt.get_text() or "")
                # 只藏標題列／介紹句；圖內「爆大量 09/23」與張數不准藏
                intro = ("大量區專圖" in s) or ("含導航指標" in s) or ("180日高低導航" in s)
                long_head = ("爆大量" in s and "壓" in s and "撐" in s) or (
                    "爆大量" in s and "開" in s and "收" in s
                )
                if intro or long_head:
                    txt.set_visible(False)

    def _fig_save(self, *a, **k):
        _pre_save(self)
        return orig_fig_save(self, *a, **k)

    def _lookup_save(fig, path, dpi):
        _pre_save(fig)
        return orig_lookup_save(fig, path, dpi)

    def _paint_nav(ax1, ax_sig, ax2, work, stock_id, stock_name, *, compact=False, card=None):
        from wayne_navigator import _fp

        orig_paint_nav(ax1, ax_sig, ax2, work, stock_id, stock_name, compact=compact, card=card)
        ax1.set_title("")
        dates = [_dk(d) for d in work["date"].tolist()]
        i = _index_of_date(dates, first_k)
        ctx["nav_i"] = i
        if i >= 0:
            lab = f"{MARK_LABEL} {_md_slash(first_k)}"
            _mark_axvline(ax1, float(i), lab)
            for ax in (ax_sig, ax2):
                if ax is None:
                    continue
                ax.axvline(float(i), color=MARK_COLOR, lw=1.4, ls=(0, (4, 2)), zorder=9, alpha=0.8)
        # ① 爆大量日與③同一天：量柱橘色＋虛線連 K／量（張數同源）
        si = _index_of_date(dates, spike_date)
        ctx["nav_spike_i"] = si
        if si >= 0:
            for ax in (ax1, ax_sig, ax2):
                _dash_spike_vline(ax, si, lw=1.55)
            bar_h = _recolor_vol_bar(ax2, si, SPIKE_BAR_COLOR)
            if bar_h <= 0 and ax2 is not None:
                try:
                    bar_h = float(work["volume"].iloc[si] or 0)
                except Exception:
                    bar_h = float(spike_lots)
            if ax2 is not None and bar_h > 0:
                # 標往左寫，不准貼右緣被裁成「爆大量 09/」
                ax2.set_ylim(0, max(ax2.get_ylim()[1], float(bar_h) * 1.42))
                ax2.annotate(
                    f"爆大量 {spike_md}　{spike_lots:,}張",
                    xy=(float(si), float(bar_h)),
                    xytext=(-14, 14),
                    textcoords="offset points",
                    ha="right",
                    va="bottom",
                    fontproperties=_fp(10.5, "bold"),
                    color="#5d4037",
                    zorder=14,
                    clip_on=False,
                    arrowprops=dict(arrowstyle="->", color=SPIKE_BAR_COLOR, lw=1.05, shrinkB=1.5),
                    bbox=dict(
                        boxstyle="round,pad=0.20",
                        facecolor="#fffde7",
                        edgecolor=SPIKE_BAR_COLOR,
                        linewidth=0.95,
                        alpha=0.97,
                    ),
                )
        try:
            ax1.figure.subplots_adjust(
                top=0.96, bottom=0.090, left=FRAME_LEFT, right=FRAME_RIGHT
            )
        except Exception:
            pass
        # ①價／量軸都只留右邊，當②③框線範本
        _force_y_right_only(ax1)
        _force_y_right_only(ax2, ylabel="日成交量（張）")
        fr = _ax_spine_frac(ax1)
        if fr:
            ctx["nav_spine_frac"] = fr
        ctx["nav_sig_h_px"] = _ax_frame_h_px(ax_sig)
        ctx["nav_zone_fracs"] = [
            _ax_box_frac(ax1),
            _ax_box_frac(ax_sig),
            _ax_box_frac(ax2),
        ]

    def _paint_vz(*args, **kwargs):
        # 03: darker band + thicker press/hold; 標籤錯層；爆大量帶張數
        import matplotlib.axes
        from wayne_navigator import _fp

        orig_hspan = matplotlib.axes.Axes.axhspan
        orig_hline = matplotlib.axes.Axes.axhline
        orig_vline = matplotlib.axes.Axes.axvline
        orig_ann = matplotlib.axes.Axes.annotate
        orig_text = matplotlib.axes.Axes.text

        def hspan(self, ymin, ymax, *a, **k):
            if k.get("color") == vz._FILL or (len(a) == 0 and k.get("alpha") == 0.42):
                k["alpha"] = 0.58
            return orig_hspan(self, ymin, ymax, *a, **k)

        def hline(self, y, *a, **k):
            col = k.get("color")
            if col in (vz._PRESS, vz._HOLD):
                k["linewidth"] = max(float(k.get("linewidth") or 1.35), 2.35)
            return orig_hline(self, y, *a, **k)

        def vline(self, x, *a, **k):
            if k.get("color") == vz._SPIKE:
                # 爆大量連線＝虛線（不准橘黃實線）
                k["linewidth"] = max(float(k.get("linewidth") or 1.2), 1.7)
                k["linestyle"] = SPIKE_DASH
                k["alpha"] = 0.92
            return orig_vline(self, x, *a, **k)

        def ann(self, text, *a, **k):
            if isinstance(text, str) and "測壓" in text:
                # 先藏產品原標；polish 會用 clip_on=False 重畫清楚那句
                k["alpha"] = 0.0
                k["visible"] = False
            return orig_ann(self, text, *a, **k)

        def text(self, x, y, s="", *a, **k):
            # 產品原壓／撐標先藏；polish 改畫在橘虛線左（字串用「壓／撐」避免誤傷）
            if isinstance(s, str) and (s.startswith("大量區壓") or s.startswith("大量區撐")):
                k["alpha"] = 0.0
                k["visible"] = False
                return orig_text(self, x, y, s, *a, **k)
            if isinstance(s, str) and ("除息" in s or "除權" in s):
                if float(x) < max(n_bars * 0.22, 10.0):
                    x = max(n_bars * 0.28, 14.0)
                    k["ha"] = "left"
                y = min(float(y), 0.88)
            if isinstance(s, str) and s in ("月線", "季線"):
                # 保留月／季線標（使用者要看）
                return orig_text(self, x, y, s, *a, **k)
            return orig_text(self, x, y, s, *a, **k)

        matplotlib.axes.Axes.axhspan = hspan
        matplotlib.axes.Axes.axhline = hline
        matplotlib.axes.Axes.axvline = vline
        matplotlib.axes.Axes.annotate = ann
        matplotlib.axes.Axes.text = text
        try:
            path = orig_paint_vz(*args, **kwargs)
        finally:
            matplotlib.axes.Axes.axhspan = orig_hspan
            matplotlib.axes.Axes.axhline = orig_hline
            matplotlib.axes.Axes.axvline = orig_vline
            matplotlib.axes.Axes.annotate = orig_ann
            matplotlib.axes.Axes.text = orig_text
        return path

    Figure.savefig = _fig_save
    wn._savefig_lookup_png = _lookup_save
    vz.GridSpec = _GS
    import matplotlib.gridspec as mgs

    mgs.GridSpec = _GS
    wn._draw_nav_legend = _noop_legend
    wn._paint_nav_on_axes = _paint_nav
    vz._paint_volume_zone = _paint_vz

    # structure save hook: mark + interval span from first_k
    def _st_save(fig, path, dpi):
        from wayne_navigator import _fp

        bars = ctx["bars"]
        work = bars[-bc._BARS :]
        dates = [_dk(r.get("date")) for r in work]
        i = _index_of_date(dates, first_k)
        ctx["st_i"] = i
        ax1 = fig.axes[0] if fig.axes else None
        ax2 = fig.axes[1] if fig.axes and len(fig.axes) > 1 else None
        # 合成只要主 K＋量柱：藏縮圖／頭牌 overlay，避免上緣殘破小圖
        for extra_ax in list(fig.axes)[2:]:
            try:
                extra_ax.set_visible(False)
            except Exception:
                continue
        # 結構「最可能＝壓轉撐 796」改跟③同源 840／761
        if ax1 is not None:
            from wayne_navigator import _fmt_price as _fp_px

            for txt in list(ax1.texts):
                s = str(txt.get_text() or "")
                if "最可能" in s and ("796" in s or "733" in s):
                    txt.set_text(s.replace("796", _fp_px(spike_hi)).replace("733", _fp_px(spike_lo)))
        if i >= 0 and ax1 is not None:
            # ② 底圖區間 = ③ visible window (first K → last)
            ax1.axvspan(float(i) - 0.45, float(len(work) - 1) + 0.45, color="#ffe0b2", alpha=0.18, zorder=0)
            lab = f"{MARK_LABEL} {_md_slash(first_k)}"
            _mark_axvline(ax1, float(i), lab)
            if ax2 is not None:
                ax2.axvline(float(i), color=MARK_COLOR, lw=1.4, ls=(0, (4, 2)), zorder=9, alpha=0.8)
        # ②爆大量標與③同一日同一張數（有效大量區日；不是結構演算法絕對最大量日）
        si = _index_of_date(dates, spike_date)
        ctx["st_spike_i"] = si
        ctx["st_spike_lots"] = int(spike_lots)
        if si >= 0 and ax1 is not None:
            for ax in (ax1, ax2):
                _dash_spike_vline(ax, si, lw=1.6)
            if ax2 is not None:
                # 舊演算法日量柱若已上色，先依漲跌還原，再把③同源日改橘
                for j, p in enumerate(list(ax2.patches)):
                    try:
                        cx = p.get_x() + p.get_width() / 2.0
                        jj = int(round(cx))
                        if 0 <= jj < len(work) and jj != si:
                            up = float(work[jj].get("close") or 0) >= float(work[jj].get("open") or 0)
                            p.set_facecolor(CANDLE_UP if up else CANDLE_DN)
                    except Exception:
                        continue
                bar_h = _recolor_vol_bar(ax2, si, SPIKE_BAR_COLOR)
                _hide_texts_matching(
                    ax2,
                    lambda s: ("爆大量" in s) or ("這根" in s and "張" in s),
                )
                if bar_h <= 0:
                    try:
                        bar_h = float(work[si].get("volume") or spike_lots)
                    except Exception:
                        bar_h = float(spike_lots)
                ymax = max(ax2.get_ylim()[1], bar_h * 1.35)
                ax2.set_ylim(0, ymax)
                ax2.annotate(
                    f"爆大量 {spike_md}　{spike_lots:,}張",
                    xy=(float(si), float(bar_h)),
                    xytext=(10, 8),
                    textcoords="offset points",
                    ha="left",
                    va="bottom",
                    fontproperties=_fp(11.0, "bold"),
                    color="#5d4037",
                    zorder=15,
                    clip_on=False,
                    arrowprops=dict(arrowstyle="->", color=SPIKE_BAR_COLOR, lw=1.1, shrinkB=1.5),
                    bbox=dict(
                        boxstyle="round,pad=0.20",
                        facecolor="#fffde7",
                        edgecolor=SPIKE_BAR_COLOR,
                        linewidth=0.95,
                        alpha=0.97,
                    ),
                )
                # 軸下日期：爆大量日保留；鄰近去重＋錯層，不准 09/23／10/02 互壓
                try:
                    xt = [float(x) for x in ax2.get_xticks()]
                    labs = [str(t.get_text() or "") for t in ax2.get_xticklabels()]
                    if not any(abs(float(x) - float(si)) < 0.51 for x in xt):
                        xt.append(float(si))
                        labs.append(spike_md)
                    else:
                        labs = [
                            spike_md if abs(float(x) - float(si)) < 0.51 else lb
                            for x, lb in zip(xt, labs)
                        ]
                    pairs = [
                        (x, lb)
                        for x, lb in zip(xt, labs)
                        if lb and not (abs(float(x) - float(si)) < 1.6 and lb != spike_md)
                    ]
                    last_md = _md_slash(dates[-1]) if dates else ""
                    first_md = _md_slash(first_k)
                    if pairs:
                        _thin_stagger_date_ticks(
                            ax2,
                            [p[0] for p in pairs],
                            [p[1] for p in pairs],
                            min_gap=7.0,
                            protect=(spike_md, "演算", last_md, first_md),
                        )
                except Exception:
                    pass
        # ②壓／撐必須跟③同一套有效大量區（840／761），不准再用結構絕對最大量日（09/22 796／733）
        # 根因：結構 volume_first_price＝近窗最大量；③＝近窗仍有效（高≥最近收）爆大量日
        from wayne_navigator import _fmt_price
        import biaoke_chart as _bc_mod

        struct_hi = None
        struct_lo = None
        for txt in list(ax1.texts if ax1 is not None else []):
            s = str(txt.get_text() or "")
            if s.startswith("壓 ") or s.startswith("撐 "):
                try:
                    num = float(s.split()[-1].replace(",", ""))
                    if s.startswith("壓 "):
                        struct_hi = num
                    else:
                        struct_lo = num
                except Exception:
                    pass
                txt.set_visible(False)
        # 舊水平線：藏掉結構原價，改畫③同源價
        if ax1 is not None:
            for line in list(ax1.lines):
                try:
                    yd = line.get_ydata()
                    if len(yd) < 1:
                        continue
                    y0 = float(yd[0])
                    if struct_hi and abs(y0 - float(struct_hi)) < 0.51:
                        line.set_visible(False)
                    if struct_lo and abs(y0 - float(struct_lo)) < 0.51:
                        line.set_visible(False)
                except Exception:
                    continue
            # hlines 也可能在 collections
            for coll in list(getattr(ax1, "collections", []) or []):
                try:
                    # LineCollection from hlines
                    segs = getattr(coll, "get_segments", lambda: None)()
                    if not segs:
                        continue
                    for seg in segs:
                        if len(seg) < 2:
                            continue
                        y0 = float(seg[0][1])
                        if (struct_hi and abs(y0 - float(struct_hi)) < 0.51) or (
                            struct_lo and abs(y0 - float(struct_lo)) < 0.51
                        ):
                            coll.set_visible(False)
                            break
                except Exception:
                    continue
            # 重畫③同源壓撐＋框內左側完整標籤（綠／洋紅框＝壓／撐＋數字，不准半截）
            x_right = ax1.get_xlim()[1]
            x_left = float(ax1.get_xlim()[0]) + 0.35
            for y_val, name, col in (
                (float(spike_hi), f"壓 {_fmt_price(spike_hi)}", _bc_mod._PRESS),
                (float(spike_lo), f"撐 {_fmt_price(spike_lo)}", _bc_mod._HOLD),
            ):
                ax1.hlines(
                    y_val,
                    xmin=-0.55,
                    xmax=max(x_right - 8.0, 10.0),
                    color=col,
                    linewidth=1.35,
                    zorder=5,
                    alpha=0.95,
                )
                ax1.annotate(
                    name,
                    xy=(x_left, y_val),
                    xytext=(VZ_TAG_X_OFFSET, 0),
                    textcoords="offset points",
                    ha="left",
                    va="center",
                    fontproperties=_fp(13.0, "bold"),
                    color=col,
                    zorder=14,
                    clip_on=False,
                    bbox=dict(
                        boxstyle="round,pad=0.26",
                        facecolor="#ffffff",
                        edgecolor=col,
                        linewidth=1.2,
                        alpha=0.96,
                    ),
                )
            ctx["st_press_hold"] = {
                "source": "vol_zone_effective",
                "hi": float(spike_hi),
                "lo": float(spike_lo),
                "struct_was": {"hi": struct_hi, "lo": struct_lo},
                "correct": "③有效大量區（高仍壓著收）＝準；結構絕對最大量日僅演算法不同",
            }
            # ylim 必須含壓撐，不准標籤落在軸外被裁
            ymin, ymax = ax1.get_ylim()
            pad = max((ymax - ymin) * 0.04, 8.0)
            ax1.set_ylim(
                min(ymin, float(spike_lo) - pad),
                max(ymax, float(spike_hi) + pad),
            )
        # 藏縮圖後把主K＋量柱抬滿上緣（對齊①主圖高度）；底邊留給錯層日期；價／量軸只留右邊
        try:
            fig.subplots_adjust(left=FRAME_LEFT, right=FRAME_RIGHT, top=0.965, bottom=0.10)
        except Exception:
            pass
        # 軌道標籤：藏舊右溝標，往左貼軌末端重畫（字級≈③壓840）；收掉右側大空白
        if ax1 is not None:
            from wayne_navigator import _fp as _st_fp

            n_bars = len(work)
            seam = float(max(n_bars - 1, 0))
            # 標籤落在橘虛線左側、貼兩條軌道；字向左長，不准再飄右溝
            tag_x = seam - 3.6
            redraw: list[tuple[str, float, str]] = []
            for txt in list(ax1.texts):
                s = str(txt.get_text() or "")
                if not any(
                    k in s
                    for k in ("平行壓", "上升軌", "最可能", "平行撐", "下降壓")
                ):
                    continue
                y = None
                try:
                    if hasattr(txt, "xyann"):
                        y = float(txt.xyann[1])
                    else:
                        y = float(txt.get_position()[1])
                except Exception:
                    try:
                        y = float(txt.get_position()[1])
                    except Exception:
                        y = None
                try:
                    col = str(txt.get_color() or "#1565c0")
                except Exception:
                    col = "#1565c0"
                if y is not None:
                    redraw.append((s, float(y), col))
                txt.set_visible(False)
                # Annotation 短引線一併藏（有平行軌就不需要短藍線）
                try:
                    ap = getattr(txt, "arrow_patch", None)
                    if ap is not None:
                        ap.set_visible(False)
                except Exception:
                    pass
            # 垂直錯開，且不准坐在軌線上（上軌標往上、下軌標往下）
            redraw.sort(key=lambda t: -t[1])
            used_y: list[float] = []
            # 上軌標若貼頂會被 ylim 壓回線上：先抬 ylim 再放標
            ymin, ymax = ax1.get_ylim()
            span = max(ymax - ymin, 1.0)
            ax1.set_ylim(ymin, ymax + span * 0.10)
            ymin, ymax = ax1.get_ylim()
            gap = max((ymax - ymin) * 0.10, 48.0)
            for s, y0, col in redraw:
                y = float(y0)
                if "平行壓" in s or "下降壓" in s or "上軌" in s:
                    # 上軌標整盒抬離線；引線指回軌端，盒本身不准壓線
                    y = min(float(y0) + gap * 1.6, ymax - gap * 0.15)
                elif "上升軌" in s or "平行撐" in s or "下軌" in s:
                    y = float(y0) - gap * 1.45
                elif "最可能" in s:
                    y = min(max(float(y0), ymax - gap * 1.4), ymax - gap * 0.35)
                for _ in range(12):
                    if not any(abs(y - u) < gap * 0.85 for u in used_y):
                        break
                    y -= gap * 0.9
                y = min(max(y, ymin + gap * 0.6), ymax - gap * 0.12)
                used_y.append(y)
                # 字級／盒對齊③「壓 840」；軌道已有平行線，不准再畫短引線交叉
                sz = 16.5 if "最可能" in s else 15.5
                va = "bottom" if ("平行壓" in s or "下降壓" in s or "上軌" in s) else (
                    "top" if ("上升軌" in s or "平行撐" in s or "下軌" in s) else "center"
                )
                ax1.text(
                    tag_x - 2.4,
                    y,
                    s,
                    ha="right",
                    va=va,
                    fontproperties=_st_fp(sz, "bold"),
                    color=col,
                    zorder=16,
                    clip_on=False,
                    bbox=dict(
                        boxstyle="round,pad=0.36",
                        facecolor="#ffffff",
                        edgecolor=col,
                        linewidth=1.35,
                        alpha=0.97,
                    ),
                )
            # 右緣只留刻度溝，不准再空一大片給舊右溝標
            x_right = seam + 10.5
            ax1.set_xlim(-0.55, x_right)
            if ax2 is not None:
                ax2.set_xlim(-0.55, x_right)
            # 通道說明：畫得出上升／下降就填②左上（紅圈位置）
            # 基準＝③「壓 840」字級，使用者允許再放大 1.55 倍
            import re as _re_tip
            import vol_zone_chart as _vz_tip

            ch_tip_info = _bc_mod.infer_parallel_channel(work) or {}
            tip_raw = str(ch_tip_info.get("tip") or "").strip()
            tip_kind = str(ch_tip_info.get("kind") or "").strip()
            tip_drawn = ""
            tip_pt = round(float(_vz_tip.VOL_ZONE_TAG_PT) * 1.55, 1)  # 16→24.8
            if tip_raw and tip_kind in ("asc", "desc"):
                bits = [
                    b.strip()
                    for b in _re_tip.split(r"(?<=[；。])", tip_raw)
                    if b and b.strip()
                ]
                lines: list[str] = []
                cur = ""
                # 字放大後每行略短，避免盒過寬壓 K
                for b in bits:
                    if not cur:
                        cur = b
                    elif len(cur) + len(b) <= 22:
                        cur = f"{cur}{b}"
                    else:
                        lines.append(cur)
                        cur = b
                if cur:
                    lines.append(cur)
                tip_drawn = "\n".join(lines[:4])
                tip_color = (
                    _bc_mod._UP_TRACK if tip_kind == "asc" else _bc_mod._DOWN_TRACK
                )
                # 軸座標左上＝紅圈空帶；略右讓開左側壓／撐晶片
                ax1.text(
                    0.10,
                    0.98,
                    tip_drawn,
                    transform=ax1.transAxes,
                    ha="left",
                    va="top",
                    fontproperties=_st_fp(float(tip_pt), "bold"),
                    color=tip_color,
                    zorder=18,
                    clip_on=True,
                    linespacing=1.22,
                    bbox=dict(
                        boxstyle="round,pad=0.34",
                        facecolor="#ffffff",
                        edgecolor=tip_color,
                        linewidth=1.35,
                        alpha=0.95,
                    ),
                )
            ctx["st_channel_tip"] = {
                "kind": tip_kind or None,
                "tip": tip_raw or None,
                "drawn": tip_drawn or None,
                "pt": tip_pt if tip_drawn else None,
                "scale": 1.55,
            }
        ctx["st_zone_fracs"] = [_ax_box_frac(ax1), _ax_box_frac(ax2)]
        _force_y_right_only(ax1)
        _force_y_right_only(ax2, ylabel="日成交量（張）")
        fr = _ax_spine_frac(ax1)
        if fr:
            ctx["st_spine_frac"] = fr
        # 結構圖必須真 PNG：產品 _savefig_lookup_png 固定 JPEG，細 K 會殘破
        from wayne_navigator import mpl_render

        with mpl_render():
            fig.savefig(path, format="png", dpi=dpi, facecolor=fig.get_facecolor())
        return path

    orig_trade = wn._nav_trade_marks
    try:
        nav_p = os.path.join(tmp, "nav.png")
        clear_lookup_render_cache()
        orig_adj = Figure.subplots_adjust

        def _adj(self, *a, **k):
            if k.get("top") == 0.70:
                k["top"] = 0.97
                k["bottom"] = 0.07
            # 左右框強制跟範本
            k["left"] = FRAME_LEFT
            k["right"] = FRAME_RIGHT
            return orig_adj(self, *a, **k)

        def _png_save(fig, path, dpi):
            """mock 直出真 PNG：JPEG 會把細 K／影線壓成殘破。"""
            _pre_save(fig)
            from wayne_navigator import mpl_render

            with mpl_render():
                fig.savefig(
                    path,
                    format="png",
                    dpi=dpi,
                    facecolor=fig.get_facecolor(),
                )
            return path

        orig_nav_dpi = wn.NAV_CHART_DPI
        wn.NAV_CHART_DPI = PANE_DPI
        Figure.subplots_adjust = _adj
        wn._savefig_lookup_png = _png_save
        try:
            nav_out = generate_chart(sid, name, db, nav_p)
        finally:
            Figure.subplots_adjust = orig_adj
            wn.NAV_CHART_DPI = orig_nav_dpi
        if not nav_out:
            raise RuntimeError("nav fail")

        bars = _bars_from_official(official, sid, name)
        ctx["bars"] = bars
        wn._savefig_lookup_png = _st_save  # 末段真 PNG＋軌道標左移加大
        struct_p = os.path.join(tmp, "st.png")
        clear_lookup_render_cache()
        orig_subplots = bc.plt.subplots
        orig_dpi = bc.BIAOKE_CHART_DPI
        orig_bodies = bc._add_ohlc_bodies
        orig_wicks = bc._add_ohlc_wicks

        def _subplots(*a, **k):
            gs = dict(k.get("gridspec_kw") or {})
            hr = gs.get("height_ratios")
            try:
                hr_t = tuple(float(x) for x in (hr or ()))
            except (TypeError, ValueError):
                hr_t = ()
            if hr_t in ((5.45, 1.45), (5.15, 1.45), (4.85, 1.85)):
                gs["height_ratios"] = (4.85, 1.85)
                gs["hspace"] = 0.05
                k = dict(k)
                k["gridspec_kw"] = gs
                # 對齊① 12.8×8.85×PANE_DPI；不准先畫超大再縮進合成欄
                if len(a) >= 2 or "figsize" in k:
                    k["figsize"] = (12.8, 8.85)
                k["dpi"] = max(int(k.get("dpi") or 0), int(PANE_DPI))
            return orig_subplots(*a, **k)

        _wick_pending: dict = {}

        def _darken_wick(col: str) -> str:
            return _wick_col(col)

        def _thick_bodies(ax, xs, opens, closes, colors, *, widths, lws, edges, min_h, z=3):
            # 真正 K：實體留縫；畫完再疊同色系貫穿影（對齊①③紅漲綠跌，不准近黑）
            widths = [min(max(float(w) * 1.35, 0.48), 0.68) for w in widths]
            lws = [max(float(lw), 1.05) for lw in lws]
            bodies = [_canon_candle_col(c) for c in colors]
            print(f"[k-body] n={len(list(xs))} z={z} w0={widths[0] if widths else None}", flush=True)
            out = orig_bodies(
                ax, xs, opens, closes, bodies,
                widths=widths, lws=lws, edges=bodies, min_h=max(float(min_h), 0.0) * 1.05, z=z,
            )
            pend = _wick_pending.pop(id(ax), None)
            if pend is not None:
                wxs, wlo, whi, wcols, wlw = pend
                if isinstance(wlw, (list, tuple)):
                    lw2 = [max(float(x), 2.40) for x in wlw]
                else:
                    lw2 = max(float(wlw), 2.40)
                print(f"[k-wick-on-body] n={len(list(wxs))} lw={lw2 if not isinstance(lw2, list) else lw2[0]} z={int(z)+6}", flush=True)
                for x, lo, hi, col in zip(wxs, wlo, whi, wcols):
                    ax.plot(
                        [float(x), float(x)],
                        [float(lo), float(hi)],
                        color=_wick_col(col),
                        linewidth=2.4,
                        solid_capstyle="butt",
                        zorder=int(z) + 8,
                        clip_on=True,
                    )
            return out

        def _thick_wicks(ax, xs, lows, highs, colors, *, lw=0.9, z=3):
            # 先暫存；等實體畫完再疊貫穿線（同色系深影）。
            bodies = [_canon_candle_col(c) for c in colors]
            _wick_pending[id(ax)] = (list(xs), list(lows), list(highs), bodies, lw)
            print(f"[k-wick] n={len(list(xs))} pending-for-body", flush=True)
            return orig_wicks(
                ax, xs, lows, highs, [_wick_col(c) for c in bodies],
                lw=( [max(float(x), 2.2) for x in lw] if isinstance(lw, (list, tuple)) else max(float(lw), 2.2) ),
                z=int(z) + 8,
            )

        bc.plt.subplots = _subplots  # type: ignore[assignment]
        bc.BIAOKE_CHART_DPI = int(PANE_DPI)
        bc._add_ohlc_bodies = _thick_bodies  # type: ignore[assignment]
        bc._add_ohlc_wicks = _thick_wicks  # type: ignore[assignment]
        try:
            struct_out = render_biaoke_structure_png(
                bars, struct_p, sid=sid, name=name,
                plate=stock_nameplate(sid, name, db), db_path=db,
            )
        finally:
            bc.plt.subplots = orig_subplots  # type: ignore[assignment]
            bc.BIAOKE_CHART_DPI = orig_dpi
            bc._add_ohlc_bodies = orig_bodies  # type: ignore[assignment]
            bc._add_ohlc_wicks = orig_wicks  # type: ignore[assignment]
        if not struct_out:
            raise RuntimeError("struct fail")
        wn._savefig_lookup_png = _png_save
        # ③與①同英寸高（8.85）；三區像素對齊交給 compose 對框，不准整張硬拉
        vz.VOL_ZONE_FIG_H_NAV = 8.85
        vol_p = os.path.join(tmp, "vol.png")
        clear_vol_zone_render_cache()
        clear_lookup_render_cache()

        # ③買點對齊①：短窗不准自行重算 leave_zero 多畫藍▲紅框
        def _trade_aligned(work, card=None):
            dates = [_dk(d) for d in work["date"].tolist()]
            d2i = {d: i for i, d in enumerate(dates)}
            buy_is = sorted(d2i[d] for d in canon_buy_dates if d in d2i)
            sell_i = d2i.get(canon_sell_date) if canon_sell_date else None
            return buy_is, sell_i

        wn._nav_trade_marks = _trade_aligned

        # ③彩箭對齊①：短窗冷啟動會重算 20／60 高低→箭頭日期錯；
        # 用① 180 日母體跑同一套狀態機，x 平移到可見窗。
        import numpy as np

        orig_overlay = wn.overlay_nav_marks_on_zone

        def _overlay_aligned(ax1, ax_sig, work, *, card=None, draw_legend=True, draw_ma20=True):
            view_dk = [_dk(d) for d in work["date"].tolist()]
            if not view_dk:
                return orig_overlay(
                    ax1, ax_sig, work, card=card, draw_legend=draw_legend, draw_ma20=draw_ma20
                )
            cw_dk = [_dk(d) for d in canon_work["date"].tolist()]
            end_d = view_dk[-1]
            end_i = max((i for i, d in enumerate(cw_dk) if d <= end_d), default=len(cw_dk) - 1)
            warm = canon_work.iloc[: end_i + 1].reset_index(drop=True)
            warm_dk = [_dk(d) for d in warm["date"].tolist()]
            try:
                start = warm_dk.index(view_dk[0])
            except ValueError:
                return orig_overlay(
                    ax1, ax_sig, work, card=card, draw_legend=draw_legend, draw_ma20=draw_ma20
                )
            real_arange = np.arange

            def _shifted_arange(*a, **k):
                arr = real_arange(*a, **k)
                try:
                    if (
                        getattr(arr, "ndim", 1) == 1
                        and len(arr) == len(warm)
                        and len(arr) > 0
                        and float(arr[0]) == 0.0
                        and abs(float(arr[-1]) - (len(warm) - 1)) < 0.51
                    ):
                        return arr.astype(float) - float(start)
                except Exception:
                    pass
                return arr

            np.arange = _shifted_arange  # type: ignore[assignment]
            try:
                orig_overlay(
                    ax1, ax_sig, warm, card=card, draw_legend=draw_legend, draw_ma20=draw_ma20
                )
            finally:
                np.arange = real_arange  # type: ignore[assignment]
            # 暖窗平移只裁 x<0 溢箭；量能列可見窗紅底要留紅三角（不准 x_min=25）
            n_hide = _strip_left_edge_arrows(ax1, ax_sig, x_min=-0.20)
            print(f"[overlay-strip] hid={n_hide}", flush=True)
            # 可見窗 xlim 保住（overlay 可能因 warm 拉寬）
            n_view = len(work)
            try:
                ax1.set_xlim(-0.55, max(n_view - 0.2, 1.0))
                if ax_sig is not None:
                    ax_sig.set_xlim(-0.55, max(n_view - 0.2, 1.0))
            except Exception:
                pass
            ctx["arrow_align"] = {
                "warm_n": len(warm),
                "view_n": n_view,
                "start": start,
                "mode": "canon_180_shift",
            }

        wn.overlay_nav_marks_on_zone = _overlay_aligned

        def _vz_save(self, *a, **k):
            _pre_save(self)
            if self.axes:
                view = pack["view"]
                dates = [_dk(d) for d in view["date"].tolist()]
                i = _index_of_date(dates, first_k)
                ctx["vz_i"] = i
                last_row = view.iloc[-1]
                path_last = dict(last_bar or {})
                if not path_last.get("close"):
                    path_last = {
                        "date": _dk(last_row.get("date")),
                        "open": float(last_row.get("open") or 0),
                        "high": float(last_row.get("high") or 0),
                        "low": float(last_row.get("low") or 0),
                        "close": float(last_row.get("close") or 0),
                    }
                path_last.setdefault("open", float(last_row.get("open") or 0))
                path_last.setdefault("high", float(last_row.get("high") or 0))
                path_last.setdefault("low", float(last_row.get("low") or 0))
                dates_v = [_dk(d) for d in view["date"].tolist()]
                hd = _dk(path_last.get("date"))
                if hd in dates_v:
                    path_last["_i"] = dates_v.index(hd)
                else:
                    path_last["_i"] = len(view) - 1
                view_bars = [
                    {
                        "date": _dk(r.get("date")),
                        "open": r.get("open"),
                        "high": r.get("high"),
                        "low": r.get("low"),
                        "close": r.get("close"),
                        "volume": r.get("volume"),
                    }
                    for r in view.to_dict("records")
                ]
                _polish_vol_figure(
                    self,
                    first_i=i,
                    first_k=first_k,
                    spike_i=spike_i,
                    spike_md=spike_md,
                    spike_lots=spike_lots,
                    spike_hi=spike_hi,
                    spike_lo=spike_lo,
                    tick_labs=tick_labs,
                    tick_pos=tick_pos,
                    last_bar=path_last,
                    bars=view_bars,
                    zone_date=spike_date,
                )
                ax_p, ax_s, _ = _pick_vol_axes(self)
                fr = _ax_spine_frac(ax_p)
                if fr:
                    ctx["vz_spine_frac"] = fr
                ctx["nav_sig_h_px"] = ctx.get("nav_sig_h_px")
                ctx["vz_sig_h_px"] = _ax_frame_h_px(ax_s)
                ctx["vz_zone_fracs"] = [
                    _ax_box_frac(ax_p),
                    _ax_box_frac(ax_s),
                    _ax_box_frac(_pick_vol_axes(self)[2]),
                ]
            k = dict(k)
            k["format"] = "png"
            k.pop("pil_kwargs", None)
            return orig_fig_save(self, *a, **k)

        Figure.savefig = _vz_save
        try:
            vol_out, vol_cap = vz.render_volume_zone_result(
                sid, name, db, vol_p, card=card, with_nav_signals=True
            )
        finally:
            wn._nav_trade_marks = orig_trade
            wn.overlay_nav_marks_on_zone = orig_overlay
        if not vol_out:
            raise RuntimeError("vol fail")
        # 對質：對齊後③畫出的買點日期
        aligned_vz_is, _ = _trade_aligned(pack["view"], card)
        buy_audit["vz_aligned_dates"] = [
            _dk(pack["view"]["date"].iloc[i]) for i in aligned_vz_is
        ]
        buy_audit["after_window_consistent"] = (
            sorted(r["date"] for r in buy_audit["canon_buys_after_window"])
            == sorted(d for d in buy_audit["vz_aligned_dates"] if d >= first_k)
        )
        buy_audit["arrow_align"] = ctx.get("arrow_align")
    finally:
        Figure.savefig = orig_fig_save
        wn._savefig_lookup_png = orig_lookup_save
        wn._draw_nav_legend = orig_legend
        wn._paint_nav_on_axes = orig_paint_nav
        vz._paint_volume_zone = orig_paint_vz
        vz.GridSpec = orig_gs
        mgs.GridSpec = orig_gs
        try:
            vz.VOL_ZONE_FIG_H_NAV = orig_fig_h
        except Exception:
            pass
        try:
            wn._nav_trade_marks = orig_trade
        except Exception:
            pass
        try:
            if "orig_overlay" in locals():
                wn.overlay_nav_marks_on_zone = orig_overlay
        except Exception:
            pass
        try:
            if "orig_sig_arrow" in locals():
                wn._sig_arrow = orig_sig_arrow
        except Exception:
            pass

    info = {
        "as_of": as_of,
        "official_as_of": _dk(official["date"].iloc[-1]),
        "first_k": first_k,
        "last_k": last_k,
        "last_bar": last_bar,
        "hi": pack.get("hi"),
        "lo": pack.get("lo"),
        "spike": _dk(pack.get("spike_date")),
        "spike_lots": spike_lots,
        "spike_i": spike_i,
        "nav_i": ctx["nav_i"],
        "st_i": ctx["st_i"],
        "vz_i": ctx["vz_i"],
        "card": bool(card),
        "emerging": bool(_card_emerging(card)),
        "vol_caption": (vol_cap or "")[:200],
        "buy_audit": buy_audit,
        "paths": {"nav": nav_out, "struct": struct_out, "vol": vol_out},
        "spine_fracs": {
            "nav": ctx.get("nav_spine_frac"),
            "struct": ctx.get("st_spine_frac"),
            "vol": ctx.get("vz_spine_frac"),
        },
        "nav_zone_fracs": ctx.get("nav_zone_fracs"),
        "st_zone_fracs": ctx.get("st_zone_fracs"),
        "vz_zone_fracs": ctx.get("vz_zone_fracs"),
        "st_press_hold": ctx.get("st_press_hold"),
        "st_channel_tip": ctx.get("st_channel_tip"),
        "query_stamp": ctx.get("query_stamp"),
        "stock_id": sid,
        "stock_name": name,
        "sig_frame": {
            "nav_px": ctx.get("nav_sig_h_px"),
            "vz_px": ctx.get("vz_sig_h_px"),
            "match": ctx.get("sig_frame"),
        },
    }
    return info


def _trim_panes(info: dict) -> list[Image.Image]:
    """Crop leftover per-pane chrome so composite can own header/legend/footer."""
    nav = Image.open(info["paths"]["nav"]).convert("RGB")
    st = Image.open(info["paths"]["struct"]).convert("RGB")
    vol = Image.open(info["paths"]["vol"]).convert("RGB")
    nh, nw = nav.height, nav.width
    n0, n1 = int(nh * 0.015), int(nh * 0.955)
    nav = nav.crop((0, n0, nw, n1)).convert("RGB")
    info["nav_zones_px"] = _fracs_to_px(info.get("nav_zone_fracs") or [], nh, n0, n1)
    sh, sw = st.height, st.width
    st, s0 = _crop_below_main_spine(st)
    info["st_zones_px"] = _fracs_to_px(info.get("st_zone_fracs") or [], sh, s0, sh)
    st = _crop_white_tail(st)
    vh, vw = vol.height, vol.width
    v0, v1 = int(vh * 0.010), vh
    vol = vol.crop((0, v0, vw, v1)).convert("RGB")
    info["vz_zones_px"] = _fracs_to_px(info.get("vz_zone_fracs") or [], vh, v0, v1)
    # ③量柱在最底；矮柱（相對爆大量）不准被當留白裁掉
    return [nav, st, vol]


def _draw_tri(d, cx, cy, color, *, up=True, size=18, hollow=False, edge=None, edge_w=3):
    """圖例三角／箭頭（恢復產品色三角，不用圓點）。"""
    half = max(7, size // 2)
    if up:
        pts = [(cx, cy - half - 3), (cx - half - 3, cy + half), (cx + half + 3, cy + half)]
    else:
        pts = [(cx, cy + half + 3), (cx - half - 3, cy - half), (cx + half + 3, cy - half)]
    if hollow:
        d.polygon(pts, outline=edge or color, fill="#ffffff")
        d.line(pts + [pts[0]], fill=edge or color, width=max(2, edge_w))
    else:
        d.polygon(pts, fill=color, outline=edge or color)
        if edge and edge != color:
            d.line(pts + [pts[0]], fill=edge, width=max(2, edge_w))


def _legend_strip(width: int, *, height: int | None = None) -> Image.Image:
    """圖例：三角／字級吃滿列高與欄內空白（老花可讀）；內容置中欄內。"""
    h = int(height if height is not None else round(270 * min(float(CHROME_SCALE), 1.15)))
    sc = min(float(CHROME_SCALE), max(0.85, h / 380.0))
    im = Image.new("RGB", (width, h), "#ffffff")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, width - 1, h - 1], outline="#cfd8dc", width=2)
    rows = [
        [
            ("#7e57c2", "量能異常", "up"),
            ("#ef5350", "警告", "up"),
            ("#ef9a9a", "警告底", "band"),
            ("#29b6f6", "月波動低", "up"),
            ("#1565c0", "買點↑藍▲紅框", "buy"),
            ("#ef6c00", "賣點↓橙", "down"),
        ],
        [
            ("#8e24aa", "20高", "down"),
            ("#fb8c00", "20高脫離", "down"),
            ("#43a047", "20低", "up"),
            ("#00897b", "20低脫離", "up"),
            ("#1e88e5", "60低", "up"),
            ("#e53935", "接近高/低", "hollow_down"),
            ("#90a4ae", "殘影", "up"),
        ],
        [
            ("#f9a825", "月線MA20", "line"),
            ("#5c6bc0", "季線MA60", "line"),
            ("#ad1457", "壓", "line"),
            ("#1b5e20", "撐", "line"),
            ("#e65100", "③窗起", "line"),
            ("#6a1b9a", "爆大量日", "line"),
        ],
    ]
    pad_x = max(12, int(round(12 * sc)))
    y = max(10, int(round(10 * sc)))
    row_h = (h - 2 * y) // 3
    base_lab = max(42, int(round(42 * sc)))
    small_lab = max(34, int(round(34 * sc)))
    for row in rows:
        n = len(row)
        gap = max(6, int(round(6 * sc)))
        cell_w = max(110, int((width - 2 * pad_x - (n - 1) * gap) / max(n, 1)))
        x = pad_x
        for col, lab, kind in row:
            bw, bh = cell_w, row_h - max(8, int(round(8 * sc)))
            d.rounded_rectangle(
                [x, y, x + bw, y + bh],
                radius=max(12, int(round(12 * sc))),
                fill="#f7f9fc",
                outline="#78909c",
                width=max(2, int(round(2 * sc))),
            )
            # 三角讓位給國字：話筒氣泡縮完要先讀到標籤，不准三角吃滿格、字變點
            tri = max(28, min(int(round(44 * sc)), int(bh * 0.40)))
            ff = _font(base_lab, True)
            tw, th = _tw(d, lab, ff)
            room = bw - tri - int(round(28 * sc))
            if tw > room:
                ff = _font(small_lab, True)
                tw, th = _tw(d, lab, ff)
            if tw > room:
                ff = _font(max(28, int(round(28 * sc))), True)
                tw, th = _tw(d, lab, ff)
            gap_icon = max(10, int(round(12 * sc)))
            group_w = tri + gap_icon + tw
            gx = x + max(8, (bw - group_w) // 2)
            cx = gx + tri // 2
            cy = y + bh // 2
            edge_w = max(6, int(round(6 * sc)))
            line_w = max(10, int(round(10 * sc)))
            if kind == "up":
                _draw_tri(d, cx, cy, col, up=True, size=tri)
            elif kind == "down":
                _draw_tri(d, cx, cy, col, up=False, size=tri)
            elif kind == "hollow_down":
                _draw_tri(d, cx, cy, col, up=False, size=tri, hollow=True, edge=col)
            elif kind == "buy":
                _draw_tri(d, cx, cy, col, up=True, size=tri, edge="#c62828", edge_w=edge_w)
            elif kind == "band":
                d.rectangle(
                    [cx - tri // 2, cy - tri // 3, cx + tri // 2, cy + tri // 3],
                    fill=col,
                    outline="#e57373",
                )
            else:
                d.line([cx - tri // 2, cy, cx + tri // 2, cy], fill=col, width=line_w)
            d.text(
                (gx + tri + gap_icon, y + (bh - th) // 2 - 1),
                lab,
                fill="#1a237e",
                font=ff,
            )
            x += bw + gap
        y += row_h
    return im


def _draw_mini_candle(d, cx, cy, *, o, h, l, c, up: bool, body_w=22, body_h=36):
    """表頭今K小圖示：實體＋貫穿影線（對齊①③紅漲綠跌）。"""
    col = CANDLE_UP if up else CANDLE_DN
    ink = WICK_UP if up else WICK_DN
    try:
        span = max(float(h) - float(l), 1e-6)
        top = (float(h) - max(float(o), float(c))) / span
        bot = (min(float(o), float(c)) - float(l)) / span
        y0 = cy - body_h // 2 + int(top * body_h)
        y1 = cy + body_h // 2 - int(bot * body_h)
        if y1 - y0 < 10:
            y1 = y0 + 10
    except Exception:
        y0, y1 = cy - body_h // 3, cy + body_h // 3
    d.rectangle([cx - body_w // 2, y0, cx + body_w // 2, y1], fill=col, outline=col)
    d.line([(cx, cy - body_h // 2 - 10), (cx, cy + body_h // 2 + 10)], fill=ink, width=4)


def _compose(panes: list[Image.Image], info: dict) -> Image.Image:
    """07 C-card, light shadow, short names; one header / legend / footer.

    合成對「對話框點開」：欄寬 COMPOSE_INNER_W、最長邊 ≤2560。
    表頭／圖例字級依這張寬設計（縮圖＋點開都要讀得懂）。
    """
    sc = float(CHROME_SCALE)
    native = max(p.width for p in panes)
    inner_w = min(max(native, 1200), COMPOSE_INNER_W)
    scaled: list[Image.Image] = []
    zscaled: list[list[tuple[int, int]]] = []
    for im, key in zip(panes, ("nav_zones_px", "st_zones_px", "vz_zones_px")):
        oh = im.height
        im2 = _fit_w(im, inner_w)
        zscaled.append(_scale_zones(info.get(key) or [], oh, im2.height))
        scaled.append(im2)
    fitted0 = _match_zone_heights_to_nav(scaled, zscaled)
    # debug：合成前各 pane 框線（確認③是否被軸外標籤拉歪）
    if os.getenv("WAYNE_THREE_DEBUG", "").strip() in ("1", "true", "yes"):
        try:
            dbg = "/opt/cursor/artifacts/6526-frame-debug"
            os.makedirs(dbg, exist_ok=True)
            for i, im in enumerate(fitted0, start=1):
                im.save(f"{dbg}/pre-align-p{i}.jpg", quality=90)
                sl, sr = _pane_spine_lr(im)
                print(
                    f"[pre-align] p{i} size={im.size} spine=({sl},{sr}) "
                    f"frac=({int(im.width*FRAME_LEFT)},{int(im.width*FRAME_RIGHT)})",
                    flush=True,
                )
        except Exception as exc:
            print(f"[pre-align] debug skip: {exc}", flush=True)
    fitted = _align_panes_to_nav_frame(fitted0, spine_fracs=info.get("spine_fracs"))
    margin_x, margin_y = 28, 22
    pad = 10
    title_h = 44
    gap = 14
    extra_last = 20
    # 表頭／圖例固定對 1480 欄；不准 ×CHROME 拉到 775 讓整張超高被 TG 砍最長邊
    head_h = 400
    legend_h = 270
    foot_h = 0  # 使用者不要底部三行小字
    card_w = inner_w + pad * 2
    width = card_w + margin_x * 2
    pane_h_sum = sum(im.height for im in fitted)
    chrome = (
        margin_y * 2
        + head_h
        + 10
        + legend_h
        + 12
        + 3 * (title_h + 8)
        + extra_last
        + gap * 2
        + foot_h
        + pad * 2 * 3
    )
    max_pane = max(900, TG_CLICK_MAX_SIDE - chrome)
    w_scale = min(1.0, inner_w / float(max((im.width for im in fitted), default=inner_w) or inner_w))
    h_scale = min(1.0, max_pane / float(pane_h_sum)) if pane_h_sum else 1.0
    body_scale = min(w_scale, h_scale)
    if body_scale < 0.999:
        fitted = [
            im.resize(
                (max(1, int(round(im.width * body_scale))), max(1, int(round(im.height * body_scale)))),
                Image.Resampling.LANCZOS,
            )
            for im in fitted
        ]
    body = 0
    for idx, im in enumerate(fitted):
        extra = extra_last if idx == 2 else 0
        body += title_h + extra + im.height + pad * 2 + 8
    height = margin_y + head_h + 10 + legend_h + 12 + body + gap * 2 + foot_h + margin_y
    canvas = Image.new("RGBA", (width, height), (232, 238, 245, 255))
    d = ImageDraw.Draw(canvas)

    # header：四欄同字級、同列高；數字畫在色塊正中
    d.rounded_rectangle(
        [margin_x, margin_y, width - margin_x, margin_y + head_h],
        radius=max(14, int(round(14 * sc))),
        fill="#ffffff",
        outline="#b0bec5",
        width=2,
    )
    lb = info["last_bar"]
    vol_lots = int(round(lb["volume"]))
    spike_lots = int(info.get("spike_lots") or 0)
    spike_md = f"{info['spike'][4:6]}/{info['spike'][6:8]}"
    stamp = info.get("query_stamp") or {}
    stamp_date = stamp.get("date") or f"{info['as_of'][:4]}/{info['as_of'][4:6]}/{info['as_of'][6:8]}"
    stamp_clock = stamp.get("clock") or "—"
    is_live = bool(stamp.get("is_live"))
    col_pad = 14
    inner_left = margin_x + col_pad
    inner_right = width - margin_x - col_pad
    col_w = (inner_right - inner_left) / 4.0
    cols_x = [inner_left + i * col_w for i in range(4)]
    # 字級對 1480 欄＋點開視窗；CHROME_SCALE 不再把字拉到欄寬放不下
    f_hint = _font(20, True)
    f_lab = _font(26, True)
    f_num = _font(40, True)
    f_chg = _font(26, True)
    f_title = _font(44, True)
    y_hint = margin_y + 10
    y_row1 = margin_y + 42
    y_row2 = margin_y + 155
    y_row3 = margin_y + 278
    chip_h = 56
    for i in range(1, 4):
        x = int(round(cols_x[i] - 10))
        d.line([x, margin_y + 16, x, margin_y + head_h - 16], fill="#e0e6ed", width=2)
    titles = ("股名", "今K（對查詢日）", "大量區壓撐（③準）", "查詢當下")
    for i, t in enumerate(titles):
        d.text((cols_x[i], y_hint), t, fill="#78909c", font=f_hint)

    sid = str(info.get("stock_id") or "").strip() or "—"
    sname = str(info.get("stock_name") or sid).strip() or sid
    nameplate = f"{sid}  {sname}"
    col_max = max(120, int(col_w) - 12)
    d.text((cols_x[0], y_row1 + 4), nameplate, fill="#1a237e", font=f_title)
    d.text(
        (cols_x[0], y_row1 + 52),
        "技術面三圖合一",
        fill="#546e7a",
        font=f_lab,
    )
    gap0 = 8
    nw, _nh = _draw_chip(
        d, cols_x[0], y_row2, "非買訊",
        font=f_lab, fill="#ffebee", ink="#c62828", outline="#c62828", height=chip_h - 8,
        max_w=col_max,
    )
    remain0 = col_max - nw - gap0
    if remain0 >= 80:
        _draw_chip(
            d, cols_x[0] + nw + gap0, y_row2,
            f"③窗起 {info['first_k'][4:6]}/{info['first_k'][6:8]}",
            font=f_lab, fill="#fff3e0", ink="#e65100", outline="#e65100", height=chip_h - 8,
            max_w=remain0,
        )
    else:
        _draw_chip(
            d, cols_x[0], y_row2 + chip_h - 2,
            f"③窗起 {info['first_k'][4:6]}/{info['first_k'][6:8]}",
            font=f_hint, fill="#fff3e0", ink="#e65100", outline="#e65100",
            height=max(48, chip_h - 24),
            max_w=col_max,
        )
    d.text((cols_x[0], y_row3), "三圖價量＝同官方柱", fill="#78909c", font=f_hint)

    o = float(lb.get("open") or 0)
    hi = float(lb.get("high") or 0)
    lo = float(lb.get("low") or 0)
    cl = float(lb.get("close") or 0)
    prev_c = lb.get("prev_close")
    chg = lb.get("change")
    pct = lb.get("pct")
    fill_c, ink_c, outline_c, up = _header_price_chip_style(
        cl, prev_c, pct, emerging=bool(info.get("emerging"))
    )
    tone = CANDLE_UP if up else CANDLE_DN
    price_lab = "盤中" if is_live else "收盤"
    d.text((cols_x[1], y_row1 + 12), "今K", fill="#546e7a", font=f_lab)
    candle_x = int(cols_x[1] + 58)
    _draw_mini_candle(
        d,
        candle_x,
        y_row1 + 28,
        o=o,
        h=hi,
        l=lo,
        c=cl,
        up=up,
        body_w=20,
        body_h=chip_h - 12,
    )
    price_txt = f"{cl:,.0f}" if cl >= 100 else f"{cl:.2f}"
    price_x = int(candle_x + 22)
    _draw_chip(
        d, price_x, y_row1, f"{price_lab}  {price_txt}",
        font=f_num, fill=fill_c, ink=ink_c, outline=outline_c, height=chip_h,
        pad_x=10,
        max_w=max(80, int(cols_x[1] + col_max - price_x)),
    )
    if chg is not None and pct is not None:
        tri = "▲" if up else "▼"
        sign = "+" if chg >= 0 else ""
        chg_txt = f"{tri} {chg:,.2f}  ({sign}{pct:.2f}%)"
        _draw_chip(
            d, cols_x[1], y_row2, chg_txt,
            font=f_chg, fill="#ffffff", ink=tone, outline=tone, height=chip_h - 8,
            pad_x=10,
            max_w=col_max,
        )
    # OHLC 兩行，不准跨欄
    d.text(
        (cols_x[1], y_row3 - 4),
        f"開{o:.0f} 高{hi:.0f} 低{lo:.0f}",
        fill="#455a64",
        font=f_hint,
    )
    d.text(
        (cols_x[1], y_row3 + 22),
        f"量{vol_lots:,}張",
        fill="#455a64",
        font=f_hint,
    )

    hi_p = float(info["hi"] or 0)
    lo_p = float(info["lo"] or 0)
    # 壓／撐：欄內並排；預估寬度放不下就直疊，不准溢到隔壁欄
    col2_max = col_max
    gap_ps = 8
    probe_p = _tw(d, f"壓  {hi_p:.0f}", f_num)[0] + 20
    probe_s = _tw(d, f"撐  {lo_p:.0f}", f_num)[0] + 20
    if probe_p + gap_ps + probe_s <= col2_max:
        pw, _ = _draw_chip(
            d, cols_x[2], y_row1, f"壓  {hi_p:.0f}",
            font=f_num, fill="#fce4ec", ink="#880e4f", outline="#ad1457",
            height=chip_h, pad_x=10, max_w=col2_max,
        )
        _draw_chip(
            d, cols_x[2] + pw + gap_ps, y_row1, f"撐  {lo_p:.0f}",
            font=f_num, fill="#e8f5e9", ink="#1b5e20", outline="#1b5e20",
            height=chip_h, pad_x=10,
            max_w=max(60, col2_max - pw - gap_ps),
        )
    else:
        stack_h = max(56, chip_h - 22)
        _draw_chip(
            d, cols_x[2], y_row1, f"壓  {hi_p:.0f}",
            font=f_lab, fill="#fce4ec", ink="#880e4f", outline="#ad1457",
            height=stack_h, pad_x=8, max_w=col2_max,
        )
        _draw_chip(
            d, cols_x[2], y_row1 + stack_h + 8, f"撐  {lo_p:.0f}",
            font=f_lab, fill="#e8f5e9", ink="#1b5e20", outline="#1b5e20",
            height=stack_h, pad_x=8, max_w=col2_max,
        )
    _draw_chip(
        d, cols_x[2], y_row2, f"爆大量 {spike_md}  {spike_lots:,}張",
        font=f_lab, fill="#fffde7", ink="#5d4037", outline=SPIKE_BAR_COLOR,
        height=chip_h - 8, pad_x=8, max_w=col2_max,
    )
    d.text((cols_x[2], y_row3), "壓撐＝③有效大量區", fill="#78909c", font=f_hint)

    stamp_wall = stamp.get("query_wall") or ""
    # 日期色塊：優先完整显示；f_num 放不下就改 f_lab，不准裁成 2026/10/02 (…
    date_font = f_num
    date_probe = _tw(d, stamp_date, date_font)[0] + 20
    if date_probe > col_max:
        date_font = f_lab
    _draw_chip(
        d, cols_x[3], y_row1, stamp_date,
        font=date_font, fill="#e8eaf6", ink="#1a237e", outline="#3949ab",
        height=chip_h, pad_x=8, max_w=col_max,
    )
    _draw_chip(
        d, cols_x[3], y_row2, stamp_clock,
        font=f_lab, fill="#e3f2fd", ink="#0d47a1", outline="#1565c0",
        height=chip_h - 8, pad_x=8, max_w=col_max,
    )
    wall_txt = f"查詢 {stamp_wall}" if stamp_wall else "—"
    d.text((cols_x[3], y_row3 - 18), wall_txt, fill="#37474f", font=f_hint)
    d.text((cols_x[3], y_row3 + 8), "橘虛線＝③窗起", fill="#e65100", font=f_hint)
    d.text(
        (cols_x[3], y_row3 + 32),
        "藍虛線＝測壓",
        fill=CEYA_LINE_COLOR,
        font=f_hint,
    )

    y = margin_y + head_h + 10
    legend = _legend_strip(card_w, height=legend_h)
    canvas.paste(legend, (margin_x, y))
    y += legend_h + 12

    names = ("高低導航", "飆大結構", "大量壓力")
    subs = (
        "180日全窗",
        "結構趨勢＋③窗底圖",
        "上＝壓力日K　下＝日成交量（張）＋月日刻度　黃柱＝爆大量日",
    )
    fills = ("#5c6bc0", "#26a69a", "#ef6c00")
    tints = ((247, 249, 252, 255), (245, 250, 247, 255), (255, 248, 243, 255))
    f_t = _font(24, True)
    f_b = _font(16, True)
    f_s = _font(15, True)

    for i, im in enumerate(fitted):
        d = ImageDraw.Draw(canvas)
        extra = extra_last if i == 2 else 0
        d.ellipse([margin_x + 8, y + 6, margin_x + 40, y + 38], fill=fills[i])
        d.text((margin_x + 16, y + 10), str(i + 1), fill="#ffffff", font=f_b)
        d.text((margin_x + 48, y + 8), names[i], fill="#37474f", font=f_t)
        d.text((margin_x + 48, y + 38), subs[i], fill=fills[i], font=f_s)
        y += title_h + extra
        # light card (07 陰影減半)；圖身若比表頭窄則置中，不准拉表頭變窄
        cw, ch = im.width + pad * 2, im.height + pad * 2
        x0 = margin_x + max(0, (card_w - cw) // 2)
        shadow = Image.new("RGBA", (cw + 18, ch + 18), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([6, 8, cw + 6, ch + 10], radius=12, fill=(15, 23, 42, 28))
        shadow = shadow.filter(ImageFilter.GaussianBlur(3))
        canvas.alpha_composite(shadow, (x0 - 2, y - 2))
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=12, fill=tints[i], outline=(176, 190, 197, 255), width=2)
        canvas.alpha_composite(card, (x0, y))
        canvas.paste(im.convert("RGBA"), (x0 + pad, y + pad))
        y += ch + gap

    # 底部三行小字已取消（使用者不要）
    return _fit_telegram_click_view(canvas.convert("RGB"))


def _pending_nav_window_compare(nav_pane: Image.Image, first_k: str, out_dir: str) -> str:
    """待確認：① 是否裁成與③同窗（會少看前面走勢）。不進確認圖。"""
    w, h = nav_pane.size
    # left = current full 180
    left = nav_pane.resize((min(w, 820), max(1, int(h * min(w, 820) / w))), Image.Resampling.LANCZOS)
    # right = mock crop last ~40% of width (approx ③ window on 180-day axis)
    x0 = int(w * 0.52)
    right_src = nav_pane.crop((x0, 0, w, h))
    right = right_src.resize(left.size, Image.Resampling.LANCZOS)
    gap, head, sub, foot = 16, 70, 44, 64
    W = left.width * 2 + gap + 40
    H = head + sub + left.height + foot + 20
    canvas = Image.new("RGB", (W, H), "#eceff1")
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, W, head], fill="#4a148c")
    d.text((16, 18), "待確認｜①要不要裁成跟③同一段窗？", fill="#ffffff", font=_font(26, True))
    d.rectangle([16, head, 16 + left.width, head + sub], fill="#ffcdd2")
    d.rectangle([16 + left.width + gap, head, W - 16, head + sub], fill="#bbdefb")
    d.text((24, head + 10), "現況：①維持 180 日（這張已採用）", fill="#b71c1c", font=_font(18, True))
    d.text((24 + left.width + gap, head + 10), "若裁：只留③窗起以後（會少看前面）", fill="#0d47a1", font=_font(18, True))
    canvas.paste(left, (16, head + sub))
    canvas.paste(right, (16 + left.width + gap, head + sub))
    d.rectangle([0, H - foot, W, H], fill="#263238")
    d.text((16, H - 44), "未採用：裁窗會拿掉 180 日脈絡。要改再說。", fill="#eceff1", font=_font(18, True))
    path = os.path.join(out_dir, "pending-01-nav-crop-to-vol-window.png")
    canvas.save(path, optimize=True)
    return path


def render_lookup_structure_result(
    stock_id: str,
    stock_name: str,
    db_path: str,
    save_path: str,
    *,
    card: Optional[dict] = None,
) -> Tuple[str, str]:
    """查股第 3 張：結構圖＝橫式原版，跟大量撐壓同一套官方日K。買訊只認藍▲紅框。"""
    sid = str(stock_id or "").strip()
    name = str(stock_name or sid).strip() or sid
    if not sid or not db_path or not save_path:
        return "", ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    try:
        from biaoke_chart import (
            _BARS,
            _STRUCTURE_LOOKUP_FIG,
            render_biaoke_structure_png,
            stock_nameplate,
        )
        from vol_zone_chart import (
            VOL_ZONE_DPI,
            load_official_ohlc,
            official_work,
            prepare_volume_zone,
        )

        # 仍走 prepare：同一套官方原柱＋除權息暖機；結構主圖加長交易日補右白
        pack = prepare_volume_zone(sid, name, db_path, save_path)
        if not pack:
            return "", ""
        need = max(int(_BARS) + 20, 280)
        long_df = official_work(load_official_ohlc(sid, db_path, need))
        if long_df is not None and not getattr(long_df, "empty", True) and len(long_df) >= 8:
            bars = _bars_from_official(long_df, sid, name)
        else:
            bars = _bars_from_official(pack["view"], sid, name)
        if len(bars) < 8:
            return "", ""
        path = render_biaoke_structure_png(
            bars,
            save_path,
            sid=sid,
            name=name,
            plate=stock_nameplate(sid, name, db_path),
            db_path=db_path,
            # 橫式滿版對齊範本五；大量撐壓仍用 VOL_ZONE_FIG_* 不動
            figsize=_STRUCTURE_LOOKUP_FIG,
            dpi=VOL_ZONE_DPI,
        )
        if not path or not os.path.isfile(path) or os.path.getsize(path) < 20000:
            return "", ""
        cap = LOOKUP_STRUCTURE_CAPTION
        try:
            from sanchi_clocks import append_sanchi_to_caption

            if isinstance(card, dict):
                cap = append_sanchi_to_caption(cap, card)
        except Exception:
            pass
        return path, cap
    except Exception as exc:
        import logging

        logging.getLogger(__name__).exception("lookup structure render failed: %s", exc)
        return "", ""


def render_three_in_one_result(
    stock_id: str,
    stock_name: str,
    db_path: str,
    save_path: str,
    *,
    card: Optional[dict] = None,
) -> Tuple[str, str]:
    """產品查股第二張：T0118 三合一。回傳 (png_path, caption)。失敗回 ("", "")。"""
    sid = str(stock_id or "").strip()
    name = str(stock_name or sid).strip() or sid
    if not sid or not db_path or not save_path:
        return "", ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    try:
        import contextlib
        import io

        # mock 遺留的 print 除錯不准刷話筒 Render 日誌
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), tempfile.TemporaryDirectory(
            prefix=f"tio-{sid}-"
        ) as tmp:
            info = _apply_patches_and_render(sid, name, db_path, tmp, card=card)
            panes = _trim_panes(info)
            canvas = _compose(panes, info)
            # PNG 快速落檔；送話筒走 _prepare_lookup_album_photo → JPEG q95 無抽樣
            low = str(save_path).lower()
            if low.endswith((".jpg", ".jpeg")):
                canvas.save(
                    save_path,
                    format="JPEG",
                    quality=THREE_IN_ONE_JPEG_QUALITY,
                    subsampling=0,
                    optimize=False,
                )
            else:
                canvas.save(save_path, format="PNG", optimize=False, compress_level=2)
        if not os.path.isfile(save_path) or os.path.getsize(save_path) < 20000:
            return "", ""
        spike = info.get("spike")
        lots = info.get("spike_lots")
        hi = info.get("hi")
        lo = info.get("lo")
        bits = [THREE_IN_ONE_CAPTION_HEAD]
        if spike:
            bits.append(f"爆大量 {_md_slash(str(spike))}")
        if lots:
            bits.append(f"{int(lots):,}張")
        if hi and lo:
            bits.append(f"壓{hi:g}/撐{lo:g}")
        bits.append("買點只認藍▲紅框")
        cap = "　".join(bits)
        try:
            from sanchi_clocks import append_sanchi_to_caption

            if isinstance(card, dict):
                cap = append_sanchi_to_caption(cap, card)
        except Exception:
            pass
        return save_path, cap
    except Exception as exc:
        import logging

        logging.getLogger(__name__).exception("three_in_one render failed: %s", exc)
        return "", ""


def render_three_in_one_png(
    stock_id: str,
    stock_name: str,
    db_path: str,
    save_path: str,
    *,
    card: Optional[dict] = None,
) -> str:
    path, _cap = render_three_in_one_result(
        stock_id, stock_name, db_path, save_path, card=card
    )
    return path or ""


def main() -> int:
    """本機煙測：WAYNE_SKIP_POLLING=1；預設 6526。"""
    from config import get_db_path

    sid = (sys.argv[1] if len(sys.argv) > 1 else "6526").strip()
    name = (sys.argv[2] if len(sys.argv) > 2 else sid).strip()
    db = get_db_path()
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        tempfile.gettempdir(), f"three-in-one-{sid}.png"
    )
    path, cap = render_three_in_one_result(sid, name, db, out)
    meta = {"sid": sid, "name": name, "out": path, "caption": cap, "lock_key": LOCK_KEY}
    if path and os.path.isfile(path):
        meta["bytes"] = os.path.getsize(path)
        im = Image.open(path)
        meta["size"] = [im.width, im.height]
    print(json.dumps(meta, ensure_ascii=False))
    return 0 if path else 1


if __name__ == "__main__":
    raise SystemExit(main())
