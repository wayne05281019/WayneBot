#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最近重點標的樣張：由尾回推五波＋前方大量壓力區＋季EPS／月營收。

觀察用，非買訊。滾動近 WIN 根：新日進、左邊掉；右側預留空位給往後日子。
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

from biaoke_next_support import find_secondary_vol_zone
from scripts.biaoke_tail_back_five_wave import analyze_bars


def drop_measure_triangle_verts(
    j_hi: float, y_hi: float, j_lo: float, y_lo: float
) -> Optional[List[Tuple[float, float]]]:
    """林友銘款跌幅量測：左高峰 → 右同高 → 右低谷（淺綠倒三角）。

    觀察用，非買訊。j_lo 須在 j_hi 右側且 y_hi > y_lo。
    """
    try:
        x0, y0 = float(j_hi), float(y_hi)
        x1, y1 = float(j_lo), float(y_lo)
    except (TypeError, ValueError):
        return None
    if not (x1 > x0 and y0 > y1):
        return None
    return [(x0, y0), (x1, y0), (x1, y1)]


def drop_measure_points(y_hi: float, y_lo: float) -> Optional[float]:
    """跌幅點差（寫進三角內）。"""
    try:
        d = float(y_hi) - float(y_lo)
    except (TypeError, ValueError):
        return None
    return d if d > 0 else None

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "wayne_market.db"
# 固定右錨滾動窗；右側略留 FUTURE_PAD（明天進日＋價標左中右三欄）
# 價標貼近末根K：TAG_NEAR_PAD 起算，左／中／右錯開，不准整排遠掛最右
# LINE_END_PAD＝水平線停在末根K旁（標籤接在線外）
WIN = 130
FUTURE_PAD = 8
LABEL_RIGHT_EXTRA = 14
LINE_END_PAD = 0.8
# 壓帶上下緣：緊貼末根K右側（使用者紅框）；反彈／四浪高再往右兩欄，中間空位留給壓帶
ZONE_NEAR_PAD = 3.0
FIB_NEAR_PAD = 18.0  # 反彈欄起點：末根K→壓帶→空→反彈，肉眼分得清
TAG_COL_GAP = 14.0
NEAR_PRICE_FRAC = 0.022
# 相容舊測試名
TAG_NEAR_PAD = FIB_NEAR_PAD
ZONE_TAG_COL = 0  # 壓帶單獨座標系，不用與反彈共欄
# 五波最底往上反彈參考（觀察非買訊）；對齊本庫／林口播常用回撤率
REBOUND_FIB_RATIOS = (0.382, 0.5, 0.618)


def rebound_fib_from_wave_bottom(
    high: float, low: float, *, ratios: tuple[float, ...] = REBOUND_FIB_RATIOS
) -> list[tuple[float, float]]:
    """自這一波最底往上：低＋(高−低)×比率。回 [(比率, 價), ...]。"""
    try:
        hi, lo = float(high), float(low)
    except (TypeError, ValueError):
        return []
    span = hi - lo
    if span <= 0:
        return []
    out: list[tuple[float, float]] = []
    for r in ratios:
        try:
            rr = float(r)
        except (TypeError, ValueError):
            continue
        if rr <= 0:
            continue
        out.append((rr, lo + span * rr))
    return out


# ②–④ 趨勢線：色／粗度與紫浪線分開；左右各多伸一截
WAVE24_LINE_COLOR = "#0f766e"  # 青石綠，避開紫浪／紅四浪／綠反彈
WAVE24_LINE_LW = 0.85
WAVE24_EXTEND_LEFT = 4.0
WAVE24_EXTEND_RIGHT = 5.0


def wave24_descend_line(
    j2: float,
    y2: float,
    j4: float,
    y4: float,
    j_end: float,
    *,
    x_clip_left: float = 0.0,
    x_clip_right: Optional[float] = None,
    extend_left: float = WAVE24_EXTEND_LEFT,
    extend_right: float = WAVE24_EXTEND_RIGHT,
) -> Optional[Tuple[float, float, float, float]]:
    """②–④ 下降趨勢線：自②左側多伸、過末日再多伸。回 (x0, y0, x1, y1)。

    觀察用，非買訊。極短實線＋小空格由呼叫端負責。
    """
    try:
        x2, p2 = float(j2), float(y2)
        x4, p4 = float(j4), float(y4)
        xe = float(j_end)
        xl = float(x_clip_left)
        xr = float(x_clip_right) if x_clip_right is not None else xe + float(extend_right)
        el = float(extend_left)
        er = float(extend_right)
    except (TypeError, ValueError):
        return None
    if x4 <= x2:
        return None
    slope = (p4 - p2) / (x4 - x2)
    x0 = max(x2 - el, xl)
    x1 = min(xe + er, xr)
    if x1 <= x0:
        return None
    y0 = p2 + slope * (x0 - x2)
    y1 = p2 + slope * (x1 - x2)
    return (x0, y0, x1, y1)


def _cjk_prop():
    for p in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ):
        if Path(p).exists():
            fm.fontManager.addfont(p)
            prop = fm.FontProperties(fname=p)
            plt.rcParams["font.family"] = prop.get_name()
            return prop
    return None


