#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把量價落底觀察命中渲成接近飆大教圖的日K：轉折結構＋一年級量標。

不准發明個股 5／9：只連轉折高低與水平位。觀察用，非買訊。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from scripts.biaoke_bottom_vol_observe_screen import YEAR_LOOKBACK, year_grade_floor

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "wayne_market.db"
HITS = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab" / "biaoke_bottom_vol_observe_20261126.json"
OUT = Path("/opt/cursor/artifacts/biaoke_bottom_vol_1126_v2")


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


def load_bars(con: sqlite3.Connection, sid: str, n: int = 180) -> List[Tuple]:
    rows = con.execute(
        "SELECT date,open,high,low,close,volume FROM daily_quotes "
        "WHERE stock_id=? ORDER BY date DESC LIMIT ?",
        (sid, n),
    ).fetchall()
    return list(
        reversed(
            [
                (str(d), float(o), float(h), float(l), float(c), float(v))
                for d, o, h, l, c, v in rows
            ]
        )
    )


def swing_pivots(
    highs: Sequence[float], lows: Sequence[float], *, left: int = 3, right: int = 3
) -> List[Tuple[int, float, str]]:
    """簡易轉折點（不是浪號）。"""
    n = len(highs)
    piv: List[Tuple[int, float, str]] = []
    for i in range(left, n - right):
        wh = highs[i - left : i + right + 1]
        wl = lows[i - left : i + right + 1]
        if highs[i] >= max(wh) - 1e-9:
            piv.append((i, highs[i], "H"))
        if lows[i] <= min(wl) + 1e-9:
            piv.append((i, lows[i], "L"))
    piv.sort(key=lambda t: t[0])
    # 去連續同向，留更極端
    out: List[Tuple[int, float, str]] = []
    for p in piv:
        if not out:
            out.append(p)
            continue
        if p[2] == out[-1][2]:
            if p[2] == "H" and p[1] >= out[-1][1]:
                out[-1] = p
            elif p[2] == "L" and p[1] <= out[-1][1]:
                out[-1] = p
        else:
            out.append(p)
    return out


STYLE_ZH = {
    "year_grade_consec": "連續一年級巨量（2383型問題量）",
    "sediment": "籌碼沉澱（2330型）",
    "both": "連續一年級＋沉澱",
    "year_grade_near_low": "近低一年級巨量",
}


