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
_BARS = 320
_WAVE_LEFT = 10
_WAVE_MIN_BARS = 14
_WAVE_MIN_PCT = 0.10
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
    fut = float(_FUTURE)

    def _pack(
        start: Dict[str, Any],
        confirmed: List[Dict[str, Any]],
        projected: List[Dict[str, Any]],
        abc: List[Dict[str, Any]],
        *,
        next_cycle: Optional[List[Dict[str, Any]]] = None,
        state: str = "",
        bubble: str = "",
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

    # ----- 候選：大級別衝動 -----
    work = list(zz)
    if work and work[0]["kind"] == "H":
        i0 = int(work[0]["i"])
        if i0 > 0:
            j = min(range(i0), key=lambda k: lows[k])
            work = [{"i": j, "kind": "L", "price": float(lows[j])}] + work

    def _impulse_from(work_zz):
        best_local = None
        best_sc = -1.0
        for si, p0 in enumerate(work_zz):
            if p0["kind"] != "L":
                continue
            seg = work_zz[si:]
            if len(seg) < 3:
                continue
            if seg[1]["kind"] != "H" or seg[2]["kind"] != "L":
                continue
            start_p, w1, w2 = seg[0], seg[1], seg[2]
            if w1["price"] <= start_p["price"] * 1.01:
                continue
            if w2["price"] >= w1["price"] * 0.995:
                continue
            if w2["price"] < start_p["price"] * 0.998:
                continue
            span = float(w2["i"]) - float(start_p["i"])
            if span < 12:
                continue
            confirmed: List[Dict[str, Any]] = [
                _wave_node(
                    "(1)", w1["i"], w1["price"], "H",
                    projected=False, date=_bar_date(rows, w1["i"]),
                ),
                _wave_node(
                    "(2)", w2["i"], w2["price"], "L",
                    projected=False, date=_bar_date(rows, w2["i"]),
                ),
            ]
            w3 = seg[3] if len(seg) > 3 and seg[3]["kind"] == "H" else None
            w4 = seg[4] if len(seg) > 4 and seg[4]["kind"] == "L" else None
            w5 = seg[5] if len(seg) > 5 and seg[5]["kind"] == "H" else None
            soft_w3 = None
            if (
                w3
                and w3["price"] > w1["price"] * 1.002
                and w4
                and w4["price"] < w3["price"] * 0.998
                and w4["price"] > start_p["price"]
            ):
                confirmed.append(
                    _wave_node(
                        "(3)", w3["i"], w3["price"], "H",
                        projected=False, date=_bar_date(rows, w3["i"]),
                    )
                )
                confirmed.append(
                    _wave_node(
                        "(4)", w4["i"], w4["price"], "L",
                        projected=False, date=_bar_date(rows, w4["i"]),
                    )
                )
                if w5 and w5["price"] > w3["price"] * 1.001:
                    len1 = float(w1["price"]) - float(start_p["price"])
                    len3 = float(w3["price"]) - float(w2["price"])
                    len5 = float(w5["price"]) - float(w4["price"])
                    if len3 + 1e-9 >= min(len1, len5):
                        confirmed.append(
                            _wave_node(
                                "(5)", w5["i"], w5["price"], "H",
                                projected=False, date=_bar_date(rows, w5["i"]),
                            )
                        )
            elif w3 and w3["price"] > w1["price"] * 1.002:
                soft_w3 = w3
            amp_pct = (float(w1["price"]) - float(start_p["price"])) / max(
                float(start_p["price"]), 1e-9
            )
            if amp_pct < 0.06:
                continue
            last_i = float(confirmed[-1]["i"])
            span_frac = span / float(max(n, 1))
            recency = (last_i / float(max(n - 1, 1))) ** 1.5
            score = amp_pct * (0.5 + 4.0 * span_frac) * (0.4 + 1.6 * recency)
            score *= 1.0 + 0.1 * float(len(confirmed))
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
            bubble="情境預估：(v) 後修正 abc（樞紐重算・不保證・不是買訊）",
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
    amp1 = float(confirmed[0]["price"]) - float(start["price"])
    projected: List[Dict[str, Any]] = []
    have = {c["label"] for c in confirmed}
    x_now = max(float(confirmed[-1]["i"]), float(n - 1))
    y_cap = max(float(confirmed[0]["price"]) * 1.35, last * 1.45)
    if ladder_lv:
        y_cap = max(y_cap, max(ladder_lv) * 1.05)
    soft_w3 = chosen.get("soft_w3")
    if "(3)" not in have:
        y3 = _pick_ladder_above(
            ladder_lv,
            float(confirmed[0]["price"]),
            default=float(confirmed[0]["price"])
            + min(amp1 * 1.618, float(confirmed[0]["price"]) * 0.35),
        )
        if soft_w3:
            y3 = max(y3, float(soft_w3["price"]) * 1.02)
        y3 = max(y3, float(confirmed[0]["price"]) * 1.05)
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
            y4 = max(y4, float(start["price"]) * 1.02)
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
                + min(amp1 * 0.8, float(src3["price"]) * 0.15),
            )
            y5 = max(y5, float(src3["price"]) * 1.03)
            y5 = min(y5, y_cap * 1.02)
            projected.append(
                _wave_node("(5)", x_now + fut * 0.88, y5, "H", projected=True, date="估")
            )
    return _pack(start, confirmed, projected, [], state="partial")



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
):
    """歷史＋未來軸標（Asia/Taipei）。少刻度、大字、帶年月；對齊浪號 x。"""
    last_dt = _ymd_to_dt(str(rows[-1].get("date") or "")) or datetime.now(_TZ)
    ticks: List[float] = []
    labels: List[str] = []
    years_seen: set = set()

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

    # 歷史：頭／中／尾（現價），避免擠
    for i in (0, n // 2, n - 1):
        _add_hist(i)
    if not any(abs(t - float(n - 1)) < 0.5 for t in ticks):
        _add_hist(n - 1)

    fut_xs: List[float] = []
    if wave_xs:
        for x in wave_xs:
            try:
                xf = float(x)
            except Exception:
                continue
            if xf > float(n - 1) + 0.5:
                fut_xs.append(xf)
    if not fut_xs:
        fut_xs = [float(n - 1) + float(_FUTURE) * f for f in (0.34, 0.62, 0.90)]
    # 未來最多 3 個，且彼此拉開
    fut_xs = sorted(fut_xs)
    placed_fut: List[float] = []
    min_gap = max(float(_FUTURE) * 0.18, 10.0)
    for xi in fut_xs:
        if xi > x_max + 0.1:
            continue
        if placed_fut and (xi - placed_fut[-1]) < min_gap:
            continue
        days = int(round(max(0.0, xi - float(n - 1)) * 1.4))
        d = last_dt + timedelta(days=days)
        ticks.append(float(xi))
        # 未來軸一律帶年，遠看也分得清
        labels.append(_fmt_axis_date(d, with_year=True))
        placed_fut.append(float(xi))
        if len(placed_fut) >= 3:
            break
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
        wave_xs = []
        if wave:
            for node in list(wave.get("projected") or []):
                try:
                    wave_xs.append(float(node.get("i") or 0))
                except Exception:
                    pass
        ticks, labels = _future_tick_labels(rows, n, x_max, wave_xs=wave_xs)
        # 軸標掛量能底軸（上圖會被量能面板裁掉）；字級約舊 v5 的 1.5～2×
        ax.set_xticks(ticks)
        ax.set_xticklabels([])
        ax.tick_params(axis="x", labelbottom=False, length=0)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels)
        for lab, xi in zip(axv.get_xticklabels(), ticks):
            is_fut = float(xi) > float(n - 1) + 0.2
            lab.set_fontproperties(_fp(16.0 if is_fut else 14.0, "bold"))
            lab.set_color("#0d47a1" if is_fut else "#111111")
            lab.set_rotation(22)
            lab.set_ha("right")
            lab.set_clip_on(False)
        axv.tick_params(axis="x", pad=8, length=5, width=1.2, colors="#111111", labelbottom=True)
        # 現價豎線＝歷史／未來分界（加粗＋淺底帶）
        ax.axvspan(float(n - 1), x_max, color="#ffffff", alpha=0.22, zorder=0)
        ax.axvline(float(n - 1), color="#212121", lw=2.2, ls="-", alpha=0.95, zorder=6)
        axv.axvline(float(n - 1), color="#212121", lw=1.8, ls="-", alpha=0.9, zorder=6)
        fig.subplots_adjust(left=0.07, right=0.94, top=0.92, bottom=0.18)
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
