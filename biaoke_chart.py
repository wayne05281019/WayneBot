# -*- coding: utf-8 -*-
"""飆大視窗專用結構圖：個股看官方日 K 量先價行。

只給按了「飆大」之後的對話。不是介紹圖、不是決策卡、不進海選。
個股主圖＝日 K：爆大量那一天最高當壓、最低當撐。
15／60 分只拿來看大盤／台指期，不准畫在這張個股圖上。
連點軌道是輔助（兩個更低的高／兩個更高的低）；不夠兩點就不畫。
不准發明 5／9 段、不准把「三日底點不破」畫成他的固定公式。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib import patches

from wayne_navigator import NAV_CHART_DPI, _fp, _mpl_serial

logger = logging.getLogger("WayneBot.BiaokeChart")

_BG = "#ffffff"
_PANEL = "#ffffff"
_GRID = "#bdbdbd"
_TEXT = "#1f2933"
_UP = "#e53935"
_DN = "#00897b"
_PRESS = "#c62828"
_HOLD = "#2e7d32"
_DOWN_TRACK = "#6a1b9a"
_UP_TRACK = "#0277bd"
_WASH = "#ef6c00"
_SPIKE_VOL = "#f9a825"
_BARS = 60


def _md(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{int(t[4:6])}/{int(t[6:8])}"
    return str(raw or "").strip()


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return "—"
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


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
    for b in range(len(hi_p) - 1, 0, -1):
        for a in range(b - 1, -1, -1):
            i, j = int(hi_p[a]), int(hi_p[b])
            if j - i < 3:
                continue
            if highs[j] < highs[i] * 0.999:
                return i, j
    return None


def _asc_low_pair(lo_p: Sequence[int], lows: Sequence[float]) -> Optional[Tuple[int, int]]:
    for b in range(len(lo_p) - 1, 0, -1):
        for a in range(b - 1, -1, -1):
            i, j = int(lo_p[a]), int(lo_p[b])
            if j - i < 3:
                continue
            if lows[j] > lows[i] * 1.001:
                return i, j
    return None


def _line_at(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    if x2 == x1:
        return y2
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


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
    up = _asc_low_pair(lo_p, lows)
    out["down_track"] = down
    out["up_track"] = up
    n = len(rows)
    notes: List[str] = []
    if spike_hi and spike_lo:
        notes.append(
            f"官方日K（不是15分）量先價行：爆大量那一天 {_md(spike_date) or spike_date} "
            f"最高 {_px(spike_hi)} 當壓、最低 {_px(spike_lo)} 當撐；站上撐後等價穩量縮才進，否則放棄。"
        )
    if down:
        y_now = _line_at(down[0], highs[down[0]], down[1], highs[down[1]], n - 1)
        out["down_now"] = y_now
        if last < y_now:
            notes.append(f"下降壓連點還壓著，要過 {_px(y_now)} 才像真突破下降壓")
        else:
            notes.append(f"收在下降壓連點 {_px(y_now)} 之上，比較像下降壓壞了；還要量價確認")
    if up:
        y_now = _line_at(up[0], lows[up[0]], up[1], lows[up[1]], n - 1)
        out["up_now"] = y_now
        if last > y_now:
            notes.append(f"上升軌連點約 {_px(y_now)}，收在上面；破這條才像軌壞掉")
        else:
            notes.append(f"收在上升軌連點 {_px(y_now)} 之下，這條上升軌先當壞了")
    if out["wash"]:
        notes.append("破撐之後又站回，比較像破線洗盤，不是保證")
    elif out.get("distribution"):
        notes.append("過壓之後又掉回撐下，比較像出貨，不是洗盤")
    elif out["under_support"]:
        notes.append("收在爆大量日低之下，他這套先放棄這次量價")
    elif out["over_press"]:
        notes.append("已過爆大量日高，比較像半山腰／突破，不是落後補漲")
    out["notes"] = notes
    out["highs"] = highs
    out["lows"] = lows
    out["closes"] = closes
    out["vols"] = vols
    return out


@_mpl_serial
def render_biaoke_structure_png(
    bars: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    sid: str = "",
    name: str = "",
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
    xs = list(range(n))
    span = max(max(highs) - min(lows), 1.0)
    ymin = min(lows) - span * 0.06
    ymax = max(highs) + span * 0.16
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    from decision_card_signals import candle_up_taiwan

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(12.8, 7.55),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.15, 1.45), hspace=0.04),
        facecolor=_BG,
    )
    ax1.set_facecolor(_PANEL)
    ax2.set_facecolor(_PANEL)
    ax1.set_ylim(ymin, ymax)
    ax1.set_xlim(-0.8, n - 0.2)
    candle_up = []
    for i in range(n):
        prev_c = closes[i - 1] if i else None
        candle_up.append(candle_up_taiwan(closes[i], prev_c, opens[i]))
    for i in range(n):
        c = _UP if candle_up[i] else _DN
        ax1.plot([xs[i], xs[i]], [lows[i], highs[i]], color=c, linewidth=1.05, zorder=3)
        body = max(abs(closes[i] - opens[i]), span * 0.0018)
        ax1.add_patch(
            patches.Rectangle(
                (xs[i] - 0.32, min(opens[i], closes[i])),
                0.64,
                body,
                facecolor=c,
                edgecolor=c,
                zorder=3,
            )
        )
    st = info.get("struct") or {}
    spike_hi = float(st.get("spike_high") or 0)
    spike_lo = float(st.get("spike_low") or 0)
    spike_i = int(info.get("spike_i") or 0)
    spike_date = str(st.get("spike_date") or "")
    if spike_hi:
        ax1.axhline(spike_hi, color=_PRESS, linewidth=1.6, zorder=4)
        ax1.text(
            n - 0.4,
            spike_hi,
            f" 壓 {_px(spike_hi)}＝爆大量日高",
            color=_PRESS,
            fontproperties=_fp(9, "bold"),
            va="bottom",
            ha="right",
        )
    if spike_lo:
        ax1.axhline(spike_lo, color=_HOLD, linewidth=1.6, zorder=4)
        ax1.text(
            n - 0.4,
            spike_lo,
            f" 撐 {_px(spike_lo)}＝爆大量日低",
            color=_HOLD,
            fontproperties=_fp(9, "bold"),
            va="top",
            ha="right",
        )
    if 0 <= spike_i < n:
        ax1.axvline(spike_i, color="#90a4ae", linewidth=0.9, linestyle="--", zorder=2)
        ax1.annotate(
            f"爆大量日 {_md(spike_date) or spike_date}\n高{_px(spike_hi)}=壓  低{_px(spike_lo)}=撐",
            xy=(spike_i, spike_hi),
            xytext=(max(spike_i - n * 0.18, 0.4), min(spike_hi + span * 0.08, ymax)),
            textcoords="data",
            color=_TEXT,
            fontproperties=_fp(9, "bold"),
            arrowprops=dict(arrowstyle="->", color="#607d8b", lw=0.9),
            zorder=7,
        )
    down = info.get("down_track")
    if down:
        x1, x2 = down
        y1, y2 = highs[x1], highs[x2]
        x_end = n - 1
        y_end = _line_at(x1, y1, x2, y2, x_end)
        ax1.plot([x1, x_end], [y1, y_end], color=_DOWN_TRACK, linewidth=1.15, linestyle=(0, (3, 2)), zorder=5)
        ax1.scatter([x1, x2], [y1, y2], color=_DOWN_TRACK, s=18, zorder=6)
        ax1.text(x_end, y_end, " 下降連點", color=_DOWN_TRACK, fontproperties=_fp(8), va="bottom")
    up = info.get("up_track")
    if up:
        x1, x2 = up
        y1, y2 = lows[x1], lows[x2]
        x_end = n - 1
        y_end = _line_at(x1, y1, x2, y2, x_end)
        ax1.plot([x1, x_end], [y1, y_end], color=_UP_TRACK, linewidth=1.15, linestyle=(0, (3, 2)), zorder=5)
        ax1.scatter([x1, x2], [y1, y2], color=_UP_TRACK, s=18, zorder=6)
        ax1.text(x_end, y_end, " 上升連點", color=_UP_TRACK, fontproperties=_fp(8), va="top")
    if info.get("wash"):
        ax1.text(
            0.01,
            0.98,
            "破線洗盤痕跡",
            transform=ax1.transAxes,
            color=_WASH,
            fontproperties=_fp(11, "bold"),
            va="top",
        )
    elif info.get("distribution"):
        ax1.text(
            0.01,
            0.98,
            "過壓後掉回＝出貨痕跡",
            transform=ax1.transAxes,
            color=_PRESS,
            fontproperties=_fp(11, "bold"),
            va="top",
        )
    title = f"{sid} {name}　官方日K・量先價行（不是15分、不是介紹圖／決策卡）".strip()
    ax1.set_title(title, fontproperties=_fp(13, "bold"), pad=22, color=_TEXT)
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID, zorder=1)
    ax1.yaxis.tick_right()
    ax1.yaxis.set_label_position("right")
    ax1.tick_params(labelsize=9, left=False, right=True, bottom=False, labelbottom=False)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(9))
    vol_colors = [_SPIKE_VOL if i == spike_i else (_UP if candle_up[i] else _DN) for i in range(n)]
    ax2.bar(xs, vols, color=vol_colors, width=0.72, zorder=3)
    if 0 <= spike_i < n and vols[spike_i]:
        ax2.annotate(
            "這根＝爆大量日",
            xy=(spike_i, vols[spike_i]),
            xytext=(min(spike_i + 3, n - 1), vols[spike_i] * 0.92),
            color=_TEXT,
            fontproperties=_fp(8, "bold"),
            arrowprops=dict(arrowstyle="->", color="#607d8b", lw=0.8),
        )
    ax2.set_ylabel("日量", fontproperties=_fp(8), color=_TEXT)
    ax2.yaxis.tick_right()
    ax2.yaxis.set_label_position("right")
    ax2.tick_params(labelsize=9, left=False, right=True)
    ax2.set_xlim(-0.8, n - 0.2)
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID)
    tick_i = list(range(0, n, max(n // 6, 5)))
    if n - 1 not in tick_i:
        tick_i.append(n - 1)
    if 0 <= spike_i < n and spike_i not in tick_i:
        tick_i.append(spike_i)
    tick_i = sorted(set(tick_i))
    labels = [_md(work[i].get("date")) or str(i) for i in tick_i]
    ax2.set_xticks(tick_i)
    ax2.set_xticklabels(labels, fontproperties=_fp(8))
    fig.subplots_adjust(left=0.04, right=0.90, top=0.88, bottom=0.10)
    fig.savefig(save_path, dpi=NAV_CHART_DPI, facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path if os.path.isfile(save_path) else ""


def chart_caption(info: Dict[str, Any], *, sid: str = "", name: str = "") -> str:
    head = f"{sid} {name}".strip()
    lines = [
        f"{head}　官方日K量先價行（不是15分、不是介紹圖／決策卡）".strip(),
        "介入買點首先量先價行：爆大量那一天最高價當壓力、最低價當支撐；站上撐或壓力轉撐之後，等價穩量縮才進，否則放棄。",
    ]
    for note in info.get("notes") or []:
        lines.append(str(note))
    lines.append("連點只是輔助。不夠兩點就不畫。個股不數 5／9 段。這不是買訊。")
    return "\n".join(x for x in lines if x)[:900]


def build_biaoke_structure_chart(
    db_path: str,
    sid: str,
    save_path: str,
    *,
    name: str = "",
) -> Dict[str, Any]:
    from biaoke_brain import load_bars

    sid = str(sid or "").strip()
    bars = load_bars(db_path, sid, n=120) if db_path and sid else []
    if not bars:
        return {"ok": False, "path": "", "caption": ""}
    nm = name or str(bars[-1].get("stock_name") or sid)
    info = analyze_structure(bars[-_BARS:])
    path = render_biaoke_structure_png(bars, save_path, sid=sid, name=nm)
    return {
        "ok": bool(path),
        "path": path or "",
        "caption": chart_caption(info, sid=sid, name=nm),
        "sid": sid,
        "name": nm,
        "wash": bool(info.get("wash")),
        "distribution": bool(info.get("distribution")),
        "notes": list(info.get("notes") or []),
    }
