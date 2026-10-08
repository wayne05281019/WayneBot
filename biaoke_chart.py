# -*- coding: utf-8 -*-
"""飆大視窗專用結構圖：個股看官方日 K 量先價行。

只給按了「飆大」之後的對話。不是介紹圖、不是決策卡、不進海選。
個股主圖＝日 K：近窗仍有效爆大量日最高當壓、最低當撐（與大量區專圖同一套）。
15／60 分只拿來看大盤／台指期，不准畫在這張個股圖上。
連點軌道是輔助（兩個更低的高＝下降壓／兩個更高的低或 2–4 低＝上升軌）；不夠兩點就不畫。
通道＝主連點＋平行另一緣（二擇一），升／降軌道破壞才算轉折。
1～5 只准從已確認的錨往前推（大盤＝他自己的第五波高；個股＝下降壓的前高），不准亂數。
不准把「三日底點不破」畫成他的固定公式。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib import patches
from matplotlib.collections import LineCollection, PolyCollection

from wayne_navigator import (
    _fp,
    _mpl_serial,
    paint_lookup_ohlc_candles,
    paint_lookup_volume_bars,
)

BIAOKE_CHART_DPI = 200
# 偏好用語＝演化區（圖上連點／壓撐延長空白）；不是保證、不是買訊
EVOLUTION_ZONE_LABEL = "演化區（不是保證・不是買訊）"

logger = logging.getLogger("WayneBot.BiaokeChart")

_BG = "#ffffff"
_PANEL = "#ffffff"
_GRID = "#cfd8dc"
_TEXT = "#1f2933"
_UP = "#e53935"
_DN = "#00897b"
_HALT = "#9e9e9e"
_PRESS = "#ad1457"
_HOLD = "#1b5e20"
_DOWN_TRACK = "#6a1b9a"
_UP_TRACK = "#0277bd"
_CH_ASC = "#00897b"  # 上升通道雙線（對齊附圖青綠色調，白底可讀）
_CH_DESC = "#00838f"  # 下降通道雙線
_WASH = "#ef6c00"
_SPIKE_VOL = "#f9a825"
# 查股結構橫式：交易日窗鎖下限≈八個月（可略多不可少）；大量撐壓近窗不動
_BARS_MIN_MONTHS = 8
_BARS_PER_MONTH = 21  # 台股約月均交易日
_BARS_MIN = int(_BARS_MIN_MONTHS * _BARS_PER_MONTH)  # 168
_BARS = 240  # ≈12 個月；必須 ≥ _BARS_MIN
_FUTURE = 10
assert _BARS >= _BARS_MIN
_PROJECT = "#e65100"
_FORK = "#5d4037"
_FUTURE_BG = "#fff6e0"
_WINDOW_BG = "#ffe0b2"
_HALO = "#ffffff"
_FRAME = "#90a4ae"
_MUTED = "#607d8b"
# 查股結構圖只留右邊股價／量刻度（左邊拿掉，避免雙軸互壓）
# 主圖左右略拉長：回收左緣空白給 K 區，右溝仍留「最可能」整盒
_FIG_LEFT = 0.028
_FIG_RIGHT = 0.918
# 結構圖右溝要塞「最可能＝看壓 ####」整盒＋邊框；右緣再留 y 刻度，不准貼齊裁切
_STRUCTURE_FIG_RIGHT = 0.948
# 直式 4:5：縮圖靠右，左邊留給頭牌，不准今K／日期壓進迷你圖
_LOOKUP_LOCATOR_LEFT = 0.575
_FIG_BOTTOM = 0.055
_FIG_BOTTOM_FB = 0.062
# 舊直式：頭牌帶在圖上方。橫式：介紹帶在上方，下緣＝主圖上緣（不准浮在 K 上壓柱）
_STOCK_MAIN_TOP = 0.658
# 橫式 pass2b：介紹帶再增高，左右欄行距拉開不准黏成一塊
_STOCK_MAIN_TOP_FULLBLEED = 0.688
_LOCATOR_LEFT = 0.500
_LOCATOR_WIDTH = _FIG_RIGHT - _LOCATOR_LEFT
_STOCK_LOCATOR_BOTTOM = 0.690
_STOCK_LOCATOR_HEIGHT = 0.278
# 橫式介紹帶：迷你圖仍在帶內右上，不准疊進主圖 K
_STOCK_LOCATOR_BOTTOM_FB = 0.712
_STOCK_LOCATOR_HEIGHT_FB = 0.248
# 縮圖右緣＝主圖右緣，上下一條線。
_STOCK_LOCATOR_RECT = (
    _LOCATOR_LEFT,
    _STOCK_LOCATOR_BOTTOM,
    _LOCATOR_WIDTH,
    _STOCK_LOCATOR_HEIGHT,
)
_STOCK_LOCATOR_RECT_FB = (
    _LOCATOR_LEFT,
    _STOCK_LOCATOR_BOTTOM_FB,
    _STRUCTURE_FIG_RIGHT - _LOCATOR_LEFT,
    _STOCK_LOCATOR_HEIGHT_FB,
)
_HEADER_X = 4.60
_HEADER_X_FB = 5.20
# 今K／漲跌：右對齊縮圖左緣；無迷你圖時略內收，吃掉中間死白、不貼右裁
_SPOT_X = _LOCATOR_LEFT * 100.0 - 0.25
_SPOT_X_NO_LOCATOR = 91.2
_SPOT_Y = 97.35
# 左上頭牌可佔到縮圖左側空白前（今K已移走）；橫式無迷你圖時拉寬晶片列
_HEADER_CHIP_MAX = 48.5
_HEADER_CHIP_MAX_FB = 82.0
# 查股結構圖橫式長寬比對齊範本五（約 1.52）；大量撐壓 figsize 不动
_STRUCTURE_LOOKUP_FIG = (12.4, 12.4 / 1.52)


def _style_frame(ax, *, hide_top=False) -> None:
    for sp in ax.spines.values():
        sp.set_color(_FRAME)
        sp.set_linewidth(0.85)
    if hide_top:
        ax.spines["top"].set_visible(False)


def _bar_is_halt(row: Dict[str, Any]) -> bool:
    if bool(row.get("is_halt")):
        return True
    try:
        vol = float(row.get("volume") or 0)
        hi = float(row.get("high") or 0)
        lo = float(row.get("low") or 0)
        return vol <= 0 and abs(hi - lo) <= 1e-8
    except (TypeError, ValueError):
        return False


def _md(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{int(t[4:6])}/{int(t[6:8])}"
    return str(raw or "").strip()


def _axis_ticks(n: int, extra: Sequence[int] = ()) -> List[int]:
    """頭尾必留。靠近尾端或爆量日的中間刻度拿掉，避免 09/09 疊在 09/14 上。

    爆量日若離最後一根 <4，只留最後一根（爆量另有豎虛線＋量標），不准日刻互壓。
    """
    n = int(n or 0)
    if n <= 0:
        return []
    if n == 1:
        return [0]
    last = n - 1
    min_extra_gap = 4
    extras = [
        int(x)
        for x in extra
        if 0 <= int(x) < n and abs(int(x) - last) >= min_extra_gap
    ]
    step = max(n // 7, 4)
    raw = list(range(0, n, step))
    if last not in raw:
        raw.append(last)
    for x in extras:
        if x not in raw:
            raw.append(x)
    keep: List[int] = []
    for i in sorted(set(raw)):
        if i in (0, last) or i in extras:
            keep.append(i)
            continue
        if any(abs(i - e) < 5 for e in extras):
            continue
        if abs(i - last) < 4:
            continue
        keep.append(i)
    return keep


def _ymd_full(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return str(raw or "").strip()


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return "—"
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _vol(val: Any) -> str:
    try:
        n = int(round(float(val or 0)))
    except (TypeError, ValueError):
        return "—"
    return f"{n:,}張"


def _bar_ohlc(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": str(row.get("date") or ""),
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "volume": row.get("volume"),
    }


def _pivots(highs: Sequence[float], lows: Sequence[float], *, left: int = 3) -> Tuple[List[int], List[int]]:
    n = len(highs)
    hi_p: List[int] = []
    lo_p: List[int] = []
    if n < left * 2 + 1:
        return hi_p, lo_p
    for i in range(left, n - 1):
        window_h = highs[i - left : i + left + 1]
        window_l = lows[i - left : i + left + 1]
        if highs[i] >= max(window_h) and highs[i] > 0:
            hi_p.append(i)
        if lows[i] <= min(window_l) and lows[i] > 0:
            lo_p.append(i)
    return hi_p, lo_p


def _desc_high_pair(hi_p: Sequence[int], highs: Sequence[float]) -> Optional[Tuple[int, int]]:
    """只連最近兩個樞紐高，而且後高必須更低。中間若有更高的高，不准跳過去畫假下降壓。"""
    if len(hi_p) < 2:
        return None
    i, j = int(hi_p[-2]), int(hi_p[-1])
    if j - i < 3:
        return None
    if highs[j] >= highs[i] * 0.999:
        return None
    mid = highs[i + 1 : j]
    if mid and max(mid) > highs[i] + 1e-9:
        return None
    return i, j


def _asc_low_pair(lo_p: Sequence[int], lows: Sequence[float]) -> Optional[Tuple[int, int]]:
    """只連最近兩個樞紐低，而且後低必須更高。中間若有更低的低，不准跳過去畫假上升撐。"""
    if len(lo_p) < 2:
        return None
    i, j = int(lo_p[-2]), int(lo_p[-1])
    if j - i < 3:
        return None
    if lows[j] <= lows[i] * 1.001:
        return None
    mid = lows[i + 1 : j]
    if mid and min(mid) < lows[i] - 1e-9:
        return None
    return i, j


def _rail_broken(last: float, y_now: float, *, above_is_ok: bool) -> bool:
    """上升撐：收在線下＝壞；下降壓：收在線上＝已過（不算『還壓著』）。"""
    if not y_now:
        return False
    if above_is_ok:
        return float(last) < float(y_now)
    return float(last) > float(y_now)


def _rail_slope_too_steep(
    x1: float, y1: float, x2: float, y2: float, *, span: float, n: int
) -> bool:
    """斜率過陡＝連點不可當有效撐／壓延長（例如兩點價差吃掉整段高低幅）。"""
    dx = float(x2) - float(x1)
    if dx < 3:
        return True
    dy = abs(float(y2) - float(y1))
    if span <= 0:
        return False
    # 每根漲超過全日高低幅 4% 就當過陡（2383 3930→5255 會觸發）
    return (dy / dx) > (span * 0.04)


def _pivot_pairs(
    pivots: Sequence[int],
    values: Sequence[float],
    *,
    ascending: bool,
    min_gap: int = 5,
    look: int = 10,
) -> List[Tuple[int, int]]:
    """從近窗樞紐找可用連點：升＝後低更高；降＝後高更低。中間不准被反向極端打穿。"""
    pts = [int(p) for p in pivots if 0 <= int(p) < len(values)]
    if len(pts) < 2:
        return []
    recent = pts[-look:] if len(pts) > look else pts
    out: List[Tuple[int, int]] = []
    for ai in range(len(recent)):
        for bi in range(ai + 1, len(recent)):
            i, j = recent[ai], recent[bi]
            if j - i < min_gap:
                continue
            yi, yj = float(values[i]), float(values[j])
            if yi <= 0 or yj <= 0:
                continue
            if ascending:
                if yj <= yi * 1.001:
                    continue
                mid = [float(values[k]) for k in range(i + 1, j)]
                if mid and min(mid) < yi - 1e-9:
                    continue
            else:
                if yj >= yi * 0.999:
                    continue
                mid = [float(values[k]) for k in range(i + 1, j)]
                if mid and max(mid) > yi + 1e-9:
                    continue
            out.append((i, j))
    return out


def _channel_width_touch(
    base_i: int,
    base_j: int,
    base_y1: float,
    base_y2: float,
    touch_pivots: Sequence[int],
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    above: bool,
    span: float,
    n: int,
) -> Optional[Tuple[int, float, float]]:
    """以他的主連點為底線，找平行寬度觸點（升軌找高；降壓找低）。用官方高低核對包覆。"""
    best: Optional[Tuple[int, float, float]] = None
    x1, x2 = float(base_i), float(base_j)
    for k in touch_pivots:
        kk = int(k)
        if kk < base_i or kk >= n:
            continue
        # 觸點最好落在兩連點之間或稍後，太遠就不像同一條通道
        if kk > base_j + max(18, (base_j - base_i) * 2):
            continue
        base_at = _line_at(x1, base_y1, x2, base_y2, float(kk))
        tv = float(highs[kk] if above else lows[kk])
        if tv <= 0:
            continue
        width = (tv - base_at) if above else (base_at - tv)
        if width < span * 0.035 or width > span * 0.85:
            continue
        inside = 0
        total = 0
        breach = 0
        for t in range(base_i, n):
            b = _line_at(x1, base_y1, x2, base_y2, float(t))
            hi = float(highs[t])
            lo = float(lows[t])
            if hi <= 0 or lo <= 0:
                continue
            total += 1
            if above:
                lo_b, hi_b = b, b + width
            else:
                lo_b, hi_b = b - width, b
            # 柱體有重疊通道才算「在裡面」
            if lo <= hi_b + span * 0.01 and hi >= lo_b - span * 0.01:
                inside += 1
            if above and hi > hi_b + span * 0.05:
                breach += 1
            if (not above) and lo < lo_b - span * 0.05:
                breach += 1
        if total < 8:
            continue
        ratio = inside / max(total, 1)
        if ratio < 0.55:
            continue
        freshness = 1.0 - (n - 1 - kk) / max(n, 1)
        score = ratio * 2.0 + freshness * 0.8 - breach * 0.12
        score -= abs(width / span - 0.28) * 0.45
        # 觸點靠近第二連點加分（跟他畫法：通道寬度常由近段極端定）
        score += max(0.0, 1.0 - abs(kk - base_j) / max(n * 0.25, 1)) * 0.35
        if best is None or score > best[2]:
            best = (kk, width, score)
    return best


def infer_parallel_channel(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """依飆大連點長上升／下降通道（二擇一、兩條平行線）。

    桌面規則原文精神：
    - 高連更低高＝下降壓（上軌）；平行下緣貼合理低＝通道下軌
    - 同次級／更高低連點＝上升軌（下軌）；平行上緣貼合理高＝通道上軌
    - 升／降軌道破壞才算轉折；個股不數 5／9 當操作
    - 兩種不准同時畫；不是買訊
    """
    rows = list(rows or [])
    n = len(rows)
    if n < 24:
        return {}
    highs = [float(r.get("high") or 0) for r in rows]
    lows = [float(r.get("low") or 0) for r in rows]
    closes = [float(r.get("close") or 0) for r in rows]
    last = float(closes[-1] or 0)
    pos_lows = [v for v in lows if v > 0]
    if not pos_lows:
        return {}
    span = max(max(highs) - min(pos_lows), 1.0)
    hi_p, lo_p = _pivots(highs, lows, left=3)
    cands: List[Dict[str, Any]] = []

    def _pack_desc(i: int, j: int, *, bonus: float = 0.0) -> None:
        # 通道主軌至少約兩週：過短兩點延長上話筒會像假錨
        if int(j) - int(i) < 10:
            return
        touch = _channel_width_touch(
            i, j, highs[i], highs[j], lo_p, highs, lows, above=False, span=span, n=n
        )
        if not touch or _rail_slope_too_steep(i, highs[i], j, highs[j], span=span, n=n):
            return
        k, width, score = touch
        top_now = _line_at(i, highs[i], j, highs[j], n - 1)
        base_now = top_now - width
        if last > top_now + span * 0.02:
            pos, alive = "過下降壓", False
        elif last < base_now - span * 0.02:
            pos, alive = "破平行撐", True
        elif last >= base_now + width * 0.66:
            pos, alive = "靠近下降壓", True
        elif last <= base_now + width * 0.34:
            pos, alive = "靠近平行撐", True
        else:
            pos, alive = "下降通道中段", True
        # 較長真連點加分（兩點距離夠才像他畫的軌道）
        span_bonus = min((int(j) - int(i)) / 24.0, 1.0) * 0.45
        cands.append(
            {
                "kind": "desc",
                "score": float(score)
                + bonus
                + span_bonus
                + (0.35 if alive and last < top_now else 0.0),
                "alive": alive,
                "pos": pos,
                "width": width,
                "base": (
                    (i, highs[i], str(rows[i].get("date") or "")),
                    (j, highs[j], str(rows[j].get("date") or "")),
                ),
                "touch": (k, lows[k], str(rows[k].get("date") or "")),
                "base_now": base_now,
                "rail_now": top_now,
            }
        )

    def _pack_asc(i: int, j: int, *, bonus: float = 0.0) -> None:
        if int(j) - int(i) < 10:
            return
        touch = _channel_width_touch(
            i, j, lows[i], lows[j], hi_p, highs, lows, above=True, span=span, n=n
        )
        if not touch or _rail_slope_too_steep(i, lows[i], j, lows[j], span=span, n=n):
            return
        k, width, score = touch
        base_now = _line_at(i, lows[i], j, lows[j], n - 1)
        top_now = base_now + width
        if last < base_now - span * 0.02:
            pos, alive = "破上升軌", False
        elif last > top_now + span * 0.02:
            pos, alive = "過平行壓", True
        elif last >= base_now + width * 0.66:
            pos, alive = "靠近平行壓", True
        elif last <= base_now + width * 0.34:
            pos, alive = "靠近上升軌", True
        else:
            pos, alive = "上升通道中段", True
        span_bonus = min((int(j) - int(i)) / 24.0, 1.0) * 0.45
        cands.append(
            {
                "kind": "asc",
                "score": float(score)
                + bonus
                + span_bonus
                + (0.35 if alive and last > base_now else -0.35),
                "alive": alive,
                "pos": pos,
                "width": width,
                "base": (
                    (i, lows[i], str(rows[i].get("date") or "")),
                    (j, lows[j], str(rows[j].get("date") or "")),
                ),
                "touch": (k, highs[k], str(rows[k].get("date") or "")),
                "base_now": base_now,
                "rail_now": top_now,
            }
        )

    # 1) 他的標準下降壓：最近兩樞紐高、後高更低、中間不高過前高
    down = _desc_high_pair(hi_p, highs)
    if down:
        _pack_desc(int(down[0]), int(down[1]), bonus=0.55)
    # 備援：近窗其他合格更低高連點（仍要過包覆閘；min_gap=10＝有長度的兩點）
    for i, j in _pivot_pairs(hi_p, highs, ascending=False, min_gap=10, look=8):
        if down and (i, j) == (int(down[0]), int(down[1])):
            continue
        _pack_desc(i, j, bonus=0.05)

    # 2) 上升軌：優先同段 2 低連 4 低（下降壓確認後）；否則更高低連點
    up = None
    if down:
        up = _impulse_support_pair(rows, int(down[0]))
    if up is None:
        up = _asc_low_pair(lo_p, lows)
    if up:
        _pack_asc(int(up[0]), int(up[1]), bonus=0.55)
    for i, j in _pivot_pairs(lo_p, lows, ascending=True, min_gap=10, look=8):
        if up and (i, j) == (int(up[0]), int(up[1])):
            continue
        _pack_asc(i, j, bonus=0.05)

    if not cands:
        return {}

    # 二擇一：還壓著的下降壓優先於已破的上升軌；兩邊都活就比分＋近端
    for c in cands:
        j = int(c["base"][1][0])
        c["score"] = float(c["score"]) + (j / max(n, 1)) * 0.4
        if c["kind"] == "desc" and last < float(c["rail_now"]):
            c["score"] += 0.45  # 收在下降壓下＝他還在講「還壓著」
        if c["kind"] == "asc" and last > float(c["base_now"]):
            c["score"] += 0.35

    best = max(cands, key=lambda c: float(c["score"]))
    # 若最佳是升、但同時有明顯還壓著的降，改採降（兩種不准並存）
    if best["kind"] == "asc":
        pressed = [
            c
            for c in cands
            if c["kind"] == "desc" and last < float(c["rail_now"]) and c.get("alive")
        ]
        if pressed:
            best = max(pressed, key=lambda c: float(c["score"]))
    elif best["kind"] == "desc" and last > float(best["rail_now"]):
        held = [
            c
            for c in cands
            if c["kind"] == "asc" and last > float(c["base_now"]) and c.get("alive")
        ]
        if held and float(held[0]["score"]) > float(best["score"]) - 0.2:
            best = max(held, key=lambda c: float(c["score"]))

    kind = str(best["kind"])
    (x1, y1, d1), (x2, y2, d2) = best["base"]
    tk, ty, td = best["touch"]
    width = float(best["width"])
    if kind == "asc":
        upper = ((x1, y1 + width, d1), (x2, y2 + width, d2))
        lower = ((x1, y1, d1), (x2, y2, d2))
        label = f"上升軌通道　{best['pos']}"
        tip = (
            f"上升軌：{_md(d1)}低{_px(y1)}～{_md(d2)}低{_px(y2)}；"
            f"平行壓貼 {_md(td)}高{_px(ty)}；現況{best['pos']}。"
            f"破上升軌才像轉折。不是買訊。"
        )
        name_u, name_l = "平行壓", "上升軌"
    else:
        upper = ((x1, y1, d1), (x2, y2, d2))
        lower = ((x1, y1 - width, d1), (x2, y2 - width, d2))
        label = f"下降壓通道　{best['pos']}"
        tip = (
            f"下降壓：{_md(d1)}高{_px(y1)}～{_md(d2)}高{_px(y2)}；"
            f"平行撐貼 {_md(td)}低{_px(ty)}；現況{best['pos']}。"
            f"過下降壓才像準備突破機會，不是保證、不是買訊。"
        )
        name_u, name_l = "下降壓", "平行撐"
    return {
        "kind": kind,
        "label": label,
        "tip": tip,
        "pos": best["pos"],
        "alive": bool(best["alive"]),
        "width": width,
        "base": best["base"],
        "upper": upper,
        "lower": lower,
        "touch": (tk, ty, td),
        "base_now": float(best["base_now"]),
        "rail_now": float(best["rail_now"]),
        "score": float(best["score"]),
        "name_u": name_u,
        "name_l": name_l,
    }


def _paint_parallel_channel(
    ax,
    ch: Dict[str, Any],
    *,
    seam: float,
    x_lo: float,
    x_hi: float,
    y_lo: float,
    y_hi: float,
    n: int,
) -> None:
    """畫上升或下降通道兩條平行線；標籤強制落在軸內，不准切一半。

    真連點只標主軌兩點＋平行寬度觸點。平行緣是主軌平移，不准再撒假樞紐點。
    """
    if not ch:
        return
    kind = str(ch.get("kind") or "")
    # 顏色跟他用語對齊：下降壓紫、上升軌藍
    color = _UP_TRACK if kind == "asc" else _DOWN_TRACK
    alive = bool(ch.get("alive"))
    if not alive:
        color = "#90a4ae"
    upper = ch.get("upper") or ()
    lower = ch.get("lower") or ()
    if len(upper) < 2 or len(lower) < 2:
        return
    (ux1, uy1, _ud1), (ux2, uy2, _ud2) = upper
    (lx1, ly1, _ld1), (lx2, ly2, _ld2) = lower
    # 有效才延長進演化區；已壞／已過只畫到最近一根
    rail_hi = float(x_hi) if alive else float(seam)
    for x1, y1, x2, y2 in (
        (ux1, uy1, ux2, uy2),
        (lx1, ly1, lx2, ly2),
    ):
        _paint_extended_rail(
            ax,
            float(x1),
            float(y1),
            float(x2),
            float(y2),
            seam=float(seam),
            x_lo=float(x_lo),
            x_hi=rail_hi,
            y_lo=float(y_lo),
            y_hi=float(y_hi),
            color=color,
        )
    touch = ch.get("touch")
    if touch:
        ax.scatter(
            [float(touch[0])],
            [float(touch[1])],
            color=color,
            s=36,
            zorder=7,
            edgecolors="white",
            linewidths=0.7,
        )
    # 主軌兩點＝真樞紐；升＝下緣低點、降＝上緣高點。不准把平行緣端點當連點。
    if kind == "asc":
        ax.scatter(
            [float(lx1), float(lx2)],
            [float(ly1), float(ly2)],
            color=color,
            s=28,
            zorder=6,
            edgecolors="white",
            linewidths=0.6,
        )
    else:
        ax.scatter(
            [float(ux1), float(ux2)],
            [float(uy1), float(uy2)],
            color=color,
            s=28,
            zorder=6,
            edgecolors="white",
            linewidths=0.6,
        )
    # 軌價標籤走右溝；通道狀態改上頭牌晶片，不准壓在 K 棒上


def _line_at(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    if x2 == x1:
        return y2
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def _clip_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    x_lo: float,
    x_hi: float,
    y_lo: float,
    y_hi: float,
) -> Optional[Tuple[float, float, float, float]]:
    """兩點連線拉到圖框左右，超出上下就裁。不准另造樞紐。"""
    x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    x_lo, x_hi = float(x_lo), float(x_hi)
    y_lo, y_hi = float(y_lo), float(y_hi)
    if x_hi <= x_lo or y_hi <= y_lo:
        return None
    if abs(x2 - x1) < 1e-9:
        if not (x_lo <= x1 <= x_hi):
            return None
        lo, hi = sorted((y1, y2))
        a, b = max(y_lo, lo), min(y_hi, hi)
        if b <= a:
            return None
        return x1, a, x1, b

    def y_at(x: float) -> float:
        return _line_at(x1, y1, x2, y2, x)

    def x_at(y: float) -> float:
        return x1 + (x2 - x1) * (y - y1) / (y2 - y1)

    xl, xr = x_lo, x_hi
    yl, yr = y_at(xl), y_at(xr)

    def _fit(x: float, y: float) -> Optional[Tuple[float, float]]:
        if y_lo <= y <= y_hi:
            return x, y
        if abs(y2 - y1) < 1e-9:
            return None
        yb = y_hi if y > y_hi else y_lo
        xn = x_at(yb)
        if xn < x_lo - 1e-6 or xn > x_hi + 1e-6:
            return None
        return max(x_lo, min(x_hi, xn)), yb

    left = _fit(xl, yl)
    right = _fit(xr, yr)
    if left is None or right is None:
        return None
    xa, ya = left
    xb, yb = right
    if xa > xb:
        xa, ya, xb, yb = xb, yb, xa, ya
    if xb - xa < 0.6:
        return None
    return xa, ya, xb, yb


def _paint_extended_rail(
    ax,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    seam: float,
    x_lo: float,
    x_hi: float,
    y_lo: float,
    y_hi: float,
    color: str,
) -> None:
    """實線拉到最近一根，虛線進演化區。左緣有空間就延長，跟上升撐同一套。"""
    clipped = _clip_line(
        x1, y1, x2, y2, x_lo=x_lo, x_hi=x_hi, y_lo=y_lo, y_hi=y_hi
    )
    if not clipped:
        return
    xa, ya, xb, yb = clipped
    if xa < seam:
        xs = [xa, min(xb, seam)]
        ys = [ya, _line_at(x1, y1, x2, y2, xs[1])]
        _halo_line(ax, xs, ys, color, lw=1.35, halo=0.9, ls="-", z=5)
    if xb > seam:
        xs = [max(xa, seam), xb]
        ys = [_line_at(x1, y1, x2, y2, xs[0]), yb]
        _halo_line(ax, xs, ys, color, lw=1.35, halo=0.9, ls=(0, (4, 2.2)), z=5)


def analyze_structure(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """從官方日 K 還原他那套：量價高低、連點、破線洗盤。不數段。"""
    from biaoke_brain import volume_first_price

    rows = list(bars or [])
    out: Dict[str, Any] = {"n": len(rows)}
    if len(rows) < 8:
        return out
    highs = [float(r.get("high") or 0) for r in rows]
    lows = [float(r.get("low") or 0) for r in rows]
    closes = [float(r.get("close") or 0) for r in rows]
    vols = [float(r.get("volume") or 0) for r in rows]
    struct = volume_first_price(rows, lookback=min(40, len(rows)))
    out["struct"] = struct
    spike_hi = float(struct.get("spike_high") or 0)
    spike_lo = float(struct.get("spike_low") or 0)
    spike_date = str(struct.get("spike_date") or "")
    spike_i = 0
    want = spike_date.replace("-", "")[:8]
    for i, r in enumerate(rows):
        if str(r.get("date") or "").replace("-", "")[:8] == want:
            spike_i = i
            break
    out["spike_i"] = spike_i
    out["spike_bar"] = _bar_ohlc(rows[spike_i]) if 0 <= spike_i < len(rows) else {}
    out["last_bar"] = _bar_ohlc(rows[-1])
    last = closes[-1] if closes else 0
    broke = False
    reclaim = False
    saw_over = False
    for i in range(spike_i + 1, len(rows)):
        if spike_lo and lows[i] < spike_lo:
            broke = True
        if broke and closes[i] >= spike_lo:
            reclaim = True
        if spike_hi and closes[i] >= spike_hi:
            saw_over = True
    out["wash"] = bool(broke and reclaim and last >= spike_lo)
    out["under_support"] = bool(spike_lo and last < spike_lo)
    out["over_press"] = bool(spike_hi and last >= spike_hi)
    out["distribution"] = bool(saw_over and last < spike_lo and not out["wash"])
    hi_p, lo_p = _pivots(highs, lows)
    down = _desc_high_pair(hi_p, highs)
    up = None
    if down:
        up = _impulse_support_pair(rows, int(down[0]))
    if up is None:
        up = _asc_low_pair(lo_p, lows)
    out["down_track"] = down
    out["up_track"] = up
    n = len(rows)
    notes: List[str] = []
    last_bar = out.get("last_bar") or {}
    spike_bar = out.get("spike_bar") or {}
    if last_bar:
        notes.append(
            f"最近收盤日 {_ymd_full(last_bar.get('date'))} "
            f"開 {_px(last_bar.get('open'))} 高 {_px(last_bar.get('high'))} "
            f"低 {_px(last_bar.get('low'))} 收 {_px(last_bar.get('close'))} "
            f"量 {_vol(last_bar.get('volume'))}"
        )
    if spike_hi and spike_lo:
        notes.append(
            f"官方日K（不是15分）量先價行：爆大量那一天 {_ymd_full(spike_date) or spike_date} "
            f"開 {_px(spike_bar.get('open'))} 高 {_px(spike_hi)} 當壓、"
            f"低 {_px(spike_lo)} 當撐、收 {_px(spike_bar.get('close'))} "
            f"量 {_vol(spike_bar.get('volume'))}；站上撐後等價穩量縮才進，否則放棄。"
        )
    if down:
        a, b = down
        y_now = _line_at(a, highs[a], b, highs[b], n - 1)
        out["down_now"] = y_now
        out["down_pts"] = (
            (a, highs[a], str(rows[a].get("date") or "")),
            (b, highs[b], str(rows[b].get("date") or "")),
        )
        if last < y_now:
            notes.append(
                f"下降連點 {_md(rows[a].get('date'))}高{_px(highs[a])}～"
                f"{_md(rows[b].get('date'))}高{_px(highs[b])}，"
                f"延長到最近約 {_px(y_now)}，還壓著；要過這價才像真突破下降壓"
            )
        else:
            notes.append(
                f"下降連點 {_md(rows[a].get('date'))}高{_px(highs[a])}～"
                f"{_md(rows[b].get('date'))}高{_px(highs[b])}，"
                f"延長到最近約 {_px(y_now)}，收在上面；還要量價確認"
            )
    if up:
        a, b = up
        y_now = _line_at(a, lows[a], b, lows[b], n - 1)
        out["up_now"] = y_now
        out["up_pts"] = (
            (a, lows[a], str(rows[a].get("date") or "")),
            (b, lows[b], str(rows[b].get("date") or "")),
        )
        broken = _rail_broken(last, y_now, above_is_ok=True)
        out["up_broken"] = broken
        span_u = max(max(highs) - min(lows), 1.0) if highs and lows else 1.0
        out["up_steep"] = _rail_slope_too_steep(a, lows[a], b, lows[b], span=span_u, n=n)
        if broken:
            notes.append(
                f"上升連點 {_md(rows[a].get('date'))}低{_px(lows[a])}～"
                f"{_md(rows[b].get('date'))}低{_px(lows[b])}，"
                f"延長到最近約 {_px(y_now)}，收在下面，這條上升軌先當壞了；"
                f"壞掉就不往演化區延長當還有效"
            )
        else:
            notes.append(
                f"上升連點 {_md(rows[a].get('date'))}低{_px(lows[a])}～"
                f"{_md(rows[b].get('date'))}低{_px(lows[b])}，"
                f"延長到最近約 {_px(y_now)}，收在上面；破這條才像軌壞掉"
            )
    if out["wash"]:
        notes.append("破撐之後又站回，比較像破線洗盤，不是保證")
    elif out.get("distribution"):
        notes.append("過壓之後又掉回撐下，比較像出貨，不是洗盤")
    # 大量日高／低判斷句（收在低下／已過高等）全股票都不打進結構圖
    # 上升／下降通道二擇一（平行雙線）；與單軌連點並行記錄，畫圖時通道優先
    ch = infer_parallel_channel(rows)
    if ch:
        out["channel"] = ch
        notes.append(str(ch.get("tip") or ch.get("label") or ""))
    out["highs"] = highs
    out["lows"] = lows
    out["closes"] = closes
    out["vols"] = vols
    proj = project_next(out)
    out["project"] = proj
    if proj.get("label"):
        notes.append("圖上演算：" + str(proj.get("label")))
    out["notes"] = notes
    return out


def project_next(info: Dict[str, Any]) -> Dict[str, Any]:
    """用壓撐＋連點＋量縮，演算接下來幾根最可能碰到哪。不是預測保證。

    準度來自他自己的順序，不是等幅測距：
    收在撐下先放棄；出貨往撐下；洗盤／站上撐都要價穩量縮才把攻壓當最可能，
    量沒縮就先整理。過壓先當壓轉撐；下降連點還壓著就不要畫保證續漲。
    """
    n = int(info.get("n") or 0)
    closes = list(info.get("closes") or [])
    if n < 8 or not closes:
        return {}
    last = float(closes[-1])
    st = info.get("struct") or {}
    spike_hi = float(st.get("spike_high") or 0)
    spike_lo = float(st.get("spike_low") or 0)
    shrinking = bool(st.get("shrinking"))
    x_end = float(n - 1 + _FUTURE)
    down_fut = None
    up_fut = None
    down_pts = info.get("down_pts")
    if down_pts:
        (x1, y1, _d1), (x2, y2, _d2) = down_pts
        down_fut = _line_at(x1, y1, x2, y2, x_end)
    up_pts = info.get("up_pts")
    if up_pts and not info.get("up_broken"):
        (x1, y1, _d1), (x2, y2, _d2) = up_pts
        # 過陡的上升連點不拿去演算未來價（會飛出圖外當假支撐）
        if not info.get("up_steep"):
            up_fut = _line_at(x1, y1, x2, y2, x_end)
        else:
            up_fut = None
    elif up_pts:
        up_fut = None
    key = "wait"
    target = last
    label = "量價壓撐不齊，不演算後續。"
    if spike_hi and spike_lo:
        label = (
            f"站上撐但量還沒縮，最可能先整理，不把攻壓 {_px(spike_hi)} 當最可能。不是保證。"
        )
    if info.get("distribution"):
        key = "distribution"
        target = spike_lo if spike_lo else last
        label = f"出貨痕跡，演算往撐 {_px(target)}／撐下。不是保證。"
    elif info.get("under_support"):
        key = "abandon"
        target = last
        label = f"收在撐 {_px(spike_lo)} 之下，這次量價先放棄，不把反彈當最可能。不是保證。"
    elif info.get("wash"):
        if shrinking and spike_hi:
            key = "wash"
            target = spike_hi
            label = f"洗盤痕跡且量縮，演算先看壓 {_px(target)}。不是保證。"
        else:
            key = "wait"
            target = last
            press = _px(spike_hi) if spike_hi else "—"
            label = (
                f"洗盤痕跡但量還沒縮，最可能先整理，不把攻壓 {press} 當最可能。不是保證。"
            )
    elif info.get("over_press"):
        down_now = float(info.get("down_now") or 0)
        clearly_over = bool(spike_hi and last > spike_hi * 1.05)
        if down_fut and down_now and last < down_now and clearly_over:
            if float(down_fut) > last * 1.005:
                key = "rail"
                target = float(down_fut)
                label = (
                    f"已明顯過壓，下降連點再 {_FUTURE} 根約 {_px(target)}，要過才像真突破；"
                    "半山腰／長抱另論。不是保證。"
                )
            else:
                key = "rail_cap"
                target = last
                label = (
                    f"已明顯過壓，現價還在下降連點下（現在約 {_px(down_now)}），"
                    f"軌再 {_FUTURE} 根下移到約 {_px(down_fut)}；最可能被軌壓著走，不是保證過軌。"
                    "半山腰／長抱另論。"
                )
        elif spike_hi:
            key = "press_hold"
            target = float(spike_hi)
            label = (
                f"已過壓 {_px(spike_hi)}，演算先把這價當壓轉撐；半山腰／長抱另論。不是保證。"
            )
        else:
            key = "press_hold"
            target = last
            label = "已過壓，半山腰／長抱另論，不畫保證續漲。"
    elif spike_hi and spike_lo and last >= spike_lo:
        if shrinking:
            key = "toward_press"
            target = spike_hi
            label = f"量縮站上撐，演算下一檔量價看壓 {_px(target)}；要價穩量縮才像進。不是保證。"
        else:
            key = "wait"
            target = last
            label = (
                f"站上撐但量還沒縮，最可能先整理，不把攻壓 {_px(spike_hi)} 當最可能。不是保證。"
            )
    path = []
    tgt = float(target)
    for i in range(_FUTURE + 1):
        t = i / float(_FUTURE)
        y = last + (tgt - last) * (1.0 - (1.0 - t) * (1.0 - t))
        path.append((float(n - 1 + i), y))
    forks: List[Dict[str, Any]] = []
    if spike_hi and abs(tgt - spike_hi) / max(abs(last), 1.0) > 0.008:
        forks.append({"name": "過壓", "y": spike_hi})
    if spike_lo and abs(tgt - spike_lo) / max(abs(last), 1.0) > 0.008:
        forks.append({"name": "破撐", "y": spike_lo})
    if down_fut and abs(tgt - float(down_fut)) / max(abs(last), 1.0) > 0.008:
        forks.append({"name": "連點延長", "y": float(down_fut)})
    mark = f"最可能→{_px(tgt)}"
    if key == "rail_cap":
        mark = "最可能＝被軌壓著"
    elif key == "abandon":
        mark = "最可能＝先放棄"
    elif key == "press_hold":
        mark = f"最可能＝壓轉撐 {_px(tgt)}"
    elif key == "distribution":
        mark = f"最可能＝往撐 {_px(tgt)}"
    elif key == "wash":
        mark = f"最可能＝看壓 {_px(tgt)}"
    elif key == "wait":
        mark = "最可能＝先整理"
    elif key == "toward_press":
        mark = f"最可能＝看壓 {_px(tgt)}"
    return {
        "horizon": _FUTURE,
        "key": key,
        "label": label,
        "mark": mark,
        "target": tgt,
        "path": path,
        "down_fut": down_fut,
        "up_fut": up_fut,
        "forks": forks,
        "shrinking": shrinking,
    }


def _price_box(ax, x, y, text, color, *, va="center", ha="left", size=13):
    ax.text(
        x,
        y,
        text,
        color=color,
        fontproperties=_fp(size, "bold"),
        va=va,
        ha=ha,
        zorder=10,
        bbox=dict(boxstyle="round,pad=0.32", facecolor="#ffffff", edgecolor=color, linewidth=1.25, alpha=0.97),
    )


def _circled_letter(ax, x, y, letter, color, *, dx=-1.8, dy=0.0, size=11):
    """線左邊（或指定偏移）寫圈起來的 A／B／C。"""
    ax.text(
        float(x) + float(dx),
        float(y) + float(dy),
        str(letter),
        color=color,
        fontproperties=_fp(size, "bold"),
        ha="center",
        va="center",
        zorder=14,
        bbox=dict(
            boxstyle="circle,pad=0.28",
            facecolor="#ffffff",
            edgecolor=color,
            linewidth=1.45,
            alpha=0.97,
        ),
    )


def _add_ohlc_wicks(
    ax,
    xs: Sequence[float],
    lows: Sequence[float],
    highs: Sequence[float],
    colors: Sequence[str],
    *,
    lw: Any = 0.9,
    z: int = 3,
) -> None:
    """影線一次畫完，不准一根一根 vlines。"""
    segs = [
        ((float(x), float(lo)), (float(x), float(hi)))
        for x, lo, hi in zip(xs, lows, highs)
    ]
    if not segs:
        return
    ax.add_collection(
        LineCollection(
            segs,
            colors=list(colors),
            linewidths=lw,
            capstyle="round",
            zorder=z,
        ),
        autolim=False,
    )


def _add_ohlc_bodies(
    ax,
    xs: Sequence[float],
    opens: Sequence[float],
    closes: Sequence[float],
    colors: Sequence[str],
    *,
    widths: Sequence[float],
    lws: Sequence[float],
    edges: Sequence[str],
    min_h: float,
    z: int = 3,
) -> None:
    """實體一次畫完，不准一根一根 Rectangle。"""
    verts = []
    for x, o, c, w in zip(xs, opens, closes, widths):
        y0 = min(float(o), float(c))
        h = max(abs(float(c) - float(o)), min_h)
        x0 = float(x) - float(w) / 2.0
        x1 = float(x) + float(w) / 2.0
        verts.append([(x0, y0), (x1, y0), (x1, y0 + h), (x0, y0 + h)])
    if not verts:
        return
    ax.add_collection(
        PolyCollection(
            verts,
            facecolors=list(colors),
            edgecolors=list(edges),
            linewidths=list(lws),
            zorder=z,
        ),
        autolim=False,
    )


def _halo_line(ax, xs, ys, color, *, lw=1.4, ls="-", z=6, halo=1.0):
    if float(halo or 0) > 0:
        ax.plot(
            xs,
            ys,
            color=_HALO,
            linewidth=lw + float(halo),
            linestyle="-",
            zorder=z,
            solid_capstyle="round",
            solid_joinstyle="round",
            alpha=0.92,
        )
    ax.plot(
        xs,
        ys,
        color=color,
        linewidth=lw,
        linestyle=ls,
        zorder=z + 1,
        solid_capstyle="round",
        solid_joinstyle="round",
    )


def _leader_note(
    ax,
    x,
    y,
    text,
    color,
    *,
    tx,
    ty,
    size=11,
    ha="left",
    va="center",
    clip: bool = False,
    shrink_b: float = 4.0,
) -> None:
    """點釘原位；虛線拉到空白處再寫字，盒子不准蓋 K。

    clip=True：標籤必須落在軸內（演化區右側／最可能），不准跳出底圖。
    """
    ax.annotate(
        str(text),
        xy=(float(x), float(y)),
        xytext=(float(tx), float(ty)),
        color=color,
        fontproperties=_fp(size, "bold"),
        ha=ha,
        va=va,
        zorder=12,
        annotation_clip=bool(clip),
        clip_on=bool(clip),
        bbox=dict(
            boxstyle="round,pad=0.28",
            facecolor="#ffffff",
            edgecolor=color,
            linewidth=1.1,
            alpha=0.97,
        ),
        arrowprops=dict(
            arrowstyle="-",
            color=color,
            lw=0.95,
            linestyle="--",
            shrinkA=0,
            shrinkB=float(shrink_b),
        ),
    )


def _callout(ax, x, y, text, color, *, dx=1.55, dy=0.0, size=11, ha="left", tx=None, ty=None):
    _leader_note(
        ax,
        x,
        y,
        text,
        color,
        tx=x + dx if tx is None else tx,
        ty=y + dy if ty is None else ty,
        size=size,
        ha=ha,
    )


def _place_band_notes(
    ax,
    notes: Sequence[Dict[str, Any]],
    *,
    ty: float,
    x_lo: float,
    x_hi: float,
    min_dx: float,
) -> None:
    """標籤排在圖上／圖下空白帶，虛線只沿自己那一根上去，不橫掃別根 K。"""
    if not notes:
        return
    ordered = sorted(notes, key=lambda n: float(n.get("x") or 0))
    txs: List[float] = []
    for note in ordered:
        tx = float(note.get("x") or 0)
        if txs and tx < txs[-1] + min_dx:
            tx = txs[-1] + min_dx
        txs.append(tx)
    if txs and txs[-1] > x_hi:
        shift = txs[-1] - x_hi
        txs = [max(x_lo, t - shift) for t in txs]
    txs = [min(max(t, x_lo), x_hi) for t in txs]
    kept: List[Tuple[Dict[str, Any], float]] = []
    for note, tx in zip(ordered, txs):
        if kept and tx - kept[-1][1] < min_dx * 0.72:
            continue
        kept.append((note, tx))
    for note, tx in kept:
        _leader_note(
            ax,
            float(note.get("x") or 0),
            float(note.get("y") or 0),
            str(note.get("text") or ""),
            str(note.get("color") or _TEXT),
            tx=tx,
            ty=ty,
            size=int(note.get("size") or 10),
            ha="center",
            va="center",
        )


def _approx_note_width(text: str, size: float = 12) -> float:
    """結構圖右溝標籤約略資料座標寬（含 bbox pad＋邊框）。偏寬估，整盒必須在畫布內。"""
    s = str(text or "")
    units = 0.0
    for ch in s:
        units += 1.0 if ord(ch) > 0x2E80 else 0.72
    # 實測 size12「最可能＝看壓 5255」約 19；邊框＋內邊距刻意估高
    return units * (float(size) / 12.0) * 2.35 + 6.8


def _note_priority(text: str) -> int:
    t = str(text or "")
    if "最可能" in t:
        return 0
    if t.startswith("壓") or t.startswith("撐"):
        return 1
    if t.startswith("昨收"):
        return 2
    if any(k in t for k in ("下降壓", "上升軌", "平行壓", "平行撐")):
        return 3
    return 4


def _dedupe_right_notes(
    notes: Sequence[Dict[str, Any]],
    *,
    span: float,
    near_frac: float = 0.028,
) -> List[Dict[str, Any]]:
    """價位太近只留優先標籤，避免壓／軌／最可能互蓋。

    「昨收」只在幾乎貼齊壓／撐時才讓；空位要留昨收（偏好鎖死）。
    """
    if not notes:
        return []
    ordered = sorted(
        notes,
        key=lambda n: (_note_priority(str(n.get("text") or "")), -float(n.get("y") or 0)),
    )
    kept: List[Dict[str, Any]] = []
    thr = max(float(span) * float(near_frac), 1.0)
    # 昨收只跟壓／撐比窄門檻；不准跟「最可能」同價附近被誤刪（416 vs 昨收 414）
    prev_thr = max(float(span) * 0.012, 0.8)
    for note in ordered:
        y = float(note.get("y") or 0)
        text = str(note.get("text") or "")
        is_prev = text.startswith("昨收")
        hit = False
        for k in kept:
            ky = float(k.get("y") or 0)
            kt = str(k.get("text") or "")
            if is_prev and "最可能" in kt:
                continue
            if (not is_prev) and "最可能" in text and kt.startswith("昨收"):
                continue
            if is_prev or kt.startswith("昨收"):
                use_thr = (
                    prev_thr
                    if (
                        kt.startswith("壓")
                        or kt.startswith("撐")
                        or kt.startswith("昨收")
                        or text.startswith("壓")
                        or text.startswith("撐")
                    )
                    else thr
                )
            else:
                use_thr = thr
            if abs(y - ky) < use_thr:
                hit = True
                break
        if hit:
            continue
        kept.append(dict(note))
    kept.sort(key=lambda n: -float(n.get("y") or 0))
    return kept


def _place_right_notes(
    ax,
    notes: Sequence[Dict[str, Any]],
    *,
    x_text: float,
    ymin: float,
    ymax: float,
    min_gap: float,
    span: float = 0.0,
    seam: Optional[float] = None,
    avoid_ys: Sequence[float] = (),
    x_max: Optional[float] = None,
    bottom_pad: float = 0.0,
) -> None:
    """右溝標籤欄：去重＋垂直錯開；字落在軌線末端右側，不准壓軌／壓 K。

    x_text 應在演化帶／軌虛線右緣之外；x_max 保證「最可能」整句入軸。
    """
    cleaned = _dedupe_right_notes(notes, span=span or min_gap * 8.0)
    if not cleaned:
        return
    # 盒高約 span*0.04；gap 太大會全擠到上下緣互壓
    gap = max(float(min_gap), (ymax - ymin) * 0.045)
    gap = min(gap, (ymax - ymin) * 0.09)
    lo = ymin + max(float(bottom_pad), gap * 1.1)
    hi = ymax - gap * 0.9
    pin_x = float(seam) if seam is not None else None
    tx = float(x_text)
    if x_max is not None:
        need = max(
            (
                _approx_note_width(str(n.get("text") or ""), float(n.get("size") or 12))
                for n in cleaned
            ),
            default=16.0,
        )
        # 右緣內邊距：整盒含邊框必須落在軸內，不准貼齊／裁掉右邊框
        fit_tx = float(x_max) - need - 8.5
        if pin_x is not None:
            tx = max(float(pin_x) + 0.8, min(tx, fit_tx))
        else:
            tx = min(tx, fit_tx)
    most = [n for n in cleaned if "最可能" in str(n.get("text") or "")]
    others = [n for n in cleaned if "最可能" not in str(n.get("text") or "")]
    # 上緣留給「最可能」一整句；下方才排壓／撐／昨收／軌（同一左緣）
    reserve = gap * 1.35
    hi_others = hi - reserve
    taken: List[float] = []
    placed: List[Tuple[Dict[str, Any], float]] = []
    if most:
        my = hi - gap * 0.2
        placed.append((most[0], my))
        taken.append(my)
    other_ys = _spread_ys_around(
        [float(n.get("y") or 0) for n in others],
        taken + [float(y) for y in avoid_ys if y is not None],
        gap,
        lo=lo,
        hi=hi_others,
    )
    for note, ty in zip(others, other_ys):
        placed.append((note, ty))
        taken.append(ty)
    # 由上往下再強制錯開：盒與盒至少 gap，不准最可能貼壓
    placed.sort(key=lambda p: -float(p[1]))
    enforced: List[Tuple[Dict[str, Any], float]] = []
    for note, ty in placed:
        for _prev, ty2 in enforced:
            if abs(ty - ty2) < gap:
                ty = ty2 - gap
        ty = min(max(ty, lo), hi)
        enforced.append((note, ty))
    placed = enforced
    # 同一左緣欄：所有標籤共用 tx，不准「最可能」因估寬偏右
    col_tx = float(tx)
    for note, ty in placed:
        ny = float(note.get("y") or 0)
        # 字中心離開釘點價，但不得再擠進已佔位（最終 enforced 已錯開）
        if abs(ty - ny) < gap * 0.45:
            cand = ny + gap * 0.7 if ty >= ny else ny - gap * 0.7
            if all(abs(cand - t) >= gap * 0.85 for _, t in placed if t != ty):
                ty = min(max(cand, lo), hi)
        stub_x = float(col_tx) - 1.35
        _leader_note(
            ax,
            stub_x,
            ty,
            str(note.get("text") or ""),
            str(note.get("color") or _TEXT),
            tx=col_tx,
            ty=ty,
            size=int(note.get("size") or 11),
            ha="left",
            va="center",
            clip=True,
            shrink_b=1.5,
        )
        ax.plot(
            [stub_x],
            [ny],
            marker="o",
            markersize=4.0,
            color=str(note.get("color") or _TEXT),
            markeredgecolor="white",
            markeredgewidth=0.55,
            zorder=13,
            linestyle="None",
            clip_on=True,
        )
        if abs(ty - ny) > gap * 0.25:
            ax.plot(
                [stub_x, stub_x],
                [ny, ty],
                color=str(note.get("color") or _TEXT),
                linewidth=0.85,
                linestyle=":",
                zorder=11,
                alpha=0.78,
                clip_on=True,
            )


def _spread_ys_around(
    movable: Sequence[float],
    fixed: Sequence[float],
    min_gap: float,
    *,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
) -> List[float]:
    """標籤文字錯開：線仍釘原價，字被固定價位／鄰居擠開，避免蓋住數字。"""
    gap = float(min_gap or 0) or 1.0
    taken = [float(v) for v in fixed]
    out: List[float] = []
    for raw in movable:
        y = float(raw)
        for _ in range(12):
            hit = None
            best = gap
            for t in taken:
                d = abs(y - t)
                if d < best:
                    hit = t
                    best = d
            if hit is None:
                break
            y = hit + gap if y >= hit else hit - gap
        if lo is not None:
            y = max(y, float(lo))
        if hi is not None:
            y = min(y, float(hi))
        out.append(y)
        taken.append(y)
    return out


def _ymd8(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def locator_positive_rows(bars: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for r in bars or []:
        try:
            if float(r.get("close") or 0) > 0:
                rows.append(r)
        except (TypeError, ValueError):
            continue
    return rows


def locator_window_index(
    rows: Sequence[Dict[str, Any]], win_from: str = "", win_to: str = ""
) -> Tuple[int, int]:
    """縮圖橙底起迄＝大圖第一根／最後一根的日期。找不到才退回尾段。"""
    wf, wt = _ymd8(win_from), _ymd8(win_to)
    i0 = i1 = None
    for i, r in enumerate(rows):
        d = _ymd8(r.get("date"))
        if wf and d >= wf and i0 is None:
            i0 = i
        if wt and d <= wt:
            i1 = i
    n = len(rows)
    if i0 is None:
        i0 = max(0, n - 90)
    if i1 is None:
        i1 = max(0, n - 1)
    if i1 < i0:
        i0, i1 = i1, i0
    return int(i0), int(i1)


def window_forecast_seams(i0: int, i1: int, fut: int) -> Tuple[float, float, float]:
    """橙底／黃底接縫跟大圖同一條：最後一根官方柱右邊 n-0.45。

    回傳 (window_lo, seam, forecast_hi)。seam 就是大圖黃底起點。
    """
    i0, i1 = int(i0), int(i1)
    fut = max(0, int(fut or 0))
    seam = float(i1) + 0.55
    return float(i0) - 0.45, seam, seam + float(fut) + 1.0


def paint_forecast_span(ax, last_i: int, fut: int, *, line: bool = True) -> float:
    _lo, seam, hi = window_forecast_seams(0, int(last_i), fut)
    ax.axvspan(seam, hi, facecolor=_FUTURE_BG, edgecolor="none", alpha=0.95, zorder=0)
    if line:
        ax.axvline(seam, color="#ffcc80", linewidth=1.1, linestyle=":", zorder=2)
    return seam


def _major_swings(
    rows: Sequence[Dict[str, Any]], *, left: int = 0, max_pts: int = 9
) -> List[Tuple[int, float, str]]:
    """長軸實際高低轉折。只連點，不數 5／9。"""
    n = len(rows)
    if left <= 0:
        left = max(4, min(12, n // 22 or 4))
    highs = [float(r.get("high") or r.get("close") or 0) for r in rows]
    lows = [float(r.get("low") or r.get("close") or 0) for r in rows]
    hi_p, lo_p = _pivots(highs, lows, left=left)
    events: List[Tuple[int, float, str]] = []
    events.extend((i, highs[i], "H") for i in hi_p)
    events.extend((i, lows[i], "L") for i in lo_p)
    events.sort(key=lambda x: x[0])
    out: List[Tuple[int, float, str]] = []
    for i, y, k in events:
        if y <= 0:
            continue
        if out and out[-1][2] == k:
            prev_y = out[-1][1]
            if (k == "H" and y >= prev_y) or (k == "L" and y <= prev_y):
                out[-1] = (i, y, k)
            continue
        out.append((i, y, k))
    if len(out) > max_pts:
        mid = out[1:-1]
        mid.sort(key=lambda t: -abs(t[1]))
        keep = {out[0], out[-1], *mid[: max(0, max_pts - 2)]}
        out = [t for t in out if t in keep]
    return out


def infer_impulse_five(
    rows: Sequence[Dict[str, Any]],
    *,
    peak_i: int,
    start_i: Optional[int] = None,
) -> Dict[str, Any]:
    """已確認第 5 高，才把前面升段推成 1～4。推不出來就不畫，不准亂數。

    點必須落在那根官方 K 的高或低：3＝起點到 5 之間真正最高；2／4＝該段真正最低。
    1-4 重疊、3 最短、或 1～2 少於 4 根＝這組不算。第 5 可以失敗（低於第 3）。
    """
    n = len(rows)
    peak_i = int(peak_i)
    if n < 16 or peak_i < 10 or peak_i >= n:
        return {}
    highs = [float(r.get("high") or 0) for r in rows]
    lows = [float(r.get("low") or 0) for r in rows]
    peak_y = highs[peak_i]
    if peak_y <= 0:
        return {}
    if start_i is None:
        lo0 = max(0, peak_i - 220)
        hi0 = peak_i - 8
        if hi0 <= lo0:
            return {}
        start_i = min(range(lo0, hi0), key=lambda i: lows[i] if lows[i] > 0 else 1e18)
    start_i = int(start_i)
    if start_i < 0 or start_i >= peak_i - 8:
        return {}
    start_y = lows[start_i]
    if start_y <= 0 or peak_y <= start_y * 1.02:
        return {}
    i3_hi = peak_i
    if i3_hi <= start_i + 4:
        return {}
    i3 = max(range(start_i + 1, i3_hi), key=lambda i: highs[i] if highs[i] > 0 else -1e18)
    # 5 左邊緊貼的高是同一座山，不能當 3。
    if i3 >= peak_i - 3:
        if start_i + 3 >= i3:
            return {}
        i3 = max(range(start_i + 1, i3), key=lambda i: highs[i] if highs[i] > 0 else -1e18)
    if highs[i3] <= 0 or i3 >= peak_i - 2:
        return {}
    i4 = min(range(i3 + 1, peak_i), key=lambda i: lows[i] if lows[i] > 0 else 1e18)
    if lows[i4] <= 0:
        return {}
    total = max(peak_y, highs[i3]) - start_y
    left = max(2, min(6, (i3 - start_i) // 18 or 2))
    hi_p, _ = _pivots(highs[start_i : i3 + 1], lows[start_i : i3 + 1], left=left)
    hi_abs = [start_i + i for i in hi_p if start_i + i < i3 - 2]
    mid1 = start_i + max(3, (i3 - start_i) // 2)
    if start_i + 1 < min(mid1, i3 - 2):
        alt = max(
            range(start_i + 1, min(mid1, i3 - 2) + 1),
            key=lambda i: highs[i] if highs[i] > 0 else -1e18,
        )
        if highs[alt] > 0 and alt not in hi_abs:
            hi_abs.append(alt)
    if not hi_abs:
        return {}

    def _pack(i1: int, i2: int) -> Optional[Dict[str, Any]]:
        if not (start_i < i1 < i2 < i3 < i4 < peak_i):
            return None
        if i2 - i1 < 4:
            return None
        if lows[i4] < highs[i1] * 0.998:
            return None
        w1 = highs[i1] - start_y
        w3 = highs[i3] - lows[i2]
        w5 = peak_y - lows[i4]
        if min(w1, w3, w5) <= 0:
            return None
        if w3 + 1e-9 < min(w1, w5):
            return None
        if total > 0 and w1 < total * 0.08:
            return None
        return {
            "start": {"i": start_i, "y": start_y, "n": "", "kind": "L"},
            "pts": [
                {"n": "1", "i": i1, "y": highs[i1], "kind": "H"},
                {"n": "2", "i": i2, "y": lows[i2], "kind": "L"},
                {"n": "3", "i": i3, "y": highs[i3], "kind": "H"},
                {"n": "4", "i": i4, "y": lows[i4], "kind": "L"},
                {"n": "5", "i": peak_i, "y": peak_y, "kind": "H"},
            ],
            "score": (w1, i2 - i1),
        }

    best: Optional[Dict[str, Any]] = None
    for i1 in sorted(hi_abs, key=lambda i: -highs[i])[:10]:
        i2 = min(range(i1 + 1, i3), key=lambda i: lows[i] if lows[i] > 0 else 1e18)
        got = _pack(i1, i2)
        if not got:
            continue
        if best is None or got["score"] > best["score"]:
            best = got
    if not best:
        return {}
    best.pop("score", None)
    return best


def _impulse_support_pair(
    rows: Sequence[Dict[str, Any]], peak_i: int
) -> Optional[Tuple[int, int]]:
    """下降壓確認第 5 高之後，上升撐＝同一推動的 2 低連 4 低。沒兩點就不畫。"""
    five = infer_impulse_five(rows, peak_i=int(peak_i))
    pts = {str(p.get("n") or ""): p for p in (five.get("pts") or [])}
    p2, p4 = pts.get("2"), pts.get("4")
    if not p2 or not p4:
        return None
    i2, i4 = int(p2["i"]), int(p4["i"])
    lows = [float(r.get("low") or 0) for r in rows]
    if not (0 <= i2 < i4 < len(lows)):
        return None
    if lows[i4] <= lows[i2] * 1.001:
        return None
    return i2, i4


def _map_five_support(
    work: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    five: Dict[str, Any],
) -> Optional[Tuple[Tuple[Any, ...], Tuple[Any, ...]]]:
    """縮圖 1～5 的 2／4 對回大圖座標，上升撐跟小圖同一組。"""
    pts = {str(p.get("n") or ""): p for p in (five.get("pts") or [])}
    p2, p4 = pts.get("2"), pts.get("4")
    if not p2 or not p4:
        return None
    i2r, i4r = int(p2["i"]), int(p4["i"])
    if not (0 <= i2r < len(rows) and 0 <= i4r < len(rows)):
        return None
    d2 = _ymd8(rows[i2r].get("date"))
    d4 = _ymd8(rows[i4r].get("date"))
    i2 = i4 = -1
    for i, r in enumerate(work):
        d = _ymd8(r.get("date"))
        if d == d2:
            i2 = i
        if d == d4:
            i4 = i
    if not (0 <= i2 < i4 < len(work)):
        return None
    return (
        (i2, float(p2["y"]), str(work[i2].get("date") or "")),
        (i4, float(p4["y"]), str(work[i4].get("date") or "")),
    )


def impulse_five_legs(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    """縮圖升段折線。數字另外用 marks，避免跟線疊在一起。"""
    pts = list((story or {}).get("pts") or [])
    start = (story or {}).get("start") or {}
    seq = ([start] if start else []) + pts
    if len(seq) < 2:
        return []
    return [
        {
            "xs": [float(p["i"]) for p in seq],
            "ys": [float(p["y"]) for p in seq],
            "color": "#5d4037",
            "lw": 1.05,
            "lab": "",
            "dots": False,
        }
    ]


def impulse_five_marks(story: Dict[str, Any], *, size: int = 13) -> List[Dict[str, Any]]:
    """1～5 要夠大。高點寫上面、低點寫下面。3／5 左右分開，不准疊在同一顆。"""
    slots = {
        "1": "above-left",
        "2": "below",
        "3": "above-left",
        "4": "below",
        "5": "above-right",
    }
    out: List[Dict[str, Any]] = []
    for p in (story or {}).get("pts") or []:
        n = str(p.get("n") or "").strip()
        if n not in slots:
            continue
        hi = str(p.get("kind") or "") == "H"
        out.append(
            {
                "x": float(p["i"]),
                "y": float(p["y"]),
                "text": n,
                "color": "#4e342e",
                "va": "bottom" if hi else "top",
                "size": size,
                "slot": slots[n],
            }
        )
    return out


def locator_legs_from_swings(
    rows: Sequence[Dict[str, Any]],
    swings: Sequence[Tuple[int, float, str]],
) -> List[Dict[str, Any]]:
    """個股縮圖：高低連成一線，每段標升／回。不是波浪段號。"""
    pts = list(swings or [])
    if len(pts) < 2:
        return []
    legs: List[Dict[str, Any]] = [
        {
            "xs": [p[0] for p in pts],
            "ys": [p[1] for p in pts],
            "color": "#37474f",
            "lab": "",
            "lw": 1.2,
        }
    ]
    for a, b in zip(pts, pts[1:]):
        span_x = abs(b[0] - a[0])
        if span_x < max(10, len(rows) // 16):
            continue
        up = b[1] > a[1]
        legs.append(
            {
                "xs": [a[0], b[0]],
                "ys": [a[1], b[1]],
                "color": "#0277bd" if up else "#6a1b9a",
                "lab": "升" if up else "回",
                "lw": 0.01,
            }
        )
    return legs


def _locator_month_ticks(rows: Sequence[Dict[str, Any]]) -> Tuple[List[int], List[str]]:
    n = len(rows)
    xt: List[int] = []
    xl: List[str] = []
    last_ym = ""
    min_gap = max(16, n // 14)
    for i, r in enumerate(rows):
        d = _ymd8(r.get("date"))
        if len(d) != 8:
            continue
        mon = int(d[4:6])
        edge = i == 0 or i == n - 1
        qtr = mon in (1, 4, 7, 10)
        if not (edge or qtr):
            continue
        ym = d[:6]
        if ym == last_ym and not edge:
            continue
        if xt and i - xt[-1] < min_gap and not edge:
            continue
        if edge and xt and i - xt[-1] < max(10, n // 22):
            xt.pop()
            xl.pop()
        last_ym = ym
        xt.append(i)
        xl.append(f"{d[2:4]}/{mon}")
    if not xt:
        d0 = _ymd8(rows[0].get("date")) if rows else ""
        d1 = _ymd8(rows[-1].get("date")) if rows else ""
        return [0, max(n - 1, 0)], [
            f"{d0[:4]}/{int(d0[4:6])}" if d0 else "",
            f"{d1[:4]}/{int(d1[4:6])}" if d1 else "今",
        ]
    return xt, xl


def paint_locator_inset(
    fig,
    bars: Sequence[Dict[str, Any]],
    *,
    win_from: str = "",
    win_to: str = "",
    rect: Tuple[float, float, float, float] = _STOCK_LOCATOR_RECT,
    title: str = "橙＝大圖區間　黃＝預估",
    ax=None,
    legs: Optional[Sequence[Dict[str, Any]]] = None,
    k_on_top: bool = False,
    forecast_n: int = 0,
    marks: Optional[Sequence[Dict[str, Any]]] = None,
    quote: Optional[Dict[str, Any]] = None,
) -> bool:
    """右上長軸縮圖：橙底＝大圖同一段日期，黃底＝兩邊都是最後一根之後的演算。橫軸月份。不在縮圖裡再套框。"""
    from decision_card_signals import candle_up_taiwan

    rows = locator_positive_rows(bars)
    if len(rows) < 24:
        return False
    i0, i1 = locator_window_index(rows, win_from, win_to)
    if ax is None:
        if fig is None:
            return False
        ax = fig.add_axes([rect[0], rect[1], rect[2], rect[3]], zorder=24)
    ax.set_facecolor("#ffffff")
    ax.patch.set_alpha(1.0)
    _style_frame(ax)
    m = len(rows)
    opens = [float(r.get("open") or r.get("close") or 0) for r in rows]
    highs = [float(r.get("high") or r.get("close") or 0) for r in rows]
    lows = [float(r.get("low") or r.get("close") or 0) for r in rows]
    closes = [float(r.get("close") or 0) for r in rows]
    lo_min = min(lows)
    hi_max = max(highs)
    pad = (hi_max - lo_min) * 0.12 or 1.0
    fut = max(0, int(forecast_n or 0))
    win_lo, seam, fut_hi = window_forecast_seams(i0, i1, fut)
    ax.axvspan(
        win_lo,
        seam,
        facecolor=_WINDOW_BG,
        edgecolor="none",
        alpha=0.92,
        zorder=0,
    )
    if fut > 0:
        ax.axvspan(
            seam,
            fut_hi,
            facecolor=_FUTURE_BG,
            edgecolor="none",
            alpha=0.95,
            zorder=1,
        )
        ax.axvline(seam, color="#ffcc80", linewidth=0.9, linestyle=":", zorder=2)
    if k_on_top:
        w = 0.94 if m <= 200 else (0.80 if m <= 400 else 0.66)
        lw = 1.15 if m <= 200 else (0.85 if m <= 400 else 0.70)
    else:
        w = 0.86 if m <= 200 else (0.68 if m <= 400 else 0.52)
        lw = 0.9 if m <= 200 else 0.55
    k_z = 8 if k_on_top else 3
    line_z = 4 if k_on_top else 6
    yspan = hi_max - lo_min

    def _draw_legs() -> None:
        for leg in legs or []:
            xs = [float(x) for x in (leg.get("xs") or [])]
            ys = [float(y) for y in (leg.get("ys") or [])]
            if len(xs) < 2:
                continue
            color = str(leg.get("color") or "#37474f")
            llw = float(leg.get("lw") or 1.15)
            ls = leg.get("ls") or "-"
            if llw >= 0.4:
                ax.plot(
                    xs,
                    ys,
                    color=color,
                    linewidth=llw,
                    linestyle=ls,
                    zorder=line_z,
                    solid_capstyle="round",
                    solid_joinstyle="round",
                    alpha=0.88 if k_on_top else 0.95,
                )
                if (not k_on_top) and leg.get("dots", True):
                    ax.scatter(
                        xs,
                        ys,
                        s=18,
                        color=color,
                        zorder=line_z + 1,
                        edgecolors="#ffffff",
                        linewidths=0.4,
                    )
            lab = str(leg.get("lab") or "").strip()
            if lab:
                mid = len(xs) // 2
                ax.text(
                    xs[mid],
                    ys[mid],
                    lab,
                    color=color,
                    fontproperties=_fp(8, "bold"),
                    ha="center",
                    va="bottom",
                    zorder=12,
                    bbox=dict(
                        boxstyle="round,pad=0.12",
                        facecolor="#ffffff",
                        edgecolor="none",
                        alpha=0.9,
                    ),
                )
            circ = str(leg.get("circle") or "").strip()
            side = str(leg.get("circle_side") or "left")
            if circ:
                if side == "mid-left":
                    mx = (xs[0] + xs[-1]) / 2.0
                    my = (ys[0] + ys[-1]) / 2.0
                    dx = -max(5.5, m * 0.018)
                    dy = yspan * 0.045
                elif side == "right":
                    mx = (xs[0] + xs[-1]) / 2.0
                    my = (ys[0] + ys[-1]) / 2.0
                    dx = max(5.5, m * 0.018)
                    dy = yspan * 0.045
                elif side == "left":
                    mx, my = xs[0], ys[0]
                    dx = -max(6.0, m * 0.022)
                    dy = yspan * 0.05
                    if mx + dx < 1.2:
                        dx = max(4.5, m * 0.012)
                        dy = yspan * 0.12
                else:
                    mid = len(xs) // 2
                    mx, my = xs[mid], ys[mid]
                    dx = 0.0
                    dy = yspan * 0.11
                _circled_letter(ax, mx, my, circ, color, dx=dx, dy=dy, size=11)

    if not k_on_top:
        _draw_legs()
    colors = []
    halt_flags = [_bar_is_halt(rows[i]) for i in range(m)]
    for i in range(m):
        prev_c = closes[i - 1] if i else None
        if halt_flags[i]:
            colors.append(_HALT)
        else:
            colors.append(_UP if candle_up_taiwan(closes[i], prev_c, opens[i]) else _DN)
    trade_i = [i for i in range(m) if not halt_flags[i]]
    _add_ohlc_wicks(
        ax,
        [float(i) for i in trade_i],
        [lows[i] for i in trade_i],
        [highs[i] for i in trade_i],
        [colors[i] for i in trade_i],
        lw=lw,
        z=k_z,
    )
    # 長軸縮圖 360 根：影線就看得懂，不逐根畫方塊，出圖比較快。
    if m <= 200 and trade_i:
        _add_ohlc_bodies(
            ax,
            [float(i) for i in trade_i],
            [opens[i] for i in trade_i],
            [closes[i] for i in trade_i],
            [colors[i] for i in trade_i],
            widths=[w] * len(trade_i),
            lws=[0.15] * len(trade_i),
            edges=[colors[i] for i in trade_i],
            min_h=(hi_max - lo_min) * 0.0015,
            z=k_z,
        )
    halt_span = max(hi_max - lo_min, 1.0)
    for i in range(m):
        if not halt_flags[i]:
            continue
        x = float(i)
        cl = float(closes[i])
        ax.plot(
            [x - 0.38, x + 0.38],
            [cl, cl],
            color=_HALT,
            linewidth=1.2,
            zorder=k_z + 1,
            solid_capstyle="round",
        )
    if k_on_top:
        _draw_legs()
    ax.scatter(
        [m - 1],
        [closes[-1]],
        s=26,
        color="#ef6c00",
        zorder=8,
        edgecolors="#ffffff",
        linewidths=0.5,
    )
    taken: List[Tuple[float, float]] = []
    for mk in marks or []:
        tx = float(mk.get("x") or 0)
        ty = float(mk.get("y") or 0)
        va = str(mk.get("va") or "bottom")
        slot = str(mk.get("slot") or "")
        dx = 0.0
        dy = yspan * (0.055 if va == "bottom" else -0.055)
        if slot == "above-left":
            dx = -max(12.0, m * 0.038)
            dy = yspan * 0.08
            va = "bottom"
        elif slot == "above-right":
            dx = max(12.0, m * 0.038)
            dy = yspan * 0.08
            va = "bottom"
        elif slot == "below":
            dx = 0.0
            dy = -yspan * 0.08
            va = "top"
        tx2 = tx + dx
        ty2 = ty + dy
        for _ in range(8):
            hit = False
            for ox, oy in taken:
                if abs(tx2 - ox) < max(10.0, m * 0.032) and abs(ty2 - oy) < yspan * 0.10:
                    ty2 += yspan * (0.055 if va == "bottom" else -0.055)
                    hit = True
                    break
            if not hit:
                break
        if abs(dx) > 0.4 or abs(ty2 - ty) > yspan * 0.02:
            ax.plot(
                [tx, tx2],
                [ty, ty2],
                color="#bcaaa4",
                linewidth=0.7,
                zorder=14,
                solid_capstyle="round",
            )
        taken.append((tx2, ty2))
        ax.text(
            tx2,
            ty2,
            str(mk.get("text") or ""),
            color=str(mk.get("color") or "#4e342e"),
            fontproperties=_fp(float(mk.get("size") or 13), "bold"),
            ha="center",
            va=va,
            zorder=15,
            bbox=dict(
                boxstyle="round,pad=0.12",
                facecolor="#ffffff",
                edgecolor="#efebe9",
                linewidth=0.6,
                alpha=0.94,
            ),
        )
    ax.set_xlim(-0.8, max(m - 0.2 + fut, fut_hi))
    ax.set_ylim(lo_min - pad, hi_max + pad * 1.22)
    ax.set_yticks([])
    ax.tick_params(left=False, labelleft=False, length=2, labelsize=8, colors="#546e7a")
    xt, xl = _locator_month_ticks(rows)
    ax.set_xticks(xt)
    ax.set_xticklabels(xl, fontproperties=_fp(9, "bold"), color=_MUTED)
    ax.set_title("")
    host = fig if fig is not None else getattr(ax, "figure", None)
    if host is not None and title:
        host.text(
            rect[0] + rect[2],
            rect[1] + rect[3] + 0.004,
            title,
            ha="right",
            va="bottom",
            fontproperties=_fp(8, "bold"),
            color=_MUTED,
            zorder=25,
        )
    if quote and host is not None:
        _paint_locator_quote(host, rect, quote)
    return True


def _paint_locator_quote(fig, rect: Tuple[float, float, float, float], quote: Dict[str, Any]) -> None:
    """今K／現價／漲跌：縮圖匡外左手邊，垂直對齊縮圖中線。不進匡內擋 K。"""
    close = quote.get("close")
    if close is None:
        return
    from decision_card_signals import candle_up_taiwan
    from wayne_navigator import _draw_mini_candle, quote_limit_chip_colors, quote_limit_side

    x, y, _w, h = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    prev = quote.get("prev")
    up = candle_up_taiwan(close, prev, quote.get("open"))
    color = _UP if up else _DN
    chip = quote_limit_chip_colors(quote_limit_side(close, prev, quote.get("pct")))
    label = str(quote.get("label") or "收盤")
    px = _px(close)
    o, hi, lo = quote.get("open"), quote.get("high"), quote.get("low")
    try:
        ohlc_ok = all(float(v) > 0 for v in (o, hi, lo, close))
    except (TypeError, ValueError):
        ohlc_ok = False
    try:
        from tg_layout import format_move_plain

        move = format_move_plain(quote.get("change"), quote.get("pct"))
    except Exception:
        move = ""
    mid_y = y + h * 0.50
    edge = x - 0.008
    pad = dict(
        boxstyle="round,pad=0.18",
        facecolor="#ffffff",
        edgecolor="none",
        alpha=0.92,
    )
    px_pad = pad
    px_color = color
    if chip:
        bg, fg = chip
        px_color = fg
        px_pad = dict(
            boxstyle="square,pad=0.18",
            facecolor=bg,
            edgecolor="none",
            alpha=1.0,
        )
    tx = edge
    if ohlc_ok:
        cax = fig.add_axes([edge - 0.090, mid_y - 0.022, 0.016, 0.054], zorder=29)
        cax.set_xlim(0, 1)
        cax.set_ylim(0, 1)
        cax.axis("off")
        cax.set_facecolor("#ffffff")
        cax.patch.set_alpha(0.92)
        _draw_mini_candle(
            cax, 0.18, 0.08, 0.64, 0.84,
            float(o), float(hi), float(lo), float(close), prev,
        )
    # 縮圖旁時段標也拉開字距（收盤／盤中／現價）
    lab = str(label or "")
    if lab in ("收盤", "盤中", "現價") and len(lab) >= 2:
        lab = "　".join(list(lab))
    fig.text(
        tx,
        mid_y + 0.036,
        "今Ｋ　" + lab,
        transform=fig.transFigure,
        ha="right",
        va="center",
        fontproperties=_fp(8, "bold"),
        color=_MUTED,
        zorder=29,
        bbox=pad,
    )
    fig.text(
        tx,
        mid_y,
        px,
        transform=fig.transFigure,
        ha="right",
        va="center",
        fontproperties=_fp(15, "bold"),
        color=px_color,
        zorder=29,
        bbox=px_pad,
    )
    if move and move != "—":
        fig.text(
            tx,
            mid_y - 0.032,
            "較昨日　" + move,
            transform=fig.transFigure,
            ha="right",
            va="center",
            fontproperties=_fp(8, "bold"),
            color=color,
            zorder=29,
            bbox=pad,
        )


def _ow(text: str, size: float = 11) -> float:
    """overlay 0–100 大約字寬。只拿來排晶片，不拿來截字。"""
    n = 0.0
    for ch in str(text or ""):
        n += 1.0 if ord(ch) > 0x2E80 else 0.55
    return n * (float(size) / 11.0) * 1.08 + 0.15


def _spaced_cjk_width(text: str, size: float = 12, *, char_gap: float = 0.72) -> float:
    """收盤／盤中等二字標：字與字加硬間距後的總寬。"""
    chars = [c for c in str(text or "") if not c.isspace()]
    if not chars:
        return 0.0
    return sum(_ow(ch, size) for ch in chars) + float(char_gap) * max(len(chars) - 1, 0)


def _paint_spaced_cjk(
    ax,
    x: float,
    y: float,
    text: str,
    *,
    color: str,
    size: float = 12,
    ha: str = "right",
    char_gap: float = 0.72,
    zorder: int = 22,
) -> float:
    """逐字畫 CJK，字與字拉開；回傳佔寬。不准「收盤／盤中」字黏字。
    ha=center：整段以 x 為中心（收盤／盤中置中於股價與迷你K 之間）。"""
    chars = [c for c in str(text or "") if not c.isspace()]
    if not chars:
        return 0.0
    total = _spaced_cjk_width("".join(chars), size, char_gap=char_gap)
    fp = _fp(int(size), "bold")
    mode = str(ha or "right")
    if mode == "center":
        cursor = float(x) - total * 0.5
        for ch in chars:
            ax.text(
                cursor, y, ch, color=color, fontproperties=fp,
                va="center", ha="left", zorder=zorder,
            )
            cursor += _ow(ch, size) + float(char_gap)
    elif mode == "right":
        cursor = float(x)
        for ch in reversed(chars):
            ax.text(
                cursor, y, ch, color=color, fontproperties=fp,
                va="center", ha="right", zorder=zorder,
            )
            cursor -= _ow(ch, size) + float(char_gap)
    else:
        cursor = float(x)
        for ch in chars:
            ax.text(
                cursor, y, ch, color=color, fontproperties=fp,
                va="center", ha="left", zorder=zorder,
            )
            cursor += _ow(ch, size) + float(char_gap)
    return total


def _in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def stock_nameplate(sid: str, name: str = "", db_path: str = "") -> Dict[str, str]:
    """股名旁官方產業；自己就是這族／長線龍頭才加一枚龍頭晶片。"""
    sid = str(sid or "").strip()
    nm = str(name or "").strip()
    industry = ""
    if db_path:
        try:
            from universe import card_industry_label

            industry = str(card_industry_label(sid, db_path) or "").strip()
        except Exception:
            industry = ""
    leader = ""
    why = ""
    try:
        from biaoke_judge import _LONG_HOLD, leader_of

        lid, _lname, why = leader_of(db_path, sid, nm)
        if lid == sid or sid in _LONG_HOLD:
            leader = "龍頭"
    except Exception:
        why = ""
    return {
        "sid": sid,
        "name": nm,
        "industry": industry,
        "leader": leader,
        "why": why,
    }


def stock_display_glance(
    glance: Optional[Dict[str, str]] = None,
    *,
    sid: str = "",
    plate: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """個股圖只留這檔用得上的句。大盤位階／別人的長抱不上這張。"""
    g = {k: v for k, v in (glance or {}).items() if str(v or "").strip()}
    g.pop("nest", None)
    plate = plate or {}
    long_ok = str(plate.get("leader") or "").strip() == "龍頭"
    if not long_ok:
        try:
            from biaoke_judge import _LONG_HOLD

            long_ok = str(sid or "").strip() in _LONG_HOLD
        except Exception:
            long_ok = False
    if not long_ok:
        g.pop("hold", None)
    for k, v in list(g.items()):
        if "他自己最新" in str(v or ""):
            g.pop(k, None)
    return g


def header_banner_lines(
    glance: Optional[Dict[str, str]] = None,
    *,
    sid: str = "",
    plate: Optional[Dict[str, str]] = None,
) -> List[str]:
    """圖上頭短句，整句畫完，不准截成…。個股不放巢穴位階。"""
    g = stock_display_glance(glance, sid=sid, plate=plate)
    out: List[str] = []
    for key in ("field", "leader"):
        bit = " ".join(str(g.get(key) or "").split())
        if bit:
            out.append(bit)
    return out


def _spot_quote(
    sid: str,
    last_bar: Optional[Dict[str, Any]] = None,
    prev_bar: Optional[Dict[str, Any]] = None,
    db_path: str = "",
) -> Dict[str, Any]:
    """右上角現價／收盤。個股改畫在左上標籤下面。pytest 不打外網；沒即時就用最後官方收。"""
    last = dict(last_bar or {})
    prev = dict(prev_bar or {})
    close = last.get("close")
    prev_c = prev.get("close") if prev.get("close") is not None else last.get("yesterday_close")
    pct = last.get("pct_change")
    chg = None
    try:
        if close is not None and prev_c not in (None, 0, 0.0):
            chg = float(close) - float(prev_c)
            if pct is None:
                pct = (chg / float(prev_c)) * 100.0
    except (TypeError, ValueError):
        chg = None
    out: Dict[str, Any] = {
        "is_live": False,
        "label": "收盤",
        "open": last.get("open"),
        "high": last.get("high"),
        "low": last.get("low"),
        "close": close,
        "prev": prev_c,
        "pct": pct,
        "change": chg,
        "date": last.get("date") or "",
        "volume": last.get("volume"),
    }
    if _in_pytest() or not sid:
        return out
    try:
        from live_quote import fetch_mis_quote

        live = fetch_mis_quote(sid) or {}
    except Exception:
        live = {}
    try:
        px = float(live.get("close") or 0)
    except (TypeError, ValueError):
        px = 0.0
    if px <= 0:
        return out
    y = live.get("yesterday_close")
    if y in (None, 0, 0.0):
        y = prev_c
    try:
        yf = float(y) if y is not None else 0.0
    except (TypeError, ValueError):
        yf = 0.0
    live_chg = live.get("change")
    live_pct = live.get("pct_change")
    if live_chg is None and yf:
        live_chg = px - yf
    if live_pct is None and yf:
        live_pct = (px - yf) / yf * 100.0
    # 盤中／收盤依時段切換（與三合一表頭同一套用詞；不准寫現價）
    out.update(
        {
            "is_live": True,
            "label": "盤中",
            "open": live.get("open") if live.get("open") is not None else out["open"],
            "high": live.get("high") if live.get("high") is not None else out["high"],
            "low": live.get("low") if live.get("low") is not None else out["low"],
            "close": px,
            "prev": yf or out["prev"],
            "pct": live_pct,
            "change": live_chg,
            "volume": live.get("volume") if live.get("volume") is not None else out["volume"],
            "update_time": live.get("update_time") or "",
        }
    )
    return out


def _draw_chip(ax, x: float, y: float, text: str, *, fc: str, ec: str, tc: str, size: int = 10) -> float:
    label = str(text or "").strip()
    if not label:
        return x
    ax.text(
        x,
        y,
        f" {label} ",
        color=tc,
        fontproperties=_fp(size, "bold"),
        va="center",
        ha="left",
        zorder=22,
        bbox=dict(
            boxstyle="round,pad=0.28",
            facecolor=fc,
            edgecolor=ec,
            linewidth=1.05,
            alpha=0.97,
        ),
    )
    return x + _ow(f" {label} ", size) + 1.15


def _paint_industry_chips(
    ax,
    plate: Dict[str, str],
    *,
    x: float,
    y: float,
    align: str = "left",
) -> float:
    """畫產業／龍頭晶片。align=right 時 x＝右緣（往左排），避免跟股價互壓。"""
    industry = str(plate.get("industry") or "").strip()
    leader = str(plate.get("leader") or "").strip() == "龍頭"
    bits: List[Tuple[str, str, str, str]] = []
    if industry:
        bits.append((industry, "#eef3f8", "#607d8b", "#37474f"))
    if leader:
        bits.append(("龍頭", "#ef6c00", "#e65100", "#ffffff"))
    if not bits:
        return float(x)
    if str(align or "left") != "right":
        cx = float(x)
        for text, fc, ec, tc in bits:
            cx = _draw_chip(ax, cx, y, text, fc=fc, ec=ec, tc=tc, size=15)
        return cx
    # 右對齊：先量寬再從右往左畫，最後仍左→右貼上
    widths = [_ow(f" {t} ", 15) + 1.15 for t, *_ in bits]
    total = sum(widths)
    cx = float(x) - total
    for (text, fc, ec, tc), _w in zip(bits, widths):
        cx = _draw_chip(ax, cx, y, text, fc=fc, ec=ec, tc=tc, size=15)
    return float(x)


def _paint_nameplate(
    ax,
    plate: Dict[str, str],
    *,
    x: float = _HEADER_X,
    y: float = 96.70,
    industry_x: Optional[float] = None,
    skip_industry: bool = False,
    title_size: int = 28,
) -> None:
    sid = str(plate.get("sid") or "")
    name = str(plate.get("name") or "")
    title = f"{sid} {name}".strip() or "官方日K"
    size = int(title_size or 28)
    ax.text(
        x,
        y,
        title,
        color=_TEXT,
        fontproperties=_fp(size, "bold"),
        va="center",
        ha="left",
        zorder=22,
    )
    if skip_industry:
        return
    # industry_x：橫式介紹帶把產業／龍頭標往右挪，不貼股名
    after_title = x + _ow(title, size) + 1.55
    if industry_x is None:
        cx = after_title
    else:
        cx = max(float(industry_x), after_title + 0.8)
    _paint_industry_chips(ax, plate, x=cx, y=y, align="left")


def _paint_spot(
    ax,
    quote: Dict[str, Any],
    *,
    x: float = _SPOT_X,
    y: float = _SPOT_Y,
    align: str = "right",
    compact: bool = False,
    move_dy: Optional[float] = None,
) -> None:
    """今K／現價／漲跌。預設置於縮圖外框左側空白，右對齊，不擋縮圖、不壓左上頭牌。"""
    close = quote.get("close")
    if close is None:
        return
    from decision_card_signals import candle_up_taiwan
    from wayne_navigator import _draw_mini_candle, quote_limit_chip_colors, quote_limit_side

    prev = quote.get("prev")
    up = candle_up_taiwan(close, prev, quote.get("open"))
    color = _UP if up else _DN
    chip = quote_limit_chip_colors(quote_limit_side(close, prev, quote.get("pct")))
    label = str(quote.get("label") or "收盤")
    px = _px(close)
    o, hi, lo = quote.get("open"), quote.get("high"), quote.get("low")
    try:
        ohlc_ok = all(float(v) > 0 for v in (o, hi, lo, close))
    except (TypeError, ValueError):
        ohlc_ok = False
    try:
        from tg_layout import format_move_plain

        move = format_move_plain(quote.get("change"), quote.get("pct"))
    except Exception:
        move = ""
    px_kw = {}
    px_color = color
    if chip:
        bg, fg = chip
        px_color = fg
        px_kw = dict(bbox=dict(boxstyle="square,pad=0.18", facecolor=bg, edgecolor="none"))
    # 時段標：收盤／盤中／現價 一律逐字拉開；字黏字＝沒做完
    session_labs = {"收盤", "盤中", "現價"}
    lab_size = 12
    # overlay 單位：二字標至少空出約半個字寬，一眼不黏
    char_gap = 1.2
    if compact:
        _paint_spaced_cjk(
            ax, x, 90, "今K", color="#546e7a", size=9, ha="left", char_gap=0.55,
        )
        if ohlc_ok:
            _draw_mini_candle(
                ax, x + 1.0, 58, 8.0, 26,
                float(o), float(hi), float(lo), float(close), prev,
            )
        lab_w = (
            _paint_spaced_cjk(
                ax, x, 42, label, color="#546e7a", size=10, ha="left", char_gap=char_gap,
            )
            if label in session_labs
            else (_ow(label, 10) or 0.0)
        )
        if label not in session_labs:
            ax.text(
                x, 42, label, color="#546e7a", fontproperties=_fp(10, "bold"),
                va="center", ha="left", zorder=22,
            )
        ax.text(
            x + lab_w + 1.35, 42, px, color=px_color,
            fontproperties=_fp(18, "bold"), va="center", ha="left", zorder=22,
            **px_kw,
        )
        if move and move != "—":
            ax.text(
                x, 16, "較昨日　" + move, color=color,
                fontproperties=_fp(10, "bold"), va="center", ha="left", zorder=22,
            )
        return
    # 右對齊：今K｜迷你K｜【收盤／盤中置中】｜股價
    # 二字標水平置中於「迷你K右緣」與「股價左緣」之間，不准黏某一邊
    if str(align or "right") == "right":
        side_pad = 1.65  # 標↔價／標↔迷你K 對稱留白
        gap_candle_jink = 1.25
        cw, ch = 1.85, 4.0
        lab_w = (
            _spaced_cjk_width(label, lab_size, char_gap=char_gap)
            if label in session_labs
            else _ow(label, lab_size)
        )
        # _ow 低估粗體數字；再乘係數＋晶片膨脹，價左緣才對得上肉眼
        price_w = _ow(px, 22) * 1.42 + (1.05 if px_kw else 0.25)
        price_left = float(x) - price_w
        # 槽寬＝標寬＋兩側對稱 pad；迷你K 右緣＝槽左
        slot_w = lab_w + 2.0 * side_pad
        candle_right = price_left - slot_w
        mid = (candle_right + price_left) * 0.5
        ax.text(
            float(x), y, px, color=px_color, fontproperties=_fp(22, "bold"),
            va="center", ha="right", zorder=22, **px_kw,
        )
        if label in session_labs:
            _paint_spaced_cjk(
                ax, mid, y, label, color="#546e7a", size=lab_size,
                ha="center", char_gap=char_gap,
            )
        else:
            ax.text(
                mid, y, label, color="#546e7a", fontproperties=_fp(lab_size, "bold"),
                va="center", ha="center", zorder=22,
            )
        cursor = candle_right
        if ohlc_ok:
            _draw_mini_candle(
                ax, cursor - cw, y - ch * 0.5, cw, ch,
                float(o), float(hi), float(lo), float(close), prev,
            )
            cursor -= cw + gap_candle_jink
        _paint_spaced_cjk(
            ax, cursor, y, "今K", color="#546e7a", size=10, ha="right", char_gap=0.55,
        )
        if move and move != "—":
            dy = (
                float(move_dy)
                if move_dy is not None
                else (4.55 if px_kw else 3.95)
            )
            ax.text(
                x, y - dy, "較昨日　" + move, color=color,
                fontproperties=_fp(12, "bold"), va="center", ha="right", zorder=22,
            )
        return
    # 左對齊備援：今K｜迷你K｜【標置中】｜股價
    gap_jink_candle = 1.25
    side_pad = 1.35
    cw, ch = 1.9, 4.0
    lab_w = (
        _spaced_cjk_width(label, lab_size, char_gap=char_gap)
        if label in session_labs
        else _ow(label, lab_size)
    )
    cursor = float(x)
    cursor += _paint_spaced_cjk(
        ax, cursor, y, "今K", color="#546e7a", size=10, ha="left", char_gap=0.55,
    ) + gap_jink_candle
    candle_left = cursor
    if ohlc_ok:
        _draw_mini_candle(
            ax, cursor, y - ch * 0.5, cw, ch,
            float(o), float(hi), float(lo), float(close), prev,
        )
        cursor += cw
    candle_right = cursor
    slot_w = lab_w + 2.0 * side_pad
    mid = candle_right + slot_w * 0.5
    if label in session_labs:
        _paint_spaced_cjk(
            ax, mid, y, label, color="#546e7a", size=lab_size,
            ha="center", char_gap=char_gap,
        )
    else:
        ax.text(
            mid, y, label, color="#546e7a", fontproperties=_fp(lab_size, "bold"),
            va="center", ha="center", zorder=22,
        )
    price_x = candle_right + slot_w
    ax.text(
        price_x, y, px, color=px_color, fontproperties=_fp(22, "bold"),
        va="center", ha="left", zorder=22, **px_kw,
    )
    if move and move != "—":
        dy = (
            float(move_dy)
            if move_dy is not None
            else (4.45 if px_kw else 3.95)
        )
        ax.text(
            x, y - dy, "較昨日　" + move, color=color,
            fontproperties=_fp(12, "bold"), va="center", ha="left", zorder=22,
        )


@_mpl_serial
def render_biaoke_structure_png(
    bars: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    sid: str = "",
    name: str = "",
    glance: Optional[Dict[str, str]] = None,
    plate: Optional[Dict[str, str]] = None,
    quote: Optional[Dict[str, Any]] = None,
    db_path: str = "",
    figsize: Optional[Tuple[float, float]] = None,
    dpi: Optional[int] = None,
) -> str:
    rows = list(bars or [])
    if len(rows) < 8 or not save_path:
        return ""
    work = rows[-_BARS:]
    info = analyze_structure(work)
    n = len(work)
    highs = info.get("highs") or [float(r.get("high") or 0) for r in work]
    lows = info.get("lows") or [float(r.get("low") or 0) for r in work]
    closes = info.get("closes") or [float(r.get("close") or 0) for r in work]
    opens = [float(r.get("open") or r.get("close") or 0) for r in work]
    vols = info.get("vols") or [float(r.get("volume") or 0) for r in work]
    last_bar0 = info.get("last_bar") or _bar_ohlc(work[-1])
    last_d = str(last_bar0.get("date") or "")[:8]
    last_c0 = float(last_bar0.get("close") or 0)
    fig_w, fig_h = (float(figsize[0]), float(figsize[1])) if figsize else (18.6, 10.8)
    portrait = fig_h / max(fig_w, 0.01) >= 1.15
    fullbleed = not portrait
    use_dpi = int(dpi or BIAOKE_CHART_DPI)
    _q0 = dict(quote or {})
    memo_key = (
        "biaoke_struct",
        str(sid or ""),
        last_d,
        round(last_c0, 4),
        int(n),
        int(len(rows)),
        int(use_dpi),
        round(fig_w, 3),
        round(fig_h, 3),
        "hdr-band-v9c" if fullbleed else "hdr-wrap3",
        int(_BARS),
        # 時段標（收盤／盤中）進鍵，不准互蓋快取
        str(_q0.get("label") or ""),
        int(bool(_q0.get("is_live"))),
        round(float((info.get("struct") or {}).get("spike_high") or 0), 2),
        round(float((info.get("struct") or {}).get("spike_vol") or 0), 0),
    )
    from wayne_navigator import _lookup_render_memo_get, _lookup_render_memo_put

    hit = _lookup_render_memo_get(memo_key, save_path)
    if hit:
        return hit
    xs = list(range(n))
    span = max(max(highs) - min(lows), 1.0)
    proj = info.get("project") or {}
    tgt = float(proj.get("target") or 0)
    y_top = max(highs) + span * 0.13
    y_bot = min(lows) - span * 0.09
    ymin = min(lows) - span * 0.18
    ymax = max(highs) + span * 0.24
    if tgt:
        ymin = min(ymin, tgt - span * 0.06)
        ymax = max(ymax, tgt + span * 0.10)
    for yf in (proj.get("down_fut"), proj.get("up_fut")):
        if yf:
            ymin = min(ymin, float(yf) - span * 0.04)
            ymax = max(ymax, float(yf) + span * 0.04)
    ymax = max(ymax, y_top + span * 0.07)
    ymin = min(ymin, y_bot - span * 0.07)
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(fig_w, fig_h),
        dpi=use_dpi,
        sharex=True,
        gridspec_kw=dict(
            height_ratios=(5.55, 1.40) if fullbleed else (5.45, 1.45),
            hspace=0.028 if fullbleed else 0.048,
        ),
        facecolor=_BG,
    )
    ax1.set_facecolor(_PANEL)
    ax2.set_facecolor(_PANEL)
    _style_frame(ax1)
    _style_frame(ax2)
    ax1.set_ylim(ymin, ymax)
    x_gutter = n + _FUTURE + 0.85
    # 先留軌末端右側的標籤欄；後面依最長「最可能」再加寬
    x_right = n + _FUTURE + 28.0
    ax1.set_xlim(-0.55, x_right)
    paint_forecast_span(ax1, n - 1, _FUTURE)
    st = info.get("struct") or {}
    spike_hi = float(st.get("spike_high") or 0)
    spike_lo = float(st.get("spike_low") or 0)
    spike_i = int(info.get("spike_i") or 0)
    spike_date = str(st.get("spike_date") or "")
    last_bar = info.get("last_bar") or _bar_ohlc(work[-1])
    prev_bar = _bar_ohlc(work[-2]) if len(work) >= 2 else {}
    spike_bar = info.get("spike_bar") or {}
    plate = dict(plate or stock_nameplate(sid, name, db_path))
    if not plate.get("sid"):
        plate["sid"] = sid
    if not plate.get("name"):
        plate["name"] = name
    quote = dict(quote or _spot_quote(sid, last_bar, prev_bar, db_path))
    halt_flags = [_bar_is_halt(work[i]) for i in range(n)]
    # 日 K＝查股共用 paint（與大量撐壓／導航同一套紅綠、柱寬、線寬）
    candle_up = paint_lookup_ohlc_candles(
        ax1,
        xs,
        opens,
        highs,
        lows,
        closes,
        halt=halt_flags,
        spike_i=spike_i,
        span=span,
        z=3,
    )
    candle_up = [bool(x) for x in candle_up]
    cols = [_HALT if halt_flags[i] else (_UP if candle_up[i] else _DN) for i in range(n)]
    band_hi: List[Dict[str, Any]] = []
    band_lo: List[Dict[str, Any]] = []
    right_notes: List[Dict[str, Any]] = []
    x_fut = float(n - 1 + _FUTURE)
    # 標籤欄左緣：演化帶後緊接溝；長窗時收窄右白，仍不准擋標籤
    label_col_left = float(n - 1) + max(float(_FUTURE) * 0.65, 5.5) + 2.4
    hline_xmax = float(label_col_left) - 1.0
    if spike_hi:
        ax1.hlines(
            spike_hi,
            xmin=-0.55,
            xmax=hline_xmax,
            color=_PRESS,
            linewidth=1.15,
            zorder=4,
            alpha=0.92,
        )
        right_notes.append(
            {"x": float(label_col_left) - 0.6, "y": spike_hi, "text": f"壓 {_px(spike_hi)}", "color": _PRESS, "size": 12}
        )
    if spike_lo:
        ax1.hlines(
            spike_lo,
            xmin=-0.55,
            xmax=hline_xmax,
            color=_HOLD,
            linewidth=1.15,
            zorder=4,
            alpha=0.92,
        )
        right_notes.append(
            {"x": float(label_col_left) - 0.6, "y": spike_lo, "text": f"撐 {_px(spike_lo)}", "color": _HOLD, "size": 12}
        )
    # 右軸空位標昨收（官方前收）；去重會避開與壓／撐太近
    try:
        prev_c_axis = float(
            prev_bar.get("close")
            or quote.get("prev")
            or last_bar.get("yesterday_close")
            or 0
        )
    except (TypeError, ValueError):
        prev_c_axis = 0.0
    if prev_c_axis > 0:
        right_notes.append(
            {
                "x": float(label_col_left) - 0.6,
                "y": float(prev_c_axis),
                "text": f"昨收 {_px(prev_c_axis)}",
                "color": "#546e7a",
                "size": 11,
            }
        )
    last_c = float(last_bar.get("close") or 0)
    if 0 <= spike_i < n:
        ax1.axvline(spike_i, color="#90a4ae", linewidth=1.05, linestyle="--", zorder=2)
    down_pts = info.get("down_pts")
    up_pts = info.get("up_pts")
    channel = dict(info.get("channel") or {})
    five: Dict[str, Any] = {}
    if down_pts and len(rows) >= n + 8:
        off0 = len(rows) - n
        five = infer_impulse_five(rows, peak_i=off0 + int(down_pts[0][0]))
        mapped = _map_five_support(work, rows, five)
        if mapped:
            up_pts = mapped
    # 有通道時以通道為準重算（含完整 bars 窗），避免 work 窗與全列不一致
    if not channel:
        channel = infer_parallel_channel(work) or {}
    # 軌虛線停在標籤欄左側（明顯空隙），不准穿進標籤盒
    rail_end = min(float(n - 1) + float(_FUTURE) * 0.22, float(label_col_left) - 5.5)
    rail_end = max(float(n - 1) + 1.0, rail_end)
    # 通道與單軌二擇一畫：有合格通道就畫平行雙線；單軌只在沒通道時畫，避免雙套互壓
    if channel.get("kind"):
        _paint_parallel_channel(
            ax1,
            channel,
            seam=float(n - 1),
            x_lo=0.0,
            x_hi=float(rail_end),
            y_lo=ymin,
            y_hi=ymax,
            n=n,
        )
        # 釘在軌末端（標籤欄左側），引線短、不准穿盒
        if channel.get("rail_now"):
            right_notes.append(
                {
                    "x": float(rail_end),
                    "y": float(channel["rail_now"]),
                    "text": f"{channel.get('name_u') or '上軌'} {_px(channel['rail_now'])}",
                    "color": _UP_TRACK if channel.get("kind") == "asc" else _DOWN_TRACK,
                    "size": 10,
                }
            )
        if channel.get("base_now"):
            right_notes.append(
                {
                    "x": float(rail_end),
                    "y": float(channel["base_now"]),
                    "text": f"{channel.get('name_l') or '下軌'} {_px(channel['base_now'])}",
                    "color": _UP_TRACK if channel.get("kind") == "asc" else _DOWN_TRACK,
                    "size": 10,
                }
            )
    else:
        if down_pts:
            (x1, y1, d1), (x2, y2, d2) = down_pts
            y_end = _line_at(x1, y1, x2, y2, x_fut)
            _paint_extended_rail(
                ax1,
                x1,
                y1,
                x2,
                y2,
                seam=float(n - 1),
                x_lo=0.0,
                x_hi=rail_end,
                y_lo=ymin,
                y_hi=ymax,
                color=_DOWN_TRACK,
            )
            ax1.scatter(
                [x1, x2],
                [y1, y2],
                color=_DOWN_TRACK,
                s=42,
                zorder=6,
                edgecolors="white",
                linewidths=0.8,
            )
            band_hi.append(
                {"x": float(x1), "y": float(y1), "text": f"下降壓 {_md(d1)}高{_px(y1)}", "color": _DOWN_TRACK, "size": 10}
            )
            if abs(y2 - (spike_hi or y2)) / span > 0.05 or x2 < n - 6:
                band_hi.append(
                    {"x": float(x2), "y": float(y2), "text": f"下降壓 {_md(d2)}高{_px(y2)}", "color": _DOWN_TRACK, "size": 10}
                )
            if abs(y_end - (tgt or y_end)) / max(span, 1.0) > 0.03:
                right_notes.append(
                    {"x": float(x_fut), "y": float(y_end), "text": f"下降壓 {_px(y_end)}", "color": _DOWN_TRACK, "size": 10}
                )
        if up_pts:
            (x1, y1, d1), (x2, y2, d2) = up_pts
            y_end = _line_at(x1, y1, x2, y2, x_fut)
            y_now = _line_at(x1, y1, x2, y2, float(n - 1))
            up_broken = bool(last_c and y_now and last_c < y_now)
            up_steep = _rail_slope_too_steep(x1, y1, x2, y2, span=span, n=n)
            rail_hi = float(n - 1) if (up_broken or up_steep) else float(rail_end)
            _paint_extended_rail(
                ax1,
                x1,
                y1,
                x2,
                y2,
                seam=float(n - 1),
                x_lo=0.0,
                x_hi=rail_hi,
                y_lo=ymin,
                y_hi=ymax,
                color=_UP_TRACK if not up_broken else "#90a4ae",
            )
            ax1.scatter(
                [x1, x2],
                [y1, y2],
                color=_UP_TRACK if not up_broken else "#90a4ae",
                s=42,
                zorder=6,
                edgecolors="white",
                linewidths=0.8,
            )
            lab_suffix = "（已壞）" if up_broken else ("（過陡僅參考）" if up_steep else "")
            band_lo.append(
                {
                    "x": float(x1),
                    "y": float(y1),
                    "text": f"上升撐 {_md(d1)}低{_px(y1)}{lab_suffix}",
                    "color": _UP_TRACK if not up_broken else "#607d8b",
                    "size": 10,
                }
            )
            if abs(y2 - (spike_lo or y2)) / span > 0.05 or x2 < n - 6:
                band_lo.append(
                    {
                        "x": float(x2),
                        "y": float(y2),
                        "text": f"上升撐 {_md(d2)}低{_px(y2)}{lab_suffix}",
                        "color": _UP_TRACK if not up_broken else "#607d8b",
                        "size": 10,
                    }
                )
            if not up_broken and not up_steep and abs(y_end - (tgt or y_end)) / max(span, 1.0) > 0.03:
                right_notes.append(
                    {"x": float(x_fut), "y": float(y_end), "text": f"上升撐 {_px(y_end)}", "color": _UP_TRACK, "size": 10}
                )
    path = list(proj.get("path") or [])
    if len(path) >= 2:
        _halo_line(
            ax1,
            [p[0] for p in path],
            [p[1] for p in path],
            _PROJECT,
            lw=1.55,
            halo=0.9,
            ls=(0, (7, 3)),
            z=7,
        )
        ax1.scatter(
            [path[-1][0]],
            [path[-1][1]],
            color=_PROJECT,
            s=48,
            zorder=9,
            edgecolors="white",
            linewidths=0.9,
        )
        mx, my = path[-1]
        right_notes.append(
            {
                "x": float(mx),
                "y": float(my),
                "text": str(proj.get("mark") or ("最可能→" + _px(proj.get("target")))),
                "color": _PROJECT,
                "size": 12,
            }
        )
    for fork in proj.get("forks") or []:
        if str(fork.get("name") or "") != "連點延長":
            continue
        fy = float(fork.get("y") or 0)
        if not fy:
            continue
        if abs(fy - (tgt or fy)) / max(span, 1.0) < 0.02:
            continue
        _halo_line(
            ax1,
            [n - 1, float(rail_end)],
            [last_c or closes[-1], fy],
            _FORK,
            lw=1.05,
            halo=0.7,
            ls=(0, (2, 2.5)),
            z=4,
        )
    _place_band_notes(ax1, band_hi, ty=y_top, x_lo=0.4, x_hi=max(n - 2.0, 2.0), min_dx=max(8.0, n * 0.11))
    _place_band_notes(ax1, band_lo, ty=y_bot, x_lo=0.4, x_hi=max(n - 2.0, 2.0), min_dx=max(8.0, n * 0.11))
    # 標籤欄：軌虛線已停在 label_col_left 左側。
    # 右溝用軸寬比例留白（勿只估固定 data 寬：xlim 一加寬，同字點徑佔更多 data，會又貼齊右緣）。
    max_note_w = max(
        (
            _approx_note_width(str(nt.get("text") or ""), float(nt.get("size") or 12))
            for nt in right_notes
        ),
        default=22.0,
    )
    # 長窗後主 K 變寬；標籤溝收窄但仍夠「最可能／壓／撐／昨收」整盒
    label_frac = 0.138
    content_right = float(label_col_left)
    need_by_frac = content_right / max(1.0 - label_frac, 0.5)
    need_by_text = content_right + max_note_w * 1.18 + 5.5
    x_right = max(float(x_right), need_by_frac, need_by_text)
    ax1.set_xlim(-0.55, x_right)
    # 字靠標籤欄左側同一緣，右側留邊框＋右軸；不准貼齊軸脊、不准最可能偏右
    gutter = float(x_right) - content_right
    x_text = content_right + max(1.5, gutter * 0.07)
    # 水平壓撐＋通道現價都要垂直讓開，盒子中心不准落在線上
    avoid_ys: List[float] = []
    if spike_hi:
        avoid_ys.append(float(spike_hi))
    if spike_lo:
        avoid_ys.append(float(spike_lo))
    if channel.get("rail_now"):
        avoid_ys.append(float(channel["rail_now"]))
    if channel.get("base_now"):
        avoid_ys.append(float(channel["base_now"]))
    evo_pad = span * 0.13
    _place_right_notes(
        ax1,
        right_notes,
        x_text=x_text,
        ymin=ymin,
        ymax=ymax,
        min_gap=span * 0.078,
        span=span,
        seam=float(n - 1),
        avoid_ys=avoid_ys,
        x_max=float(x_right),
        bottom_pad=evo_pad,
    )
    # 演化區說明留在米色帶內（標籤欄左側），兩行短句
    evo_cx = float(n - 1) + float(_FUTURE) * 0.50
    ax1.text(
        evo_cx,
        ymin + span * 0.042,
        "演化區",
        color="#546e7a",
        fontproperties=_fp(9, "bold"),
        ha="center",
        va="bottom",
        zorder=8,
        clip_on=True,
    )
    ax1.text(
        evo_cx,
        ymin + span * 0.008,
        "（不是保證・不是買訊）",
        color="#546e7a",
        fontproperties=_fp(8, "bold"),
        ha="center",
        va="bottom",
        zorder=8,
        clip_on=True,
    )
    mark = ""
    mc = _TEXT
    if info.get("wash"):
        mark = "破線洗盤痕跡（破撐後站回，不是保證）"
        mc = _WASH
    elif info.get("distribution"):
        mark = "過壓後掉回撐下＝出貨痕跡"
        mc = _PRESS
    # 大量日高／低判斷句（收在低下／已過高等）全股票都不打
    banner_bits = header_banner_lines(glance, sid=sid, plate=plate)
    ov = fig.add_axes([0, 0, 1, 1], facecolor="none", zorder=12)
    ov.set_xlim(0, 100)
    ov.set_ylim(0, 100)
    ov.axis("off")
    ov.patch.set_alpha(0)
    ov.set_navigate(False)
    # 橫式：介紹帶在主圖上方（下緣＝主圖上緣），不准浮框壓住 K
    # 長窗主圖已 ~240 根：迷你圖要真的多一段歷史才開，免得只多十根就擠掉滿寬介紹帶
    has_locator = len(rows) >= n + (60 if fullbleed else 8)
    band_floor = (
        float(_STOCK_MAIN_TOP_FULLBLEED) * 100.0 + 0.55
        if fullbleed
        else 66.5
    )
    if fullbleed:
        import matplotlib.patches as mpatches

        band_bot = float(_STOCK_MAIN_TOP_FULLBLEED) * 100.0
        # 無迷你圖：介紹框拉滿寬；頂緣內縮＝Telegram 點開避開靈動島
        box_w = (
            96.6
            if not has_locator
            else (_LOCATOR_LEFT * 100.0) - 2.2
        )
        box_top_pad = 1.35  # 頂安全距（點開滿版）
        ov.add_patch(
            mpatches.FancyBboxPatch(
                (1.6, band_bot + 0.35),
                box_w,
                100.0 - band_bot - box_top_pad - 0.15,
                boxstyle="round,pad=0.22,rounding_size=0.55",
                facecolor="#ffffff",
                edgecolor="#90caf9",
                linewidth=1.05,
                alpha=0.98,
                zorder=1,
                clip_on=False,
            )
        )
    spot_x = float(_SPOT_X_NO_LOCATOR if (fullbleed and not has_locator) else _SPOT_X)
    header_x = float(_HEADER_X_FB if fullbleed else _HEADER_X)
    # 橫式：股名左（離頂）；產業／今K 右欄分行拉開，不准左右黏成一塊
    name_y = 96.55 if fullbleed else float(_SPOT_Y)
    _paint_nameplate(
        ov,
        plate,
        x=header_x,
        skip_industry=bool(fullbleed),
        y=float(name_y),
        title_size=22 if fullbleed else 28,
    )
    if fullbleed:
        # 產業與股名同行右側；今K 整列下移，垂直拉開
        _paint_industry_chips(
            ov,
            plate,
            x=float(spot_x) - 0.35,
            y=float(name_y),
            align="right",
        )
    date_line = f"最近收盤 {_ymd_full(last_bar.get('date'))}"
    chip_max = (_LOOKUP_LOCATOR_LEFT * 100.0 - 2.8) if portrait else (
        float(_HEADER_CHIP_MAX_FB) if (fullbleed and not has_locator) else _HEADER_CHIP_MAX
    )
    # 橫式介紹帶：左右欄每行再拉開；狀態晶片不准掉進主圖、不准貼帶底
    if fullbleed:
        # 介紹帶 ~31%：列距 ≥3.4，股名／價／漲跌／晶片不黏
        date_y, ohlc_y1, ohlc_y2 = 92.85, 89.35, 85.85
        spike_y1, spike_y2, mute_y, chip_y0 = 82.15, 78.75, 75.45, 72.05
        chip_step = 3.45
        # 今K 在產業下方再拉開；較昨日再往下（不准貼產業晶片／收盤列）
        spot_y = 90.25
        spot_move_dy = 6.55
    else:
        date_y, ohlc_y1, ohlc_y2 = 92.85, 89.35, 86.35
        spike_y1, spike_y2, mute_y, chip_y0 = 83.15, 80.15, 76.85, 73.55
        chip_step = 3.6
        spot_y = float(_SPOT_Y)
        spot_move_dy = None
    ov.text(
        header_x,
        date_y,
        date_line,
        color=_TEXT,
        fontproperties=_fp(15 if fullbleed else 16, "bold"),
        va="center",
        ha="left",
    )
    ohlc_1 = (
        f"開 {_px(last_bar.get('open'))}　高 {_px(last_bar.get('high'))}　"
        f"低 {_px(last_bar.get('low'))}"
    )
    # 橫式有右側今K／較昨日時，左欄只留量，不准「收」與「較昨日」互壓
    if quote and not portrait:
        ohlc_2 = f"量 {_vol(last_bar.get('volume'))}"
    else:
        ohlc_2 = f"收 {_px(last_bar.get('close'))}　量 {_vol(last_bar.get('volume'))}"
    # 開高低收／爆大量日一律兩行且不同 Y，不准跟今K同一條互壓
    ov.text(
        header_x, ohlc_y1, ohlc_1, color=_TEXT,
        fontproperties=_fp(14 if fullbleed else 15, "bold"),
        va="center", ha="left",
    )
    ov.text(
        header_x, ohlc_y2, ohlc_2, color=_TEXT,
        fontproperties=_fp(14 if fullbleed else 15, "bold"),
        va="center", ha="left",
    )
    spike_1 = f"爆大量日 {_ymd_full(spike_date)}"
    spike_2 = (
        f"高 {_px(spike_hi)}＝壓　低 {_px(spike_lo)}＝撐　"
        f"量 {_vol(spike_bar.get('volume'))}"
    )
    ov.text(
        header_x, spike_y1, spike_1, color=_PRESS,
        fontproperties=_fp(14 if fullbleed else 15, "bold"),
        va="center", ha="left",
    )
    ov.text(
        header_x, spike_y2, spike_2, color=_PRESS,
        fontproperties=_fp(14 if fullbleed else 15, "bold"),
        va="center", ha="left",
    )
    ov.text(
        header_x,
        mute_y,
        "不是15分、不是介紹圖／決策卡",
        color=_MUTED,
        fontproperties=_fp(12 if fullbleed else 13, "bold"),
        va="center",
        ha="left",
    )
    chip_x, chip_y = header_x, chip_y0
    if mark:
        chip_x = _draw_chip(ov, chip_x, chip_y, mark, fc="#ffffff", ec=mc, tc=mc, size=12 if fullbleed else 13)
        chip_x = header_x
        chip_y -= chip_step
    ch_lab = str((channel or {}).get("label") or "").strip()
    if ch_lab:
        ch_color = _UP_TRACK if str((channel or {}).get("kind") or "") == "asc" else _DOWN_TRACK
        ch_bits = [b for b in ch_lab.replace("　", " ").split() if b] + ["不是買訊"]
        for bit in ch_bits:
            need = _ow(f" {bit} ", 12) + 1.3
            if chip_x > header_x + 0.2 and chip_x + need > chip_max:
                if chip_y - chip_step < band_floor:
                    break
                chip_x = header_x
                chip_y -= chip_step
            chip_x = _draw_chip(
                ov, chip_x, chip_y, bit, fc="#ffffff", ec=ch_color, tc=ch_color,
                size=11 if fullbleed else 12,
            )
        chip_x, chip_y = header_x, chip_y - chip_step
    for bit in banner_bits:
        need = _ow(f" {bit} ", 12) + 1.3
        if chip_x > header_x + 0.2 and chip_x + need > chip_max:
            if chip_y - chip_step < band_floor:
                break
            chip_x = header_x
            chip_y -= chip_step
        if chip_y < band_floor:
            break
        chip_x = _draw_chip(
            ov, chip_x, chip_y, bit, fc="#f4f6f8", ec="#90a4ae", tc="#37474f",
            size=11 if fullbleed else 12,
        )
    # 直式查股：頭牌已有開高低收；再畫今K會壓進迷你圖。橫式才留今K。
    if quote and not portrait:
        _paint_spot(
            ov,
            quote,
            x=spot_x,
            y=spot_y,
            move_dy=spot_move_dy,
        )
    if has_locator:
        loc_legs: List[Dict[str, Any]] = []
        loc_marks: List[Dict[str, Any]] = []
        if down_pts:
            off = len(rows) - n
            if not five:
                five = infer_impulse_five(rows, peak_i=off + int(down_pts[0][0]))
            loc_legs.extend(impulse_five_legs(five))
            loc_marks.extend(impulse_five_marks(five, size=12))
            (x1, y1, _d1), (x2, y2, _d2) = down_pts
            xa, ya = float(off + x1), float(y1)
            xb, yb = float(off + x2), float(y2)
            loc_hi = max(float(r.get("high") or 0) for r in rows) or y1
            loc_lo = min(float(r.get("low") or 0) for r in rows if float(r.get("low") or 0) > 0) or y2
            clipped = _clip_line(
                xa,
                ya,
                xb,
                yb,
                x_lo=0.0,
                x_hi=float(len(rows) - 1 + _FUTURE),
                y_lo=loc_lo - (loc_hi - loc_lo) * 0.04,
                y_hi=loc_hi + (loc_hi - loc_lo) * 0.08,
            )
            if clipped:
                loc_legs.append(
                    {
                        "xs": [clipped[0], clipped[2]],
                        "ys": [clipped[1], clipped[3]],
                        "color": _DOWN_TRACK,
                        "lw": 1.25,
                        "lab": "",
                        "dots": False,
                    }
                )
        # 數得出 1～5 才標數字。數不出來不改寫升／回，那不是波浪。
        loc_left = _LOOKUP_LOCATOR_LEFT if portrait else _LOCATOR_LEFT
        loc_rect = (
            loc_left,
            _STOCK_LOCATOR_BOTTOM_FB if fullbleed else _STOCK_LOCATOR_BOTTOM,
            _STRUCTURE_FIG_RIGHT - loc_left,
            _STOCK_LOCATOR_HEIGHT_FB if fullbleed else _STOCK_LOCATOR_HEIGHT,
        )
        paint_locator_inset(
            fig,
            rows,
            win_from=str(work[0].get("date") or ""),
            win_to=str(work[-1].get("date") or ""),
            rect=loc_rect if portrait else (
                _STOCK_LOCATOR_RECT_FB if fullbleed else _STOCK_LOCATOR_RECT
            ),
            title="橙＝大圖區間　黃＝預估",
            legs=loc_legs,
            forecast_n=_FUTURE,
            marks=loc_marks,
        )
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID, zorder=1)
    # 只留右邊股價刻度
    ax1.yaxis.set_ticks_position("right")
    ax1.tick_params(
        labelsize=12,
        left=False,
        right=True,
        labelleft=False,
        labelright=True,
        bottom=False,
        labelbottom=False,
        length=5,
        width=0.8,
    )
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(12, "bold"))
    vol_heights, vol_ylim, _vol_missing = paint_lookup_volume_bars(
        ax2,
        xs,
        vols,
        candle_up,
        halt=halt_flags,
        spike_i=spike_i,
        z=3,
    )
    vmax = float(vol_ylim) if vol_ylim else 1.0
    ax2.set_ylim(0, vmax * 1.28)
    if 0 <= spike_i < n and vols[spike_i]:
        # 量標拉到空白帶，避開量柱本體
        vol_tx = min(n - 1.2, spike_i + 6.5) if spike_i < n - 8 else max(1.0, spike_i - 6.5)
        _leader_note(
            ax2,
            float(spike_i),
            float(vols[spike_i]),
            f"這根＝爆大量　{_vol(vols[spike_i])}",
            _TEXT,
            tx=vol_tx,
            ty=vmax * 1.12,
            size=11,
            ha="left" if vol_tx >= spike_i else "right",
            va="center",
        )
    ax2.set_ylabel("")
    ax2.yaxis.set_ticks_position("right")
    ax2.tick_params(
        labelsize=11,
        left=False,
        right=True,
        labelleft=False,
        labelright=True,
        length=5,
        width=0.8,
    )
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{int(round(v)):,}"))
    for lab in ax2.get_yticklabels():
        lab.set_fontproperties(_fp(11, "bold"))
    ax2.set_xlim(-0.55, x_right)
    paint_forecast_span(ax2, n - 1, _FUTURE, line=False)
    ax2.axvline(n - 0.45, color="#b0bec5", linewidth=1.0, linestyle=":", zorder=2)
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID)
    tick_i = _axis_ticks(n, extra=(spike_i,))
    if n - 1 + _FUTURE not in tick_i:
        tick_i.append(n - 1 + _FUTURE)
    labels = []
    for i in tick_i:
        if i >= n:
            labels.append("演算")
            continue
        d = _ymd_full(work[i].get("date"))
        labels.append(d[5:].replace("-", "/") if d else _md(work[i].get("date")))
    ax2.set_xticks(tick_i)
    ax2.set_xticklabels(labels, fontproperties=_fp(11, "bold"))
    fig.subplots_adjust(
        left=_FIG_LEFT,
        right=_STRUCTURE_FIG_RIGHT,
        top=_STOCK_MAIN_TOP if portrait else _STOCK_MAIN_TOP_FULLBLEED,
        bottom=_FIG_BOTTOM_FB if fullbleed else _FIG_BOTTOM,
    )
    # 查詢時間：直式放頭牌右上（縮圖左側），不准壓迷你圖
    # 橫式：貼介紹帶底緣內側，不准飄到頂裁／靈動島
    try:
        from decision_card_signals import format_card_query_stamp

        date_s, clock_s = format_card_query_stamp(
            is_live=False,
            latest_date=last_d,
            stock_id=str(sid or ""),
        )
        stamp_x = (_LOOKUP_LOCATOR_LEFT - 0.012) if portrait else (
            _STRUCTURE_FIG_RIGHT - 0.012
        )
        stamp_y = 0.988 if portrait else (
            _STOCK_MAIN_TOP_FULLBLEED + 0.012 if fullbleed else _STOCK_MAIN_TOP + 0.006
        )
        fig.text(
            stamp_x,
            stamp_y,
            f"{date_s} {clock_s}",
            ha="right",
            va="top" if portrait else "bottom",
            fontproperties=_fp(11, "bold"),
            color="#455a64",
            zorder=14,
        )
    except Exception:
        pass
    from wayne_navigator import _savefig_lookup_png

    _savefig_lookup_png(fig, save_path, use_dpi)
    plt.close(fig)
    if os.path.isfile(save_path):
        _lookup_render_memo_put(memo_key, save_path)
        return save_path
    return ""


def _short(text: str, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


_FIELD_LECTURE = "個股最重要是產業趨勢還在不在；技術分析最有用在大盤。"


def neuron_glance(fired: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """圖上／說明用的六顆短句。不准開場念規則。"""
    out: Dict[str, str] = {}
    if not isinstance(fired, dict):
        return out
    by = {
        str(s.get("id") or ""): s
        for s in (fired.get("steps") or [])
        if isinstance(s, dict)
    }
    nest = str((by.get("nest") or {}).get("text") or "")
    m = re.search(r"現在位階[^。]+", nest)
    if m:
        out["nest"] = m.group(0).rstrip("。").split("；再前", 1)[0].strip()
    elif "45839 之上" in nest:
        out["nest"] = "大盤官方收還在 45839 之上"
    elif "已低於他自己點的 9/3 低 45839" in nest:
        out["nest"] = "大盤官方收已低於 45839，覆巢先當有事"
    elif nest:
        out["nest"] = nest.split("。")[0].strip(" ；")
    field = str((by.get("field") or {}).get("text") or "").replace(_FIELD_LECTURE, "").strip(" ；。")
    if "護城河最高" in field:
        m = re.search(r"[^。]*護城河最高[^。]*", field)
        out["field"] = (m.group(0) if m else field).split("；")[0].strip(" ；")
    elif re.search(r"F[14]0?", field):
        m = re.search(r"[^。]*F[14]0?[^。]*", field)
        out["field"] = (m.group(0) if m else field).split("；")[0].strip(" ；")
    elif "護城河" in field:
        m = re.search(r"[^。]*護城河[^。]*", field)
        out["field"] = (m.group(0) if m else field).split("；")[0].strip(" ；")
    elif field:
        out["field"] = field.split("。")[0].strip(" ；")
    lead = str((by.get("leader") or {}).get("text") or "")
    if "自己就是" in lead:
        out["leader"] = "自己就是這族龍頭"
    elif lead:
        out["leader"] = lead.split("（", 1)[0].strip(" ；。")
    hold = str((by.get("hold") or {}).get("text") or "")
    if "勿輕易調節" in hold and "可抱到明年" in hold:
        out["hold"] = "長抱：可抱到明年，勿輕易調節"
    elif "勿輕易調節" in hold:
        out["hold"] = "長抱：勿輕易調節"
    elif "可抱到明年" in hold:
        out["hold"] = "長抱：可抱到明年"
    elif "只當進出" in hold or "不要偷換成可抱到明年" in hold:
        out["hold"] = "這檔先當進出，不是長抱名單"
    elif hold:
        out["hold"] = _short(hold, 72)
    doubt = str((by.get("doubt") or {}).get("text") or "")
    if "公開文沒點名" in doubt:
        out["doubt"] = "公開文沒點名這檔，可能看錯"
    elif "沒疊滿" in doubt:
        out["doubt"] = "沒疊滿就不講死"
    elif doubt:
        out["doubt"] = _short(doubt, 48)
    think = str(fired.get("think") or "").strip()
    if think:
        out["think"] = _short(think, 280)
    return out


def chart_caption(
    info: Dict[str, Any],
    *,
    sid: str = "",
    name: str = "",
    glance: Optional[Dict[str, str]] = None,
    plate: Optional[Dict[str, str]] = None,
    surface: Optional[Dict[str, Any]] = None,
) -> str:
    head = f"{sid} {name}".strip()
    plate = plate or {}
    extras = "　".join(
        x for x in (str(plate.get("industry") or "").strip(), str(plate.get("leader") or "").strip()) if x
    )
    if extras:
        head = f"{head}　{extras}".strip()
    lines = [
        f"{head}　官方日K量先價行".strip(),
    ]
    g = stock_display_glance(glance, sid=sid, plate=plate)
    st = info.get("struct") or {}
    last_bar = info.get("last_bar") or {}
    spike_hi = st.get("spike_high")
    spike_lo = st.get("spike_low")
    if spike_hi and spike_lo:
        tape = (
            f"這檔收 {_px(last_bar.get('close'))}，爆大量那一天 "
            f"{_ymd_full(st.get('spike_date'))} 高 {_px(spike_hi)}＝壓、"
            f"低 {_px(spike_lo)}＝撐、量 {_vol(st.get('spike_volume') or (info.get('spike_bar') or {}).get('volume'))}。"
        )
        if info.get("wash"):
            tape += "破撐之後又站回，比較像破線洗盤。"
        elif info.get("distribution"):
            tape += "過壓之後又掉回撐下，比較像出貨。"
        # 大量日高／低判斷句不上 caption
        lines.append(tape)
    ch = info.get("channel") or {}
    tip = str(ch.get("tip") or "").strip()
    if tip:
        lines.append(tip)
    else:
        try:
            close_f = float(last_bar.get("close") or 0)
        except (TypeError, ValueError):
            close_f = 0.0
        try:
            down_now = float(info.get("down_now") or 0)
        except (TypeError, ValueError):
            down_now = 0.0
        try:
            up_now = float(info.get("up_now") or 0)
        except (TypeError, ValueError):
            up_now = 0.0
        if down_now:
            lines.append(
                f"下降壓延長約 {_px(down_now)}"
                + ("還壓著。" if close_f and close_f < down_now else "收在上。")
            )
        if up_now and not info.get("up_broken"):
            lines.append(f"上升撐延長約 {_px(up_now)}。")
    proj = info.get("project") or {}
    if proj.get("label"):
        lines.append("圖上演算：" + str(proj.get("label")))
    if surface:
        try:
            from biaoke_chain import desk_caption_judgment

            bit = desk_caption_judgment(surface)
            if bit:
                for ln in bit.splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    if ln in lines:
                        continue
                    if any(ln[:16] in x for x in lines):
                        continue
                    lines.append(ln)
        except Exception:
            pass
    if g.get("hold"):
        lines.append(g["hold"])
    if g.get("doubt"):
        lines.append(g["doubt"])
    else:
        lines.append("沒疊滿就不講死。")
    lines.append("圖右演化區＝壓撐／連點延長，不是保證、不是買訊。個股不數浪。")
    return "\n".join(x for x in lines if x)[:1100]


def build_biaoke_structure_chart(
    db_path: str,
    sid: str,
    save_path: str,
    *,
    name: str = "",
    ask: str = "",
    uid: str = "",
) -> Dict[str, Any]:
    from biaoke_brain import load_bars

    sid = str(sid or "").strip()
    bars = load_bars(db_path, sid, n=360) if db_path and sid else []
    if not bars:
        return {"ok": False, "path": "", "caption": ""}
    nm = name or str(bars[-1].get("stock_name") or sid)
    info = analyze_structure(bars[-_BARS:])
    # 代號出圖也走串接表達面：文字桌與圖說同一條判斷／官方結構
    q = (ask or "").strip() or sid
    surface: Dict[str, Any] = {}
    glance: Dict[str, str] = {}
    try:
        from biaoke_chain import desk_surface

        surface = desk_surface(db_path, q, uid=uid) or {}
        glance = dict(surface.get("glance") or {})
    except Exception:
        logger.debug("飆大結構圖神經元略過", exc_info=True)
        surface = {}
        glance = {}
    plate = stock_nameplate(sid, nm, db_path)
    prev = bars[-2] if len(bars) >= 2 else {}
    last = info.get("last_bar") or bars[-1]
    quote = _spot_quote(sid, last, prev, db_path)
    path = render_biaoke_structure_png(
        bars,
        save_path,
        sid=sid,
        name=nm,
        glance=glance,
        plate=plate,
        quote=quote,
        db_path=db_path,
    )
    try:
        from biaoke_forecast import record_stock, verify_due

        record_stock(db_path, sid, bars, name=nm)
        verify_due(db_path, sid)
    except Exception:
        logger.debug("結構圖演算建檔略過", exc_info=True)
    return {
        "ok": bool(path),
        "path": path or "",
        "caption": chart_caption(
            info, sid=sid, name=nm, glance=glance, plate=plate, surface=surface
        ),
        "sid": sid,
        "name": nm,
        "wash": bool(info.get("wash")),
        "distribution": bool(info.get("distribution")),
        "project": dict(info.get("project") or {}),
        "notes": list(info.get("notes") or []),
        "glance": glance,
        "surface": {
            "lead": str(surface.get("lead") or ""),
            "judge": str(surface.get("judge") or ""),
            "rail": str(surface.get("rail") or ""),
        },
    }