def _ymd(d: Any) -> str:
    s = str(d or "").replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _rev_yi(v: float) -> str:
    """月營收庫內＝千元 → 億。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{x / 100000:.2f}"


def _dodge_right_ys(
    prices: List[float],
    *,
    y_lo: float,
    y_hi: float,
    min_gap_frac: float = 0.055,
    near_frac: float = NEAR_PRICE_FRAC,
    forbid_cols: Optional[set[int]] = None,
) -> Tuple[List[float], List[int]]:
    """價標顯示 Y＋左中右欄：高→低輪流可用欄，近價同簇也錯開，不准互壓。

    回傳 (placed_ys, cols)；cols[i]∈可用欄＝左／中／右。
    forbid_cols：例如壓帶佔中欄時，反彈標不准再踩中欄。
    """
    if not prices:
        return [], []
    span = max(y_hi - y_lo, 1.0)
    near = max(span * float(near_frac), span * 0.004)
    gap = span * float(min_gap_frac)
    blocked = set(forbid_cols or ())
    allowed = [c for c in (0, 1, 2) if c not in blocked] or [0, 1, 2]
    order = sorted(range(len(prices)), key=lambda i: prices[i], reverse=True)
    # 全域在可用欄輪流（垂直相鄰不在同一條直線）
    cols = [0] * len(prices)
    for rank, i in enumerate(order):
        cols[i] = allowed[rank % len(allowed)]
    # 近價分簇：同簇再強制不同欄
    clusters: List[List[int]] = []
    for i in order:
        if not clusters:
            clusters.append([i])
            continue
        prev = clusters[-1][-1]
        if abs(float(prices[i]) - float(prices[prev])) < near:
            clusters[-1].append(i)
        else:
            clusters.append([i])
    # 只有近價多顆簇才重派欄；單顆簇保留全域輪流（否則全被蓋回 0）
    for cl in clusters:
        if len(cl) < 2:
            continue
        used: set[int] = set()
        for k, i in enumerate(cl):
            c = allowed[k % len(allowed)]
            spins = 0
            while c in used and spins < len(allowed):
                c = allowed[(allowed.index(c) + 1) % len(allowed)]
                spins += 1
            cols[i] = c
            used.add(c)
    placed = [float(p) for p in prices]
    # 同欄才做 Y dodge（不同欄可同高）
    for c in (0, 1, 2):
        idxs = [i for i in order if cols[i] == c]
        last = y_hi + gap
        for i in idxs:
            y = min(float(prices[i]), last - gap)
            placed[i] = y
            last = y
        # 邊界推回
        if not idxs:
            continue
        vals = [placed[i] for i in idxs]
        mn, mx = min(vals), max(vals)
        if mn < y_lo:
            sh = y_lo - mn
            for i in idxs:
                placed[i] += sh
            mx = max(placed[i] for i in idxs)
        if mx > y_hi:
            sh = mx - y_hi
            for i in idxs:
                placed[i] -= sh
            last = y_hi + gap
            for i in idxs:
                y = min(placed[i], last - gap)
                placed[i] = max(y, y_lo)
                last = placed[i]
    return placed, cols


def _paint_right_price_tags(
    ax,
    *,
    x_anchor: float,
    tags: List[Dict[str, Any]],
    y_lo: float,
    y_hi: float,
    prop,
    x_text: float | None = None,
    forbid_cols: Optional[set[int]] = None,
) -> None:
    """價標貼近末根K：左／中／右錯開吃滿空位，短截對齊真價。

    x_anchor＝末根K；x_text＝第一欄起點（預設 anchor+TAG_NEAR_PAD）。
    forbid_cols：壓帶中欄紅框保留時傳入。
    """
    if not tags:
        return
    prices = [float(t["price"]) for t in tags]
    dys, cols = _dodge_right_ys(
        prices,
        y_lo=y_lo,
        y_hi=y_hi,
        min_gap_frac=0.055,
        forbid_cols=forbid_cols,
    )
    base_xt = float(
        x_text if x_text is not None else (float(x_anchor) + TAG_NEAR_PAD)
    )
    stub = 2.2
    span = max(y_hi - y_lo, 1.0)
    for t, dy, true_y, col in zip(tags, dys, prices, cols):
        xt = base_xt + TAG_COL_GAP * float(col)
        # 從末根K旁拉到該欄短截，線短可讀、不飛到圖外
        ax.plot(
            [float(x_anchor) + 0.35, xt - 0.4],
            [true_y, true_y],
            color=t.get("edge", "#94a3b8"),
            lw=0.85,
            alpha=0.65,
            solid_capstyle="butt",
            zorder=12,
            clip_on=False,
        )
        ax.plot(
            [xt - stub, xt - 0.35],
            [true_y, true_y],
            color=t.get("edge", "#94a3b8"),
            lw=1.15,
            solid_capstyle="butt",
            zorder=13,
            clip_on=False,
        )
        if abs(dy - true_y) > span * 0.008:
            ax.plot(
                [xt - 0.35, xt - 0.35],
                [true_y, dy],
                color=t.get("edge", "#94a3b8"),
                lw=0.7,
                alpha=0.7,
                zorder=13,
                clip_on=False,
            )
        ax.text(
            xt,
            dy,
            str(t["text"]),
            color=t.get("color", "#111"),
            fontsize=float(t.get("fontsize", 9.5)),
            fontweight="bold",
            fontproperties=prop,
            va="center",
            ha="left",
            clip_on=False,
            zorder=14,
            bbox=dict(
                boxstyle="round,pad=0.18",
                facecolor=t.get("facecolor", "#fff"),
                edgecolor=t.get("edge", "#94a3b8"),
                alpha=0.97,
            ),
        )


def _eps_singles_cum(
    qi: List[Tuple[int, int, float]], year: int
) -> Tuple[Dict[int, float], Optional[float]]:
    """季報常為累計；拆成單季＋累計。"""
    by = {(int(y), int(s)): float(e) for y, s, e in qi if e is not None}
    q_raw = {s: by.get((year, s)) for s in (1, 2, 3)}
    singles: Dict[int, float] = {}
    cum: Optional[float] = None
    if q_raw.get(1) is None:
        return singles, cum
    singles[1] = float(q_raw[1])
    # 累計形：Q2≥Q1、Q3≥Q2
    if (
        q_raw.get(2) is not None
        and q_raw[2] >= q_raw[1] - 1e-9
        and (q_raw.get(3) is None or q_raw[3] >= q_raw[2] - 1e-9)
    ):
        singles[2] = float(q_raw[2]) - float(q_raw[1])
        if q_raw.get(3) is not None:
            singles[3] = float(q_raw[3]) - float(q_raw[2])
            cum = float(q_raw[3])
        else:
            cum = float(q_raw[2])
    else:
        if q_raw.get(2) is not None:
            singles[2] = float(q_raw[2])
        if q_raw.get(3) is not None:
            singles[3] = float(q_raw[3])
        cum = sum(singles.values()) if singles else None
    return singles, cum


def pick_forward_pressure_zone(
    bars: List[dict], close: float
) -> Optional[Dict[str, Any]]:
    """前方大量壓力：優先整帶在收盤上方（下緣＞收）；沒有再退回現價落區內的次大量。

    ``find_secondary_vol_zone`` 會優先回 prox_gap=0（現價落區內）；這裡把已看過的
    重疊日從序列拿掉再重算，直到出現下緣＞收的前方帶（API 只支援單日 exclude）。
    """
    inside_fallback: Optional[Dict[str, Any]] = None
    seen: set[str] = set()
    work = list(bars)
    for _ in range(16):
        z = find_secondary_vol_zone(
            work,
            direction="above",
            ref_hi=max(close * 0.999, 1e-9),
            close=close,
            lookback=180,
        )
        if not z:
            break
        d = _ymd(z.get("date"))
        if d and d in seen:
            break
        if d:
            seen.add(d)
        lo = float(z.get("low") or 0)
        hi = float(z.get("high") or 0)
        if lo > close + 1e-9:
            out = dict(z)
            out["zone_role"] = "forward"
            return out
        if inside_fallback is None and hi >= close - 1e-9:
            fb = dict(z)
            fb["zone_role"] = "inside"
            inside_fallback = fb
        if not d:
            break
        # 拿掉整日（含重疊帶），下一輪才能滾到真正前方
        work = [b for b in work if _ymd(b.get("date")) != d]
    return inside_fallback


# 右上三行字級樣式（figure pt）；話筒選定前可並渲對照
HEADER_STYLES: Dict[str, Dict[str, float]] = {
    "A": {"name": 16.0, "price": 28.0, "chg": 15.5, "k": 8.5, "name_gap": 0.003, "chg_pad": 0.007},
    "B": {"name": 15.0, "price": 20.0, "chg": 14.0, "k": 8.0, "name_gap": 0.004, "chg_pad": 0.006},
    "C": {"name": 13.0, "price": 32.0, "chg": 12.0, "k": 8.0, "name_gap": 0.002, "chg_pad": 0.008},
    "D": {"name": 18.0, "price": 24.0, "chg": 14.0, "k": 9.0, "name_gap": 0.003, "chg_pad": 0.006},
    "E": {"name": 14.0, "price": 22.0, "chg": 13.0, "k": 8.0, "name_gap": 0.002, "chg_pad": 0.005},
}
HEADER_STYLE_DEFAULT = "B"  # 2026-11-27 話筒選第二款


def paint(
    sid: str,
    out: Path,
    *,
    db_path: Path = DB,
    header_style: str = HEADER_STYLE_DEFAULT,
) -> Dict[str, Any]:
    prop = _cjk_prop()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = list(
        reversed(
            con.execute(
                "SELECT date,open,high,low,close,volume,stock_name FROM daily_quotes "
                "WHERE stock_id=? ORDER BY date DESC LIMIT 260",
                (sid,),
            ).fetchall()
        )
    )
    if len(rows) < 40:
        con.close()
        raise SystemExit(f"{sid}: not enough bars")
    bars = [
        {
            "date": str(d),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v),
            "name": str(n or sid),
        }
        for d, o, h, l, c, v, n in rows
    ]
    name = bars[-1]["name"] or sid
    uni = con.execute(
        "SELECT stock_name FROM stock_universe WHERE stock_id=?", (sid,)
    ).fetchone()
    if uni and uni[0]:
        name = str(uni[0])
    asof = _ymd(bars[-1]["date"])
    close = bars[-1]["close"]
    open_ = bars[-1]["open"]
    high = bars[-1]["high"]
    low = bars[-1]["low"]
    vol = bars[-1]["volume"]

    tb = analyze_bars(bars)
    pts = tb.five_points or []
    if not (tb.ok_five and len(pts) >= 6):
        con.close()
        raise SystemExit(f"{sid}: five-wave not ok — {tb.fail_reason_zh or tb.note_zh}")

    w4 = pts[4]
    ns = tb.new_start
    room = (w4.price - close) / close * 100.0

    qi = con.execute(
        "SELECT year,season,eps FROM quarterly_income WHERE stock_id=? "
        "ORDER BY year DESC, season DESC LIMIT 12",
        (sid,),
    ).fetchall()
    years = sorted({int(y) for y, s, e in qi}, reverse=True)
    year = years[0] if years else int(asof[:4])
    singles, cum = _eps_singles_cum(
        [(int(y), int(s), float(e)) for y, s, e in qi if e is not None], year
    )

    mr = con.execute(
        "SELECT yyyymm, revenue FROM monthly_revenue WHERE stock_id=? "
        "ORDER BY yyyymm DESC LIMIT 6",
        (sid,),
    ).fetchall()
    mr_y = [(m, r) for m, r in mr if str(m).startswith(str(year))]
    mr_show = mr_y[:1] if mr_y else []

    fine = con.execute(
        "SELECT chain FROM stock_fine_industry WHERE stock_id=?", (sid,)
    ).fetchone()
    ind_fine = (fine[0] if fine else "") or ""
    ind_main_row = con.execute(
        "SELECT industry FROM monthly_revenue WHERE stock_id=? ORDER BY yyyymm DESC LIMIT 1",
        (sid,),
    ).fetchone()
    ind_main = (ind_main_row[0] if ind_main_row else "") or ""

    zone = pick_forward_pressure_zone(bars, close)

    x0 = max(0, len(bars) - WIN)
    view = bars[x0:]

    def vi(abs_i: int) -> int:
        return abs_i - x0

    n = len(view)
    opens = [b["open"] for b in view]
    highs = [b["high"] for b in view]
    lows = [b["low"] for b in view]
    closes = [b["close"] for b in view]
    vols = [b["volume"] for b in view]
    dates = [_ymd(b["date"]) for b in view]

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(13.4, 9.2),
        gridspec_kw={"height_ratios": [3.4, 1.25]},
        sharex=True,
    )
    bg = "#f7f5f0"
    fig.patch.set_facecolor(bg)
    for a in (ax, axv):
        a.set_facecolor(bg)
        a.tick_params(colors="#333")
        for sp in a.spines.values():
            sp.set_color("#bbb")
        a.grid(True, color="#e6e2da", lw=0.6, zorder=0)

    # 水平線／色帶右端停在標籤 gutter 前，右側必須空
    _x_line_end = float(n - 1 + LINE_END_PAD)
    _x_left = -1.2

    zone_date = ""
    zone_vol = 0.0
    zone_role = ""
    if zone:
        lo, hi = float(zone["low"]), float(zone["high"])
        zone_date = str(zone.get("date") or "")
        zone_vol = float(zone.get("volume") or 0)
        zone_role = str(zone.get("zone_role") or "")
        band_lab = (
            "前方大量壓力區" if zone_role == "forward" else "大量區（現價落區內）"
        )
        # 壓力帶用灰藍，黃色留給「新起漲」；右緣數字稍後統一錯開
        ax.fill_between(
            [_x_left, _x_line_end],
            lo,
            hi,
            facecolor="#cbd5e1",
            alpha=0.45,
            zorder=1,
            label=band_lab,
        )
        ax.hlines(hi, _x_left, _x_line_end, color="#475569", ls="-", lw=1.45, alpha=0.95)
        ax.hlines(lo, _x_left, _x_line_end, color="#475569", ls="-", lw=1.45, alpha=0.95)
        # 壓帶上下緣標稍後掛左側；這裡只留帶與線

    yr = max(highs) - min(lows)
    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        col = "#d64545" if c >= o else "#2f9e6b"
        ax.vlines(i, l, h, color=col, lw=1.0, zorder=2)
        bh = max(abs(c - o), yr * 0.0015)
        ax.add_patch(
            Rectangle(
                (i - 0.38, min(o, c)), 0.76, bh, facecolor=col, edgecolor=col, zorder=3
            )
        )

    # 真用處：抓五波「最底」，用起→底段長×黃金切割標「反彈可能到哪」（觀察非買訊）
    # 不是秀 111／1795 點差裝飾；四浪高紅線仍保留對照
    wave_hi = float(pts[0].price)
    wave_lo = float(pts[-1].price)
    fib_lvls = rebound_fib_from_wave_bottom(wave_hi, wave_lo)
    j_bottom = vi(pts[-1].i)
    if fib_lvls:
        top618 = max(p for _, p in fib_lvls)
        if top618 > wave_lo:
            ax.fill_between(
                [_x_left, _x_line_end],
                wave_lo,
                top618,
                facecolor="#bbf7d0",
                alpha=0.14,
                zorder=0.8,
                label="淺綠＝反彈參考帶（至0.618）",
            )
        for _ratio, px in fib_lvls:
            ax.hlines(
                px,
                _x_left,
                _x_line_end,
                color="#059669",
                ls="--",
                lw=1.05,
                alpha=0.75,
                zorder=4,
            )
        if 0 <= j_bottom < n:
            ax.plot(
                [j_bottom],
                [wave_lo],
                marker="v",
                markersize=5.5,
                color="#047857",
                markeredgecolor="#064e3b",
                markeredgewidth=0.5,
                zorder=8,
                label=f"這一波最底 {wave_lo:g}",
            )

    # 先定 ylim，浪圈才能判斷貼底／貼頂，不准裁進量圖
    _extra_ys = [w4.price, wave_lo] + [p for _, p in fib_lvls]
    if zone:
        _extra_ys.extend([float(zone["high"]), float(zone["low"])])
    y_hi = max(highs + _extra_ys)
    y_lo = min(lows + [wave_lo])
    pad = (y_hi - y_lo) * 0.06
    ylim_lo = y_lo - pad * 1.85
    ylim_hi = y_hi + pad * 1.15
    ax.set_ylim(ylim_lo, ylim_hi)
    _span_y = max(ylim_hi - ylim_lo, 1.0)

    # 教法：紫細線＝五波下跌；圖內只留①～⑤圓圈（價只在最右）
    labels = ["起", "1", "2", "3", "4", "終"]
    vis_pts = []
    for k, p in enumerate(pts):
        j = vi(p.i)
        if 0 <= j < n:
            vis_pts.append((j, p.price, p.kind, labels[k]))
    if len(vis_pts) >= 2:
        xs_w = [t[0] for t in vis_pts]
        ys_w = [t[1] for t in vis_pts]
        ax.plot(
            xs_w,
            ys_w,
            color="#7c3aed",
            lw=1.45,
            zorder=7,
            solid_capstyle="round",
            label="紫細線＝五波下跌",
        )
        for j, price, kind, lab in vis_pts:
            ax.scatter(
                [j],
                [price],
                s=16,
                c="#7c3aed",
                zorder=9,
                edgecolors="#fff",
                lw=0.4,
            )
            wave_no = {"起": None, "終": "5"}.get(lab, lab)
            if wave_no is None:
                continue
            # 小圈貼近頂／底：高點略上、低點略下；貼底⑤改微左上防裁量圖
            near_bot = float(price) <= ylim_lo + _span_y * 0.12
            if lab in ("2", "4") or kind == "H":
                xytext = (0, 7)
            elif lab == "終" and near_bot:
                xytext = (-6, 8)
            elif kind == "L" or lab in ("1", "3", "終"):
                xytext = (0, -7)
            else:
                xytext = (0, -6)
            ax.annotate(
                str(wave_no if lab != "終" else "5"),
                xy=(j, price),
                xytext=xytext,
                textcoords="offset points",
                ha="center",
                va="center",
                color="#5b21b6",
                fontsize=7.2,
                fontweight="bold",
                fontproperties=prop,
                zorder=10,
                clip_on=False,
                bbox=dict(
                    boxstyle="circle,pad=0.12",
                    facecolor="#f5f3ff",
                    edgecolor="#7c3aed",
                    linewidth=0.9,
                    alpha=0.97,
                ),
            )

    ax.hlines(
        w4.price,
        _x_left,
        _x_line_end,
        color="#dc2626",
        ls="-",
        lw=1.7,
        alpha=0.92,
        label=f"次級四浪高 {w4.price:.0f}",
        zorder=5,
    )

    # ②–④ 下降趨勢線：細青石綠＋極短實線小空格；左右各多伸一截（觀察）
    if len(pts) >= 5:
        _w24 = wave24_descend_line(
            vi(pts[2].i),
            float(pts[2].price),
            vi(pts[4].i),
            float(pts[4].price),
            float(n - 1),
            x_clip_left=float(_x_left),
            x_clip_right=float(_x_line_end),
        )
        if _w24 is not None:
            _x0, _y0, _x1, _y1 = _w24
            (_ln24,) = ax.plot(
                [_x0, _x1],
                [_y0, _y1],
                color=WAVE24_LINE_COLOR,
                lw=WAVE24_LINE_LW,
                solid_capstyle="butt",
                solid_joinstyle="miter",
                zorder=8,
                label="②–④下降趨勢線（左右延伸）",
            )
            _ln24.set_dashes((2.2, 1.6))

    # 黃線＝五波走完後新起漲軌跡；字／大菱形一律不准蓋日K（字只進圖例）
    bounce_from = ns if ns is not None else (pts[-1] if pts else None)
    if bounce_from is not None:
        j = vi(bounce_from.i)
        if 0 <= j < n:
            ax.plot(
                [j, n - 1],
                [bounce_from.price, close],
                color="#ca8a04",
                lw=1.7,
                zorder=6,
                solid_capstyle="round",
                label="黃線＝新起漲",
            )
            ax.plot(
                [j, n - 1],
                [bounce_from.price, close],
                color="#facc15",
                lw=1.15,
                zorder=7,
                solid_capstyle="round",
            )
            # 起點只用線端小點（無菱形、無「新起漲」浮字）
            ax.plot(
                [j],
                [bounce_from.price],
                marker="o",
                markersize=4.5,
                color="#ca8a04",
                markeredgecolor="#a16207",
                markeredgewidth=0.6,
                zorder=7,
            )

    ax.hlines(
        close,
        _x_left,
        _x_line_end,
        color="#0f766e",
        ls=":",
        lw=1.15,
        alpha=0.75,
        zorder=5,
    )

    zone_i = None
    if zone_date:
        for i, d in enumerate(dates):
            if d == zone_date:
                zone_i = i
                break
        if zone_i is not None:
            # 來源日垂直虛線：價帶 ↔ 量柱對得上
            ax.axvline(zone_i, color="#ea580c", ls="--", lw=1.1, alpha=0.75, zorder=4)
            axv.axvline(zone_i, color="#ea580c", ls="--", lw=1.1, alpha=0.75, zorder=4)

    # 壓力來源日量柱：趨勢圖同款琥珀黃＋白邊，柱頂寫當日成交張數
    for i, (v, o, c) in enumerate(zip(vols, opens, closes)):
        if zone_i is not None and i == zone_i:
            axv.bar(
                i,
                v,
                width=0.82,
                color="#ffeb3b",
                edgecolor="#f59e0b",
                linewidth=1.15,
                alpha=1.0,
                zorder=3,
            )
        else:
            col = "#d64545" if c >= o else "#2f9e6b"
            axv.bar(i, v, width=0.72, color=col, alpha=0.72, zorder=2)

    vmax = max(vols) if vols else 1.0
    axv.set_ylim(0, vmax * 1.22)  # 柱頂張數標留空
    if zone_i is not None and float(vols[zone_i] or 0) > 0:
        md = f"{dates[zone_i][4:6]}/{dates[zone_i][6:8]}"
        axv.annotate(
            f"{vols[zone_i]:.0f}張\n{md}",
            xy=(float(zone_i), float(vols[zone_i])),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.4,
            fontweight="bold",
            fontproperties=prop,
            color="#7c2d12",
            zorder=9,
            clip_on=False,
        )
    # 量圖上方只留今日量（來源日張數已寫在琥珀柱頂）
    axv.text(
        0.0,
        1.16,
        f"今日 {vol:.0f} 張" + ("　｜　黃柱＝壓力來源日" if zone_i is not None else ""),
        transform=axv.transAxes,
        ha="left",
        va="bottom",
        color="#374151",
        fontsize=7.6,
        fontweight="bold",
        fontproperties=prop,
        bbox=dict(
            boxstyle="round,pad=0.2",
            facecolor="#fffbeb",
            edgecolor="#fbbf24",
            alpha=0.96,
        ),
        zorder=8,
        clip_on=False,
    )

    eps_bits = [f"Q{s} {singles[s]:.2f}" for s in (1, 2, 3) if s in singles]
    eps_line = "　".join(eps_bits) if eps_bits else "—"
    cum_s = f"{cum:.2f}" if cum is not None else "—"
    # 月營收：只寫已公告月；11／12 尚未＝明講，不跟季EPS混
    if mr_show:
        ym, rev = mr_show[0]
        ym = str(ym)
        mon = int(ym[4:6])
        have = {int(str(m)[4:6]) for m, _ in mr_y}
        miss = [m for m in (11, 12) if m not in have]
        miss_s = "、".join(f"{m}月" for m in miss) + "尚未" if miss else "已公告至最新月"
        mr_line = f"月營收 {year}年{mon}月 {_rev_yi(float(rev))}億（{miss_s}）"
    else:
        mr_line = f"月營收 {year}年 —（11、12月尚未）"

    fund = (
        f"產業 {ind_main or '—'}｜{ind_fine or '—'}\n"
        f"前三季單季EPS　{eps_line}\n"
        f"前三季累計　{cum_s} 元（無月EPS官方）\n"
        f"{mr_line}"
    )
    # 基本面盒改價量夾縫左格（與線段圖例並排）；這裡不壓日K

    # 距四浪高％掛價圖內右上（表頭股名價改到 figure 右上紅框，這裡避開）
    ax.text(
        0.995,
        0.92,
        f"距四浪高還有 {room:.1f}%",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9.0,
        fontweight="bold",
        fontproperties=prop,
        color="#b91c1c",
        bbox=dict(
            boxstyle="round,pad=0.24",
            facecolor="#fee2e2",
            edgecolor="#f87171",
            alpha=0.95,
        ),
        zorder=15,
        clip_on=False,
    )

    asof_face = f"{asof[0:4]}/{asof[4:6]}/{asof[6:8]} 盤後"
    ohlc_line = f"開 {open_:.0f}　高 {high:.0f}　低 {low:.0f}　收 {close:.0f}　量 {vol:.0f} 張"
    # 左上瘦帶：日期／觀察＋OHLC；長說明改貼主圖頂，股名價在右上
    sub1 = f"{asof_face}｜觀察非買訊"
    sub2 = ohlc_line
    sub3 = (
        f"紫細線＝五波下跌　②–④下降趨勢線延伸至末日　最底＋反彈0.382/0.5/0.618（觀察）　黃線＝新起漲｜"
        f"滾動近{WIN}根（新日進、左邊掉；右留空給價標）"
    )
    ax.set_title("")  # 股名價改 figure 右上，不准再置中標題搶位
    # 圖例改放到價／量夾縫（附圖紅框），不准壓左上日K
    ax.set_ylabel("價（元）", fontproperties=prop)
    axv.set_ylabel("成交量（張）", fontproperties=prop)

    # 幾何：末根K → 空 → 反彈／四浪高（壓帶標改左側）
    _x_zone = float(n - 1 + ZONE_NEAR_PAD)  # 保留常數相容；標籤已改左側
    _x_text = float(n - 1 + FIB_NEAR_PAD)
    _xlim_right = _x_text + TAG_COL_GAP * 1.0 + float(LABEL_RIGHT_EXTRA)
    ax.set_xlim(_x_left, _xlim_right)
    if zone:
        _zlo, _zhi = float(zone["low"]), float(zone["high"])
        # 壓上緣／壓下緣掛灰帶左側（不准跟右邊反彈欄擠）
        _x_zone_lab = float(_x_left) + 0.35
        ax.text(
            _x_zone_lab,
            _zhi,
            f"壓上緣 {_zhi:.0f}",
            ha="left",
            va="bottom",
            fontsize=8.4,
            fontweight="bold",
            fontproperties=prop,
            color="#1e293b",
            zorder=15,
            clip_on=False,
            bbox=dict(
                boxstyle="round,pad=0.2",
                facecolor="#f8fafc",
                edgecolor="#475569",
                linewidth=1.1,
                alpha=0.98,
            ),
        )
        ax.text(
            _x_zone_lab,
            _zlo,
            f"壓下緣 {_zlo:.0f}",
            ha="left",
            va="top",
            fontsize=8.4,
            fontweight="bold",
            fontproperties=prop,
            color="#1e293b",
            zorder=15,
            clip_on=False,
            bbox=dict(
                boxstyle="round,pad=0.2",
                facecolor="#f8fafc",
                edgecolor="#475569",
                linewidth=1.1,
                alpha=0.98,
            ),
        )

    # 末根K旁不再寫收價；收／即時價改右上大字卡

    # 右側價位角標：最底／反彈切割／四浪高（收價在表頭卡）
    right_tags: List[Dict[str, Any]] = [
        {
            "price": float(w4.price),
            "text": f"四浪高 {w4.price:.0f}",
            "color": "#991b1b",
            "facecolor": "#fee2e2",
            "edge": "#f87171",
            "fontsize": 9.5,
        },
        {
            "price": float(wave_lo),
            "text": f"最底 {wave_lo:.0f}",
            "color": "#064e3b",
            "facecolor": "#ecfdf5",
            "edge": "#34d399",
            "fontsize": 8.8,
        },
    ]
    for ratio, px in fib_lvls:
        right_tags.append(
            {
                "price": float(px),
                "text": f"反彈{ratio:g} {px:.0f}",
                "color": "#065f46",
                "facecolor": "#d1fae5",
                "edge": "#10b981",
                "fontsize": 8.4,
            }
        )
    _paint_right_price_tags(
        ax,
        x_anchor=float(n - 1),
        x_text=_x_text,
        tags=right_tags,
        y_lo=ylim_lo + _span_y * 0.06,
        y_hi=ylim_hi - _span_y * 0.08,
        prop=prop,
        # 反彈只走兩欄（0/1），壓帶已單獨佔末根K旁紅框位
        forbid_cols={2},
    )

    step = max(1, n // 10)
    ticks = list(range(0, n, step))
    axv.set_xticks(ticks)
    axv.set_xticklabels(
        [dates[i][4:6] + "/" + dates[i][6:8] for i in ticks], fontsize=8
    )

    # 表頭瘦帶：抬高主圖，左副標與右上三行同帶，不准左上留大片空白
    prev_close: Optional[float] = None
    if len(bars) >= 2:
        try:
            prev_close = float(bars[-2]["close"])
        except (TypeError, ValueError, KeyError):
            prev_close = None
    chg_c = "#111111"
    chg_line = ""
    if prev_close and prev_close > 0:
        dlt = float(close) - float(prev_close)
        pct = dlt / float(prev_close) * 100.0
        chg_c = "#dc2626" if dlt >= 0 else "#059669"
        sign = "＋" if dlt >= 0 else "－"
        chg_line = f"較昨日　{sign}{abs(dlt):.0f}（{sign}{abs(pct):.2f}%）"

    _hx = 0.972
    _hs = HEADER_STYLES.get(str(header_style or HEADER_STYLE_DEFAULT).upper()) or HEADER_STYLES[HEADER_STYLE_DEFAULT]
    _fs_name = float(_hs["name"])
    _fs_price = float(_hs["price"])
    _fs_chg = float(_hs["chg"])
    _fs_k = float(_hs["k"])
    _name_gap = float(_hs["name_gap"])
    _chg_pad = float(_hs["chg_pad"])
    _name_s = f"{sid}　{name}"
    _price_s = f"{close:.0f}"
    _chg_s = chg_line or "較昨日　—"

    def _fig_extent(txt: str, fs: float):
        t = fig.text(
            0.5,
            0.5,
            txt,
            ha="right",
            va="center",
            fontsize=fs,
            fontweight="bold",
            fontproperties=prop,
            alpha=0.0,
        )
        fig.canvas.draw()
        bb = t.get_window_extent(renderer=fig.canvas.get_renderer())
        inv = fig.transFigure.inverted()
        p0 = inv.transform((bb.x0, bb.y0))
        p1 = inv.transform((bb.x1, bb.y1))
        t.remove()
        return float(p1[0] - p0[0]), float(p1[1] - p0[1])

    _nw, _nh = _fig_extent(_name_s, _fs_name)
    _pw, _ph = _fig_extent(_price_s, _fs_price)
    _cw, _ch = _fig_extent(_chg_s, _fs_chg)
    del _nw, _cw

    # 依字級估表頭帶高 → 抬主圖；右塊自頂往下排
    _band = _nh + _name_gap + _ph + _chg_pad + _ch + 0.018
    _top = max(0.88, min(0.93, 1.0 - _band))
    # 價量夾縫：左右兩格同寬同高（附圖雙紅框比例）
    fig.subplots_adjust(top=_top, hspace=0.46)
    fig.canvas.draw()
    ax_pos = ax.get_position()
    axv_pos = axv.get_position()
    _gap_bot = float(axv_pos.y1) + 0.010
    _gap_top = float(ax_pos.y0) - 0.010
    _box_h = max(0.062, _gap_top - _gap_bot)
    _box_y = (_gap_bot + _gap_top) * 0.5 - _box_h * 0.5
    _pair_l, _pair_r, _pair_gap = 0.075, 0.925, 0.022
    _box_w = (_pair_r - _pair_l - _pair_gap) * 0.5
    _x_fund = _pair_l
    _x_leg = _pair_l + _box_w + _pair_gap
    for _bx, _fc, _ec in (
        (_x_fund, "#fff7ed", "#fdba74"),
        (_x_leg, "#ffffff", "#94a3b8"),
    ):
        fig.patches.append(
            FancyBboxPatch(
                (_bx, _box_y),
                _box_w,
                _box_h,
                boxstyle="round,pad=0.006,rounding_size=0.012",
                facecolor=_fc,
                edgecolor=_ec,
                linewidth=1.2,
                transform=fig.transFigure,
                zorder=21,
            )
        )
    _ax_fund = fig.add_axes(
        [_x_fund + 0.010, _box_y + 0.008, _box_w - 0.020, _box_h - 0.016]
    )
    _ax_fund.set_axis_off()
    _ax_fund.patch.set_alpha(0.0)
    _ax_fund.text(
        0.5,
        0.5,
        fund,
        ha="center",
        va="center",
        fontsize=7.2,
        fontproperties=prop,
        color="#1f2937",
        transform=_ax_fund.transAxes,
        zorder=22,
    )
    _handles, _labels = ax.get_legend_handles_labels()
    if _handles:
        _ax_leg = fig.add_axes(
            [_x_leg + 0.010, _box_y + 0.008, _box_w - 0.020, _box_h - 0.016]
        )
        _ax_leg.set_axis_off()
        _ax_leg.patch.set_alpha(0.0)
        _ax_leg.legend(
            _handles,
            _labels,
            loc="center",
            ncol=2,
            fontsize=6.2,
            frameon=False,
            borderpad=0.2,
            labelspacing=0.35,
            columnspacing=0.8,
            handlelength=1.6,
            prop=prop,
        )

    _y_name = 0.992
    _y_price = _y_name - _nh - _name_gap - _ph * 0.50
    _y_chg = _y_price - (_ph * 0.50 + _ch * 0.50 + _chg_pad)
    # 左帶加重：日期／OHLC 與右上同高，吃掉中左空白；長說明貼主圖頂
    _lx = 0.035
    fig.text(
        _lx,
        _y_name,
        sub1,
        color="#0f172a",
        fontsize=11.0,
        fontweight="bold",
        fontproperties=prop,
        ha="left",
        va="top",
        zorder=20,
    )
    fig.text(
        _lx,
        _y_price,
        sub2,
        color="#334155",
        fontsize=10.0,
        fontweight="bold",
        fontproperties=prop,
        ha="left",
        va="center",
        zorder=20,
    )
    fig.text(
        _lx,
        _y_chg,
        "觀察用｜非買訊",
        color="#64748b",
        fontsize=9.0,
        fontweight="bold",
        fontproperties=prop,
        ha="left",
        va="center",
        zorder=20,
    )
    fig.text(
        ax_pos.x0,
        ax_pos.y1 + 0.003,
        sub3,
        color="#6b7280",
        fontsize=6.6,
        fontproperties=prop,
        ha="left",
        va="bottom",
        zorder=20,
    )
    fig.text(
        _hx,
        _y_name,
        _name_s,
        ha="right",
        va="top",
        fontsize=_fs_name,
        fontweight="bold",
        fontproperties=prop,
        color="#0f172a",
        zorder=21,
    )
    fig.text(
        _hx,
        _y_price,
        _price_s,
        ha="right",
        va="center",
        fontsize=_fs_price,
        fontweight="bold",
        fontproperties=prop,
        color=chg_c,
        zorder=21,
    )
    fig.text(
        _hx,
        _y_chg,
        _chg_s,
        ha="right",
        va="center",
        fontsize=_fs_chg,
        fontweight="bold",
        fontproperties=prop,
        color=chg_c,
        zorder=21,
    )
    # 縮圖K：高≈大價 0.62、寬高比 3.2:5.6；左標「今K」8.5
    _k_h = max(0.028, min(0.048, _ph * 0.62))
    _k_w = _k_h * (3.2 / 5.6)
    _gap = 0.004
    _k_x = _hx - _pw - _gap - _k_w
    _k_y = _y_price - _k_h * 0.5
    fig.text(
        _k_x - _gap,
        _y_price,
        "今K",
        ha="right",
        va="center",
        fontsize=_fs_k,
        fontweight="bold",
        fontproperties=prop,
        color="#64748b",
        zorder=21,
    )
    ax_k = fig.add_axes([_k_x, _k_y, _k_w, _k_h])
    ax_k.set_axis_off()
    ax_k.patch.set_alpha(0.0)
    _o, _h, _l, _c = float(open_), float(high), float(low), float(close)
    _rng = max(_h - _l, abs(_c) * 0.012, 1e-6)
    _kcol = "#e53935"
    if prev_close is not None:
        _kcol = "#e53935" if _c >= float(prev_close) else "#00897b"

    def _ky(p: float) -> float:
        return 0.08 + (float(p) - _l) / _rng * 0.84

    ax_k.plot(
        [0.5, 0.5],
        [_ky(_l), _ky(_h)],
        color=_kcol,
        lw=1.6,
        solid_capstyle="round",
        zorder=2,
    )
    _blo, _bhi = _ky(min(_o, _c)), _ky(max(_o, _c))
    ax_k.add_patch(
        Rectangle(
            (0.19, _blo),
            0.62,
            max(_bhi - _blo, 0.04),
            facecolor=_kcol,
            edgecolor=_kcol,
            lw=0.35,
            zorder=3,
        )
    )
    ax_k.set_xlim(0, 1)
    ax_k.set_ylim(0, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    con.close()
    meta = {
        "sid": sid,
        "name": name,
        "asof": asof,
        "close": close,
        "room_pct": round(room, 2),
        "w4": w4.price,
        "zone_date": zone_date,
        "zone_vol": zone_vol,
        "zone_role": zone_role,
        "zone": zone,
        "eps": eps_line,
        "cum": cum_s,
        "mr": mr_line,
        "out": str(out),
    }
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", default="2383")
    ap.add_argument(
        "--out",
        default="/opt/cursor/artifacts/focus_targets_sample_2383_v3.png",
    )
    args = ap.parse_args()
    meta = paint(str(args.sid).strip(), Path(args.out))
    for k, v in meta.items():
        if k == "zone":
            continue
        print(k, v)
    z = meta.get("zone") or {}
    print(
        "zone_detail",
        z.get("date"),
        z.get("low"),
        z.get("high"),
        z.get("volume"),
        z.get("prox_gap"),
        z.get("zone_role"),
    )


if __name__ == "__main__":
    main()
