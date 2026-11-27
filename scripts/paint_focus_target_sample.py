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
from matplotlib.patches import Rectangle

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
# 固定右錨滾動窗；右側再留 FUTURE_PAD 根空位（明天起時間往右長）
# LABEL_RIGHT_EXTRA＝價標專用再加寬，字貼最右 gutter，不准貼末根K
# LINE_END_PAD＝水平線／色帶右端停點（標籤欄前必須空）
WIN = 130
FUTURE_PAD = 22
LABEL_RIGHT_EXTRA = 52
LINE_END_PAD = 1.5
TAG_COL_GAP = 24.0  # 雙欄字寬約一盒，欄距不夠會看起來像互壓
NEAR_PRICE_FRAC = 0.022  # 2449：201／199 也要進同簇雙欄
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
    min_gap_frac: float = 0.072,
    near_frac: float = NEAR_PRICE_FRAC,
) -> Tuple[List[float], List[int]]:
    """右側角標顯示 Y＋欄位：近價改雙欄，跨簇再強制最小間距，不准互壓。

    回傳 (placed_ys, cols)；cols[i]∈{0,1}，1＝往右一欄。
    """
    if not prices:
        return [], []
    span = max(y_hi - y_lo, 1.0)
    near = max(span * float(near_frac), span * 0.004)
    gap = span * float(min_gap_frac)
    order = sorted(range(len(prices)), key=lambda i: prices[i], reverse=True)
    # 近價分簇（高→低）
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
    cols = [0] * len(prices)
    for cl in clusters:
        for k, i in enumerate(cl):
            cols[i] = 1 if (k % 2 == 1) else 0
    # 跨簇 dodge：同簇用真價中位當代表，再映回各員（雙欄員可留真價）
    placed = [float(p) for p in prices]
    # 先對「每簇代表」做間距；代表＝簇內最高價（視覺上靠真價）
    reps: List[Tuple[int, float]] = []  # (cluster_idx, rep_y)
    for ci, cl in enumerate(clusters):
        rep = max(float(prices[i]) for i in cl)
        reps.append((ci, rep))
    last = y_hi + gap
    rep_placed: Dict[int, float] = {}
    for ci, rep in reps:
        y = min(rep, last - gap)
        rep_placed[ci] = y
        last = y
    # 邊界推回
    vals = list(rep_placed.values())
    mn, mx = min(vals), max(vals)
    if mn < y_lo:
        sh = y_lo - mn
        rep_placed = {k: v + sh for k, v in rep_placed.items()}
        mx = max(rep_placed.values())
    if mx > y_hi:
        sh = mx - y_hi
        rep_placed = {k: v - sh for k, v in rep_placed.items()}
        order_c = sorted(rep_placed.keys(), key=lambda c: rep_placed[c], reverse=True)
        last = y_hi + gap
        for ci in order_c:
            y = min(rep_placed[ci], last - gap)
            rep_placed[ci] = max(y, y_lo)
            last = rep_placed[ci]
    for ci, cl in enumerate(clusters):
        base = rep_placed[ci]
        if len(cl) == 1:
            placed[cl[0]] = base
            continue
        # 雙欄＋同欄微錯開：3 顆近價時不准兩顆同欄同 Y 互蓋
        col_n = [0, 0]
        for k, i in enumerate(cl):
            c = cols[i]
            placed[i] = base - col_n[c] * gap * 0.85
            col_n[c] += 1
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
) -> None:
    """右側價位角標：字只貼最右 gutter；短截對齊真價；近價雙欄。

    不准從末根K拉長線過來（看起來像標籤貼在K旁）。
    x_anchor 保留相容，實際不用來當文字錨。
    """
    if not tags:
        return
    _ = x_anchor  # 相容舊呼叫
    prices = [float(t["price"]) for t in tags]
    dys, cols = _dodge_right_ys(prices, y_lo=y_lo, y_hi=y_hi, min_gap_frac=0.072)
    base_xt = float(x_text if x_text is not None else 0.0)
    stub = 4.0  # 短截只在標籤欄內
    span = max(y_hi - y_lo, 1.0)
    for t, dy, true_y, col in zip(tags, dys, prices, cols):
        xt = base_xt + (TAG_COL_GAP if col else 0.0)
        ax.plot(
            [xt - stub, xt - 0.6],
            [true_y, true_y],
            color=t.get("edge", "#94a3b8"),
            lw=1.0,
            solid_capstyle="butt",
            zorder=13,
            clip_on=False,
        )
        if abs(dy - true_y) > span * 0.008:
            ax.plot(
                [xt - 0.6, xt - 0.6],
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
                boxstyle="round,pad=0.22",
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


def paint(sid: str, out: Path, *, db_path: Path = DB) -> Dict[str, Any]:
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
        # 壓帶上下緣標籤掛左邊，不准跟右欄價標擠
        ax.text(
            _x_left + 0.35,
            hi,
            f"壓上緣 {hi:.0f}",
            ha="left",
            va="bottom",
            fontsize=8.2,
            fontweight="bold",
            fontproperties=prop,
            color="#1e293b",
            zorder=12,
            clip_on=False,
            bbox=dict(
                boxstyle="round,pad=0.18",
                facecolor="#f8fafc",
                edgecolor="#64748b",
                alpha=0.96,
            ),
        )
        ax.text(
            _x_left + 0.35,
            lo,
            f"壓下緣 {lo:.0f}",
            ha="left",
            va="top",
            fontsize=8.2,
            fontweight="bold",
            fontproperties=prop,
            color="#1e293b",
            zorder=12,
            clip_on=False,
            bbox=dict(
                boxstyle="round,pad=0.18",
                facecolor="#f8fafc",
                edgecolor="#64748b",
                alpha=0.96,
            ),
        )

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

    for i, (v, o, c) in enumerate(zip(vols, opens, closes)):
        if zone_i is not None and i == zone_i:
            col = "#ea580c"
            alpha = 1.0
        else:
            col = "#d64545" if c >= o else "#2f9e6b"
            alpha = 0.72
        axv.bar(i, v, width=0.72, color=col, alpha=alpha, zorder=2)

    # 量標掛在量圖「上方縫隙」（axes y>1），完全不進量柱區
    vmax = max(vols) if vols else 1.0
    axv.set_ylim(0, vmax * 1.08)
    _vol_note_bits = []
    if zone_i is not None:
        md = f"{dates[zone_i][4:6]}/{dates[zone_i][6:8]}"
        _vol_note_bits.append(f"壓力來源量（橘）{md} {vols[zone_i]:.0f}張")
    _vol_note_bits.append(f"今日 {vol:.0f} 張")
    axv.text(
        0.0,
        1.16,
        "　｜　".join(_vol_note_bits),
        transform=axv.transAxes,
        ha="left",
        va="bottom",
        color="#374151",
        fontsize=7.6,
        fontweight="bold",
        fontproperties=prop,
        bbox=dict(
            boxstyle="round,pad=0.2",
            facecolor="#fff7ed",
            edgecolor="#fdba74",
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
    # 基本面盒靠左下，避開黃線終段
    ax.text(
        0.01,
        0.015,
        fund,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=8.2,
        fontproperties=prop,
        color="#1f2937",
        bbox=dict(
            boxstyle="round,pad=0.4",
            facecolor="#fff7ed",
            edgecolor="#fdba74",
            alpha=0.96,
        ),
        zorder=10,
    )

    # 距四浪高％掛價圖內偏右上，但避開右欄價標 gutter
    ax.text(
        0.78,
        0.995,
        f"距四浪高還有 {room:.1f}%",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9.5,
        fontweight="bold",
        fontproperties=prop,
        color="#b91c1c",
        bbox=dict(
            boxstyle="round,pad=0.28",
            facecolor="#fee2e2",
            edgecolor="#f87171",
            alpha=0.95,
        ),
        zorder=15,
        clip_on=False,
    )

    asof_face = f"{asof[0:4]}/{asof[4:6]}/{asof[6:8]} 盤後"
    title = f"{sid}　{name}　收盤 {close:.0f} 元"
    ohlc_line = f"開 {open_:.0f}　高 {high:.0f}　低 {low:.0f}　收 {close:.0f}　量 {vol:.0f} 張"
    # 表頭兩行：標題單獨；副標拆兩行，不准壓進圖內文字
    sub1 = f"{asof_face}｜{ohlc_line}｜觀察非買訊"
    sub2 = (
        f"紫細線＝五波下跌　最底＋反彈0.382/0.5/0.618（觀察）　黃線＝新起漲｜"
        f"滾動近{WIN}根（新日進、左邊掉；右留空給價標）"
    )
    ax.set_title(
        title, color="#111", fontsize=15.5, pad=30, fontweight="bold", fontproperties=prop
    )
    ax.legend(
        loc="upper left",
        fontsize=6.8,
        framealpha=0.92,
        ncol=2,
        bbox_to_anchor=(0.01, 0.99),
        borderpad=0.35,
    )
    ax.set_ylabel("價（元）", fontproperties=prop)
    axv.set_ylabel("成交量（張）", fontproperties=prop)

    # 收／即時價貼近末根K右側，不准丟進最右欄去擠
    ax.annotate(
        f"收 {close:.0f}",
        xy=(float(n - 1), float(close)),
        xytext=(9, 0),
        textcoords="offset points",
        ha="left",
        va="center",
        fontsize=9.2,
        fontweight="bold",
        fontproperties=prop,
        color="#115e59",
        zorder=16,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.2",
            facecolor="#ccfbf1",
            edgecolor="#14b8a6",
            alpha=0.97,
        ),
    )

    # 右側價位角標：最底／反彈切割／四浪高（壓帶掛左；收貼末根K）
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
    _x_text = float(n - 1 + FUTURE_PAD + 4.0)
    _xlim_right = _x_text + LABEL_RIGHT_EXTRA
    ax.set_xlim(_x_left, _xlim_right)
    _paint_right_price_tags(
        ax,
        x_anchor=float(n - 1),
        x_text=_x_text,
        tags=right_tags,
        y_lo=ylim_lo + _span_y * 0.06,
        y_hi=ylim_hi - _span_y * 0.08,
        prop=prop,
    )

    step = max(1, n // 10)
    ticks = list(range(0, n, step))
    axv.set_xticks(ticks)
    axv.set_xticklabels(
        [dates[i][4:6] + "/" + dates[i][6:8] for i in ticks], fontsize=8
    )

    fig.subplots_adjust(top=0.86, hspace=0.28)
    # 副標放在標題與圖之間（figure 座標），不准壓進圖內
    fig.canvas.draw()
    ax_pos = ax.get_position()
    fig.text(
        ax_pos.x0,
        min(ax_pos.y1 + 0.034, 0.955),
        sub1,
        color="#374151",
        fontsize=8.0,
        fontproperties=prop,
        ha="left",
        va="bottom",
    )
    fig.text(
        ax_pos.x0,
        min(ax_pos.y1 + 0.012, 0.935),
        sub2,
        color="#6b7280",
        fontsize=7.6,
        fontproperties=prop,
        ha="left",
        va="bottom",
    )
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
