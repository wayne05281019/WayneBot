# -*- coding: utf-8 -*-
"""個股「情境預估（不保證）」圖：VEGAS＋下降壓＋前高＋DC 風格浪號／虛線路徑。

獨立附加、永遠不是買訊。使用者鎖死：僅此子鈕可標 (1)–(5)／abc 情境浪號
（其他鈕仍守 §12 不准發明 5／9）。浪號＝樞紐重算情境，不保證、不改買訊。
失敗回 None；呼叫端必須吞錯，不准擋查股四張／主選單。
Asia/Taipei；只讀官方日 K。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger("WayneBot.ScenarioForecast")

# 近窗對齊結構圖量級；不夠就不硬畫長均
_BARS = 168
_FUTURE = 28
_DPI = 160
_MIN_BARS = 40

_BG = "#ffffff"
_TUNNEL = "#1565c0"
_EMA12 = "#43a047"
_EMA_SLOW = "#90a4ae"
_PRESS = "#6a1b9a"
_LADDER = "#c62828"
_TEXT = "#37474f"
_WAVE = "#d32f2f"
_WAVE_DASH = "#78909c"
_TAG_BG = "#546e7a"
_BUBBLE = "#1565c0"
_PATH_COLORS = ("#90a4ae", "#78909c", "#607d8b")


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
    highs: Sequence[float], lows: Sequence[float], *, left: int = 3
) -> List[Dict[str, Any]]:
    try:
        from biaoke_chart import _pivots
    except Exception:
        return []
    hi_p, lo_p = _pivots(list(highs), list(lows), left=left)
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
        else:
            out.append(p)
    return out


def _pick_ladder_above(levels: Sequence[float], floor: float, *, default: float) -> float:
    for lv in sorted(float(x) for x in levels if float(x) > 0):
        if lv > floor * 1.005:
            return float(lv)
    return float(default)


def infer_dc_wave_scenario(
    rows: Sequence[Dict[str, Any]],
    ladders: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """樞紐重算上升 5 浪情境：已走標 (1)(2)…；未走虛線 (3)(4)(5)；必要時 abc。

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
    zz = _alternating_zigzag(highs, lows, left=3)
    if len(zz) < 3:
        return empty
    ladder_lv = sorted(
        {float(x.get("price") or 0) for x in (ladders or []) if float(x.get("price") or 0) > 0}
    )

    best = None
    best_score = -1.0
    # 候選：以 L 起的交替段，至少走到 (1)(2)
    for si, p0 in enumerate(zz):
        if p0["kind"] != "L":
            continue
        seg = zz[si:]
        if len(seg) < 3:
            continue
        # 需要 H L …
        if seg[1]["kind"] != "H" or seg[2]["kind"] != "L":
            continue
        start, w1, w2 = seg[0], seg[1], seg[2]
        if w1["price"] <= start["price"] * 1.01:
            continue
        if w2["price"] >= w1["price"] * 0.995:
            continue
        if w2["price"] < start["price"] * 0.92:
            # 破底太深當失敗浪，仍可分數較低
            pass
        confirmed: List[Dict[str, Any]] = [
            {
                "label": "(1)",
                "i": float(w1["i"]),
                "price": float(w1["price"]),
                "kind": "H",
                "projected": False,
            },
            {
                "label": "(2)",
                "i": float(w2["i"]),
                "price": float(w2["price"]),
                "kind": "L",
                "projected": False,
            },
        ]
        w3 = seg[3] if len(seg) > 3 and seg[3]["kind"] == "H" else None
        w4 = seg[4] if len(seg) > 4 and seg[4]["kind"] == "L" else None
        w5 = seg[5] if len(seg) > 5 and seg[5]["kind"] == "H" else None
        if w3 and w3["price"] > w1["price"] * 1.002:
            confirmed.append(
                {
                    "label": "(3)",
                    "i": float(w3["i"]),
                    "price": float(w3["price"]),
                    "kind": "H",
                    "projected": False,
                }
            )
            if w4 and w4["price"] < w3["price"] * 0.998 and w4["price"] > start["price"]:
                confirmed.append(
                    {
                        "label": "(4)",
                        "i": float(w4["i"]),
                        "price": float(w4["price"]),
                        "kind": "L",
                        "projected": False,
                    }
                )
                if w5 and w5["price"] > w3["price"] * 1.001:
                    confirmed.append(
                        {
                            "label": "(5)",
                            "i": float(w5["i"]),
                            "price": float(w5["price"]),
                            "kind": "H",
                            "projected": False,
                        }
                    )

        amp = float(w1["price"]) - float(start["price"])
        if amp <= 0:
            continue
        # 越靠近現在、振幅越大、規則越完整越好
        recency = 1.0 + float(w2["i"]) / float(max(n, 1))
        completeness = float(len(confirmed))
        score = amp * recency * (1.0 + 0.15 * completeness)
        if w2["price"] < start["price"]:
            score *= 0.55
        # (1) 已貼近窗內最高 → 虛線 (3)(5) 易噴出比例；扣分改選更早骨架
        win_hi = max(highs) if highs else float(w1["price"])
        if float(w1["price"]) >= win_hi * 0.97 and "(3)" not in {c["label"] for c in confirmed}:
            score *= 0.35
        # 有前高候選高於 (1) 加分（虛線有錨）
        if any(lv > float(w1["price"]) * 1.01 for lv in ladder_lv):
            score *= 1.25
        if score > best_score:
            best_score = score
            best = {
                "start": {
                    "i": float(start["i"]),
                    "price": float(start["price"]),
                    "kind": "L",
                },
                "confirmed": confirmed,
                "seg_tail": seg[3:],
            }

    if not best:
        return empty

    confirmed = list(best["confirmed"])
    start = best["start"]
    amp1 = float(confirmed[0]["price"]) - float(start["price"])
    projected: List[Dict[str, Any]] = []
    have = {c["label"] for c in confirmed}

    def _x_next(prev_i: float, bars: float) -> float:
        return float(prev_i) + float(bars)

    # 虛線價上限：避免 y 軸被 1.618 延伸撐爆（手機縮圖仍要可讀）
    y_cap = max(float(confirmed[0]["price"]) * 1.22, last * 1.35)
    if ladder_lv:
        y_cap = max(y_cap, max(ladder_lv) * 1.03)

    # 補虛線未走浪
    if "(3)" not in have:
        base_i = float(confirmed[-1]["i"])
        y3 = _pick_ladder_above(
            ladder_lv,
            float(confirmed[0]["price"]),
            default=float(confirmed[0]["price"])
            + min(amp1 * 1.0, float(confirmed[0]["price"]) * 0.18),
        )
        y3 = max(y3, float(confirmed[0]["price"]) * 1.02)
        y3 = min(y3, y_cap)
        projected.append(
            {
                "label": "(3)",
                "i": _x_next(base_i, 8),
                "price": float(y3),
                "kind": "H",
                "projected": True,
            }
        )
    if "(4)" not in have:
        src3 = next((c for c in confirmed + projected if c["label"] == "(3)"), None)
        src2 = next((c for c in confirmed if c["label"] == "(2)"), None)
        if src3 and src2:
            y4 = float(src3["price"]) - 0.382 * (
                float(src3["price"]) - float(src2["price"])
            )
            y4 = max(y4, float(src2["price"]) * 1.01)
            projected.append(
                {
                    "label": "(4)",
                    "i": _x_next(float(src3["i"]), 6),
                    "price": float(y4),
                    "kind": "L",
                    "projected": True,
                }
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
                {
                    "label": "(5)",
                    "i": _x_next(float(src4["i"]), 7),
                    "price": float(y5),
                    "kind": "H",
                    "projected": True,
                }
            )

    # 完整 5 浪後若還有回檔樞紐 → abc
    abc: List[Dict[str, Any]] = []
    if "(5)" in have:
        w5c = next(c for c in confirmed if c["label"] == "(5)")
        tail = [p for p in best["seg_tail"] if p["i"] > w5c["i"]]
        # 對齊：H5 後應 L(a) H(b) L(c)
        # confirmed 的 (5) 來自 seg；tail 是 seg[3:] 可能含 3,4,5 之後
        after = []
        for p in zz:
            if p["i"] > w5c["i"]:
                after.append(p)
        if (
            len(after) >= 3
            and after[0]["kind"] == "L"
            and after[1]["kind"] == "H"
            and after[2]["kind"] == "L"
        ):
            for lab, p in zip(("a", "b", "c"), after[:3]):
                abc.append(
                    {
                        "label": lab,
                        "i": float(p["i"]),
                        "price": float(p["price"]),
                        "kind": p["kind"],
                        "projected": False,
                    }
                )

    # 路徑點：起點 → 已走 → 虛線
    path_done: List[Tuple[float, float]] = [
        (float(start["i"]), float(start["price"]))
    ]
    for c in confirmed:
        path_done.append((float(c["i"]), float(c["price"])))
    path_proj: List[Tuple[float, float]] = []
    if projected:
        path_proj.append(path_done[-1])
        for c in projected:
            path_proj.append((float(c["i"]), float(c["price"])))

    conf_labs = [c["label"] for c in confirmed]
    proj_labs = [c["label"] for c in projected]
    if abc:
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
        "labels": conf_labs + proj_labs + [a["label"] for a in abc],
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


