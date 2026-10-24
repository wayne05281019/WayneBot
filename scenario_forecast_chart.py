# -*- coding: utf-8 -*-
"""個股「情境預估（不保證）」圖：DC 視覺臉＋VEGAS／浪號／虛線未來路徑。

視覺對齊 TradingView：淺灰底、白框／黑棒 K、白／粉紅／藍路徑、
浪號沿時間軸（未走伸右側未來）、右側彩底價標、區間帶。
獨立附加、永遠不是買訊。僅此子鈕可標浪；其他鈕仍守 §12。
失敗回 None；不准擋查股四張／主選單。Asia/Taipei；官方日 K 選點；
盤中可疊決策卡真開高低收＋量（與圖一～四同源），不准假柱。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

logger = logging.getLogger("WayneBot.ScenarioForecast")

_TZ = ZoneInfo("Asia/Taipei")

# 近窗對齊結構圖量級；右側未來軸長度依該檔浪段根數對稱（非固定曆日終點）
_BARS = 320
_WAVE_LEFT = 10
_WAVE_MIN_BARS = 14
_WAVE_MIN_PCT = 0.10
# 未來軸上下限（交易日根數）：不夠讀／過長都裁；真正長度由 `_dc_future_horizon` 算
_FUTURE_MIN = 18
_FUTURE_MAX = 160
_FUTURE_FALLBACK = 48  # 無浪骨架時的短預設（不再用固定 72→家家 27/01）
_DPI = 168
_MIN_BARS = 40
# 日曆換算：交易日→約略日曆日（軸標用；與舊 _future_tick_labels 一致）
_CAL_PER_BAR = 1.4

# DC 配色鎖（v4）：白實線已走／黑線 abc／白虛線未來；禁全紅粗線壓 K
_BG = "#e6e6e6"
_GRID = "#c5c8cc"
_TUNNEL = "#1e88e5"
_EMA12 = "#43a047"
_EMA_SLOW = "#e57373"
_PRESS = "#5c6bc0"  # 斜壓：藍紫，非血紅
_SUPPORT = "#78909c"  # 斜撐
_LADDER = "#e53935"  # 僅水平關鍵／右側紅標
_TEXT = "#212121"
_WAVE_IMP = "#fafafa"  # 已走：白實線
_WAVE_IMP_EDGE = "#424242"
_WAVE_PROJ = "#ffffff"  # 未走：白虛線
_WAVE_ABC = "#111111"  # abc：黑線
_PIN = "#ff4081"  # 粉紅 map-pin
_TAG_BG = "#757575"  # 灰框區間文案
_TAG_HOT = "#e53935"  # 右側紅底精準價
_TAG_NOW = "#212121"  # 右側現價黑標
_BUBBLE = "#1565c0"
_ZONE_SUP = "#9e9e9e"  # 支撐灰帶
_ZONE_TGT = "#90caf9"  # 目標藍帶
_ZONE_OK = "#b0bec5"  # 滿足／回測區
_CHANNEL = "#ba68c8"  # 紫平行通道
_PATH_COLORS = ("#b0bec5", "#90a4ae", "#78909c")
_VOL_UP = "#bdbdbd"
_VOL_DN = "#757575"


def _ema(closes: Sequence[float], n: int) -> List[float]:
    vals = [float(x or 0) for x in closes]
    if not vals or n < 1:
        return []
    k = 2.0 / (float(n) + 1.0)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1.0 - k)
        out.append(e)
    return out


def _rows_from_df(df) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if df is None or getattr(df, "empty", True):
        return rows
    for _, r in df.iterrows():
        try:
            o = float(r.get("open") or 0)
            h = float(r.get("high") or 0)
            lo = float(r.get("low") or 0)
            c = float(r.get("close") or 0)
            v = float(r.get("volume") or 0)
        except Exception:
            continue
        if h <= 0 or lo <= 0 or c <= 0:
            continue
        rows.append(
            {
                "date": str(r.get("date") or ""),
                "stock_name": str(r.get("stock_name") or ""),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": v,
            }
        )
    return rows


def _tunnel_stance(last: float, e144: float, e169: float) -> str:
    lo = min(e144, e169)
    hi = max(e144, e169)
    if last > hi * 1.002:
        return "之上"
    if last < lo * 0.998:
        return "之下"
    return "之中"


def infer_desc_press(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """樞紐下降壓：复用 biaoke 最近兩樞紐高規則；不夠兩點＝{}。"""
    try:
        from biaoke_chart import _desc_high_pair, _line_at, _pivots, _px, _md
    except Exception:
        return {}
    rows = list(rows or [])
    n = len(rows)
    if n < 24:
        return {}
    highs = [float(r.get("high") or 0) for r in rows]
    closes = [float(r.get("close") or 0) for r in rows]
    hi_p, _ = _pivots(highs, [float(r.get("low") or 0) for r in rows], left=3)
    pair = _desc_high_pair(hi_p, highs)
    if not pair:
        return {}
    i, j = int(pair[0]), int(pair[1])
    if j - i < 10:
        return {}
    y_now = _line_at(float(i), highs[i], float(j), highs[j], float(n - 1))
    last = float(closes[-1] or 0)
    if last > y_now * 1.002:
        pos = "已過下降壓"
    elif abs(last - y_now) / max(y_now, 1e-9) < 0.015:
        pos = "靠近下降壓"
    else:
        pos = "下降壓下"
    return {
        "i": i,
        "j": j,
        "y1": float(highs[i]),
        "y2": float(highs[j]),
        "d1": str(rows[i].get("date") or ""),
        "d2": str(rows[j].get("date") or ""),
        "y_now": float(y_now),
        "pos": pos,
        "tip": (
            f"下降壓：{_md(rows[i].get('date'))}高{_px(highs[i])}～"
            f"{_md(rows[j].get('date'))}高{_px(highs[j])}；現況{pos}。不是買訊。"
        ),
    }


def infer_prior_high_ladders(
    rows: Sequence[Dict[str, Any]], *, max_n: int = 3
) -> List[Dict[str, Any]]:
    """近窗樞紐高階梯候選：收盤尚未明顯站上者，最多 3 條。"""
    try:
        from biaoke_chart import _pivots, _px, _md
    except Exception:
        return []
    rows = list(rows or [])
    n = len(rows)
    if n < 20:
        return []
    highs = [float(r.get("high") or 0) for r in rows]
    lows = [float(r.get("low") or 0) for r in rows]
    last = float(rows[-1].get("close") or 0)
    hi_p, _ = _pivots(highs, lows, left=3)
    cands: List[Tuple[float, int]] = []
    seen = set()
    for idx in reversed(hi_p):
        h = float(highs[idx])
        if h <= 0:
            continue
        key = round(h, 2)
        if key in seen:
            continue
        if last >= h * 0.995:
            continue
        seen.add(key)
        cands.append((h, int(idx)))
        if len(cands) >= int(max_n):
            break
    cands.sort(key=lambda t: t[0])
    out: List[Dict[str, Any]] = []
    for h, idx in cands:
        out.append(
            {
                "price": float(h),
                "date": str(rows[idx].get("date") or ""),
                "i": int(idx),
                "label": f"候選 {_px(h)}",
                "tip": f"前高候選 {_md(rows[idx].get('date'))}高{_px(h)}（非保證）",
            }
        )
    return out


def _fmt_px(v: float) -> str:
    try:
        from biaoke_chart import _px

        return str(_px(float(v)))
    except Exception:
        x = float(v)
        if abs(x - round(x)) < 1e-6:
            return str(int(round(x)))
        return f"{x:.2f}".rstrip("0").rstrip(".")


def _alternating_zigzag(
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    left: int = 5,
    min_bars: int = 6,
    min_pct: float = 0.035,
) -> List[Dict[str, Any]]:
    """顯著擺動 zigzag：濾毛刺（語料歸納：間隔≥6、幅度≥~3.5%）。"""
    try:
        from biaoke_chart import _pivots
    except Exception:
        return []
    hi_p, lo_p = _pivots(list(highs), list(lows), left=int(left))
    raw: List[Dict[str, Any]] = []
    for i in hi_p:
        raw.append({"i": int(i), "kind": "H", "price": float(highs[i])})
    for i in lo_p:
        raw.append({"i": int(i), "kind": "L", "price": float(lows[i])})
    raw.sort(key=lambda p: p["i"])
    out: List[Dict[str, Any]] = []
    for p in raw:
        if not out:
            out.append(p)
            continue
        if p["kind"] == out[-1]["kind"]:
            if p["kind"] == "H" and p["price"] >= out[-1]["price"]:
                out[-1] = p
            elif p["kind"] == "L" and p["price"] <= out[-1]["price"]:
                out[-1] = p
            continue
        bars = int(p["i"]) - int(out[-1]["i"])
        amp = abs(float(p["price"]) - float(out[-1]["price"])) / max(
            float(out[-1]["price"]), 1e-9
        )
        if bars < int(min_bars) or amp < float(min_pct):
            continue
        out.append(p)
    return out


def _pick_ladder_above(levels: Sequence[float], floor: float, *, default: float) -> float:
    for lv in sorted(float(x) for x in levels if float(x) > 0):
        if lv > floor * 1.005:
            return float(lv)
    return float(default)


def _bar_date(rows: Sequence[Dict[str, Any]], i: float) -> str:
    ii = int(round(float(i)))
    if ii < 0 or ii >= len(rows):
        return ""
    d = str(rows[ii].get("date") or "")
    return d[4:8] if len(d) >= 8 else d


def _wave_node(
    label: str,
    i: float,
    price: float,
    kind: str,
    *,
    projected: bool,
    date: str = "",
    next_cycle: bool = False,
) -> Dict[str, Any]:
    node: Dict[str, Any] = {
        "label": label,
        "i": float(i),
        "price": float(price),
        "kind": kind,
        "projected": bool(projected),
        "date": str(date or ""),
    }
    if next_cycle:
        node["next_cycle"] = True
    return node


def _leg_bars(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """兩浪點之間的交易日根數（絕對值）。"""
    try:
        return abs(float(b.get("i") or 0) - float(a.get("i") or 0))
    except Exception:
        return 0.0


def _confirmed_leg_bars(
    start: Dict[str, Any], confirmed: Sequence[Dict[str, Any]]
) -> Dict[str, float]:
    """已走浪段根數：'(1)'=start→(1)、'(2)'=(1)→(2)…。DC 時間對稱用這組。"""
    out: Dict[str, float] = {}
    nodes: List[Dict[str, Any]] = [dict(start or {})] + [dict(c) for c in (confirmed or [])]
    for a, b in zip(nodes, nodes[1:]):
        lab = str(b.get("label") or "").strip()
        if not lab:
            continue
        bars = _leg_bars(a, b)
        if bars > 0:
            out[lab] = float(bars)
    return out


def _dc_mirror_leg_bars(
    want: str,
    legs: Dict[str, float],
    *,
    prior_corr_bars: float = 0.0,
) -> float:
    """未走浪段應佔幾根：對齊 DC「根數對根數」時間對稱（非固定 FUTURE 比例）。

    對照 media/dc-style-refs 2404／3529／3661＋docs/dc-wave-drawing-logic-year-corpus.md：
    - (3) 鏡射 (1)；若 (1) 很短且前有長修正，拉到 max(1.618·(1), 0.5·修正)
    - (4) 鏡射 (2)（交替）
    - (5) 鏡射已走 (3)，否則 (1)（2404：W5≈W3≈3 個月）
    """
    w1 = float(legs.get("(1)") or 0.0)
    w2 = float(legs.get("(2)") or 0.0)
    w3 = float(legs.get("(3)") or 0.0)
    if w1 <= 0:
        w1 = 20.0
    if w2 <= 0:
        w2 = max(12.0, w1 * 0.618)
    want = str(want or "").strip()
    if want == "(3)":
        base = max(w1, float(_WAVE_MIN_BARS))
        if w1 < 16.0 and float(prior_corr_bars or 0) >= 30.0:
            base = max(base, w1 * 1.618, float(prior_corr_bars) * 0.5)
        return float(max(base, 14.0))
    if want == "(4)":
        return float(max(w2, 10.0))
    if want == "(5)":
        src = w3 if w3 > 0 else w1
        return float(max(src, 14.0))
    return float(max(w1, 14.0))


def _dc_project_impulse_xs(
    start: Dict[str, Any],
    confirmed: Sequence[Dict[str, Any]],
    *,
    x_now: float,
    n: int,
    prior_corr_bars: float = 0.0,
) -> Tuple[Dict[str, float], float, Dict[str, float]]:
    """依已走浪段根數投影 (3)(4)(5) 的 x，並回傳 future_bars（自 n-1 起算）。

    回傳：(label→x, future_bars, label→Δbars)。
    軸終點＝最遠投影點＋末段 0.35·Δ（DC 常留反應空白；不是家家拉到同一曆日）。
    """
    legs = _confirmed_leg_bars(start, confirmed)
    have = {str(c.get("label") or "") for c in (confirmed or [])}
    by_lab = {str(c.get("label") or ""): c for c in (confirmed or [])}
    xs: Dict[str, float] = {}
    durs: Dict[str, float] = {}
    cursor = float(x_now)

    def _anchor(lab: str) -> float:
        node = by_lab.get(lab)
        if node is not None:
            return float(node.get("i") or 0)
        return float(xs.get(lab) or cursor)

    if "(3)" not in have:
        d3 = _dc_mirror_leg_bars("(3)", legs, prior_corr_bars=prior_corr_bars)
        durs["(3)"] = d3
        xs["(3)"] = float(x_now) + d3
        cursor = xs["(3)"]
    else:
        cursor = max(cursor, _anchor("(3)"))

    if "(4)" not in have:
        d4 = _dc_mirror_leg_bars("(4)", legs, prior_corr_bars=prior_corr_bars)
        durs["(4)"] = d4
        base = max(float(x_now), _anchor("(3)") if "(3)" in have or "(3)" in xs else float(x_now))
        xs["(4)"] = base + d4
        cursor = xs["(4)"]
    else:
        cursor = max(cursor, _anchor("(4)"))

    if "(5)" not in have:
        d5 = _dc_mirror_leg_bars("(5)", legs, prior_corr_bars=prior_corr_bars)
        durs["(5)"] = d5
        base = max(float(x_now), _anchor("(4)") if "(4)" in have or "(4)" in xs else float(x_now))
        # (4) 已在過去：仍從 max(x_now, x4) 起算整段鏡射根數（2404：W5≈W3）
        xs["(5)"] = base + d5
        cursor = xs["(5)"]

    # 僅「(3)(4)(5) 全虛」的早段衝動：總跨度若過短才等比拉長（3529 短 W1）。
    # 已走長段只虛 (5)（2404）不准用 2.5·(W1+W2) 再爆開。
    if (
        "(3)" in durs
        and "(4)" in durs
        and "(5)" in durs
        and "(1)" in legs
        and "(2)" in legs
    ):
        raw_span = max(xs.values()) - float(x_now)
        # 上限 100：對齊 DC 3529 數月窗，避免拉到半年以上假軸
        target = max(
            raw_span,
            min(2.5 * (float(legs["(1)"]) + float(legs["(2)"])), 100.0),
            48.0,
        )
        if raw_span > 1e-6 and target > raw_span * 1.05:
            scale = target / raw_span
            for lab in list(xs.keys()):
                xs[lab] = float(x_now) + (xs[lab] - float(x_now)) * scale
                if lab in durs:
                    durs[lab] = float(durs[lab]) * scale
            cursor = max(xs.values())

    last_dur = 0.0
    for lab in ("(5)", "(4)", "(3)"):
        if lab in durs:
            last_dur = float(durs[lab])
            break
    if last_dur <= 0 and legs:
        last_dur = float(max(legs.values()))
    pad = max(last_dur * 0.35, 8.0)
    x_end = (max(xs.values()) if xs else float(x_now)) + pad
    future_bars = float(x_end) - float(n - 1)
    future_bars = max(float(_FUTURE_MIN), min(float(_FUTURE_MAX), future_bars))
    # 軸不夠長時等比壓縮投影 x，不准把 (3)(4)(5) 全夾成同一個 x（否則未來折線消失）
    x_cap = float(n - 1) + float(future_bars)
    if xs:
        far = max(float(v) for v in xs.values())
        if far > x_cap + 1e-6 and far > float(x_now) + 1e-6:
            usable = max(float(x_cap) - float(x_now) - max(pad * 0.15, 4.0), 12.0)
            raw = far - float(x_now)
            scale = usable / raw if raw > 1e-9 else 1.0
            for lab in list(xs.keys()):
                xs[lab] = float(x_now) + (float(xs[lab]) - float(x_now)) * scale
                if lab in durs:
                    durs[lab] = float(durs[lab]) * scale
        else:
            for lab in list(xs.keys()):
                if xs[lab] > x_cap:
                    xs[lab] = x_cap - max(pad * 0.25, 4.0)
    return xs, future_bars, durs


def _dc_abc_future_bars(
    abc: Sequence[Dict[str, Any]],
    *,
    peak: Optional[Dict[str, Any]],
    deadline: Optional[Dict[str, Any]],
    n: int,
) -> float:
    """abc 修正軌：未來軸跟期限／修正跨度走，不准再灌固定 72 根到同一 27/01。

    DC 3661：主敘是 (v)+abc＋斜壓期限；右側只留條件窗／盤整空白，不是五浪長軸。
    """
    n = int(n)
    x_now = float(n - 1)
    cands: List[float] = []
    if deadline and deadline.get("i") is not None:
        di = float(deadline["i"])
        if di > x_now:
            cands.append(di - x_now + 6.0)
    span = 0.0
    if abc and peak:
        try:
            span = abs(float(abc[-1].get("i") or 0) - float(peak.get("i") or 0))
        except Exception:
            span = 0.0
    elif abc and len(abc) >= 2:
        span = _leg_bars(abc[0], abc[-1])
    if span > 0:
        cands.append(max(span * 0.4, 18.0))
    if not cands:
        cands.append(float(_FUTURE_FALLBACK) * 0.55)
    fut = max(cands)
    return float(max(_FUTURE_MIN, min(_FUTURE_MAX, fut)))


def _clamp_future_bars(fut: float) -> float:
    try:
        v = float(fut)
    except Exception:
        v = float(_FUTURE_FALLBACK)
    if v <= 0:
        v = float(_FUTURE_FALLBACK)
    return float(max(_FUTURE_MIN, min(_FUTURE_MAX, v)))


def _snap_support_band_price(
    rows: Sequence[Dict[str, Any]], i: float, raw_low: float
) -> float:
    """(2) 用撐帶敘事：長下影時改釘實體底／心理關，不只釘極值。

    可讀 dc_sf_rules.support_band（D.C 日對質當天寫入）；讀不到用預設。
    """
    ii = int(round(float(i)))
    if ii < 0 or ii >= len(rows):
        return float(raw_low)
    r = rows[ii]
    try:
        o = float(r.get("open") or 0)
        h = float(r.get("high") or 0)
        lo = float(r.get("low") or 0)
        c = float(r.get("close") or 0)
    except Exception:
        return float(raw_low)
    if lo <= 0 or h <= 0:
        return float(raw_low)
    wick_ratio = 0.975
    psych_steps = (50.0, 100.0)
    try:
        from dc_scenario_silent_verify import load_rules
        from config import get_db_path

        sb = (load_rules(str(get_db_path() or "")) or {}).get("support_band") or {}
        if isinstance(sb, dict):
            if sb.get("wick_ratio"):
                wick_ratio = float(sb["wick_ratio"])
            if sb.get("psych_steps"):
                psych_steps = tuple(float(x) for x in sb["psych_steps"])
    except Exception:
        pass
    body_lo = min(o, c) if o > 0 and c > 0 else lo
    # 無長下影＝極值就是撐，不改（避免 821→850 誤推）
    if lo >= body_lo * float(wick_ratio):
        return float(raw_low)
    px = body_lo
    # 心理關：落在影線～實體上緣＋3%
    span_hi = max(h, body_lo) * 1.03
    cands: List[float] = []
    for step in psych_steps:
        base = float(int(body_lo / step) * step)
        for k in range(-2, 5):
            lv = base + float(k) * step
            if lo * 0.99 <= lv <= span_hi:
                cands.append(lv)
    if cands:
        above = [x for x in cands if x >= body_lo * 0.98]
        pool = above or cands
        px = min(pool, key=lambda x: abs(x - body_lo))
    return float(max(px, body_lo * 0.995))


def _retarget_first_equal_peak(
    work_zz: Sequence[Dict[str, Any]],
    start: Dict[str, Any],
    confirmed: List[Dict[str, Any]],
    lows: Sequence[float],
    rows: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """同價再測：年線級 (1) 優先首峰（如 2404 2025-09），不鎖在再測峰。"""
    w1 = next((c for c in confirmed if c["label"] == "(1)"), None)
    w2 = next((c for c in confirmed if c["label"] == "(2)"), None)
    if not w1 or not w2:
        return start, confirmed
    earlier = [
        p
        for p in work_zz
        if p.get("kind") == "H"
        and float(p["i"]) < float(w1["i"]) - 0.5
        and abs(float(p["price"]) - float(w1["price"]))
        / max(float(w1["price"]), 1e-9)
        <= 0.025
    ]
    if not earlier:
        return start, confirmed
    e1 = min(earlier, key=lambda p: float(p["i"]))
    if float(w2["i"]) <= float(e1["i"]):
        return start, confirmed
    i0 = int(e1["i"])
    if i0 <= 0:
        return start, confirmed
    j = int(min(range(i0), key=lambda k: float(lows[k])))
    new_start = {
        "i": float(j),
        "price": float(lows[j]),
        "kind": "L",
        "date": _bar_date(rows, j),
    }
    new_conf = [
        _wave_node(
            "(1)",
            e1["i"],
            e1["price"],
            "H",
            projected=False,
            date=_bar_date(rows, e1["i"]),
        )
    ] + [c for c in confirmed if c["label"] != "(1)"]
    return new_start, new_conf


def _ending_fifth_band(src3_price: float) -> Tuple[float, float]:
    """終端／楔形 (5) 目標帶：貼 (3) 上沿（1450→約 1530）。"""
    lo = float(src3_price) * 0.995
    hi = float(src3_price) * 1.055
    return lo, hi


def _wave4_fulfill_band(
    p1: float, p2: float, p3: float
) -> Tuple[float, float]:
    """(4) 滿足區：取 (3)→(2) 的 0.5～0.618 回撤帶，並與 (1) 價鄰域取聯集。

    可遷移（D.C.）：(4) 常回 (1) 附近／半數回撤，不是只釘 0.382 單點。
    回傳 (lo, hi)，lo≤hi。不准當買訊。
    """
    try:
        a1, a2, a3 = float(p1), float(p2), float(p3)
    except Exception:
        return 0.0, 0.0
    if a3 <= a2:
        return min(a1, a2), max(a1, a3)
    span = a3 - a2
    fib_lo = a3 - 0.618 * span
    fib_hi = a3 - 0.50 * span
    z_lo = min(fib_lo, a1 * 0.97)
    z_hi = max(fib_hi, a1 * 1.08)
    if z_lo > z_hi:
        z_lo, z_hi = z_hi, z_lo
    return float(z_lo), float(z_hi)


def _wave_desc_press_vb(
    rows: Sequence[Dict[str, Any]],
    peak: Dict[str, Any],
    b_node: Dict[str, Any],
) -> Dict[str, Any]:
    """abc 敘事下降壓：(v)→(b) 延伸。"""
    n = len(rows)
    i = int(round(float(peak["i"])))
    j = int(round(float(b_node["i"])))
    if j - i < 8 or i < 0 or j >= n:
        return {}
    y1 = float(peak["price"])
    y2 = float(b_node["price"])
    slope = (y2 - y1) / float(j - i)
    y_now = y2 + slope * (float(n - 1) - float(j))
    last = float(rows[-1].get("close") or 0)
    if last > y_now * 1.002:
        pos = "已過下降壓"
    elif abs(last - y_now) / max(y_now, 1e-9) < 0.015:
        pos = "靠近下降壓"
    else:
        pos = "下降壓下"
    return {
        "i": i,
        "j": j,
        "y1": y1,
        "y2": y2,
        "d1": str(rows[i].get("date") or ""),
        "d2": str(rows[j].get("date") or ""),
        "y_now": float(y_now),
        "pos": pos,
        "source": "wave_vb",
        "tip": (
            f"下降壓：(v)高{_fmt_px(y1)}～(b)高{_fmt_px(y2)}；現況{pos}。"
            f"不保證・不是買訊。"
        ),
    }


def _deadline_after_c(
    rows: Sequence[Dict[str, Any]], c_i: float, *, bars: int = 18
) -> Dict[str, Any]:
    """修正 (c) 後期限豎線（約 18 根≈一個月內條件窗）。"""
    n = len(rows)
    ii = min(n - 1, max(0, int(round(float(c_i))) + int(bars)))
    return {
        "i": float(ii),
        "date": str(rows[ii].get("date") or ""),
        "label": _bar_date(rows, ii),
    }


def infer_dc_wave_scenario(
    rows: Sequence[Dict[str, Any]],
    ladders: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """大級別浪階定稿：長窗 degree zigzag；abc 與衝動分軌；未轉折不凍 (3)。

    規則見 docs/dc-wave-drawing-logic-year-corpus.md。僅情境預估；不是買訊。
    """
    rows = list(rows or [])
    n = len(rows)
    empty: Dict[str, Any] = {}
    if n < _MIN_BARS:
        return empty
    highs = [float(r.get("high") or 0) for r in rows]
    lows = [float(r.get("low") or 0) for r in rows]
    last = float(rows[-1].get("close") or 0)
    if last <= 0:
        return empty
    zz = _alternating_zigzag(
        highs,
        lows,
        left=int(_WAVE_LEFT),
        min_bars=int(_WAVE_MIN_BARS),
        min_pct=float(_WAVE_MIN_PCT),
    )
    fine = _alternating_zigzag(highs, lows, left=5, min_bars=6, min_pct=0.05)
    if len(zz) < 2 and len(fine) < 3:
        return empty
    ladder_lv = sorted(
        {float(x.get("price") or 0) for x in (ladders or []) if float(x.get("price") or 0) > 0}
    )

    def _pack(
        start: Dict[str, Any],
        confirmed: List[Dict[str, Any]],
        projected: List[Dict[str, Any]],
        abc: List[Dict[str, Any]],
        *,
        next_cycle: Optional[List[Dict[str, Any]]] = None,
        state: str = "",
        bubble: str = "",
        desc_press: Optional[Dict[str, Any]] = None,
        deadline: Optional[Dict[str, Any]] = None,
        zones: Optional[List[Dict[str, Any]]] = None,
        wedge: Optional[Dict[str, Any]] = None,
        future_bars: Optional[float] = None,
        leg_bars: Optional[Dict[str, float]] = None,
        proj_durs: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        next_cycle = list(next_cycle or [])
        path_done: List[Tuple[float, float]] = [
            (float(start["i"]), float(start["price"]))
        ]
        for c in confirmed:
            path_done.append((float(c["i"]), float(c["price"])))
        path_proj: List[Tuple[float, float]] = []
        if projected:
            if next_cycle and abc:
                path_proj.append((float(abc[-1]["i"]), float(abc[-1]["price"])))
            else:
                path_proj.append(path_done[-1])
            # DC 週線可遷移（新唐 186465869）：波3 先過已走 (1) 前高，再中繼，再到 (3)
            # 不准直跳終點、也不准抄單檔 800 絕對價
            path_proj.extend(
                _dc_w3_climb_waypoints(
                    confirmed, projected, last=last, x_now=float(n - 1)
                )
            )
            for c in projected:
                path_proj.append((float(c["i"]), float(c["price"])))
        conf_labs = [c["label"] for c in confirmed]
        proj_labs = [c["label"] for c in projected]
        if not bubble:
            if abc and not projected:
                bubble = "情境預估：完成浪後修正 abc（樞紐重算・不保證・不是買訊）"
                state = state or "abc"
            elif abc and next_cycle:
                bubble = "情境預估：abc 後虛線新一輪（不保證・不是買訊）"
                state = state or "abc_next"
            elif conf_labs and proj_labs:
                bubble = (
                    f"情境預估：已標{''.join(conf_labs)}，虛線{''.join(proj_labs)}"
                    f"（不保證・不是買訊）"
                )
                state = state or "partial"
            else:
                bubble = "情境預估：上升浪骨架（不保證・不是買訊）"
                state = state or "partial"
        # 無顯式 future_bars：從投影最遠 x 推（仍非固定 72）
        fut = future_bars
        if fut is None:
            x_now = float(n - 1)
            far = x_now
            for c in projected:
                try:
                    far = max(far, float(c.get("i") or 0))
                except Exception:
                    pass
            fut = _clamp_future_bars(far - x_now + 8.0)
        else:
            fut = _clamp_future_bars(float(fut))
        return {
            "start": start,
            "confirmed": confirmed,
            "projected": projected,
            "abc": abc,
            "path_done": path_done,
            "path_proj": path_proj,
            "bubble": bubble,
            "state": state,
            "labels": conf_labs + [a["label"] for a in abc] + proj_labs,
            "next_cycle": next_cycle,
            "desc_press": dict(desc_press or {}),
            "deadline": dict(deadline or {}),
            "zones": list(zones or []),
            "wedge": dict(wedge or {}),
            "future_bars": float(fut),
            "leg_bars": dict(leg_bars or {}),
            "proj_durs": dict(proj_durs or {}),
        }

    # ----- 候選：大級別衝動 -----
    work = list(zz)
    if work and work[0]["kind"] == "H":
        i0 = int(work[0]["i"])
        if i0 > 0:
            j = min(range(i0), key=lambda k: lows[k])
            work = [{"i": j, "kind": "L", "price": float(lows[j])}] + work

    def _impulse_from(work_zz):
        """大級別衝動：允許跨中間樞紐塌縮成 L→max(H)→L。

        DC 新唐類：細 zigzag 會在大 (1) 裡塞中段高低，只看相鄰
        L-H-L 會把真 (1)(2) 拆碎或誤判破起點。可遷移：同一對起迄低點
        之間取最高峰為 (1)，再找其後最低合格 (2)。
        """
        best_local = None
        best_sc = -1.0
        zz = list(work_zz or [])
        n_zz = len(zz)
        for i in range(n_zz):
            if zz[i]["kind"] != "L":
                continue
            start_p = zz[i]
            for k in range(i + 2, n_zz):
                if zz[k]["kind"] != "L":
                    continue
                w2 = zz[k]
                mid = zz[i + 1 : k]
                hs = [p for p in mid if p["kind"] == "H"]
                if not hs:
                    continue
                w1 = max(hs, key=lambda p: float(p["price"]))
                if float(w1["price"]) <= float(start_p["price"]) * 1.01:
                    continue
                if float(w2["price"]) >= float(w1["price"]) * 0.995:
                    continue
                # (2) 不可破 (1) 起點（標準衝動）
                if float(w2["price"]) < float(start_p["price"]) * 0.998:
                    continue
                # (2) 須在 (1) 峰之後
                if float(w2["i"]) <= float(w1["i"]):
                    continue
                span = float(w2["i"]) - float(start_p["i"])
                if span < 12:
                    continue
                amp_pct = (float(w1["price"]) - float(start_p["price"])) / max(
                    float(start_p["price"]), 1e-9
                )
                if amp_pct < 0.06:
                    continue
                confirmed: List[Dict[str, Any]] = [
                    _wave_node(
                        "(1)",
                        w1["i"],
                        w1["price"],
                        "H",
                        projected=False,
                        date=_bar_date(rows, w1["i"]),
                    ),
                    _wave_node(
                        "(2)",
                        w2["i"],
                        w2["price"],
                        "L",
                        projected=False,
                        date=_bar_date(rows, w2["i"]),
                    ),
                ]
                # (2) 之後的相鄰段：若已走出完整 (3)(4)／軟 (3)
                after = [p for p in zz[k + 1 :] if float(p["i"]) > float(w2["i"])]
                soft_w3 = None
                w3 = after[0] if after and after[0]["kind"] == "H" else None
                w4 = after[1] if len(after) > 1 and after[1]["kind"] == "L" else None
                w5 = after[2] if len(after) > 2 and after[2]["kind"] == "H" else None
                # 跨樞紐時 (3) 取 (2) 後最高峰（未確認回撤前僅 soft）
                post_hs = [p for p in after if p["kind"] == "H"]
                if (
                    w3
                    and float(w3["price"]) > float(w1["price"]) * 1.002
                    and w4
                    and float(w4["price"]) < float(w3["price"]) * 0.998
                    and float(w4["price"]) > float(start_p["price"])
                ):
                    confirmed.append(
                        _wave_node(
                            "(3)",
                            w3["i"],
                            w3["price"],
                            "H",
                            projected=False,
                            date=_bar_date(rows, w3["i"]),
                        )
                    )
                    confirmed.append(
                        _wave_node(
                            "(4)",
                            w4["i"],
                            w4["price"],
                            "L",
                            projected=False,
                            date=_bar_date(rows, w4["i"]),
                        )
                    )
                    if w5 and float(w5["price"]) > float(w3["price"]) * 1.001:
                        len1 = float(w1["price"]) - float(start_p["price"])
                        len3 = float(w3["price"]) - float(w2["price"])
                        len5 = float(w5["price"]) - float(w4["price"])
                        if len3 + 1e-9 >= min(len1, len5):
                            confirmed.append(
                                _wave_node(
                                    "(5)",
                                    w5["i"],
                                    w5["price"],
                                    "H",
                                    projected=False,
                                    date=_bar_date(rows, w5["i"]),
                                )
                            )
                elif post_hs:
                    peak3 = max(post_hs, key=lambda p: float(p["price"]))
                    if float(peak3["price"]) > float(w1["price"]) * 1.002:
                        soft_w3 = peak3
                    elif float(peak3["price"]) > float(w2["price"]) * 1.05:
                        # 未過 (1) 的早段反彈：仍可當 soft 抬高 (3) 下限
                        soft_w3 = peak3
                last_i = float(confirmed[-1]["i"])
                span_frac = span / float(max(n, 1))
                recency = (last_i / float(max(n - 1, 1))) ** 1.5
                # 偏好更大級別幅度；略罰過遠的舊段
                score = amp_pct * (0.5 + 4.0 * span_frac) * (0.4 + 1.6 * recency)
                score *= 1.0 + 0.1 * float(len(confirmed))
                # 同窗多組時，(2) 越靠近現在越好（活躍段）
                score *= 0.85 + 0.15 * (float(w2["i"]) / float(max(n - 1, 1)))
                if score > best_sc:
                    best_sc = score
                    best_local = {
                        "start": start_p,
                        "confirmed": confirmed,
                        "soft_w3": soft_w3,
                        "score": score,
                        "span": span,
                        "amp": amp_pct,
                    }
        return best_local

    impulse = _impulse_from(work)

    # ----- 候選：大頂後 abc（僅當其後沒有更強的新衝動）-----
    abc_cand = None
    use = zz if len(zz) >= 2 else fine
    hi_piv = [p for p in use if p["kind"] == "H"]
    if hi_piv:
        peak = max(hi_piv, key=lambda p: p["price"])
        if float(peak["price"]) >= max(highs) * 0.92:
            after = [p for p in fine if p["i"] > peak["i"]]
            abc_nodes: List[Dict[str, Any]] = []
            for i in range(len(after) - 2):
                a, b, c = after[i], after[i + 1], after[i + 2]
                if a["kind"] == "L" and b["kind"] == "H" and c["kind"] == "L":
                    # 修正要夠深
                    if (
                        c["price"] < peak["price"] * 0.70
                        and c["price"] <= a["price"] * 1.05
                        and b["price"] < peak["price"] * 0.98
                    ):
                        abc_nodes = [a, b, c]
                        break
            if abc_nodes:
                c = abc_nodes[2]
                post_hs = [p for p in use if p["kind"] == "H" and p["i"] > c["i"]]
                broke_peak = any(p["price"] > peak["price"] * 1.01 for p in post_hs)
                # 自 c 起是否已走出新衝動（3529：(Y) 後 (1)(2)）
                post_work = [p for p in fine if p["i"] >= c["i"]]
                if post_work and post_work[0]["kind"] != "L":
                    post_work = [c] + [p for p in post_work if p["i"] > c["i"]]
                new_imp = _impulse_from(post_work) if len(post_work) >= 3 else None
                b_px = float(abc_nodes[1]["price"])
                ci = int(c["i"])
                post_max = max(highs[ci:]) if ci < n else float(c["price"])
                # 反彈未過 (b)→修正主敘（3661）；過 (b)／續推→(Y) 後新循環（3529）
                recovered_past_b = post_max >= b_px * 0.98
                strong_new = bool(
                    new_imp
                    and recovered_past_b
                    and new_imp["amp"] >= 0.15
                    and float(new_imp["confirmed"][0]["price"]) > float(c["price"]) * 1.12
                )
                # 若大頂其實是衝動的 (3)（其後有 (4)），優先衝動
                peak_is_w3 = bool(
                    impulse
                    and any(
                        c0["label"] == "(3)"
                        and abs(float(c0["i"]) - float(peak["i"])) < 1.5
                        for c0 in impulse["confirmed"]
                    )
                )
                if peak_is_w3:
                    pass
                elif strong_new and new_imp:
                    abc_cand = {"force_new_imp": new_imp}
                elif not broke_peak:
                    pre_ls = [p for p in use if p["kind"] == "L" and p["i"] < peak["i"]]
                    if pre_ls:
                        st = pre_ls[-1]
                    else:
                        ii = max(0, int(peak["i"]) - 20)
                        st = {
                            "i": ii,
                            "price": float(min(lows[ii : int(peak["i"]) + 1] or [lows[0]])),
                            "kind": "L",
                        }
                    abc_cand = {
                        "start": st,
                        "peak": peak,
                        "abc_nodes": abc_nodes,
                        "new_imp": new_imp,
                    }

    # 決策：完整衝動含 (3)(4) > abc（未過 b）> 自 c 新衝動 > 一般衝動
    chosen = None
    mode = "impulse"
    if (
        impulse
        and any(c["label"] == "(4)" for c in impulse["confirmed"])
        and impulse["span"] >= 60
    ):
        chosen = impulse
        mode = "impulse"
    elif abc_cand:
        mode = "abc"
    elif impulse:
        chosen = impulse
        mode = "impulse"
    else:
        return empty

    # abc 候選若其實已 strong_new，改走新衝動（在建立 abc_cand 時已濾；此處處理僅 new_imp）
    if mode == "abc" and abc_cand and abc_cand.get("force_new_imp"):
        chosen = abc_cand["force_new_imp"]
        mode = "impulse"

    if mode == "abc" and abc_cand:
        peak = abc_cand["peak"]
        st = abc_cand["start"]
        confirmed = [
            _wave_node(
                "(v)",
                peak["i"],
                peak["price"],
                "H",
                projected=False,
                date=_bar_date(rows, peak["i"]),
            )
        ]
        abc = [
            _wave_node(
                lab,
                p["i"],
                p["price"],
                p["kind"],
                projected=False,
                date=_bar_date(rows, p["i"]),
            )
            for lab, p in zip(("a", "b", "c"), abc_cand["abc_nodes"])
        ]
        b_node = abc[1] if len(abc) > 1 else None
        c_node = abc[2] if len(abc) > 2 else None
        press_vb = (
            _wave_desc_press_vb(rows, confirmed[0], b_node) if b_node else {}
        )
        deadline = (
            _deadline_after_c(rows, float(c_node["i"]), bars=18) if c_node else {}
        )
        zones: List[Dict[str, Any]] = []
        if c_node:
            cp = float(c_node["price"])
            zones.append(
                {
                    "lo": cp * 0.97,
                    "hi": cp * 1.04,
                    "kind": "ok",
                    "label": f"滿足 {_fmt_px(cp)}",
                }
            )
        dl_lab = str((deadline or {}).get("label") or "").strip()
        bubble = (
            f"情境預估：下降壓(v)–(b)"
            + (f"；{dl_lab}前站上才轉多敘事" if dl_lab else "")
            + "（不保證・不是買訊）"
        )
        fut_abc = _dc_abc_future_bars(
            abc, peak=confirmed[0] if confirmed else None, deadline=deadline, n=n
        )
        return _pack(
            {
                "i": float(st["i"]),
                "price": float(st["price"]),
                "kind": "L",
                "date": _bar_date(rows, st["i"]),
            },
            confirmed,
            [],
            abc,
            state="abc",
            bubble=bubble,
            desc_press=press_vb,
            deadline=deadline,
            zones=zones,
            future_bars=fut_abc,
            leg_bars=_confirmed_leg_bars(
                {
                    "i": float(st["i"]),
                    "price": float(st["price"]),
                    "kind": "L",
                },
                confirmed + abc,
            ),
        )

    assert chosen is not None
    confirmed = list(chosen["confirmed"])
    start_p = chosen["start"]
    start = {
        "i": float(start_p["i"]),
        "price": float(start_p["price"]),
        "kind": "L",
        "date": _bar_date(rows, start_p["i"]),
    }
    # 年線級 (1)：同價再測改釘首峰；起點移到首峰前低
    start, confirmed = _retarget_first_equal_peak(
        work, start, confirmed, lows, rows
    )
    # 可遷移：同一 (1)(2) 下，起點改釘 (1) 前、仍不破 (2) 規則的最低 L
    # （避免中段較高 L 搶成起點，DC 新唐類真起點常是大行情前的更低）
    try:
        w1n = next(c for c in confirmed if c.get("label") == "(1)")
        w2n = next(c for c in confirmed if c.get("label") == "(2)")
        w1i, w1px = float(w1n["i"]), float(w1n["price"])
        w2px = float(w2n["price"])
        better = [
            p
            for p in work
            if p.get("kind") == "L"
            and float(p["i"]) < w1i
            and w2px >= float(p["price"]) * 0.998
            and w1px > float(p["price"]) * 1.01
        ]
        if better:
            low_p = min(better, key=lambda p: float(p["price"]))
            if float(low_p["price"]) < float(start["price"]) * 0.995:
                start = {
                    "i": float(low_p["i"]),
                    "price": float(low_p["price"]),
                    "kind": "L",
                    "date": _bar_date(rows, low_p["i"]),
                }
    except Exception:
        pass
    # (2) 撐帶：長下影不釘極值
    for idx, node in enumerate(confirmed):
        if node.get("label") == "(2)" and node.get("kind") == "L":
            snapped = _snap_support_band_price(
                rows, float(node["i"]), float(node["price"])
            )
            confirmed[idx] = dict(node)
            confirmed[idx]["price"] = float(snapped)
    amp1 = float(confirmed[0]["price"]) - float(start["price"])
    projected: List[Dict[str, Any]] = []
    have = {c["label"] for c in confirmed}
    x_now = max(float(confirmed[-1]["i"]), float(n - 1))
    # 前修正跨度（Y／深低前的下降）：短 (1) 時拉長 (3) 時間對稱
    prior_corr = 0.0
    try:
        si = int(round(float(start["i"])))
        if 2 <= si < n:
            pre_peak_i = max(range(0, si), key=lambda k: highs[k])
            prior_corr = float(si - int(pre_peak_i))
    except Exception:
        prior_corr = 0.0
    proj_xs, fut_imp, proj_durs = _dc_project_impulse_xs(
        start,
        confirmed,
        x_now=x_now,
        n=n,
        prior_corr_bars=prior_corr,
    )
    # 樂觀參考軸頂：深 (2)（回撤≥50% amp1）允許看到 1.618～2.618 延伸，
    # 否則舊 1.35×(1) 會把未來滿足點壓成「像只標過去近高」。可遷移，非抄單檔價。
    n2 = next((c for c in confirmed if c["label"] == "(2)"), None)
    deep_w2 = False
    if n2 and amp1 > 0:
        retr = (float(confirmed[0]["price"]) - float(n2["price"])) / max(amp1, 1e-9)
        deep_w2 = retr >= 0.50
    y_cap = max(float(confirmed[0]["price"]) * 1.35, last * 1.45)
    y_cap = max(y_cap, float(confirmed[0]["price"]) + amp1 * 1.618)
    if deep_w2:
        # (3) 看×2.618；(5) 需再高一截（DC 週線 (5)＞(3)）。×3＝可遷移上限帶，非抄 800。
        y_cap = max(
            y_cap,
            float(start["price"]) + amp1 * 2.618,
            float(n2["price"]) + amp1 * 1.618,
            float(confirmed[0]["price"]) * 1.618,
            float(confirmed[0]["price"]) * 2.618,
            float(confirmed[0]["price"]) * 3.0,
        )
    if ladder_lv:
        y_cap = max(y_cap, max(ladder_lv) * 1.05)
    soft_w3 = chosen.get("soft_w3")
    zones = []
    wedge: Dict[str, Any] = {}
    if "(3)" not in have:
        y3_default = float(confirmed[0]["price"]) + min(
            amp1 * 1.618, float(confirmed[0]["price"]) * 0.35
        )
        if deep_w2 and n2:
            # 樂觀 (3)：DC 週線常見過 (1) 後看 (1)×1.618～2.618 帶
            # （新唐圖 (1)≈228 →×2.618≈598，對他針腳 619 同帶；不准寫死 619）
            y3_default = max(
                y3_default,
                float(n2["price"]) + amp1 * 1.618,
                float(confirmed[0]["price"]) * 1.618,
                float(confirmed[0]["price"]) * 2.618,
            )
        y3 = _pick_ladder_above(
            ladder_lv,
            float(confirmed[0]["price"]),
            default=y3_default,
        )
        if soft_w3:
            y3 = max(y3, float(soft_w3["price"]) * 1.02)
        y3 = max(y3, float(confirmed[0]["price"]) * 1.05)
        y3 = min(y3, y_cap)
        projected.append(
            _wave_node(
                "(3)",
                float(proj_xs.get("(3)", x_now + 24)),
                y3,
                "H",
                projected=True,
                date="估",
            )
        )
    if "(4)" not in have:
        src3 = next((c for c in confirmed + projected if c["label"] == "(3)"), None)
        src2 = next((c for c in confirmed if c["label"] == "(2)"), None)
        src1 = next((c for c in confirmed if c["label"] == "(1)"), None)
        if src3 and src2:
            # 可遷移：優先落在 (4) 滿足區（(1) 鄰＋0.5～0.618），不盲釘 0.382 單點
            y4 = float(src3["price"]) - 0.50 * (
                float(src3["price"]) - float(src2["price"])
            )
            if src1:
                z_lo, z_hi = _wave4_fulfill_band(
                    float(src1["price"]),
                    float(src2["price"]),
                    float(src3["price"]),
                )
                if z_hi > z_lo > 0:
                    y4 = min(max(y4, z_lo), z_hi)
                    zones.append(
                        {
                            "lo": float(z_lo),
                            "hi": float(z_hi),
                            "kind": "ok",
                            "label": f"{_fmt_px(z_hi)}/{_fmt_px(z_lo)}",
                        }
                    )
            y4 = max(y4, float(start["price"]) * 1.02)
            projected.append(
                _wave_node(
                    "(4)",
                    float(proj_xs.get("(4)", x_now + 36)),
                    y4,
                    "L",
                    projected=True,
                    date="估",
                )
            )
    if "(5)" not in have:
        src3 = next((c for c in confirmed + projected if c["label"] == "(3)"), None)
        src4 = next((c for c in confirmed + projected if c["label"] == "(4)"), None)
        src2 = next((c for c in confirmed if c["label"] == "(2)"), None)
        if src3 and src4:
            y5_default = float(src3["price"]) + min(
                amp1 * 0.8, float(src3["price"]) * 0.15
            )
            if deep_w2:
                # 樂觀 (5)：常 ≥ (3)，可再延伸約 0.618～1.0× amp1
                y5_default = max(
                    y5_default,
                    float(src3["price"]) + amp1 * 0.618,
                    float(src4["price"]) + amp1,
                )
            y5 = _pick_ladder_above(
                ladder_lv,
                float(src3["price"]),
                default=y5_default,
            )
            y5 = max(y5, float(src3["price"]) * 1.03)
            y5 = min(y5, y_cap * 1.02)
            # 已走 (3)(4)：終端楔形 (5) 對齊 (3) 上沿帶（1450–1530）
            if "(3)" in have and "(4)" in have:
                blo, bhi = _ending_fifth_band(float(src3["price"]))
                in_band = [lv for lv in ladder_lv if blo <= float(lv) <= bhi]
                if in_band:
                    y5 = float(max(in_band))
                elif y5 > bhi * 1.01:
                    y5 = float(bhi)
                else:
                    y5 = float(min(max(y5, blo), bhi))
                zones.append(
                    {
                        "lo": float(blo),
                        "hi": float(bhi),
                        "kind": "tgt",
                        "label": f"{_fmt_px(blo)}/{_fmt_px(bhi)}",
                    }
                )
            projected.append(
                _wave_node(
                    "(5)",
                    float(proj_xs.get("(5)", x_now + 48)),
                    y5,
                    "H",
                    projected=True,
                    date="估",
                )
            )
    # 楔形雙軌：上 (1)(3)、下 (2)(4)
    n1 = next((c for c in confirmed if c["label"] == "(1)"), None)
    n2 = next((c for c in confirmed if c["label"] == "(2)"), None)
    n3 = next((c for c in confirmed + projected if c["label"] == "(3)"), None)
    n4 = next((c for c in confirmed + projected if c["label"] == "(4)"), None)
    if n1 and n2 and n3 and n4:
        wedge = {
            "upper": (
                float(n1["i"]),
                float(n1["price"]),
                float(n3["i"]),
                float(n3["price"]),
            ),
            "lower": (
                float(n2["i"]),
                float(n2["price"]),
                float(n4["i"]),
                float(n4["price"]),
            ),
        }
    # (2) 撐帶灰區
    if n2:
        bp = float(n2["price"])
        zones.append(
            {
                "lo": bp * 0.985,
                "hi": bp * 1.035,
                "kind": "sup",
                "label": f"撐 {_fmt_px(bp)}",
            }
        )
    # 若投影點超出初估 future，以實際最遠點重算
    if projected:
        far = max(float(p["i"]) for p in projected)
        fut_imp = _clamp_future_bars(max(fut_imp, far - float(n - 1) + max(
            float((proj_durs or {}).get("(5)") or (proj_durs or {}).get("(3)") or 14) * 0.35,
            8.0,
        )))
    return _pack(
        start,
        confirmed,
        projected,
        [],
        state="partial",
        zones=zones,
        wedge=wedge,
        future_bars=fut_imp,
        leg_bars=_confirmed_leg_bars(start, confirmed),
        proj_durs=proj_durs,
    )



def _dc_w3_climb_waypoints(
    confirmed: Sequence[Dict[str, Any]],
    projected: Sequence[Dict[str, Any]],
    *,
    last: float,
    x_now: float,
) -> List[Tuple[float, float]]:
    """未走 (3) 爬升中繼：先過 (1) 前高，再約 0.382 中繼（DC 週線針腳語意）。

    對照 CMoney 2590523／186465869 新唐週線：222→290/300→(3)。
    可遷移＝過前高＋比例中繼；不是抄 619／800。
    """
    n1 = next((c for c in confirmed if str(c.get("label") or "") == "(1)"), None)
    n3 = next((c for c in projected if str(c.get("label") or "") == "(3)"), None)
    if not n1 or not n3:
        return []
    try:
        y1 = float(n1["price"])
        y3 = float(n3["price"])
        x3 = float(n3["i"])
        x0 = float(x_now)
        last_px = float(last or 0)
    except Exception:
        return []
    if y3 <= y1 * 1.02 or x3 <= x0 + 1.0:
        return []
    span = x3 - x0
    out: List[Tuple[float, float]] = []
    if last_px < y1 * 0.995:
        out.append((x0 + 0.28 * span, y1))
    y_mid = y1 + 0.382 * (y3 - y1)
    if y_mid > y1 * 1.02 and y_mid < y3 * 0.98:
        out.append((x0 + 0.55 * span, float(y_mid)))
    return out


def _optimistic_fallback_levels(rows: Sequence[Dict[str, Any]], last: float) -> List[float]:
    """無前高階梯時的樂觀參考階（全檔通用；不是買訊）。

    優先近窗歷史高（仍高於現價）；否則用現價×1.05／1.12／1.20。
    查每一支都要有可讀未來路徑時的後備，不准特判單一股號。
    """
    last = float(last or 0)
    if last <= 0:
        return []
    highs = [float(r.get("high") or 0) for r in (rows or []) if float(r.get("high") or 0) > 0]
    out: List[float] = []
    if highs:
        peak = float(max(highs))
        if peak > last * 1.002:
            out.append(round(peak, 4))
        # 次高：近窗高點裡略低於峰、仍高於現價
        below = sorted({round(h, 4) for h in highs if last * 1.002 < h < peak * 0.995})
        for h in below[-2:]:
            if h not in out:
                out.append(h)
    if len(out) < 2:
        for m in (1.05, 1.12, 1.20):
            lv = round(last * m, 4)
            if lv > last * 1.002 and lv not in out:
                out.append(lv)
            if len(out) >= 3:
                break
    return sorted(out)[:3]


def infer_scenario_paths(
    rows: Sequence[Dict[str, Any]],
    ladders: Sequence[Dict[str, Any]],
    *,
    n_bars: Optional[int] = None,
    max_paths: int = 3,
) -> List[Dict[str, Any]]:
    """相位 1.5：2～3 條淺色虛線情境階梯（現價附近→最近前高→下一階）。

    全檔共用：上市／上櫃／興櫃同一入口。無浪或 abc 完成無投影時走這裡；
    連前高階梯也沒有時改樂觀後備階，不准右半空白。
    """
    rows = list(rows or [])
    n = int(n_bars if n_bars is not None else len(rows))
    if n < _MIN_BARS or not rows:
        return []
    last = float(rows[-1].get("close") or 0)
    if last <= 0:
        return []
    levels = sorted(
        {
            round(float(x.get("price") or 0), 4)
            for x in (ladders or [])
            if float(x.get("price") or 0) > last * 1.002
        }
    )
    if not levels:
        levels = _optimistic_fallback_levels(rows, last)
    if not levels:
        return []
    use = levels[:3]
    pacings = (
        (3.0, 5.0, 5.0),
        (2.0, 4.0, 4.5),
        (1.5, 3.0, 3.5),
    )
    n_paths = max(1, min(int(max_paths), 3, len(use) + 1))
    if len(use) == 1:
        n_paths = min(2, n_paths)
    else:
        n_paths = min(3, max(2, n_paths))
    out: List[Dict[str, Any]] = []
    x0 = float(n - 1)
    for pi in range(n_paths):
        pace = pacings[min(pi, len(pacings) - 1)]
        depth = min(len(use), 1 + pi if len(use) > 1 else 1)
        if len(use) >= 2 and pi == n_paths - 1:
            depth = len(use)
        rung_prices = [last] + use[:depth]
        pts: List[Tuple[float, float]] = [(x0, last)]
        x = x0
        steps_meta: List[Dict[str, Any]] = []
        prev = last
        for si, yp in enumerate(rung_prices[1:], start=1):
            dx = float(pace[min(si - 1, len(pace) - 1)])
            x_h = x + dx
            pts.append((x_h, prev))
            pts.append((x_h, float(yp)))
            gap = float(yp) - float(prev)
            gap_pct = (gap / max(prev, 1e-9)) * 100.0
            steps_meta.append(
                {
                    "from": float(prev),
                    "to": float(yp),
                    "low": float(min(prev, yp)),
                    "high": float(max(prev, yp)),
                    "gap": float(gap),
                    "gap_pct": float(gap_pct),
                    "x": float(x_h),
                    "label": (
                        f"{_fmt_px(prev)}→{_fmt_px(yp)}"
                        f"（+{_fmt_px(gap)}／{gap_pct:.1f}%）"
                    ),
                }
            )
            x = x_h
            prev = float(yp)
        pts.append((x + 1.2, prev))
        out.append(
            {
                "id": pi + 1,
                "points": pts,
                "steps": steps_meta,
                "color": _PATH_COLORS[min(pi, len(_PATH_COLORS) - 1)],
                "tip": "情境階梯（不保證・不是買訊）",
            }
        )
    return out


def dodge_label_ys(
    anchors: Sequence[Tuple[float, float, str]],
    *,
    min_gap: float,
) -> List[Tuple[float, float, str]]:
    """標籤 y 自動避讓：同側由低到高推開，避免互壓。"""
    items = [(float(x), float(y), str(t)) for x, y, t in (anchors or []) if t]
    if not items:
        return []
    items.sort(key=lambda t: (t[1], t[0]))
    gap = max(float(min_gap), 1e-9)
    placed: List[Tuple[float, float, str]] = []
    last_y = None
    for x, y, t in items:
        yy = y
        if last_y is not None and yy < last_y + gap:
            yy = last_y + gap
        placed.append((x, yy, t))
        last_y = yy
    return placed


def build_scenario_meta(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rows or [])
    closes = [float(r.get("close") or 0) for r in rows]
    last = float(closes[-1] or 0) if closes else 0.0
    meta: Dict[str, Any] = {
        "vegas": {},
        "desc_press": {},
        "ladders": [],
        "paths": [],
        "wave": {},
        "caption_bits": [],
    }
    e12 = _ema(closes, 12) if len(closes) >= 12 else []
    e144 = _ema(closes, 144) if len(closes) >= 144 else []
    e169 = _ema(closes, 169) if len(closes) >= 169 else []
    e576 = _ema(closes, 576) if len(closes) >= 576 else []
    e676 = _ema(closes, 676) if len(closes) >= 676 else []
    if e144 and e169 and last > 0:
        st = _tunnel_stance(last, e144[-1], e169[-1])
        meta["vegas"] = {
            "stance": st,
            "ema12": float(e12[-1]) if e12 else None,
            "ema144": float(e144[-1]),
            "ema169": float(e169[-1]),
            "ema576": float(e576[-1]) if e576 else None,
            "ema676": float(e676[-1]) if e676 else None,
        }
        meta["caption_bits"].append(f"隧道{st}")
    press = infer_desc_press(rows)
    if press:
        meta["desc_press"] = press
        meta["caption_bits"].append(str(press.get("pos") or "下降壓"))
    ladders = infer_prior_high_ladders(rows, max_n=3)
    if ladders:
        meta["ladders"] = ladders
        meta["caption_bits"].append(
            "候選 " + "／".join(_fmt_px(x["price"]) for x in ladders)
        )
    wave = infer_dc_wave_scenario(rows, ladders)
    if wave:
        meta["wave"] = wave
        labs = "".join(wave.get("labels") or [])
        if labs:
            meta["caption_bits"].append(f"浪號{labs}")
        if wave.get("bubble"):
            meta["caption_bits"].append("情境預估／不保證")
    # 有未走投影時以浪虛線為主，少畫階梯避互壓。
    # 完成 abc／無 projected 時仍疊樂觀階梯，避免右半空白「像只標過去」。
    has_proj = bool(wave and (wave.get("projected") or wave.get("path_proj")))
    if not has_proj:
        paths = infer_scenario_paths(rows, ladders, n_bars=len(rows), max_paths=3)
        if paths:
            meta["paths"] = paths
            meta["caption_bits"].append(f"情境階梯{len(paths)}條")
    meta["_series"] = {
        "e12": e12,
        "e144": e144,
        "e169": e169,
        "e576": e576,
        "e676": e676,
    }
    return meta


def chart_note_lines(wave: Dict[str, Any]) -> str:
    """圖頂說明：走法＋已走／修正／未走轉折點位。永遠不是買訊。"""
    wave = wave or {}

    def _px(node: Dict[str, Any]) -> str:
        try:
            return _fmt_px(float(node.get("price")))
        except Exception:
            return ""

    def _groups(nodes: Sequence[Dict[str, Any]], head: str) -> List[str]:
        bits = []
        for node in nodes or []:
            lab = str(node.get("label") or "").strip()
            px = _px(node)
            if not lab or not px:
                continue
            bits.append(f"{lab} {px}")
        lines = []
        for i in range(0, len(bits), 3):
            chunk = "　".join(bits[i : i + 3])
            lines.append(f"{head} {chunk}" if i == 0 else f"　　 {chunk}")
        return lines

    def _path_mode() -> str:
        pm = str(wave.get("path_mode") or "").strip()
        if pm in ("impulse", "abc", "mixed"):
            return pm
        state = str(wave.get("state") or "").strip()
        if state == "abc":
            return "abc"
        if state == "abc_next":
            return "mixed"
        has_abc = bool(wave.get("abc"))
        has_proj = bool(wave.get("projected"))
        if has_abc and has_proj:
            return "mixed"
        if has_abc and not has_proj:
            return "abc"
        return "impulse"

    mode_key = _path_mode()
    mode = {"impulse": "衝動浪", "abc": "修正浪", "mixed": "衝動後修正"}.get(
        mode_key, ""
    )
    lines = ["情境預估" + (f"：{mode}" if mode else "")]
    lines.extend(_groups(list(wave.get("confirmed") or []), "已走"))
    if mode_key != "impulse":
        lines.extend(_groups(list(wave.get("abc") or []), "修正"))
    lines.extend(_groups(list(wave.get("projected") or []), "未走"))
    lines.append("不保證・不是買訊")
    return "\n".join(line for line in lines if line)


def format_scenario_caption(sid: str, name: str, meta: Dict[str, Any]) -> str:
    sid = str(sid or "").strip()
    name = str(name or "").strip()
    head = f"{sid}{name}　情境預估（不保證・不是買訊）".strip()
    bits = [str(b) for b in (meta or {}).get("caption_bits") or [] if b]
    wave = (meta or {}).get("wave") or {}
    # D.C 日對質寫入的說法模板（dc_sf_rules）；讀不到就用預設。不准當買訊。
    narr_suffix = ""
    try:
        from dc_scenario_silent_verify import load_rules
        from config import get_db_path

        rules = load_rules(str(get_db_path() or ""))
        tmpl = rules.get("narrative_template") or {}
        if isinstance(tmpl, dict) and tmpl.get("suffix"):
            narr_suffix = str(tmpl.get("suffix") or "").strip()
        method_words = list((tmpl or {}).get("method_words") or []) if isinstance(tmpl, dict) else []
    except Exception:
        narr_suffix = ""
        method_words = []
    if wave.get("bubble"):
        # 圖說優先用浪情境句；仍硬釘不是買訊。方法詞只補已經畫得出來的。
        body = str(wave["bubble"])
        try:
            from dc_scenario_silent_verify import method_clause

            extra = method_clause(body, wave, method_words)
            if extra:
                body = body.rstrip("。") + extra
        except Exception:
            pass
        if narr_suffix and narr_suffix not in body:
            body = body.rstrip("。") + "；" + narr_suffix
        if "不是買訊" not in body:
            body += "。不是買訊"
        return head + "\n" + body
    if bits:
        extra = f"；{narr_suffix}" if narr_suffix else ""
        return head + "\n" + "；".join(bits) + extra + "。濾網／候選不是買訊。"
    if narr_suffix:
        return head + "\n" + narr_suffix
    return head + "\n隧道／下降壓／浪號情境；不是買訊。"


def _paint_bw_candles(
    ax,
    xs: Sequence[float],
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> None:
    """DC 底圖：上＝白心黑框、下＝實心黑（不准紅綠搶浪線）。"""
    ink = "#111111"
    for i, x in enumerate(xs):
        o, h, lo, c = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i])
        ax.plot([x, x], [lo, h], color=ink, lw=0.65, solid_capstyle="round", zorder=2)
        body_lo, body_hi = min(o, c), max(o, c)
        height = max(body_hi - body_lo, (h - lo) * 0.015 + 1e-6)
        up = c >= o
        ax.add_patch(
            Rectangle(
                (x - 0.32, body_lo),
                0.64,
                height,
                facecolor="#ffffff" if up else ink,
                edgecolor=ink,
                linewidth=0.75,
                zorder=3,
            )
        )


def _paint_gray_volume(ax, xs, vols, ups) -> float:
    """低飽和灰階量柱（不准紅綠）。"""
    vmax = max(float(v) for v in vols) if vols else 1.0
    vmax = max(vmax, 1.0)
    for i, x in enumerate(xs):
        v = float(vols[i] or 0)
        ax.add_patch(
            Rectangle(
                (x - 0.32, 0.0),
                0.64,
                v,
                facecolor=_VOL_UP if ups[i] else _VOL_DN,
                edgecolor="none",
                alpha=0.72,
                zorder=2,
            )
        )
    ax.set_ylim(0, vmax * 1.15)
    return vmax


def _ymd_to_dt(s: str) -> Optional[datetime]:
    s = str(s or "").replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=_TZ)
    except Exception:
        return None


def _fmt_axis_date(dt: datetime, *, with_year: bool) -> str:
    """軸標：帶年用 2026/11/14；同年度可 11月14日。一眼可讀。"""
    if with_year:
        return f"{dt.year}/{dt.month:02d}/{dt.day:02d}"
    return f"{dt.month}月{dt.day}日"


def _future_tick_labels(
    rows: Sequence[Dict[str, Any]],
    n: int,
    x_max: float,
    *,
    wave_xs: Optional[Sequence[float]] = None,
    future_bars: Optional[float] = None,
):
    """歷史＋未來軸標（Asia/Taipei）。少刻度、帶年月。

    未來刻度錨在該檔投影浪點 x（DC：軸長跟情境幾何走），不是固定 0.88·72。
    """
    last_dt = _ymd_to_dt(str(rows[-1].get("date") or "")) or datetime.now(_TZ)
    ticks: List[float] = []
    labels: List[str] = []
    years_seen: set = set()
    fut = _clamp_future_bars(
        float(future_bars) if future_bars is not None else float(_FUTURE_FALLBACK)
    )

    def _add_hist(i: int) -> None:
        i = max(0, min(int(i), n - 1))
        d = _ymd_to_dt(str(rows[i].get("date") or ""))
        if d is None:
            return
        # 少刻度：約 3 個歷史＋現在
        if ticks and abs(float(i) - ticks[-1]) < max(n / 8.0, 18.0):
            return
        with_year = d.year not in years_seen or abs(float(i) - float(n - 1)) < 0.5
        years_seen.add(d.year)
        ticks.append(float(i))
        labels.append(_fmt_axis_date(d, with_year=with_year))

    def _add_future(xi: float) -> None:
        xi = float(xi)
        if xi <= float(n - 1) + 0.5:
            return
        if xi > x_max + 0.5:
            return
        min_gap = max(fut * 0.28, 16.0)
        if ticks and (xi - ticks[-1]) < min_gap:
            return
        days = int(round(max(0.0, xi - float(n - 1)) * float(_CAL_PER_BAR)))
        d = last_dt + timedelta(days=days)
        years_seen.add(d.year)
        ticks.append(xi)
        labels.append(_fmt_axis_date(d, with_year=True))

    # 歷史：略內縮頭／中／現價，避免旋轉大字被左緣切斷
    head_i = max(0, min(n - 1, int(round(n * 0.04))))
    for i in (head_i, n // 2, n - 1):
        _add_hist(i)
    if not any(abs(t - float(n - 1)) < 0.5 for t in ticks):
        _add_hist(n - 1)

    # 未來：優先錨投影浪點（遠→近挑到最多 2 個），再補軸終點
    cand: List[float] = []
    for x in wave_xs or []:
        try:
            xf = float(x)
        except Exception:
            continue
        if xf > float(n - 1) + 1.0:
            cand.append(xf)
    cand = sorted(set(cand))
    # 取最遠一個＋若跨度大再取中段一個（對齊 3529：(3)與(5) 兩標）
    pick: List[float] = []
    if cand:
        pick.append(cand[-1])
        if len(cand) >= 2 and (cand[-1] - cand[0]) >= max(fut * 0.35, 20.0):
            mid = cand[len(cand) // 2]
            if mid < cand[-1] - 8:
                pick.insert(0, mid)
    for xi in pick:
        _add_future(xi)
    # 若浪點太近或沒有投影：仍標該檔 future_bars 終點（分檔終點，非全球同一日）
    axis_end = float(n - 1) + fut * 0.92
    if not pick or (ticks and ticks[-1] < float(n - 1) + fut * 0.55):
        _add_future(min(axis_end, x_max))
    return ticks, labels


# 日期在價、量之間。9pt 水平置中後，3081 最右兩日仍分開。
_AXIS_DATE_PT = 9.0
# 中縫要容得下這行字，不壓價圖、不壓量柱。
_PRICE_VOL_HSPACE = 0.10
_CHART_BOTTOM = 0.06


def _style_axis_date_labels(ax, ticks, n: int) -> None:
    """年月與預估日同一小字：水平、不旋轉，置中在刻度上。不錯開。"""
    from wayne_navigator import _fp

    for lab, xi in zip(ax.get_xticklabels(), ticks):
        is_fut = float(xi) > float(n - 1) + 0.2
        lab.set_fontproperties(_fp(_AXIS_DATE_PT, "bold"))
        lab.set_color("#0d47a1" if is_fut else "#111111")
        lab.set_rotation(0)
        lab.set_ha("center")
        lab.set_va("top")
        lab.set_clip_on(False)


def _ladder_range_note(price: float, idx: int, n: int) -> str:
    """灰框區間文案：如 63/66、關鍵點位。"""
    p = float(price)
    if n == 1:
        lo, hi = p * 0.97, p * 1.03
        return f"{_fmt_px(lo)}/{_fmt_px(hi)}"
    if idx == n // 2:
        return "關鍵點位"
    # 鄰近 ±2%～3% 區間
    band = 0.025 if p >= 100 else 0.04
    return f"{_fmt_px(p * (1 - band))}/{_fmt_px(p * (1 + band))}"


def _infer_asc_support(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """樞紐上升撐：夠兩點才畫。"""
    try:
        from biaoke_chart import _asc_low_pair, _pivots, _line_at
    except Exception:
        return {}
    rows = list(rows or [])
    n = len(rows)
    if n < 24:
        return {}
    highs = [float(r.get("high") or 0) for r in rows]
    lows = [float(r.get("low") or 0) for r in rows]
    _, lo_p = _pivots(highs, lows, left=3)
    pair = _asc_low_pair(lo_p, lows)
    if not pair:
        return {}
    i, j = int(pair[0]), int(pair[1])
    if j - i < 10:
        return {}
    return {
        "i": i,
        "j": j,
        "y1": float(lows[i]),
        "y2": float(lows[j]),
        "y_now": float(_line_at(float(i), lows[i], float(j), lows[j], float(n - 1))),
    }


def _paint_wave_dir_arrows(ax, wave: Dict[str, Any]) -> None:
    """方向箭：修正腿綠下、衝動腿紅上（語意＝走勢意圖，不是買訊）。

    可遷移（D.C.）：(1)→(2)／(3)→(4) 綠下；(2)→(3)／(4)→(5) 紅上。
    """
    wave = wave or {}
    nodes: List[Tuple[float, float, str]] = []
    for n in list(wave.get("confirmed") or []) + list(wave.get("projected") or []):
        try:
            nodes.append(
                (float(n["i"]), float(n["price"]), str(n.get("label") or ""))
            )
        except Exception:
            continue
    # 依 x 排序，兩兩連段
    nodes.sort(key=lambda t: t[0])
    for i in range(len(nodes) - 1):
        x0, y0, _lab0 = nodes[i]
        x1, y1, lab1 = nodes[i + 1]
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            continue
        # 箭畫在段中後 55%，避免壓浪號
        t = 0.55
        xa, ya = x0 + t * dx, y0 + t * dy
        down = dy < 0
        col = _EMA12 if down else _LADDER
        # 只在關鍵腿畫：下到 (2)(4)；上到 (3)(5)
        if down and lab1 not in ("(2)", "(4)", "(b)"):
            continue
        if (not down) and lab1 not in ("(3)", "(5)", "(c)", "(1)"):
            continue
        try:
            ax.annotate(
                "",
                xy=(x1, y1),
                xytext=(xa, ya),
                arrowprops={
                    "arrowstyle": "-|>",
                    "color": col,
                    "lw": 1.6,
                    "mutation_scale": 14,
                    "shrinkA": 0,
                    "shrinkB": 6,
                },
                zorder=6,
            )
        except Exception:
            continue


def _draw_price_tag(
    ax, x: float, y: float, text: str, *, fp, face: str, color: str = "white"
) -> None:
    ax.text(
        x,
        y,
        text,
        color=color,
        fontproperties=fp,
        ha="left",
        va="center",
        zorder=8,
        bbox={
            "boxstyle": "round,pad=0.22",
            "facecolor": face,
            "edgecolor": "none",
            "alpha": 0.94,
        },
    )


def _draw_gray_note(ax, x: float, y: float, text: str, *, fp) -> None:
    ax.text(
        x,
        y,
        text,
        color="white",
        fontproperties=fp,
        ha="right",
        va="bottom",
        zorder=7,
        bbox={
            "boxstyle": "round,pad=0.18",
            "facecolor": _TAG_BG,
            "edgecolor": "none",
            "alpha": 0.9,
        },
    )


def _draw_wave_label(
    ax, x: float, y: float, label: str, *, kind: str, fp, color: str
) -> None:
    va = "bottom" if kind == "H" else "top"
    ax.plot(x, y, "o", ms=10.5, color=color, mfc="#fafafa", mew=1.55, zorder=7)
    ax.annotate(
        label,
        xy=(x, y),
        xytext=(0, 10 if kind == "H" else -10),
        textcoords="offset points",
        color=color,
        fontproperties=fp,
        ha="center",
        va=va,
        zorder=8,
        clip_on=False,
    )


def _draw_map_pin(ax, x: float, y: float) -> None:
    """粉紅 map-pin（預估峰）。"""
    ax.plot(x, y, marker="o", ms=7, color=_PIN, zorder=9)
    ax.plot(
        x,
        y,
        marker="v",
        ms=11,
        color=_PIN,
        markeredgecolor="#c2185b",
        markeredgewidth=0.6,
        zorder=9,
    )


def _draw_date_badge(ax, x: float, y_bottom: float, text: str, *, fp) -> None:
    ax.text(
        x,
        y_bottom,
        text,
        color="white",
        fontproperties=fp,
        ha="center",
        va="top",
        zorder=8,
        clip_on=False,
        bbox={
            "boxstyle": "round,pad=0.15",
            "facecolor": _TAG_HOT,
            "edgecolor": "none",
            "alpha": 0.92,
        },
    )


def _parallel_channel_rails(
    pts: Sequence[Tuple[float, float]],
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """紫平行通道雙軌：中線±振幅。"""
    if len(pts) < 2:
        return None
    px = np.asarray([p[0] for p in pts], dtype=float)
    py = np.asarray([p[1] for p in pts], dtype=float)
    amp = max(float(np.nanmax(py) - np.nanmin(py)) * 0.14, float(abs(py[-1])) * 0.028)
    return px, py - amp, py + amp, py


def _paint(
    rows: Sequence[Dict[str, Any]],
    meta: Dict[str, Any],
    out_path: str,
    *,
    sid: str,
    name: str,
) -> Optional[str]:
    from wayne_navigator import _fp, mpl_render

    rows = list(rows or [])
    n = len(rows)
    if n < _MIN_BARS:
        return None
    series = meta.get("_series") or {}
    e12 = list(series.get("e12") or [])
    e144 = list(series.get("e144") or [])
    e169 = list(series.get("e169") or [])
    e576 = list(series.get("e576") or [])
    e676 = list(series.get("e676") or [])
    press = meta.get("desc_press") or {}
    ladders = list(meta.get("ladders") or [])
    paths = list(meta.get("paths") or [])
    wave = meta.get("wave") or {}

    xs = np.arange(n, dtype=float)
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    vols = [float(r.get("volume") or 0) for r in rows]
    ups = [closes[i] >= opens[i] for i in range(n)]

    with mpl_render():
        fig, (ax, axv) = plt.subplots(
            2,
            1,
            figsize=(10.6, 7.6),
            gridspec_kw={"height_ratios": [3.35, 0.95], "hspace": _PRICE_VOL_HSPACE},
            facecolor=_BG,
        )
        ax.set_facecolor(_BG)
        axv.set_facecolor(_BG)
        _paint_bw_candles(ax, xs, opens, highs, lows, closes)
        _paint_gray_volume(axv, xs, vols, ups)

        # 底部支撐區間帶（近窗低區）
        lo_band = sorted(lows)[: max(3, n // 12)]
        if lo_band:
            z0, z1 = float(min(lo_band)), float(max(lo_band) * 1.04)
            ax.axhspan(z0, z1, color=_ZONE_SUP, alpha=0.18, zorder=1)

        # Vegas 雙隧道：藍＝144/169；紅＝576/676（語意＝均線隧道，不是未來浪陰影）
        if e144 and e169 and len(e144) == n and len(e169) == n:
            lo = np.minimum(np.asarray(e144), np.asarray(e169))
            hi = np.maximum(np.asarray(e144), np.asarray(e169))
            ax.fill_between(xs, lo, hi, color=_TUNNEL, alpha=0.14, zorder=2)
            ax.plot(xs, e144, color=_TUNNEL, lw=1.05, zorder=3)
            ax.plot(xs, e169, color=_TUNNEL, lw=1.05, zorder=3)
        if e12 and len(e12) == n:
            ax.plot(xs, e12, color=_EMA12, lw=0.85, zorder=3)
        if e576 and e676 and len(e576) == n and len(e676) == n:
            slo = np.minimum(np.asarray(e576), np.asarray(e676))
            shi = np.maximum(np.asarray(e576), np.asarray(e676))
            ax.fill_between(xs, slo, shi, color=_EMA_SLOW, alpha=0.14, zorder=2)
            ax.plot(xs, e576, color=_EMA_SLOW, lw=0.85, zorder=3, alpha=0.9)
            ax.plot(xs, e676, color=_EMA_SLOW, lw=0.85, zorder=3, alpha=0.9)
        elif e576 and len(e576) == n:
            ax.plot(xs, e576, color=_EMA_SLOW, lw=0.75, zorder=2, alpha=0.8)
        elif e676 and len(e676) == n:
            ax.plot(xs, e676, color=_EMA_SLOW, lw=0.75, zorder=2, alpha=0.8)

        fut_bars = _clamp_future_bars(
            float(wave.get("future_bars") or _FUTURE_FALLBACK)
            if wave
            else float(_FUTURE_FALLBACK)
        )
        x_end = float(n - 1) + float(fut_bars)
        # 浪階自帶下降壓優先於通用樞紐壓
        if wave.get("desc_press"):
            press = dict(wave.get("desc_press") or {})
        if press and press.get("i") is not None and press.get("j") is not None:
            i = int(press["i"])
            j = int(press["j"])
            y1 = float(press["y1"])
            y2 = float(press["y2"])
            if j - i >= 8:
                slope = (y2 - y1) / float(j - i)
                y_end = y2 + slope * (x_end - float(j))
                ax.plot(
                    [float(i), x_end],
                    [y1, y_end],
                    color=_PRESS,
                    lw=1.45,
                    zorder=4,
                    alpha=0.9,
                )

        # 滿足／目標／撐帶
        for z in list(wave.get("zones") or []):
            try:
                zlo, zhi = float(z["lo"]), float(z["hi"])
            except Exception:
                continue
            kind = str(z.get("kind") or "sup")
            col = (
                _ZONE_TGT
                if kind == "tgt"
                else _ZONE_OK
                if kind == "ok"
                else _ZONE_SUP
            )
            ax.axhspan(zlo, zhi, color=col, alpha=0.20 if kind != "sup" else 0.16, zorder=1)

        # 楔形／平行雙軌（上 (1)(3)・下 (2)(4)）
        wedge = wave.get("wedge") or {}
        if wedge.get("upper") and wedge.get("lower"):
            try:
                ux0, uy0, ux1, uy1 = [float(x) for x in wedge["upper"]]
                lx0, ly0, lx1, ly1 = [float(x) for x in wedge["lower"]]
                us = (uy1 - uy0) / max(ux1 - ux0, 1e-9)
                ls = (ly1 - ly0) / max(lx1 - lx0, 1e-9)
                x_w0 = min(ux0, lx0)
                x_w1 = max(x_end, ux1, lx1)
                xs_w = np.linspace(x_w0, x_w1, 48)
                yu = uy0 + us * (xs_w - ux0)
                yl = ly0 + ls * (xs_w - lx0)
                ax.plot(xs_w, yu, color=_CHANNEL, lw=1.15, alpha=0.85, zorder=3)
                ax.plot(xs_w, yl, color=_CHANNEL, lw=1.15, alpha=0.85, zorder=3)
                ax.fill_between(xs_w, yl, yu, color=_CHANNEL, alpha=0.10, zorder=2)
            except Exception:
                pass

        # 期限豎線（abc 條件窗）
        deadline = wave.get("deadline") or {}
        if deadline.get("i") is not None:
            try:
                dxi = float(deadline["i"])
                ax.axvline(dxi, color="#546e7a", lw=1.35, ls=(0, (3, 3)), alpha=0.9, zorder=4)
                axv.axvline(dxi, color="#546e7a", lw=1.1, ls=(0, (3, 3)), alpha=0.85, zorder=4)
                dlab = str(deadline.get("label") or "").strip()
                if dlab:
                    ax.text(
                        dxi,
                        0.98,
                        dlab,
                        transform=ax.get_xaxis_transform(),
                        color="#37474f",
                        fontproperties=_fp(7.2, "bold"),
                        ha="center",
                        va="top",
                        zorder=8,
                        clip_on=False,
                    )
            except Exception:
                pass

        for lad in ladders:
            y = float(lad["price"])
            ax.axhline(y, color=_LADDER, lw=1.05, alpha=0.8, zorder=3)

        # 浪路徑：已走淺粉紅；未走白虛線伸右側；abc 藍
        if wave:
            done = list(wave.get("path_done") or [])
            proj = list(wave.get("path_proj") or [])
            abc_pts = [
                (float(a["i"]), float(a["price"])) for a in (wave.get("abc") or [])
            ]
            if len(done) >= 2:
                # 白描邊＋粉紅芯，避免跟灰底糊成一團
                ax.plot(
                    [p[0] for p in done],
                    [p[1] for p in done],
                    color="#ffffff",
                    lw=2.4,
                    zorder=5,
                    alpha=0.95,
                )
                ax.plot(
                    [p[0] for p in done],
                    [p[1] for p in done],
                    color=_WAVE_IMP,
                    lw=1.55,
                    zorder=5,
                    alpha=0.95,
                )
            if len(proj) >= 2:
                # 淺紫通道帶包住預估折線
                px = np.asarray([p[0] for p in proj], dtype=float)
                py = np.asarray([p[1] for p in proj], dtype=float)
                if len(px) >= 2:
                    amp = max(float(np.nanmax(py) - np.nanmin(py)) * 0.12, float(py[-1]) * 0.03)
                    ax.fill_between(
                        px, py - amp, py + amp, color=_CHANNEL, alpha=0.16, zorder=4
                    )
                ax.plot(
                    px,
                    py,
                    color="#212121",
                    lw=2.6,
                    ls=(0, (5, 3)),
                    zorder=5,
                    alpha=0.55,
                )
                ax.plot(
                    px,
                    py,
                    color=_WAVE_PROJ,
                    lw=1.7,
                    ls=(0, (5, 3)),
                    zorder=5,
                    alpha=0.98,
                )
            if len(abc_pts) >= 2:
                # 接在 (5) 後
                if done:
                    abc_line = [done[-1]] + abc_pts
                else:
                    abc_line = abc_pts
                ax.plot(
                    [p[0] for p in abc_line],
                    [p[1] for p in abc_line],
                    color=_WAVE_ABC,
                    lw=1.45,
                    zorder=5,
                    alpha=0.95,
                )

            _paint_wave_dir_arrows(ax, wave)

            # 浪號略放大：手機縮圖仍要讀得出未來 (3)(4)(5)
            fp_w = _fp(11.4, "bold")
            fp_tag = _fp(8.2, "bold")
            fp_d = _fp(6.8)
            for node in list(wave.get("confirmed") or []):
                _draw_wave_label(
                    ax,
                    float(node["i"]),
                    float(node["price"]),
                    str(node["label"]),
                    kind=str(node.get("kind") or "H"),
                    fp=fp_w,
                    color=_WAVE_IMP,
                )
                dtxt = str(node.get("date") or "").strip()
                if dtxt:
                    y_off = -abs(float(node["price"]) * 0.018) if str(node.get("kind")) == "H" else abs(float(node["price"]) * 0.018)
                    _draw_date_badge(
                        ax,
                        float(node["i"]),
                        float(node["price"]) + y_off,
                        f"{dtxt}·{_fmt_px(float(node['price']))}",
                        fp=fp_d,
                    )
            for node in list(wave.get("projected") or []):
                _draw_wave_label(
                    ax,
                    float(node["i"]),
                    float(node["price"]),
                    str(node["label"]),
                    kind=str(node.get("kind") or "H"),
                    fp=fp_w,
                    color="#212121",
                )
                if node.get("kind") == "H":
                    # pin 在浪點；價標併右軸 dodge，避免跟 (5)／1530 互壓
                    _draw_map_pin(ax, float(node["i"]), float(node["price"]))
            # 區間帶已 axhspan；灰框改併右軸 dodge，避免跟紅價標互壓
            for node in list(wave.get("abc") or []):
                _draw_wave_label(
                    ax,
                    float(node["i"]),
                    float(node["price"]),
                    str(node["label"]),
                    kind=str(node.get("kind") or "L"),
                    fp=fp_w,
                    color=_WAVE_ABC,
                )

        # 階梯：無浪、或有浪但無未走投影（abc 完成態）時畫，保證未來可讀
        label_anchors: List[Tuple[float, float, str]] = []
        if paths:
            deepest = None
            for path in paths:
                pts = list(path.get("points") or [])
                if len(pts) < 2:
                    continue
                px = [float(p[0]) for p in pts]
                py = [float(p[1]) for p in pts]
                col = str(path.get("color") or _PATH_COLORS[0])
                ax.plot(
                    px,
                    py,
                    color=col,
                    lw=1.35,
                    ls=(0, (5, 3)),
                    alpha=0.85,
                    zorder=5,
                    solid_capstyle="round",
                )
                steps = list(path.get("steps") or [])
                if deepest is None or len(steps) > len(deepest.get("steps") or []):
                    deepest = path
            seen_lbl = set()
            for st in (deepest or {}).get("steps") or []:
                txt = str(st.get("label") or "").strip()
                if not txt or txt in seen_lbl:
                    continue
                seen_lbl.add(txt)
                label_anchors.append(
                    (
                        float(st.get("x") or (n - 1)) + 0.4,
                        float(st.get("to") or st.get("high") or 0),
                        txt,
                    )
                )

        # 右側關鍵價：只留紅底價標（不再重複畫「候選 xxx」字，避免互壓）
        y_span = max(highs) - min(lows) if highs and lows else 1.0
        min_gap = max(y_span * 0.055, (max(closes) or 1.0) * 0.02)
        right_tags: List[Tuple[float, float, str]] = []
        for lad in ladders:
            right_tags.append(
                (x_end + 0.2, float(lad["price"]), f"{_fmt_px(float(lad['price']))}")
            )
        # 已走 (1) 前高：DC 波3 第一參考（過前高）；現價仍低於時上右軸
        last_close = float(closes[-1] or 0) if closes else 0.0
        for node in list(wave.get("confirmed") or []):
            if str(node.get("label") or "") != "(1)":
                continue
            try:
                y1 = float(node["price"])
            except Exception:
                continue
            if last_close > 0 and y1 > last_close * 1.002:
                near = any(
                    abs(y1 - float(t[1])) / max(abs(y1), 1e-9) < 0.02
                    for t in right_tags
                )
                if not near:
                    right_tags.append((x_end + 0.2, y1, _fmt_px(y1)))
        # 虛線峰／谷價：只走右軸紅標
        for node in list(wave.get("projected") or []):
            try:
                right_tags.append(
                    (
                        x_end + 0.2,
                        float(node["price"]),
                        _fmt_px(float(node["price"])),
                    )
                )
            except Exception:
                pass
        # 滿足／撐帶灰框；目標帶(tgt)只留 axhspan，不再重複灰字
        for z in list(wave.get("zones") or []):
            try:
                if str(z.get("kind") or "") == "tgt":
                    continue
                mid = 0.5 * (float(z["lo"]) + float(z["hi"]))
                note = str(z.get("label") or _ladder_range_note(mid, 0, 1))
                near = any(
                    abs(mid - float(t[1])) / max(abs(mid), 1e-9) < 0.045
                    for t in right_tags
                )
                if near:
                    continue
                right_tags.append((x_end + 0.2, mid, note))
            except Exception:
                pass
        if press and press.get("y_now") is not None and press.get("j") is not None:
            if int(press["j"]) - int(press["i"]) >= 8:
                label_anchors.append(
                    (
                        float(n - 1) - 2.0,
                        float(press["y_now"]),
                        f"下降壓 {_fmt_px(float(press['y_now']))}",
                    )
                )

        placed = dodge_label_ys(label_anchors, min_gap=min_gap)
        for x, y, txt in placed:
            if not txt:
                continue
            ax.text(
                min(float(x), float(n - 1) - 0.8),
                y,
                txt,
                color=_PRESS if txt.startswith("下降壓") else _TEXT,
                fontproperties=_fp(7.0, "bold"),
                ha="right",
                va="bottom",
                zorder=6,
                alpha=0.95,
                bbox={
                    "boxstyle": "round,pad=0.15",
                    "facecolor": "#eceff1",
                    "edgecolor": "none",
                    "alpha": 0.88,
                },
            )
        rt = dodge_label_ys(right_tags, min_gap=min_gap)
        for x, y, txt in rt:
            face = _TAG_HOT if str(txt).replace(".", "").isdigit() else _TAG_BG
            _draw_price_tag(ax, x_end + 0.15, y, txt, fp=_fp(7.4, "bold"), face=face)

        note = str(wave.get("bubble") or "").strip() or chart_note_lines(wave)
        # 說明放圖上方，不壓 K、不壓點位。他的圖有配文，縮圖也要讀得到。
        fig.text(
            0.09,
            0.985,
            note,
            fontproperties=_fp(12, "bold"),
            color=_TEXT,
            ha="left",
            va="top",
        )

        title = f"{sid} {name}　情境預估（不保證・不是買訊）".strip()
        ax.set_title(title, fontproperties=_fp(11, "bold"), color=_TEXT, pad=6)
        x_max = x_end + 3.5
        if wave:
            for p in list(wave.get("path_proj") or []) + list(wave.get("projected") or []):
                try:
                    x_max = max(
                        x_max,
                        float(p[0] if isinstance(p, (list, tuple)) else p["i"]) + 2.0,
                    )
                except Exception:
                    pass
        ax.set_xlim(-0.8, x_max)
        axv.set_xlim(-0.8, x_max)
        # y 含預估高點，但留邊
        y_hi = max(highs)
        y_lo = min(lows)
        for node in list(wave.get("projected") or []) + list(wave.get("confirmed") or []):
            y_hi = max(y_hi, float(node.get("price") or 0))
            y_lo = min(y_lo, float(node.get("price") or y_lo))
        pad = (y_hi - y_lo) * 0.08 + 1e-6
        ax.set_ylim(y_lo - pad, y_hi + pad * 1.25)

        ax.grid(True, color=_GRID, lw=0.55, zorder=0)
        axv.grid(True, color=_GRID, lw=0.55, zorder=0)
        ax.tick_params(labelsize=8, colors=_TEXT)
        axv.tick_params(labelsize=7, colors=_TEXT)
        wave_xs = []
        if wave:
            for node in list(wave.get("projected") or []):
                try:
                    wave_xs.append(float(node.get("i") or 0))
                except Exception:
                    pass
        ticks, labels = _future_tick_labels(
            rows,
            n,
            x_max,
            wave_xs=wave_xs,
            future_bars=fut_bars,
        )
        # 日期放價圖與量圖中縫，對準刻度；量柱底不再掛日期
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        _style_axis_date_labels(ax, ticks, n)
        ax.tick_params(
            axis="x", pad=2, length=3, width=0.8, colors="#111111", labelbottom=True
        )
        axv.set_xticks(ticks)
        axv.set_xticklabels([])
        axv.tick_params(axis="x", labelbottom=False, length=0)
        # 圖頂多行說明要淨空；行數多就再往下讓
        n_note = max(1, str(note).count("\n") + 1)
        top = max(0.72, min(0.90, 0.98 - 0.032 * float(n_note) - 0.05))
        fig.subplots_adjust(left=0.09, right=0.93, top=top, bottom=_CHART_BOTTOM)
        # 現價豎線＝歷史／未來分界（加粗＋淺底帶）
        ax.axvspan(float(n - 1), x_max, color="#ffffff", alpha=0.22, zorder=0)
        ax.axvline(float(n - 1), color="#212121", lw=2.2, ls="-", alpha=0.95, zorder=6)
        axv.axvline(float(n - 1), color="#212121", lw=1.8, ls="-", alpha=0.9, zorder=6)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=_DPI, facecolor=_BG)
        plt.close(fig)

    if os.path.isfile(out_path) and os.path.getsize(out_path) > 20_000:
        return out_path
    return None


def render_scenario_forecast(
    stock_id: str,
    db_path: str,
    out_path: str,
    *,
    card: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """渲情境預估圖。回 (path|None, caption, meta)。失敗 path=None，不准拋到查股主路徑。

    官方原柱選點／浪階；盤中有決策卡真報價時，縮圖末日 K／量與趨勢（隧道／浪）
    疊同卡（與圖一～四同源 `overlay_live_face_from_card`），不准假柱。
    """
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    out = str(out_path or "").strip()
    empty_meta: Dict[str, Any] = {}
    if not sid or not path or not out:
        return None, "情境預估暫略（參數不足）。不是買訊。", empty_meta
    try:
        from vol_zone_chart import load_official_ohlc, official_work

        raw = load_official_ohlc(sid, path, max(_BARS + 40, 720))
        work = official_work(raw)
        all_rows = _rows_from_df(work)
        # 查詢當下：決策卡盤中真開高低收＋量疊臉柱，趨勢線跟著最後一根走。
        if isinstance(card, dict) and card.get("is_live"):
            try:
                from live_quote import overlay_live_face_from_card

                over = overlay_live_face_from_card(
                    all_rows, card, stock_id=sid
                )
                if isinstance(over, list) and len(over) >= len(all_rows):
                    # 保留股名；overlay 可能帶 is_live 等欄
                    name0 = str(all_rows[-1].get("stock_name") or "") if all_rows else ""
                    cleaned: List[Dict[str, Any]] = []
                    for r in over:
                        if not isinstance(r, dict):
                            continue
                        try:
                            o = float(r.get("open") or 0)
                            h = float(r.get("high") or 0)
                            lo = float(r.get("low") or 0)
                            c = float(r.get("close") or 0)
                            v = float(r.get("volume") or 0)
                        except Exception:
                            continue
                        if h <= 0 or lo <= 0 or c <= 0:
                            continue
                        cleaned.append(
                            {
                                "date": str(r.get("date") or ""),
                                "stock_name": str(r.get("stock_name") or name0),
                                "open": o,
                                "high": h,
                                "low": lo,
                                "close": c,
                                "volume": v,
                                "is_live": bool(r.get("is_live")),
                            }
                        )
                    if len(cleaned) >= _MIN_BARS:
                        all_rows = cleaned
            except Exception:
                logger.debug("情境預估疊盤中臉柱略過 sid=%s", sid, exc_info=True)
        if len(all_rows) < _MIN_BARS:
            return (
                None,
                f"{sid}　情境預估暫略（官方日K不足）。不是買訊。",
                empty_meta,
            )
        meta_full = build_scenario_meta(all_rows)
        rows = all_rows[-_BARS:] if len(all_rows) > _BARS else all_rows
        series_full = meta_full.get("_series") or {}
        cut = len(rows)
        ladders = infer_prior_high_ladders(rows, max_n=3)
        press = infer_desc_press(rows)
        wave = infer_dc_wave_scenario(rows, ladders)
        try:
            from dc_scenario_silent_verify import align_wave_turns, load_rules

            spec = (load_rules(path) or {}).get(f"turns:{sid}") or {}
            if spec and wave:
                wave = align_wave_turns(wave, rows, spec)
        except Exception:
            logger.debug("情境預估轉折對齊略過 sid=%s", sid, exc_info=True)
        if wave:
            wave = dict(wave)
            wave["bubble"] = chart_note_lines(wave)
        if wave and wave.get("desc_press"):
            press = dict(wave.get("desc_press") or {})
        # 與 build_scenario_meta 同規：有未走投影才抑階梯；abc 完成態仍疊樂觀階梯
        has_proj = bool(wave and (wave.get("projected") or wave.get("path_proj")))
        paths = (
            []
            if has_proj
            else infer_scenario_paths(rows, ladders, n_bars=len(rows), max_paths=3)
        )
        meta = {
            "vegas": meta_full.get("vegas") or {},
            "desc_press": press,
            "ladders": ladders,
            "paths": paths,
            "wave": wave,
            "caption_bits": [],
            "_series": {
                k: (list(v)[-cut:] if list(v) else [])
                for k, v in series_full.items()
            },
        }
        if meta["vegas"]:
            meta["caption_bits"].append(f"隧道{meta['vegas'].get('stance')}")
        if meta["desc_press"]:
            meta["caption_bits"].append(str(meta["desc_press"].get("pos") or "下降壓"))
        if meta["ladders"]:
            meta["caption_bits"].append(
                "候選 " + "／".join(_fmt_px(x["price"]) for x in meta["ladders"])
            )
        if wave:
            labs = "".join(wave.get("labels") or [])
            if labs:
                meta["caption_bits"].append(f"浪號{labs}")
            meta["caption_bits"].append("情境預估／不保證")
        if paths:
            meta["caption_bits"].append(f"情境階梯{len(paths)}條")
        name = str(rows[-1].get("stock_name") or "")
        painted = _paint(rows, meta, out, sid=sid, name=name)
        cap = format_scenario_caption(sid, name, meta)
        if not painted:
            return None, f"{sid}　情境預估暫略。不是買訊。", meta
        meta_out = {
            "vegas": meta.get("vegas") or {},
            "desc_press": dict(meta.get("desc_press") or {}),
            "ladders": list(meta.get("ladders") or []),
            "wave": {
                "state": (wave or {}).get("state"),
                "labels": list((wave or {}).get("labels") or []),
                "bubble": (wave or {}).get("bubble"),
                "confirmed": list((wave or {}).get("confirmed") or []),
                "projected": list((wave or {}).get("projected") or []),
                "abc": list((wave or {}).get("abc") or []),
                "next_cycle": list((wave or {}).get("next_cycle") or []),
                "path_proj": list((wave or {}).get("path_proj") or []),
                "future_bars": (wave or {}).get("future_bars"),
                "leg_bars": dict((wave or {}).get("leg_bars") or {}),
                "proj_durs": dict((wave or {}).get("proj_durs") or {}),
            }
            if wave
            else {},
            "paths": [
                {
                    "id": p.get("id"),
                    "steps": list(p.get("steps") or []),
                    "tip": p.get("tip"),
                }
                for p in (meta.get("paths") or [])
            ],
        }
        return painted, cap, meta_out
    except Exception:
        logger.exception("情境預估渲圖失敗 sid=%s", sid)
        return None, f"{sid}　情境預估暫略。不是買訊。", empty_meta