def paint(hit: Dict[str, Any], bars: List[Tuple], prop, out_path: Path) -> None:
    # 顯示窗：沉澱用較長；連續巨量用約半年也可，統一 150
    bars = bars[-150:] if len(bars) > 150 else bars
    xs = list(range(len(bars)))
    opens = [b[1] for b in bars]
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    closes = [b[4] for b in bars]
    vols = [b[5] for b in bars]
    dates = [b[0] for b in bars]

    # 一年門檻用更長窗（若有）
    year_vols = vols  # 顯示窗內；門檻以 hit 欄為準
    floor = float(hit.get("year_grade_floor") or 0)
    ymax = float(hit.get("vol_year_max") or max(year_vols or [1]))
    if floor <= 0:
        floor, ymax = year_grade_floor(vols[-min(len(vols), YEAR_LOOKBACK) :])

    low60 = float(hit["low_60"])
    piv = swing_pivots(highs, lows, left=3, right=3)

    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(11.2, 7.6), gridspec_kw={"height_ratios": [3.1, 1.1]}, sharex=True
    )
    fig.patch.set_facecolor("#0f1419")
    for a in (ax, axv):
        a.set_facecolor("#0f1419")
        a.tick_params(colors="#c8d0d8")
        for sp in a.spines.values():
            sp.set_color("#3a4550")

    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        up = c >= o
        col = "#e85d5d" if up else "#3dbf7a"
        ax.vlines(i, l, h, color=col, linewidth=1.0, zorder=2)
        body_lo, body_hi = min(o, c), max(o, c)
        height = max(body_hi - body_lo, (max(highs) - min(lows)) * 0.002)
        ax.add_patch(
            Rectangle((i - 0.35, body_lo), 0.7, height, facecolor=col, edgecolor=col, zorder=3)
        )

    # 轉折折線（不標 1–5）
    if len(piv) >= 2:
        ax.plot(
            [p[0] for p in piv],
            [p[1] for p in piv],
            color="#c77dff",
            linewidth=1.4,
            alpha=0.85,
            zorder=4,
            label="轉折結構（非浪號）",
        )
        for i, price, kind in piv[-8:]:
            ax.scatter([i], [price], s=18, c="#e0b0ff", zorder=5)
            ax.annotate(
                f"{price:.0f}",
                xy=(i, price),
                xytext=(0, 8 if kind == "H" else -12),
                textcoords="offset points",
                ha="center",
                color="#d8b4fe",
                fontsize=7,
                fontproperties=prop,
            )

    ax.axhline(
        low60,
        color="#ff4d9a",
        linestyle="-",
        linewidth=1.3,
        alpha=0.9,
        label=f"近60低 {low60:.2f}",
    )

    for i, (v, o, c) in enumerate(zip(vols, opens, closes)):
        col = "#e85d5d" if c >= o else "#3dbf7a"
        yg = v >= floor - 1e-9
        axv.bar(i, v, width=0.7, color=col, alpha=0.95 if yg else 0.35, zorder=2)
        if yg:
            circ = plt.Circle(
                (i, v * 1.02),
                0.55,
                fill=False,
                ec="#4da3ff",
                lw=1.4,
                zorder=6,
                clip_on=False,
            )
            # annotate instead of circle in data coords (scale issues)
            axv.annotate(
                "一年級",
                xy=(i, v),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                color="#7ec8ff",
                fontsize=7,
                fontproperties=prop,
            )

    axv.axhline(floor, color="#ff8a4c", linestyle="--", linewidth=1.15, alpha=0.9)
    axv.axhline(ymax, color="#ff8a4c", linestyle=":", linewidth=0.8, alpha=0.45)
    axv.text(
        0.01,
        0.92,
        f"一年級門檻 {floor:.0f}（年最大 {ymax:.0f}）",
        transform=axv.transAxes,
        color="#ffb080",
        fontsize=8,
        fontproperties=prop,
    )

    style_zh = STYLE_ZH.get(hit["style"], hit["style"])
    title = f"{hit['stock_id']} {hit['stock_name']}｜{hit['market']}｜{style_zh}"
    sub = (
        f"asof {hit.get('as_of','')}｜收 {hit['close']}｜距60低 {hit['dist_to_low_pct']}%｜"
        f"回撤 {hit['drawdown_pct']}%｜量/年最大 {hit['vol_ratio_year']}×｜觀察非買訊｜不標5/9"
    )
    ax.set_title(title, color="#f2f5f8", fontsize=13, pad=10, fontproperties=prop)
    ax.text(0.0, 1.02, sub, transform=ax.transAxes, color="#9aa7b5", fontsize=8.5, fontproperties=prop)
    ax.legend(
        loc="upper left",
        fontsize=8,
        facecolor="#1a222b",
        edgecolor="#3a4550",
        labelcolor="#e0e6ec",
    )
    ax.set_ylabel("價", color="#c8d0d8", fontproperties=prop)
    axv.set_ylabel("量", color="#c8d0d8", fontproperties=prop)
    step = max(1, len(bars) // 8)
    axv.set_xticks(xs[::step])
    axv.set_xticklabels(
        [d[4:6] + "/" + d[6:8] for d in dates[::step]], color="#c8d0d8", fontsize=8
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> int:
    prop = _cjk_prop()
    payload = json.loads(HITS.read_text(encoding="utf-8"))
    asof = payload["as_of"]
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    paths = []
    for hit in payload.get("hits") or []:
        hit = dict(hit)
        hit["as_of"] = asof
        bars = load_bars(con, hit["stock_id"], n=220)
        out = OUT / f"{hit['market']}_{hit['stock_id']}_{hit['style']}.png"
        paint(hit, bars, prop, out)
        paths.append(str(out))
        print("painted", hit["stock_id"], out)
    # 2383 教學對照（可能已離開洗盤區）
    teach_hit = {
        "stock_id": "2383",
        "stock_name": "台光電",
        "market": "TW",
        "style": "year_grade_consec",
        "close": 0,
        "low_60": 0,
        "drawdown_pct": 0,
        "dist_to_low_pct": 0,
        "vol_ratio_year": 0,
        "year_grade_floor": 0,
        "vol_year_max": 0,
        "as_of": asof,
    }
    bars = load_bars(con, "2383", n=220)
    if bars:
        from scripts.biaoke_bottom_vol_observe_screen import score_bottom_vol

        # force paint with computed floors even if not in wash zone
        vols = [b[5] for b in bars]
        floor, ymax = year_grade_floor(vols[-YEAR_LOOKBACK:])
        low60 = min(b[3] for b in bars[-60:])
        hi120 = max(b[2] for b in bars[-120:])
        c = bars[-1][4]
        teach_hit.update(
            {
                "close": c,
                "low_60": low60,
                "dist_to_low_pct": round((c - low60) / low60 * 100, 2),
                "drawdown_pct": round((hi120 - c) / hi120 * 100, 2),
                "year_grade_floor": floor,
                "vol_year_max": ymax,
                "vol_ratio_year": round(bars[-1][5] / ymax, 3) if ymax else 0,
            }
        )
        out = OUT / "TW_2383_teach_ref.png"
        paint(teach_hit, bars, prop, out)
        paths.append(str(out))
        print("painted teach_ref 2383", out)
        _ = score_bottom_vol  # silence lint
    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "as_of": asof,
                "n": len(payload.get("hits") or []),
                "charts": paths,
                "buy_signal": False,
                "vol_rule": "year_grade = max(0.70*year_max, p92)",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
