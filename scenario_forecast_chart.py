# -*- coding: utf-8 -*-
"""個股「情境預估（不保證）」圖：DC 視覺臉＋VEGAS／浪號／虛線未來路徑。

視覺對齊 TradingView：淺灰底、白框／黑棒 K、白／粉紅／藍路徑、
浪號沿時間軸（未走伸右側未來）、右側彩底價標、區間帶。
獨立附加、永遠不是買訊。僅此子鈕可標浪；其他鈕仍守 §12。
失敗回 None；不准擋查股四張／主選單。Asia/Taipei；只讀官方日 K。
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

# 近窗對齊結構圖量級；右側留足未來時間軸給 (3)(4)(5)
_BARS = 168
_FUTURE = 72
_DPI = 168
_MIN_BARS = 40

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


def infer_dc_wave_scenario(
    rows: Sequence[Dict[str, Any]],
    ladders: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """顯著樞紐重算上升 5 浪：活躍段優先；未走虛線伸右側；abc 近窗才 next_cycle。

    僅供情境預估子鈕；不保證、不是買訊。
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
    zz = _alternating_zigzag(highs, lows, left=5, min_bars=6, min_pct=0.035)
    if len(zz) < 3:
        return empty
    ladder_lv = sorted(
        {float(x.get("price") or 0) for x in (ladders or []) if float(x.get("price") or 0) > 0}
    )

    best = None
    best_score = -1.0
    for si, p0 in enumerate(zz):
        if p0["kind"] != "L":
            continue
        seg = zz[si:]
        if len(seg) < 3:
            continue
        if seg[1]["kind"] != "H" or seg[2]["kind"] != "L":
            continue
        start, w1, w2 = seg[0], seg[1], seg[2]
        if w1["price"] <= start["price"] * 1.01:
            continue
        if w2["price"] >= w1["price"] * 0.995:
            continue
        # 硬規則：W2 不可明顯破起點（標準衝動）
        if w2["price"] < start["price"] * 0.998:
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
        w3 = seg[3] if len(seg) > 3 and seg[3]["kind"] == "H" else None
        w4 = seg[4] if len(seg) > 4 and seg[4]["kind"] == "L" else None
        w5 = seg[5] if len(seg) > 5 and seg[5]["kind"] == "H" else None
        if w3 and w3["price"] > w1["price"] * 1.002:
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
            # W4 不重疊 W1 價區
            if (
                w4
                and w4["price"] < w3["price"] * 0.998
                and w4["price"] > w1["price"] * 1.001
            ):
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
                if w5 and w5["price"] > w3["price"] * 1.001:
                    len1 = float(w1["price"]) - float(start["price"])
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

        amp_pct = (float(w1["price"]) - float(start["price"])) / max(
            float(start["price"]), 1e-9
        )
        if amp_pct < 0.03:
            continue
        last_i = float(confirmed[-1]["i"])
        # 活躍分：近窗權重最高（修 v3 鎖舊五月浪）
        recency = (last_i / float(max(n - 1, 1))) ** 2
        gap = float(n - 1) - last_i
        tail_bonus = 1.45 if gap <= 40 else (1.0 if gap <= 55 else 0.35)
        completeness = 1.0 + 0.08 * float(len(confirmed))
        score = amp_pct * (0.25 + 3.2 * recency) * completeness * tail_bonus
        win_hi = max(highs) if highs else float(w1["price"])
        if float(w1["price"]) >= win_hi * 0.97 and "(3)" not in {
            c["label"] for c in confirmed
        }:
            if float(w1["i"]) < n * 0.55:
                score *= 0.25
        if any(lv > float(w1["price"]) * 1.01 for lv in ladder_lv):
            score *= 1.15
        if score > best_score:
            best_score = score
            best = {
                "start": _wave_node(
                    "0",
                    start["i"],
                    start["price"],
                    "L",
                    projected=False,
                    date=_bar_date(rows, start["i"]),
                ),
                "confirmed": confirmed,
            }

    if not best:
        return empty

    confirmed = list(best["confirmed"])
    start = {
        "i": float(best["start"]["i"]),
        "price": float(best["start"]["price"]),
        "kind": "L",
        "date": str(best["start"].get("date") or ""),
    }
    amp1 = float(confirmed[0]["price"]) - float(start["price"])
    projected: List[Dict[str, Any]] = []
    have = {c["label"] for c in confirmed}

    x_now = max(float(confirmed[-1]["i"]), float(n - 1))
    fut = float(_FUTURE)
    y_cap = max(float(confirmed[0]["price"]) * 1.22, last * 1.35)
    if ladder_lv:
        y_cap = max(y_cap, max(ladder_lv) * 1.03)

    if "(3)" not in have:
        y3 = _pick_ladder_above(
            ladder_lv,
            float(confirmed[0]["price"]),
            default=float(confirmed[0]["price"])
            + min(amp1 * 1.0, float(confirmed[0]["price"]) * 0.18),
        )
        y3 = max(y3, float(confirmed[0]["price"]) * 1.02)
        y3 = min(y3, y_cap)
        projected.append(
            _wave_node("(3)", x_now + fut * 0.32, y3, "H", projected=True, date="估")
        )
    if "(4)" not in have:
        src3 = next((c for c in confirmed + projected if c["label"] == "(3)"), None)
        src2 = next((c for c in confirmed if c["label"] == "(2)"), None)
        if src3 and src2:
            y4 = float(src3["price"]) - 0.382 * (
                float(src3["price"]) - float(src2["price"])
            )
            y4 = max(y4, float(src2["price"]) * 1.01)
            y4 = max(y4, float(confirmed[0]["price"]) * 1.005)
            projected.append(
                _wave_node("(4)", x_now + fut * 0.55, y4, "L", projected=True, date="估")
            )
    if "(5)" not in have:
        src3 = next((c for c in confirmed + projected if c["label"] == "(3)"), None)
        src4 = next((c for c in confirmed + projected if c["label"] == "(4)"), None)
        if src3 and src4:
            y5 = _pick_ladder_above(
                ladder_lv,
                float(src3["price"]),
                default=float(src3["price"])
                + min(amp1 * 0.8, float(src3["price"]) * 0.12),
            )
            y5 = max(y5, float(src3["price"]) * 1.015)
            y5 = min(y5, y_cap * 1.02)
            projected.append(
                _wave_node("(5)", x_now + fut * 0.88, y5, "H", projected=True, date="估")
            )

    abc: List[Dict[str, Any]] = []
    if "(5)" in have:
        w5c = next(c for c in confirmed if c["label"] == "(5)")
        after = [p for p in zz if p["i"] > w5c["i"]]
        if (
            len(after) >= 3
            and after[0]["kind"] == "L"
            and after[1]["kind"] == "H"
            and after[2]["kind"] == "L"
        ):
            for lab, p in zip(("a", "b", "c"), after[:3]):
                abc.append(
                    _wave_node(
                        lab,
                        p["i"],
                        p["price"],
                        p["kind"],
                        projected=False,
                        date=_bar_date(rows, p["i"]),
                    )
                )

    # 僅 abc.c 靠近現在才開下一輪（修 v3 五月舊 abc 濫開）
    next_cycle: List[Dict[str, Any]] = []
    c_recent = bool(abc) and float(abc[-1]["i"]) >= float(n - 25)
    five_done_fresh = (
        "(5)" in have
        and not projected
        and float(confirmed[-1]["i"]) >= float(n - 25)
    )
    if last > 0 and (c_recent or (five_done_fresh and not abc)):
        if abc and c_recent:
            base = abc[-1]
        else:
            w5c = next(c for c in confirmed if c["label"] == "(5)")
            base = {
                "i": max(float(w5c["i"]), float(n - 1)),
                "price": float(last),
                "kind": "L",
            }
            for p in reversed(zz):
                if p["i"] >= w5c["i"] and p["kind"] == "L":
                    base = {
                        "i": float(p["i"]),
                        "price": float(p["price"]),
                        "kind": "L",
                    }
                    break
        x0 = max(float(base["i"]), float(n - 1))
        y0 = float(base["price"])
        top5 = next((c for c in confirmed if c["label"] == "(5)"), None)
        t1 = _pick_ladder_above(ladder_lv, y0, default=y0 * 1.08)
        if top5:
            t1 = min(max(t1, y0 * 1.05), float(top5["price"]) * 1.05)
        t3 = min(float(_pick_ladder_above(ladder_lv, t1, default=t1 * 1.12)), float(y_cap))
        t5 = min(
            float(_pick_ladder_above(ladder_lv, t3, default=t3 * 1.08)),
            float(y_cap) * 1.02,
        )
        t2 = y0 + (t1 - y0) * 0.38
        t4 = max(t1 + (t3 - t1) * 0.45, float(confirmed[0]["price"]) * 1.005)
        seq = [
            ("(1)", x0 + fut * 0.18, t1, "H"),
            ("(2)", x0 + fut * 0.34, t2, "L"),
            ("(3)", x0 + fut * 0.55, t3, "H"),
            ("(4)", x0 + fut * 0.70, t4, "L"),
            ("(5)", x0 + fut * 0.90, t5, "H"),
        ]
        for lab, xi, yi, kind in seq:
            next_cycle.append(
                _wave_node(lab, xi, yi, kind, projected=True, date="估", next_cycle=True)
            )
        if not projected:
            projected = list(next_cycle)

    path_done: List[Tuple[float, float]] = [
        (float(start["i"]), float(start["price"]))
    ]
    for c in confirmed:
        path_done.append((float(c["i"]), float(c["price"])))
    path_proj: List[Tuple[float, float]] = []
    if projected:
        if next_cycle and abc and c_recent:
            path_proj.append((float(abc[-1]["i"]), float(abc[-1]["price"])))
        else:
            path_proj.append(path_done[-1])
        for c in projected:
            path_proj.append((float(c["i"]), float(c["price"])))

    conf_labs = [c["label"] for c in confirmed]
    proj_labs = [c["label"] for c in projected]
    if abc and next_cycle and c_recent:
        bubble = "情境預估：5浪後abc，虛線新一輪(1)–(5)（不保證・不是買訊）"
        state = "abc_next"
    elif abc:
        bubble = "情境預估：5浪後修正 abc（樞紐重算・不保證・不是買訊）"
        state = "abc"
    elif len(conf_labs) >= 5 and not proj_labs:
        bubble = "情境預估：完整上升5浪骨架（樞紐重算・不保證・不是買訊）"
        state = "complete5"
    elif conf_labs and proj_labs:
        bubble = (
            f"情境預估：已標{''.join(conf_labs)}，虛線{''.join(proj_labs)}"
            f"（不保證・不是買訊）"
        )
        state = "partial"
    else:
        bubble = "情境預估：上升浪骨架（不保證・不是買訊）"
        state = "partial"

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
    }



