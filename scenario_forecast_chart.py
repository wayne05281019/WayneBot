# -*- coding: utf-8 -*-
"""個股「情境預估（不保證）」相位一／1.5 圖：VEGAS＋下降壓＋前高＋虛線情境階梯。

獨立附加、非買訊、不准浪號／虛浪／抄 D.C 死價。
相位 1.5：淺色虛線 2～3 條階梯（現價附近→最近前高→下一階），標高低＋間距並避讓。
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
_FUTURE = 18
_DPI = 160
_MIN_BARS = 40

_BG = "#ffffff"
_UP = "#e53935"
_DN = "#00897b"
_TUNNEL = "#1565c0"
_EMA12 = "#43a047"
_EMA_SLOW = "#90a4ae"
_PRESS = "#6a1b9a"
_LADDER = "#c62828"
_TEXT = "#37474f"
# 情境階梯路徑（淺／虛線；非買訊）
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
        # 已明顯站上就不當壓候選
        if last >= h * 0.995:
            continue
        seen.add(key)
        cands.append((h, int(idx)))
        if len(cands) >= int(max_n):
            break
    cands.sort(key=lambda t: t[0])  # 低到高畫
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


def infer_scenario_paths(
    rows: Sequence[Dict[str, Any]],
    ladders: Sequence[Dict[str, Any]],
    *,
    n_bars: Optional[int] = None,
    max_paths: int = 3,
) -> List[Dict[str, Any]]:
    """相位 1.5：2～3 條淺色虛線情境階梯（現價附近→最近前高→下一階）。

    只重算幾何；不是買訊、不准浪號／死價。階梯不足 1 階＝[]。
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
        return []
    # 用到的前高階：至少 1、最多 3（現價→L1→L2…）
    use = levels[:3]
    # 時間節奏：保守／基準／稍快（只影響虛線落點，不保證）
    pacings = (
        (3.0, 5.0, 5.0),
        (2.0, 4.0, 4.5),
        (1.5, 3.0, 3.5),
    )
    n_paths = max(1, min(int(max_paths), 3, len(use) + 1))
    # 有 1 階也畫 2 條不同節奏；有 2+ 階最多 3 條
    if len(use) == 1:
        n_paths = min(2, n_paths)
    else:
        n_paths = min(3, max(2, n_paths))
    out: List[Dict[str, Any]] = []
    x0 = float(n - 1)
    for pi in range(n_paths):
        pace = pacings[min(pi, len(pacings) - 1)]
        # 第 k 條走前 min(len(use), 1+k) 階，讓 2～3 條有層次
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
            pts.append((x_h, prev))  # 水平
            pts.append((x_h, float(yp)))  # 垂直階
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
        # 末端再水平一點，看起來像情境延續而非尖點
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
    # 硬擋浪號字樣
    banned = ("波5", "波4", "1–5", "浪型", "艾略特", "(3)", "(4)", "(5)")
    safe = [b for b in bits if not any(x in b for x in banned)]
    if safe:
        return head + "\n" + "；".join(safe) + "。濾網／候選不是買訊。"
    return head + "\n隧道／下降壓／情境階梯；不是買訊。"


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
            figsize=(10.2, 7.2),
            gridspec_kw={"height_ratios": [3.2, 1.0], "hspace": 0.06},
            facecolor=_BG,
        )
        ax.set_facecolor(_BG)
        axv.set_facecolor(_BG)
        paint_lookup_ohlc_candles(ax, xs, opens, highs, lows, closes)
        candle_up = [closes[i] >= opens[i] for i in range(n)]
        _vh, vol_ylim, _vm = paint_lookup_volume_bars(axv, xs, vols, candle_up)
        configure_lookup_vol_axis(axv, float(vol_ylim or 1.0))

        # VEGAS tunnel fill 144–169
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
        # 有夠點才畫下降壓；沒有就不畫
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
            ax.axhline(y, color=_LADDER, lw=0.85, alpha=0.55, zorder=3, ls=":")

        # 相位 1.5：淺色虛線情境階梯 2～3 條（不數浪）
        label_anchors: List[Tuple[float, float, str]] = []
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

        # 只標最深一條的高低＋間距，避免多路徑同文互壓
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

        # 前高候選（右側）；下降壓有夠點才標
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
                fontproperties=_fp(7.0, "bold"),
                ha="right",
                va="bottom",
                zorder=6,
                alpha=0.92,
            )

        title = f"{sid} {name}　情境預估（不保證・不是買訊）".strip()
        ax.set_title(title, fontproperties=_fp(11, "bold"), color=_TEXT, pad=8)
        ax.set_xlim(-0.8, x_end + 0.4)
        ax.grid(True, color="#eceff1", lw=0.6, zorder=0)
        axv.grid(True, color="#eceff1", lw=0.6, zorder=0)
        ax.tick_params(labelsize=8, colors=_TEXT)
        axv.tick_params(labelsize=7, colors=_TEXT)
        # date ticks sparse
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

        # 多抓柱給 EMA 暖機（676）；畫面仍只畫近窗 _BARS
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
        # 把均線序列切成與近窗同長，供畫圖
        series_full = meta_full.get("_series") or {}
        cut = len(rows)
        ladders = infer_prior_high_ladders(rows, max_n=3)
        press = infer_desc_press(rows)
        paths = infer_scenario_paths(rows, ladders, n_bars=len(rows), max_paths=3)
        meta = {
            "vegas": meta_full.get("vegas") or {},
            "desc_press": press,
            "ladders": ladders,
            "paths": paths,
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
        if meta["paths"]:
            meta["caption_bits"].append(f"情境階梯{len(meta['paths'])}條")
        name = str(rows[-1].get("stock_name") or "")
        painted = _paint(rows, meta, out, sid=sid, name=name)
        cap = format_scenario_caption(sid, name, meta)
        if not painted:
            return None, f"{sid}　情境預估暫略。不是買訊。", meta
        meta_out = {
            "vegas": meta.get("vegas") or {},
            "desc_press": dict(meta.get("desc_press") or {}),
            "ladders": list(meta.get("ladders") or []),
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
