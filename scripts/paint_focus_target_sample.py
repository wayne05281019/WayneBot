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

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "wayne_market.db"
# 固定右錨滾動窗；右側再留 FUTURE_PAD 根空位（明天起時間往右長）
WIN = 130
FUTURE_PAD = 18


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
        2, 1, figsize=(12.6, 9.0), gridspec_kw={"height_ratios": [3.4, 1.25]}, sharex=True
    )
    bg = "#f7f5f0"
    fig.patch.set_facecolor(bg)
    for a in (ax, axv):
        a.set_facecolor(bg)
        a.tick_params(colors="#333")
        for sp in a.spines.values():
            sp.set_color("#bbb")
        a.grid(True, color="#e6e2da", lw=0.6, zorder=0)

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
        # 壓力帶用灰藍，黃色留給「新起漲」白／黃教法線
        ax.axhspan(lo, hi, facecolor="#cbd5e1", alpha=0.45, zorder=1, label=band_lab)
        ax.axhline(hi, color="#475569", ls="-", lw=1.45, alpha=0.95)
        ax.axhline(lo, color="#475569", ls="-", lw=1.45, alpha=0.95)
        ax.annotate(
            f"壓上緣 {hi:.0f}",
            xy=(n - 1, hi),
            xytext=(10, 6),
            textcoords="offset points",
            color="#1e293b",
            fontsize=10,
            fontweight="bold",
            fontproperties=prop,
            clip_on=False,
            bbox=dict(
                boxstyle="round,pad=0.22",
                facecolor="#f8fafc",
                edgecolor="#64748b",
                alpha=0.97,
            ),
        )
        ax.annotate(
            f"壓下緣 {lo:.0f}",
            xy=(n - 1, lo),
            xytext=(10, -16),
            textcoords="offset points",
            color="#1e293b",
            fontsize=10,
            fontweight="bold",
            fontproperties=prop,
            clip_on=False,
            bbox=dict(
                boxstyle="round,pad=0.22",
                facecolor="#f8fafc",
                edgecolor="#64748b",
                alpha=0.97,
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

    # 教法：紫細線＝五波下跌（淺底比白線黑邊清楚）；黃線＝新一波起漲
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
                s=28,
                c="#7c3aed",
                zorder=9,
                edgecolors="#fff",
                lw=0.55,
            )
            # 起／終側標（仿籌碼K線）；中間轉折錯開上下，避免互壓
            if lab == "起":
                ax.annotate(
                    f"← {price:.0f}",
                    xy=(j, price),
                    xytext=(10, 8),
                    textcoords="offset points",
                    color="#dc2626",
                    fontsize=9.5,
                    fontweight="bold",
                    fontproperties=prop,
                    zorder=10,
                )
            elif lab == "終":
                ax.annotate(
                    f"{price:.0f} →",
                    xy=(j, price),
                    xytext=(-48, -16),
                    textcoords="offset points",
                    color="#16a34a",
                    fontsize=9.5,
                    fontweight="bold",
                    fontproperties=prop,
                    zorder=10,
                )
            else:
                dy = 14 if kind == "H" else -20
                # 點 2／3 再微偏，減與鄰標重疊
                if lab == "2":
                    dy = 16
                elif lab == "3":
                    dy = -22
                ax.annotate(
                    f"{lab} {price:.0f}",
                    xy=(j, price),
                    xytext=(0, dy),
                    textcoords="offset points",
                    ha="center",
                    color="#5b21b6",
                    fontsize=8,
                    fontweight="bold",
                    fontproperties=prop,
                    zorder=10,
                )

    ax.axhline(
        w4.price,
        color="#dc2626",
        ls="-",
        lw=1.7,
        alpha=0.92,
        label=f"次級四浪高 {w4.price:.0f}",
    )
    ax.annotate(
        f"四浪高 {w4.price:.0f}",
        xy=(n - 1, w4.price),
        xytext=(10, 6),
        textcoords="offset points",
        color="#991b1b",
        fontsize=10,
        fontweight="bold",
        fontproperties=prop,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.22",
            facecolor="#fee2e2",
            edgecolor="#f87171",
            alpha=0.97,
        ),
    )

    # 黃線＝五波走完後的新一波起漲（新開始低 → 今日收）
    bounce_from = ns if ns is not None else (pts[-1] if pts else None)
    if bounce_from is not None:
        j = vi(bounce_from.i)
        if 0 <= j < n:
            ax.scatter(
                [j],
                [bounce_from.price],
                s=110,
                c="#eab308",
                marker="D",
                zorder=11,
                edgecolors="#854d0e",
                lw=1.2,
                label="黃線＝新起漲",
            )
            ax.plot(
                [j, n - 1],
                [bounce_from.price, close],
                color="#ca8a04",
                lw=2.4,
                zorder=8,
                solid_capstyle="round",
            )
            ax.plot(
                [j, n - 1],
                [bounce_from.price, close],
                color="#facc15",
                lw=1.9,
                zorder=9,
                solid_capstyle="round",
            )
            # 「新起漲」標在黃線中段偏右上，避開紫線轉折數字
            ax.annotate(
                "新起漲",
                xy=(j + (n - 1 - j) * 0.62, bounce_from.price + (close - bounce_from.price) * 0.62),
                xytext=(10, 14),
                textcoords="offset points",
                color="#854d0e",
                fontsize=8.5,
                fontweight="bold",
                fontproperties=prop,
                zorder=12,
                bbox=dict(
                    boxstyle="round,pad=0.18",
                    facecolor="#fef9c3",
                    edgecolor="#eab308",
                    alpha=0.95,
                ),
            )

    ax.axhline(close, color="#0f766e", ls=":", lw=1.15, alpha=0.75)
    # 收盤標放右側、略低於線，避壓上緣／四浪高角標
    ax.annotate(
        f"收 {close:.0f}",
        xy=(n - 1, close),
        xytext=(10, -22),
        textcoords="offset points",
        color="#115e59",
        fontsize=10.5,
        fontweight="bold",
        fontproperties=prop,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.25",
            facecolor="#ccfbf1",
            edgecolor="#14b8a6",
            alpha=0.97,
        ),
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

    if zone_i is not None:
        md = f"{dates[zone_i][4:6]}/{dates[zone_i][6:8]}"
        axv.annotate(
            f"壓力來源量（橘）\n{md}　{vols[zone_i]:.0f}張",
            xy=(zone_i, vols[zone_i]),
            xytext=(14, 14),
            textcoords="offset points",
            color="#9a3412",
            fontsize=8.5,
            fontweight="bold",
            fontproperties=prop,
            arrowprops=dict(arrowstyle="->", color="#ea580c", lw=1.3),
            bbox=dict(
                boxstyle="round,pad=0.25",
                facecolor="#ffedd5",
                edgecolor="#fb923c",
                alpha=0.96,
            ),
        )

    axv.annotate(
        f"今日 {vol:.0f} 張",
        xy=(n - 1, vol),
        xytext=(-62, 12),
        textcoords="offset points",
        color="#111",
        fontsize=9,
        fontweight="bold",
        fontproperties=prop,
        arrowprops=dict(arrowstyle="->", color="#333", lw=0.8),
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

    # 空間％放右上內側，不跟表頭搶位
    ax.text(
        0.995,
        0.88,
        f"距四浪高還有\n{room:.1f}%",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=11,
        fontweight="bold",
        fontproperties=prop,
        color="#b91c1c",
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="#fee2e2",
            edgecolor="#f87171",
            alpha=0.95,
        ),
        zorder=10,
    )

    asof_face = f"{asof[0:4]}/{asof[4:6]}/{asof[6:8]} 盤後"
    title = f"{sid}　{name}　收盤 {close:.0f} 元"
    ohlc_line = f"開 {open_:.0f}　高 {high:.0f}　低 {low:.0f}　收 {close:.0f}　量 {vol:.0f} 張"
    # 表頭兩行：標題單獨；副標拆兩行，不准壓進圖內文字
    sub1 = f"{asof_face}｜{ohlc_line}｜觀察非買訊"
    sub2 = f"紫細線＝五波下跌　黃線＝新起漲｜滾動近{WIN}根（新日進、左邊掉；右留{FUTURE_PAD}根空位）"
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
    # 右留空：明天起往右長；左＝滾動掉舊根
    ax.set_xlim(-1.2, n - 1 + FUTURE_PAD)
    # 上方多留一點給轉折標，避免貼齊表頭
    y_hi = max(highs + [w4.price, float(zone["high"]) if zone else 0])
    y_lo = min(lows)
    pad = (y_hi - y_lo) * 0.06
    ax.set_ylim(y_lo - pad * 0.4, y_hi + pad * 1.15)
    step = max(1, n // 10)
    ticks = list(range(0, n, step))
    axv.set_xticks(ticks)
    axv.set_xticklabels(
        [dates[i][4:6] + "/" + dates[i][6:8] for i in ticks], fontsize=8
    )

    fig.subplots_adjust(top=0.86, hspace=0.10)
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