def infer_scenario_paths(
    rows: Sequence[Dict[str, Any]],
    ladders: Sequence[Dict[str, Any]],
    *,
    n_bars: Optional[int] = None,
    max_paths: int = 3,
) -> List[Dict[str, Any]]:
    """相位 1.5：2～3 條淺色虛線情境階梯（現價附近→最近前高→下一階）。"""
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
    # 有浪號主路徑時少畫多條階梯，避免互壓；無浪才用階梯虛線
    if not wave:
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


def format_scenario_caption(sid: str, name: str, meta: Dict[str, Any]) -> str:
    sid = str(sid or "").strip()
    name = str(name or "").strip()
    head = f"{sid}{name}　情境預估（不保證・不是買訊）".strip()
    bits = [str(b) for b in (meta or {}).get("caption_bits") or [] if b]
    wave = (meta or {}).get("wave") or {}
    if wave.get("bubble"):
        # 圖說優先用浪情境句；仍硬釘不是買訊
        body = str(wave["bubble"])
        if "不是買訊" not in body:
            body += "。不是買訊"
        return head + "\n" + body
    if bits:
        return head + "\n" + "；".join(bits) + "。濾網／候選不是買訊。"
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


def _future_tick_labels(rows: Sequence[Dict[str, Any]], n: int, x_max: float):
    """歷史日期＋未來估月標（Asia/Taipei）。"""
    last_dt = _ymd_to_dt(str(rows[-1].get("date") or "")) or datetime.now(_TZ)
    ticks: List[float] = []
    labels: List[str] = []
    step = max(1, n // 5)
    for i in range(0, n, step):
        ticks.append(float(i))
        labels.append(str(rows[i].get("date") or "")[4:])
    if float(n - 1) not in ticks:
        ticks.append(float(n - 1))
        labels.append(str(rows[-1].get("date") or "")[4:])
    for frac in (0.32, 0.55, 0.88):
        xi = float(n - 1) + float(_FUTURE) * frac
        if xi > x_max + 0.1:
            continue
        days = int(round((_FUTURE * frac) * 1.4))
        d = last_dt + timedelta(days=days)
        ticks.append(xi)
        labels.append(d.strftime("%m%d") + "估")
    return ticks, labels


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
            gridspec_kw={"height_ratios": [3.35, 0.95], "hspace": 0.05},
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

        if e144 and e169 and len(e144) == n and len(e169) == n:
            lo = np.minimum(np.asarray(e144), np.asarray(e169))
            hi = np.maximum(np.asarray(e144), np.asarray(e169))
            ax.fill_between(xs, lo, hi, color=_TUNNEL, alpha=0.10, zorder=2)
            ax.plot(xs, e144, color=_TUNNEL, lw=1.05, zorder=3)
            ax.plot(xs, e169, color=_TUNNEL, lw=1.05, zorder=3)
        if e12 and len(e12) == n:
            ax.plot(xs, e12, color=_EMA12, lw=0.85, zorder=3)
        if e576 and len(e576) == n:
            ax.plot(xs, e576, color=_EMA_SLOW, lw=0.75, zorder=2, alpha=0.8)
        if e676 and len(e676) == n:
            ax.plot(xs, e676, color=_EMA_SLOW, lw=0.75, zorder=2, alpha=0.8)

        x_end = float(n - 1 + _FUTURE)
        if press and press.get("i") is not None and press.get("j") is not None:
            i = int(press["i"])
            j = int(press["j"])
            y1 = float(press["y1"])
            y2 = float(press["y2"])
            if j - i >= 10:
                slope = (y2 - y1) / float(j - i)
                y_end = y2 + slope * (x_end - float(j))
                ax.plot(
                    [float(i), x_end],
                    [y1, y_end],
                    color=_PRESS,
                    lw=1.25,
                    zorder=4,
                    alpha=0.85,
                )

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

            fp_w = _fp(8.8, "bold")
            fp_tag = _fp(7.6, "bold")
            fp_d = _fp(6.4)
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
                    # 粉紅 pin
                    ax.plot(
                        float(node["i"]),
                        float(node["price"]),
                        marker="v",
                        ms=9,
                        color="#ff4081",
                        zorder=8,
                    )
                    _draw_price_tag(
                        ax,
                        float(node["i"]) + 0.6,
                        float(node["price"]),
                        _fmt_px(float(node["price"])),
                        fp=fp_tag,
                        face=_TAG_HOT,
                    )
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

        if not wave:
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
            label_anchors: List[Tuple[float, float, str]] = []
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
        else:
            label_anchors = []

        # 右側關鍵價：紅底白字（DC 價軸彩標）
        y_span = max(highs) - min(lows) if highs and lows else 1.0
        min_gap = max(y_span * 0.04, (max(closes) or 1.0) * 0.014)
        right_tags: List[Tuple[float, float, str]] = []
        for lad in ladders:
            right_tags.append(
                (x_end + 0.2, float(lad["price"]), f"{_fmt_px(float(lad['price']))}")
            )
            label_anchors.append(
                (
                    x_end - 1.2,
                    float(lad["price"]),
                    str(lad.get("label") or f"候選 {_fmt_px(float(lad['price']))}"),
                )
            )
        if press and press.get("y_now") is not None and press.get("j") is not None:
            if int(press["j"]) - int(press["i"]) >= 10:
                label_anchors.append(
                    (
                        x_end - 1.5,
                        float(press["y_now"]),
                        f"下降壓 {_fmt_px(float(press['y_now']))}",
                    )
                )

        placed = dodge_label_ys(label_anchors, min_gap=min_gap)
        for x, y, txt in placed:
            if not txt:
                continue
            ax.text(
                min(float(x), x_end - 0.4),
                y,
                txt,
                color=_LADDER if txt.startswith("候選") else _PRESS if txt.startswith("下降壓") else _TEXT,
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
            _draw_price_tag(ax, x_end + 0.15, y, txt, fp=_fp(7.4, "bold"), face=_TAG_HOT)

        bubble = str(wave.get("bubble") or "").strip()
        if not bubble:
            bubble = "情境預估（不保證・不是買訊）"
        ax.text(
            0.015,
            0.035,
            bubble,
            transform=ax.transAxes,
            color="white",
            fontproperties=_fp(8.0, "bold"),
            ha="left",
            va="bottom",
            zorder=9,
            bbox={
                "boxstyle": "round,pad=0.38",
                "facecolor": _BUBBLE,
                "edgecolor": "#0d47a1",
                "alpha": 0.93,
            },
        )

        title = f"{sid} {name}　情境預估（不保證・不是買訊）".strip()
        ax.set_title(title, fontproperties=_fp(11, "bold"), color=_TEXT, pad=8)
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
        ticks, labels = _future_tick_labels(rows, n, x_max)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, fontproperties=_fp(7.0))
        axv.set_xticks(ticks)
        axv.set_xticklabels([])
        # 現價豎虛線＝時間軸「現在」
        ax.axvline(float(n - 1), color="#757575", lw=0.8, ls="--", alpha=0.7, zorder=2)
        fig.subplots_adjust(left=0.07, right=0.93, top=0.93, bottom=0.06)
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
) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """渲情境預估圖。回 (path|None, caption, meta)。失敗 path=None，不准拋到查股主路徑。"""
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
        paths = (
            []
            if wave
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
        elif paths:
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
