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
import re
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
_GRID = "#cfd8dc"
_TEXT = "#1f2933"
_UP = "#e53935"
_DN = "#00897b"
_PRESS = "#ad1457"
_HOLD = "#1b5e20"
_DOWN_TRACK = "#6a1b9a"
_UP_TRACK = "#0277bd"
_WASH = "#ef6c00"
_SPIKE_VOL = "#f9a825"
_BARS = 60
_FUTURE = 10
_PROJECT = "#e65100"
_FORK = "#5d4037"
_FUTURE_BG = "#fff6e0"
_HALO = "#ffffff"


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
    if up_pts:
        (x1, y1, _d1), (x2, y2, _d2) = up_pts
        up_fut = _line_at(x1, y1, x2, y2, x_end)
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


def _halo_line(ax, xs, ys, color, *, lw=2.0, ls="-", z=6):
    ax.plot(
        xs,
        ys,
        color=_HALO,
        linewidth=lw + 2.4,
        linestyle="-",
        zorder=z,
        solid_capstyle="round",
        solid_joinstyle="round",
        alpha=0.95,
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
) -> None:
    """點釘原位；虛線拉到空白處再寫字，盒子不准蓋 K。"""
    ax.annotate(
        str(text),
        xy=(float(x), float(y)),
        xytext=(float(tx), float(ty)),
        color=color,
        fontproperties=_fp(size, "bold"),
        ha=ha,
        va=va,
        zorder=12,
        annotation_clip=False,
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
            shrinkB=4,
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
    for note, tx in zip(ordered, txs):
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


def _place_right_notes(
    ax,
    notes: Sequence[Dict[str, Any]],
    *,
    x_text: float,
    ymin: float,
    ymax: float,
    min_gap: float,
) -> None:
    """演算區右側空白：虛線拉到右溝，字錯開，不壓延伸線。"""
    if not notes:
        return
    lo = ymin + min_gap * 0.4
    hi = ymax - min_gap * 0.4
    tys = _spread_ys_around(
        [float(n.get("y") or 0) for n in notes],
        [],
        min_gap,
        lo=lo,
        hi=hi,
    )
    for note, ty in zip(notes, tys):
        _leader_note(
            ax,
            float(note.get("x") or 0),
            float(note.get("y") or 0),
            str(note.get("text") or ""),
            str(note.get("color") or _TEXT),
            tx=x_text,
            ty=ty,
            size=int(note.get("size") or 11),
            ha="left",
            va="center",
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


# 個股長軸縮圖：表頭右側專用帶，不准 inset 蓋 K、不准蓋開高低量。
_STOCK_LOCATOR_RECT = (0.70, 0.695, 0.27, 0.155)


def _ymd8(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def paint_locator_inset(
    fig,
    bars: Sequence[Dict[str, Any]],
    *,
    win_from: str = "",
    win_to: str = "",
    rect: Tuple[float, float, float, float] = (0.68, 0.735, 0.30, 0.22),
    title: str = "長軸定位　橙框＝大圖這段",
    ax=None,
) -> bool:
    """預售屋配置圖那種整棟縮圖：長時間軸小 K，標出大圖落在哪一段。"""
    from decision_card_signals import candle_up_taiwan

    rows = []
    for r in bars or []:
        try:
            if float(r.get("close") or 0) > 0:
                rows.append(r)
        except (TypeError, ValueError):
            continue
    if len(rows) < 24:
        return False
    wf, wt = _ymd8(win_from), _ymd8(win_to)
    i0 = i1 = None
    for i, r in enumerate(rows):
        d = _ymd8(r.get("date"))
        if wf and d >= wf and i0 is None:
            i0 = i
        if wt and d <= wt:
            i1 = i
    if i0 is None:
        i0 = max(0, len(rows) - 90)
    if i1 is None:
        i1 = len(rows) - 1
    if i1 < i0:
        i0, i1 = i1, i0
    if ax is None:
        if fig is None:
            return False
        ax = fig.add_axes([rect[0], rect[1], rect[2], rect[3]], zorder=24)
    ax.set_facecolor("#ffffff")
    ax.patch.set_alpha(1.0)
    for sp in ax.spines.values():
        sp.set_color("#ef6c00")
        sp.set_linewidth(1.4)
    m = len(rows)
    opens = [float(r.get("open") or r.get("close") or 0) for r in rows]
    highs = [float(r.get("high") or r.get("close") or 0) for r in rows]
    lows = [float(r.get("low") or r.get("close") or 0) for r in rows]
    closes = [float(r.get("close") or 0) for r in rows]
    lo_min = min(lows)
    hi_max = max(highs)
    pad = (hi_max - lo_min) * 0.08 or 1.0
    ax.axvspan(
        i0 - 0.6,
        i1 + 0.6,
        facecolor="#ffe082",
        edgecolor="#ef6c00",
        linewidth=1.35,
        alpha=0.58,
        zorder=1,
    )
    w = 0.72 if m <= 200 else (0.58 if m <= 400 else 0.42)
    lw = 0.7 if m <= 200 else 0.4
    for i in range(m):
        prev_c = closes[i - 1] if i else None
        up = candle_up_taiwan(closes[i], prev_c, opens[i])
        c = _UP if up else _DN
        ax.vlines(i, lows[i], highs[i], color=c, linewidth=lw, zorder=3)
        body = max(abs(closes[i] - opens[i]), (hi_max - lo_min) * 0.0012)
        ax.add_patch(
            patches.Rectangle(
                (i - w / 2, min(opens[i], closes[i])),
                w,
                body,
                facecolor=c,
                edgecolor=c,
                linewidth=0.12,
                zorder=3,
            )
        )
    ax.scatter(
        [m - 1],
        [closes[-1]],
        s=22,
        color="#ef6c00",
        zorder=5,
        edgecolors="#ffffff",
        linewidths=0.5,
    )
    ax.set_xlim(-0.8, m - 0.2)
    ax.set_ylim(lo_min - pad, hi_max + pad)
    ax.set_yticks([])
    ax.tick_params(left=False, labelleft=False, length=2, labelsize=7, colors="#546e7a")
    d0 = _ymd8(rows[0].get("date"))
    d1 = _ymd8(rows[-1].get("date"))
    xt = [0, m - 1]
    xl = [
        f"{d0[:4]}/{int(d0[4:6])}" if d0 else "",
        f"{d1[:4]}/{int(d1[4:6])}" if d1 else "今",
    ]
    ax.set_xticks(xt)
    ax.set_xticklabels(xl, fontproperties=_fp(7, "bold"))
    ax.set_title(title, fontproperties=_fp(8, "bold"), color="#e65100", loc="left", pad=2.5)
    return True


def _ow(text: str, size: float = 11) -> float:
    """overlay 0–100 大約字寬。只拿來排晶片，不拿來截字。"""
    n = 0.0
    for ch in str(text or ""):
        n += 1.0 if ord(ch) > 0x2E80 else 0.55
    return n * (float(size) / 11.0) * 1.08 + 0.15


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


def header_banner_lines(glance: Optional[Dict[str, str]] = None) -> List[str]:
    """圖上頭三顆短句，整句畫完，不准截成…。"""
    g = glance or {}
    out: List[str] = []
    for key in ("nest", "field", "leader"):
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
    """右上角現價／收盤。pytest 不打外網；沒即時就用最後官方收。"""
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
    out.update(
        {
            "is_live": True,
            "label": "現價",
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


def _paint_nameplate(ax, plate: Dict[str, str], *, x: float = 4.15, y: float = 96.35) -> None:
    sid = str(plate.get("sid") or "")
    name = str(plate.get("name") or "")
    title = f"{sid} {name}".strip() or "官方日K"
    ax.text(
        x,
        y,
        title,
        color=_TEXT,
        fontproperties=_fp(17, "bold"),
        va="center",
        ha="left",
        zorder=22,
    )
    cx = x + _ow(title, 17) + 1.35
    industry = str(plate.get("industry") or "").strip()
    if industry:
        cx = _draw_chip(
            ax, cx, y, industry, fc="#eef3f8", ec="#607d8b", tc="#37474f", size=10
        )
    if str(plate.get("leader") or "").strip() == "龍頭":
        _draw_chip(ax, cx, y, "龍頭", fc="#ef6c00", ec="#e65100", tc="#ffffff", size=10)


def _paint_spot(ax, quote: Dict[str, Any], *, x: float = 97.6, y: float = 96.35) -> None:
    close = quote.get("close")
    if close is None:
        return
    from decision_card_signals import candle_up_taiwan
    from wayne_navigator import _draw_mini_candle

    prev = quote.get("prev")
    up = candle_up_taiwan(close, prev, quote.get("open"))
    color = _UP if up else _DN
    label = str(quote.get("label") or "收盤")
    px = _px(close)
    ax.text(
        x,
        y,
        px,
        color=color,
        fontproperties=_fp(22, "bold"),
        va="center",
        ha="right",
        zorder=22,
    )
    lab_x = x - _ow(px, 22) - 0.55
    ax.text(
        lab_x,
        y,
        label,
        color="#546e7a",
        fontproperties=_fp(11, "bold"),
        va="center",
        ha="right",
        zorder=22,
    )
    o, hi, lo = quote.get("open"), quote.get("high"), quote.get("low")
    try:
        ohlc_ok = all(float(v) > 0 for v in (o, hi, lo, close))
    except (TypeError, ValueError):
        ohlc_ok = False
    if ohlc_ok:
        cw, ch = 2.55, 4.8
        candle_right = lab_x - _ow(label, 11) - 0.9
        _draw_mini_candle(
            ax,
            candle_right - cw,
            y - ch * 0.5,
            cw,
            ch,
            float(o),
            float(hi),
            float(lo),
            float(close),
            prev,
        )
        ax.text(
            candle_right - cw - 0.35,
            y,
            "今K",
            color="#546e7a",
            fontproperties=_fp(8, "bold"),
            va="center",
            ha="right",
            zorder=22,
        )
    try:
        from tg_layout import format_move_plain

        move = format_move_plain(quote.get("change"), quote.get("pct"))
    except Exception:
        move = ""
    if move and move != "—":
        ax.text(
            x,
            y - 3.15,
            "較昨日　" + move,
            color=color,
            fontproperties=_fp(12, "bold"),
            va="center",
            ha="right",
            zorder=22,
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
    from decision_card_signals import candle_up_taiwan

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(14.8, 10.2),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.45, 1.45), hspace=0.048),
        facecolor=_BG,
    )
    ax1.set_facecolor(_PANEL)
    ax2.set_facecolor(_PANEL)
    ax1.set_ylim(ymin, ymax)
    x_gutter = n + _FUTURE + 1.55
    x_right = n + _FUTURE + 9.6
    ax1.set_xlim(-0.55, x_right)
    ax1.axvspan(n - 0.45, n + _FUTURE + 0.55, facecolor=_FUTURE_BG, edgecolor="none", zorder=0)
    ax1.axvline(n - 0.45, color="#ffcc80", linewidth=1.15, linestyle=":", zorder=2)
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
    prev_bar = _bar_ohlc(work[-2]) if len(work) >= 2 else {}
    spike_bar = info.get("spike_bar") or {}
    plate = dict(plate or stock_nameplate(sid, name, db_path))
    if not plate.get("sid"):
        plate["sid"] = sid
    if not plate.get("name"):
        plate["name"] = name
    quote = dict(quote or _spot_quote(sid, last_bar, prev_bar, db_path))
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
        w = 0.58 if i == spike_i else 0.46
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
    band_hi: List[Dict[str, Any]] = []
    band_lo: List[Dict[str, Any]] = []
    right_notes: List[Dict[str, Any]] = []
    if spike_hi:
        ax1.axhline(spike_hi, color=_PRESS, linewidth=1.55, zorder=4, alpha=0.92)
        right_notes.append(
            {"x": float(n - 1), "y": spike_hi, "text": f"壓 {_px(spike_hi)}", "color": _PRESS, "size": 12}
        )
    if spike_lo:
        ax1.axhline(spike_lo, color=_HOLD, linewidth=1.55, zorder=4, alpha=0.92)
        right_notes.append(
            {"x": float(n - 1), "y": spike_lo, "text": f"撐 {_px(spike_lo)}", "color": _HOLD, "size": 12}
        )
    last_c = float(last_bar.get("close") or 0)
    if 0 <= spike_i < n:
        ax1.axvline(spike_i, color="#90a4ae", linewidth=1.05, linestyle="--", zorder=2)
    down_pts = info.get("down_pts")
    up_pts = info.get("up_pts")
    x_fut = n - 1 + _FUTURE
    if down_pts:
        (x1, y1, d1), (x2, y2, d2) = down_pts
        y_now = _line_at(x1, y1, x2, y2, float(n - 1))
        y_end = _line_at(x1, y1, x2, y2, x_fut)
        _halo_line(ax1, [x1, n - 1], [y1, y_now], _DOWN_TRACK, lw=1.7, ls="-", z=5)
        _halo_line(
            ax1, [n - 1, x_fut], [y_now, y_end], _DOWN_TRACK, lw=1.7, ls=(0, (4, 2.2)), z=5
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
            {"x": float(x1), "y": float(y1), "text": f"{_md(d1)}高{_px(y1)}", "color": _DOWN_TRACK, "size": 10}
        )
        if abs(y2 - (spike_hi or y2)) / span > 0.05 or x2 < n - 6:
            band_hi.append(
                {"x": float(x2), "y": float(y2), "text": f"{_md(d2)}高{_px(y2)}", "color": _DOWN_TRACK, "size": 10}
            )
        right_notes.append(
            {"x": float(x_fut), "y": float(y_end), "text": f"連點延長 {_px(y_end)}", "color": _DOWN_TRACK, "size": 10}
        )
    if up_pts:
        (x1, y1, d1), (x2, y2, d2) = up_pts
        y_now = _line_at(x1, y1, x2, y2, float(n - 1))
        y_end = _line_at(x1, y1, x2, y2, x_fut)
        _halo_line(ax1, [x1, n - 1], [y1, y_now], _UP_TRACK, lw=1.7, ls="-", z=5)
        _halo_line(
            ax1, [n - 1, x_fut], [y_now, y_end], _UP_TRACK, lw=1.7, ls=(0, (4, 2.2)), z=5
        )
        ax1.scatter(
            [x1, x2],
            [y1, y2],
            color=_UP_TRACK,
            s=42,
            zorder=6,
            edgecolors="white",
            linewidths=0.8,
        )
        band_lo.append(
            {"x": float(x1), "y": float(y1), "text": f"{_md(d1)}低{_px(y1)}", "color": _UP_TRACK, "size": 10}
        )
        if abs(y2 - (spike_lo or y2)) / span > 0.05 or x2 < n - 6:
            band_lo.append(
                {"x": float(x2), "y": float(y2), "text": f"{_md(d2)}低{_px(y2)}", "color": _UP_TRACK, "size": 10}
            )
        right_notes.append(
            {"x": float(x_fut), "y": float(y_end), "text": f"連點延長 {_px(y_end)}", "color": _UP_TRACK, "size": 10}
        )
    path = list(proj.get("path") or [])
    if len(path) >= 2:
        _halo_line(
            ax1,
            [p[0] for p in path],
            [p[1] for p in path],
            _PROJECT,
            lw=2.2,
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
            [n - 1, x_fut],
            [last_c or closes[-1], fy],
            _FORK,
            lw=1.15,
            ls=(0, (2, 2.5)),
            z=4,
        )
    _place_band_notes(ax1, band_hi, ty=y_top, x_lo=0.4, x_hi=max(n - 2.0, 2.0), min_dx=7.2)
    _place_band_notes(ax1, band_lo, ty=y_bot, x_lo=0.4, x_hi=max(n - 2.0, 2.0), min_dx=7.2)
    _place_right_notes(
        ax1,
        right_notes,
        x_text=x_gutter,
        ymin=ymin,
        ymax=ymax,
        min_gap=span * 0.055,
    )
    ax1.text(
        n + _FUTURE * 0.45,
        ymin + span * 0.012,
        "演算區（不是保證）",
        color="#546e7a",
        fontproperties=_fp(10, "bold"),
        ha="center",
        va="bottom",
        zorder=8,
    )
    mark = ""
    mc = _TEXT
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
    banner_bits = header_banner_lines(glance)
    ov = fig.add_axes([0, 0, 1, 1], facecolor="none", zorder=12)
    ov.set_xlim(0, 100)
    ov.set_ylim(0, 100)
    ov.axis("off")
    ov.patch.set_alpha(0)
    ov.set_navigate(False)
    _paint_nameplate(ov, plate)
    _paint_spot(ov, quote)
    ov.text(
        4.15,
        92.35,
        f"最近收盤 {_ymd_full(last_bar.get('date'))}",
        color=_TEXT,
        fontproperties=_fp(12, "bold"),
        va="center",
        ha="left",
    )
    ov.text(
        4.15,
        89.7,
        (
            f"開 {_px(last_bar.get('open'))}　高 {_px(last_bar.get('high'))}　"
            f"低 {_px(last_bar.get('low'))}　收 {_px(last_bar.get('close'))}　"
            f"量 {_vol(last_bar.get('volume'))}"
        ),
        color=_TEXT,
        fontproperties=_fp(12, "bold"),
        va="center",
        ha="left",
    )
    ov.text(
        4.15,
        87.05,
        (
            f"爆大量日 {_ymd_full(spike_date)}　高 {_px(spike_hi)}＝壓　低 {_px(spike_lo)}＝撐　"
            f"量 {_vol(spike_bar.get('volume'))}"
        ),
        color=_PRESS,
        fontproperties=_fp(12, "bold"),
        va="center",
        ha="left",
    )
    ov.text(
        4.15,
        84.5,
        "不是15分、不是介紹圖／決策卡",
        color="#546e7a",
        fontproperties=_fp(11, "bold"),
        va="center",
        ha="left",
    )
    chip_x, chip_y = 4.15, 81.7
    if mark:
        chip_x = _draw_chip(ov, chip_x, chip_y, mark, fc="#ffffff", ec=mc, tc=mc, size=10)
        chip_x, chip_y = 4.15, 78.6
    for bit in banner_bits:
        need = _ow(f" {bit} ", 10) + 1.2
        if chip_x > 4.2 and chip_x + need > 64:
            if chip_y - 3.05 < 73:
                break
            chip_x = 4.15
            chip_y -= 3.05
        chip_x = _draw_chip(
            ov, chip_x, chip_y, bit, fc="#f4f6f8", ec="#90a4ae", tc="#37474f", size=10
        )
    if len(rows) >= n + 16:
        paint_locator_inset(
            fig,
            rows,
            win_from=str(work[0].get("date") or ""),
            win_to=str(work[-1].get("date") or ""),
            rect=_STOCK_LOCATOR_RECT,
            title="長軸定位　橙框＝大圖這段",
        )
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID, zorder=1)
    ax1.yaxis.tick_left()
    ax1.yaxis.set_label_position("left")
    ax1.tick_params(labelsize=11, left=True, right=False, bottom=False, labelbottom=False, length=5, width=0.8)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(11, "bold"))
    vol_colors = [_SPIKE_VOL if i == spike_i else (_UP if candle_up[i] else _DN) for i in range(n)]
    ax2.bar(xs, vols, color=vol_colors, width=0.68, zorder=3, edgecolor="#ffffff", linewidth=0.2)
    vmax = max(vols) if vols else 1.0
    ax2.set_ylim(0, vmax * 1.45)
    if 0 <= spike_i < n and vols[spike_i]:
        vol_tx = min(n - 1.2, spike_i + 5.2) if spike_i < n - 6 else max(0.8, spike_i - 5.2)
        _leader_note(
            ax2,
            float(spike_i),
            float(vols[spike_i]),
            f"這根＝爆大量　{_vol(vols[spike_i])}",
            _TEXT,
            tx=vol_tx,
            ty=vmax * 1.22,
            size=11,
            ha="left" if vol_tx >= spike_i else "right",
            va="center",
        )
    ax2.set_ylabel("日成交量（張）", fontproperties=_fp(11, "bold"), color=_TEXT)
    ax2.yaxis.tick_left()
    ax2.yaxis.set_label_position("left")
    ax2.tick_params(labelsize=11, left=True, right=False, length=5, width=0.8)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{int(round(v)):,}"))
    for lab in ax2.get_yticklabels():
        lab.set_fontproperties(_fp(10, "bold"))
    ax2.set_xlim(-0.55, x_right)
    ax2.axvspan(n - 0.45, n + _FUTURE + 0.35, facecolor=_FUTURE_BG, edgecolor="none", zorder=0)
    ax2.axvline(n - 0.45, color="#b0bec5", linewidth=1.0, linestyle=":", zorder=2)
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
    fig.subplots_adjust(left=0.07, right=0.80, top=0.69, bottom=0.072)
    fig.savefig(save_path, dpi=NAV_CHART_DPI, facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path if os.path.isfile(save_path) else ""


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
) -> str:
    head = f"{sid} {name}".strip()
    plate = plate or {}
    extras = "　".join(
        x for x in (str(plate.get("industry") or "").strip(), str(plate.get("leader") or "").strip()) if x
    )
    if extras:
        head = f"{head}　{extras}".strip()
    lines = [
        f"{head}　官方日K量先價行（不是15分、不是介紹圖／決策卡）".strip(),
    ]
    g = glance or {}
    if g.get("nest"):
        lines.append(g["nest"])
    field_lead = " ".join(x for x in (g.get("field"), g.get("leader")) if x)
    if field_lead:
        lines.append(field_lead)
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
        elif info.get("under_support"):
            tape += "收在爆大量日低之下，這次量價先放棄。"
        elif info.get("over_press"):
            tape += "已過爆大量日高，比較像半山腰。"
        lines.append(tape)
    proj = info.get("project") or {}
    if proj.get("label"):
        lines.append("圖上演算：" + str(proj.get("label")))
    if g.get("hold"):
        lines.append(g["hold"])
    if g.get("doubt"):
        lines.append(g["doubt"])
    else:
        lines.append("沒疊滿就不講死。")
    lines.append("縮圖＝更長時間軸，橙框是大圖這段。連點只是輔助。不夠兩點就不畫。個股不數 5／9 段。這不是買訊。")
    lines.append("延伸線已建檔，官方柱走完再對質。不是保證。")
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
    bars = load_bars(db_path, sid, n=280) if db_path and sid else []
    if not bars:
        return {"ok": False, "path": "", "caption": ""}
    nm = name or str(bars[-1].get("stock_name") or sid)
    info = analyze_structure(bars[-_BARS:])
    fired = None
    q = (ask or "").strip()
    if q:
        try:
            from biaoke_chain import fire_chain

            fired = fire_chain(db_path, q, uid=uid)
        except Exception:
            logger.debug("飆大結構圖神經元略過", exc_info=True)
            fired = None
    glance = neuron_glance(fired)
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
        "caption": chart_caption(info, sid=sid, name=nm, glance=glance, plate=plate),
        "sid": sid,
        "name": nm,
        "wash": bool(info.get("wash")),
        "distribution": bool(info.get("distribution")),
        "project": dict(info.get("project") or {}),
        "notes": list(info.get("notes") or []),
        "glance": glance,
    }
