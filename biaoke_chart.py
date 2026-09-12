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
        if last > y_now:
            notes.append(
                f"上升連點 {_md(rows[a].get('date'))}低{_px(lows[a])}～"
                f"{_md(rows[b].get('date'))}低{_px(lows[b])}，"
                f"延長到最近約 {_px(y_now)}，收在上面；破這條才像軌壞掉"
            )
        else:
            notes.append(
                f"上升連點 {_md(rows[a].get('date'))}低{_px(lows[a])}～"
                f"{_md(rows[b].get('date'))}低{_px(lows[b])}，"
                f"延長到最近約 {_px(y_now)}，收在下面，這條上升軌先當壞了"
            )
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


def _price_box(ax, x, y, text, color, *, va="center", ha="left", size=12):
    ax.text(
        x,
        y,
        text,
        color=color,
        fontproperties=_fp(size, "bold"),
        va=va,
        ha=ha,
        zorder=8,
        bbox=dict(boxstyle="round,pad=0.28", facecolor="#ffffff", edgecolor=color, linewidth=1.1, alpha=0.96),
    )


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
    ymin = min(lows) - span * 0.05
    ymax = max(highs) + span * 0.22
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    from decision_card_signals import candle_up_taiwan

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(14.4, 8.6),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.35, 1.55), hspace=0.045),
        facecolor=_BG,
    )
    ax1.set_facecolor(_PANEL)
    ax2.set_facecolor(_PANEL)
    ax1.set_ylim(ymin, ymax)
    x_right = n + 5.2
    ax1.set_xlim(-0.55, x_right)
    candle_up = []
    for i in range(n):
        prev_c = closes[i - 1] if i else None
        candle_up.append(candle_up_taiwan(closes[i], prev_c, opens[i]))
    st = info.get("struct") or {}
    spike_hi = float(st.get("spike_high") or 0)
    spike_lo = float(st.get("spike_low") or 0)
    spike_i = int(info.get("spike_i") or 0)
    spike_date = str(st.get("spike_date") or "")
    last_bar = info.get("last_bar") or _bar_ohlc(work[-1])
    spike_bar = info.get("spike_bar") or {}
    for i in range(n):
        c = _UP if candle_up[i] else _DN
        thick = 1.55 if i == spike_i else 1.15
        ax1.plot(
            [xs[i], xs[i]],
            [lows[i], highs[i]],
            color=c,
            linewidth=thick,
            zorder=3,
            solid_capstyle="round",
        )
        body = max(abs(closes[i] - opens[i]), span * 0.0016)
        w = 0.62 if i == spike_i else 0.52
        ax1.add_patch(
            patches.Rectangle(
                (xs[i] - w / 2, min(opens[i], closes[i])),
                w,
                body,
                facecolor=c,
                edgecolor="#f9a825" if i == spike_i else c,
                linewidth=1.35 if i == spike_i else 0.6,
                zorder=3,
            )
        )
    if spike_hi:
        ax1.axhline(spike_hi, color=_PRESS, linewidth=1.85, zorder=4)
        _price_box(
            ax1,
            n + 0.55,
            spike_hi,
            f"壓 {_px(spike_hi)}",
            _PRESS,
            va="center",
            ha="left",
            size=13,
        )
    if spike_lo:
        ax1.axhline(spike_lo, color=_HOLD, linewidth=1.85, zorder=4)
        _price_box(
            ax1,
            n + 0.55,
            spike_lo,
            f"撐 {_px(spike_lo)}",
            _HOLD,
            va="center",
            ha="left",
            size=13,
        )
    last_c = float(last_bar.get("close") or 0)
    if last_c and (not spike_hi or abs(last_c - spike_hi) / span > 0.08) and (
        not spike_lo or abs(last_c - spike_lo) / span > 0.08
    ):
        _price_box(
            ax1,
            n + 0.55,
            last_c,
            f"收 {_px(last_c)}",
            _TEXT,
            va="center",
            ha="left",
            size=12,
        )
    if 0 <= spike_i < n:
        ax1.axvline(spike_i, color="#90a4ae", linewidth=1.05, linestyle="--", zorder=2)
        box_ha = "right" if spike_i > n * 0.62 else "center"
        box_x = spike_i - 0.45 if box_ha == "right" else spike_i
        _price_box(
            ax1,
            box_x,
            min(spike_hi + span * 0.06, ymax - span * 0.02) if spike_hi else highs[spike_i],
            f"爆大量日 {_ymd_full(spike_date)}",
            _TEXT,
            va="bottom",
            ha=box_ha,
            size=12,
        )
    down_pts = info.get("down_pts")
    if down_pts:
        (x1, y1, d1), (x2, y2, d2) = down_pts
        y_end = _line_at(x1, y1, x2, y2, n - 1)
        ax1.plot([x1, n - 1], [y1, y_end], color=_DOWN_TRACK, linewidth=1.2, linestyle=(0, (4, 2.2)), zorder=5)
        ax1.scatter([x1, x2], [y1, y2], color=_DOWN_TRACK, s=36, zorder=6)
        ax1.text(x1, y1, f"{_md(d1)}高{_px(y1)} ", color=_DOWN_TRACK, fontproperties=_fp(11, "bold"), va="bottom", ha="right")
        if x2 < n - 4 or abs(y2 - (spike_hi or y2)) / span > 0.07:
            ax1.text(x2, y2, f" {_md(d2)}高{_px(y2)}", color=_DOWN_TRACK, fontproperties=_fp(11, "bold"), va="bottom", ha="left")
    up_pts = info.get("up_pts")
    if up_pts:
        (x1, y1, d1), (x2, y2, d2) = up_pts
        y_end = _line_at(x1, y1, x2, y2, n - 1)
        ax1.plot([x1, n - 1], [y1, y_end], color=_UP_TRACK, linewidth=1.2, linestyle=(0, (4, 2.2)), zorder=5)
        ax1.scatter([x1, x2], [y1, y2], color=_UP_TRACK, s=36, zorder=6)
        ax1.text(x1, y1, f"{_md(d1)}低{_px(y1)} ", color=_UP_TRACK, fontproperties=_fp(11, "bold"), va="top", ha="right")
        if x2 < n - 4 or abs(y2 - (spike_lo or y2)) / span > 0.07:
            ax1.text(x2, y2, f" {_md(d2)}低{_px(y2)}", color=_UP_TRACK, fontproperties=_fp(11, "bold"), va="top", ha="left")
    mark = ""
    if info.get("wash"):
        mark = "破線洗盤痕跡（破撐後站回，不是保證）"
        mc = _WASH
    elif info.get("distribution"):
        mark = "過壓後掉回撐下＝出貨痕跡"
        mc = _PRESS
    elif info.get("under_support"):
        mark = "收在爆大量日低之下，這次量價先放棄"
        mc = _PRESS
    elif info.get("over_press"):
        mark = "已過爆大量日高（半山腰／突破，長抱另論）"
        mc = _WASH
    if mark:
        ax1.text(
            0.012,
            0.985,
            mark,
            transform=ax1.transAxes,
            color=mc,
            fontproperties=_fp(12, "bold"),
            va="top",
            zorder=8,
            bbox=dict(boxstyle="round,pad=0.28", facecolor="#ffffff", edgecolor=mc, linewidth=1.0),
        )
    ohlc_s = (
        f"最近收盤 {_ymd_full(last_bar.get('date'))}　"
        f"開 {_px(last_bar.get('open'))}　高 {_px(last_bar.get('high'))}　"
        f"低 {_px(last_bar.get('low'))}　收 {_px(last_bar.get('close'))}　"
        f"量 {_vol(last_bar.get('volume'))}"
    )
    spike_s = (
        f"爆大量日 {_ymd_full(spike_date)}　"
        f"開 {_px(spike_bar.get('open'))}　高 {_px(spike_hi)}＝壓　"
        f"低 {_px(spike_lo)}＝撐　收 {_px(spike_bar.get('close'))}　"
        f"量 {_vol(spike_bar.get('volume'))}　｜不是15分、不是介紹圖／決策卡"
    )
    fig.text(
        0.045,
        0.965,
        f"{sid} {name}　官方日K・量先價行".strip(),
        fontproperties=_fp(18, "bold"),
        color=_TEXT,
        va="top",
    )
    fig.text(0.045, 0.928, ohlc_s, fontproperties=_fp(13, "bold"), color=_TEXT, va="top")
    fig.text(0.045, 0.896, spike_s, fontproperties=_fp(13, "bold"), color=_PRESS, va="top")
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID, zorder=1)
    ax1.yaxis.tick_right()
    ax1.yaxis.set_label_position("right")
    ax1.tick_params(labelsize=11, left=False, right=True, bottom=False, labelbottom=False, length=5, width=0.8)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(11, "bold"))
    vol_colors = [_SPIKE_VOL if i == spike_i else (_UP if candle_up[i] else _DN) for i in range(n)]
    ax2.bar(xs, vols, color=vol_colors, width=0.68, zorder=3, edgecolor="#ffffff", linewidth=0.2)
    vmax = max(vols) if vols else 1.0
    ax2.set_ylim(0, vmax * 1.32)
    if 0 <= spike_i < n and vols[spike_i]:
        _price_box(
            ax2,
            spike_i,
            vols[spike_i],
            f"這根＝爆大量　{_vol(vols[spike_i])}",
            _TEXT,
            va="bottom",
            ha="center",
            size=11,
        )
    ax2.set_ylabel("日成交量（張）", fontproperties=_fp(11, "bold"), color=_TEXT)
    ax2.yaxis.tick_right()
    ax2.yaxis.set_label_position("right")
    ax2.tick_params(labelsize=11, left=False, right=True, length=5, width=0.8)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{int(round(v)):,}"))
    for lab in ax2.get_yticklabels():
        lab.set_fontproperties(_fp(10, "bold"))
    ax2.set_xlim(-0.55, x_right)
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID)
    step = max(n // 7, 4)
    tick_i = list(range(0, n, step))
    if n - 1 not in tick_i:
        tick_i.append(n - 1)
    if 0 <= spike_i < n and spike_i not in tick_i:
        tick_i.append(spike_i)
    tick_i = sorted(set(tick_i))
    keep = []
    for i in tick_i:
        if i in (0, n - 1) or i == spike_i:
            keep.append(i)
            continue
        if 0 <= spike_i < n and abs(i - spike_i) < 3:
            continue
        keep.append(i)
    tick_i = keep
    labels = []
    for i in tick_i:
        d = _ymd_full(work[i].get("date"))
        labels.append(d[5:].replace("-", "/") if d else _md(work[i].get("date")))
    ax2.set_xticks(tick_i)
    ax2.set_xticklabels(labels, fontproperties=_fp(11, "bold"))
    fig.subplots_adjust(left=0.045, right=0.87, top=0.78, bottom=0.08)
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
    return "\n".join(x for x in lines if x)[:1200]


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