def _draw_price_tag(ax, x: float, y: float, text: str, *, fp) -> None:
    ax.text(
        x,
        y,
        text,
        color="white",
        fontproperties=fp,
        ha="left",
        va="center",
        zorder=8,
        bbox={
            "boxstyle": "round,pad=0.22",
            "facecolor": _TAG_BG,
            "edgecolor": "none",
            "alpha": 0.92,
        },
    )


def _draw_wave_label(ax, x: float, y: float, label: str, *, kind: str, fp) -> None:
    # 高點標上方、低點標下方
    va = "bottom" if kind == "H" else "top"
    ax.plot(x, y, "o", ms=11, color=_WAVE, mfc="white", mew=1.5, zorder=7)
    ax.annotate(
        label,
        xy=(x, y),
        xytext=(0, 9 if kind == "H" else -9),
        textcoords="offset points",
        color=_WAVE,
        fontproperties=fp,
        ha="center",
        va=va,
        zorder=8,
        clip_on=False,
    )


def _paint(
    rows: Sequence[Dict[str, Any]],
    meta: Dict[str, Any],
    out_path: str,
    *,
    sid: str,
    name: str,
) -> Optional[str]:
    from wayne_navigator import (
        _fp,
        configure_lookup_vol_axis,
        mpl_render,
        paint_lookup_ohlc_candles,
        paint_lookup_volume_bars,
    )

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

    with mpl_render():
        fig, (ax, axv) = plt.subplots(
            2,
            1,
            figsize=(10.2, 7.4),
            gridspec_kw={"height_ratios": [3.25, 1.0], "hspace": 0.06},
            facecolor=_BG,
        )
        ax.set_facecolor(_BG)
        axv.set_facecolor(_BG)
        paint_lookup_ohlc_candles(ax, xs, opens, highs, lows, closes)
        candle_up = [closes[i] >= opens[i] for i in range(n)]
        _vh, vol_ylim, _vm = paint_lookup_volume_bars(axv, xs, vols, candle_up)
        configure_lookup_vol_axis(axv, float(vol_ylim or 1.0))

        if e144 and e169 and len(e144) == n and len(e169) == n:
            lo = np.minimum(np.asarray(e144), np.asarray(e169))
            hi = np.maximum(np.asarray(e144), np.asarray(e169))
            ax.fill_between(xs, lo, hi, color=_TUNNEL, alpha=0.12, zorder=2)
            ax.plot(xs, e144, color=_TUNNEL, lw=1.15, zorder=3)
            ax.plot(xs, e169, color=_TUNNEL, lw=1.15, zorder=3)
        if e12 and len(e12) == n:
            ax.plot(xs, e12, color=_EMA12, lw=0.9, zorder=3)
        if e576 and len(e576) == n:
            ax.plot(xs, e576, color=_EMA_SLOW, lw=0.8, zorder=2, alpha=0.85)
        if e676 and len(e676) == n:
            ax.plot(xs, e676, color=_EMA_SLOW, lw=0.8, zorder=2, alpha=0.85)

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
                    lw=1.35,
                    zorder=4,
                )

        for lad in ladders:
            y = float(lad["price"])
            ax.axhline(y, color=_LADDER, lw=0.95, alpha=0.75, zorder=3)

        # DC 浪號路徑：已走實線＋未走虛線
        if wave:
            done = list(wave.get("path_done") or [])
            proj = list(wave.get("path_proj") or [])
            if len(done) >= 2:
                ax.plot(
                    [p[0] for p in done],
                    [p[1] for p in done],
                    color=_WAVE,
                    lw=1.45,
                    zorder=5,
                    alpha=0.9,
                )
            if len(proj) >= 2:
                ax.plot(
                    [p[0] for p in proj],
                    [p[1] for p in proj],
                    color=_WAVE_DASH,
                    lw=1.5,
                    ls=(0, (5, 3)),
                    zorder=5,
                    alpha=0.9,
                )
            fp_w = _fp(8.5, "bold")
            fp_tag = _fp(7.5, "bold")
            for node in list(wave.get("confirmed") or []) + list(
                wave.get("projected") or []
            ) + list(wave.get("abc") or []):
                _draw_wave_label(
                    ax,
                    float(node["i"]),
                    float(node["price"]),
                    str(node["label"]),
                    kind=str(node.get("kind") or "H"),
                    fp=fp_w,
                )
                if node.get("projected") and node.get("kind") == "H":
                    _draw_price_tag(
                        ax,
                        float(node["i"]) + 0.35,
                        float(node["price"]),
                        _fmt_px(float(node["price"])),
                        fp=fp_tag,
                    )

        # 無浪時才畫多條階梯虛線
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
                    alpha=0.82,
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

        for lad in ladders:
            label_anchors.append(
                (x_end - 0.15, float(lad["price"]), str(lad.get("label") or ""))
            )
        if press and press.get("y_now") is not None and press.get("j") is not None:
            if int(press["j"]) - int(press["i"]) >= 10:
                label_anchors.append(
                    (
                        x_end - 0.2,
                        float(press["y_now"]),
                        f"下降壓 {_fmt_px(float(press['y_now']))}",
                    )
                )

        y_span = max(highs) - min(lows) if highs and lows else 1.0
        min_gap = max(y_span * 0.035, (max(closes) or 1.0) * 0.012)
        placed = dodge_label_ys(label_anchors, min_gap=min_gap)
        for x, y, txt in placed:
            if not txt:
                continue
            is_press = txt.startswith("下降壓")
            is_lad = txt.startswith("候選")
            col = _PRESS if is_press else (_LADDER if is_lad else _TEXT)
            ax.text(
                min(float(x), x_end - 0.05),
                y,
                txt,
                color=col,
                fontproperties=_fp(7.2, "bold"),
                ha="right",
                va="bottom",
                zorder=6,
                alpha=0.92,
            )

        # 圖內說明氣泡（DC 清晰度；非買訊）
        bubble = str(wave.get("bubble") or "").strip()
        if not bubble:
            bubble = "情境預估（不保證・不是買訊）"
        ax.text(
            0.02,
            0.03,
            bubble,
            transform=ax.transAxes,
            color="white",
            fontproperties=_fp(8.2, "bold"),
            ha="left",
            va="bottom",
            zorder=9,
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": _BUBBLE,
                "edgecolor": "none",
                "alpha": 0.92,
            },
        )

        title = f"{sid} {name}　情境預估（不保證・不是買訊）".strip()
        ax.set_title(title, fontproperties=_fp(11, "bold"), color=_TEXT, pad=8)
        # x 上限含虛線預估
        x_max = x_end + 0.4
        if wave:
            for p in list(wave.get("path_proj") or []) + list(wave.get("projected") or []):
                try:
                    x_max = max(x_max, float(p[0] if isinstance(p, (list, tuple)) else p["i"]) + 1.5)
                except Exception:
                    pass
        ax.set_xlim(-0.8, x_max)
        ax.grid(True, color="#eceff1", lw=0.6, zorder=0)
        axv.grid(True, color="#eceff1", lw=0.6, zorder=0)
        ax.tick_params(labelsize=8, colors=_TEXT)
        axv.tick_params(labelsize=7, colors=_TEXT)
        step = max(1, n // 6)
        ticks = list(range(0, n, step))
        if n - 1 not in ticks:
            ticks.append(n - 1)
        ax.set_xticks(ticks)
        ax.set_xticklabels(
            [str(rows[i].get("date") or "")[4:] for i in ticks],
            fontsize=7,
        )
        axv.set_xticks(ticks)
        axv.set_xticklabels([])
        fig.subplots_adjust(left=0.07, right=0.98, top=0.93, bottom=0.06)
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
