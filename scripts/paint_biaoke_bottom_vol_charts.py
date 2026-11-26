#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量價落底圖：大量＋由尾回推（今日漲→近低新開始→往回試五波）。

觀察用，非買訊；回推標「起/1/2/3/4/終」僅定義結構，非話筒浪號認證。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from scripts.biaoke_bottom_vol_observe_screen import YEAR_LOOKBACK, year_grade_floor
from scripts.biaoke_tail_back_five_wave import analyze_bars

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "wayne_market.db"
HITS = (
    ROOT
    / "docs"
    / "expert_notes"
    / "飆客"
    / "decade_lab"
    / "biaoke_bottom_vol_observe_20261126.json"
)
OUT = Path("/opt/cursor/artifacts/biaoke_bottom_vol_1126_v3")


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


def load_bars(con: sqlite3.Connection, sid: str, n: int = 280) -> List[dict]:
    rows = con.execute(
        "SELECT date,open,high,low,close,volume FROM daily_quotes "
        "WHERE stock_id=? ORDER BY date DESC LIMIT ?",
        (sid, n),
    ).fetchall()
    out = []
    for d, o, h, l, c, v in reversed(rows):
        out.append(
            {
                "date": str(d),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
            }
        )
    return out


STYLE_ZH = {
    "year_grade_consec": "連續一年級巨量（2383型）",
    "sediment": "籌碼沉澱（2330型）",
    "both": "連續一年級＋沉澱",
    "year_grade_near_low": "近低一年級巨量",
}


def paint(hit: Dict[str, Any], bars: List[dict], prop, out_path: Path) -> Dict[str, Any]:
    bars = bars[-220:] if len(bars) > 220 else bars
    xs = list(range(len(bars)))
    opens = [b["open"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]
    dates = [b["date"] for b in bars]

    floor = float(hit.get("year_grade_floor") or 0)
    ymax = float(hit.get("vol_year_max") or max(vols or [1]))
    if floor <= 0:
        floor, ymax = year_grade_floor(vols[-min(len(vols), YEAR_LOOKBACK) :])
    low60 = float(hit["low_60"])

    tb = analyze_bars(bars)
    tb_d = tb.as_dict()

    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(12.2, 8.2), gridspec_kw={"height_ratios": [3.25, 1.15]}, sharex=True
    )
    bg = "#f7f5f0"
    fig.patch.set_facecolor(bg)
    for a in (ax, axv):
        a.set_facecolor(bg)
        a.tick_params(colors="#333")
        for sp in a.spines.values():
            sp.set_color("#bbbbbb")
        a.grid(True, color="#e6e2da", lw=0.6, zorder=0)

    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        up = c >= o
        col = "#d64545" if up else "#2f9e6b"
        ax.vlines(i, l, h, color=col, lw=1.0, zorder=2)
        body_lo, body_hi = min(o, c), max(o, c)
        height = max(body_hi - body_lo, (max(highs) - min(lows)) * 0.0015)
        ax.add_patch(
            Rectangle((i - 0.38, body_lo), 0.76, height, facecolor=col, edgecolor=col, zorder=3)
        )

    ax.axhline(low60, color="#c9184a", ls="-", lw=1.35, alpha=0.8, label=f"近60低 {low60:.2f}")

    # 新開始：今日漲 → 連回前低
    if tb.new_start is not None:
        ns = tb.new_start
        ax.scatter([ns.i], [ns.price], s=90, c="#2563eb", zorder=8, marker="D", label="新開始低")
        # 連到今日收
        ax.plot(
            [ns.i, len(bars) - 1],
            [ns.price, closes[-1]],
            color="#2563eb",
            lw=2.4,
            ls="-",
            zorder=7,
            label="今日漲連回近低",
        )
        ax.annotate(
            "新開始",
            xy=(ns.i, ns.price),
            xytext=(6, -18),
            textcoords="offset points",
            color="#1d4ed8",
            fontsize=10,
            fontweight="bold",
            fontproperties=prop,
        )

    # 由低往回五波
    pts = tb.five_points or []
    labels = ["起", "1", "2", "3", "4", "終"]
    if len(pts) >= 2:
        col = "#7b2cbf" if tb.ok_five else "#9a3412"
        ax.plot(
            [p.i for p in pts],
            [p.price for p in pts],
            color=col,
            lw=3.0 if tb.ok_five else 2.0,
            zorder=6,
            label=("由尾回推五波（可定義）" if tb.ok_five else "由尾回推（未過五波檢核）"),
        )
        for k, p in enumerate(pts[:6]):
            lab = labels[k] if k < len(labels) else str(k)
            ax.scatter([p.i], [p.price], s=42, c=col, zorder=9, edgecolors="#fff", linewidths=0.7)
            ax.annotate(
                f"{lab}\n{p.price:.0f}",
                xy=(p.i, p.price),
                xytext=(0, 12 if p.kind == "H" else -22),
                textcoords="offset points",
                ha="center",
                color=col,
                fontsize=8,
                fontweight="bold",
                fontproperties=prop,
            )

    # 量：一年級
    for i, (v, o, c) in enumerate(zip(vols, opens, closes)):
        col = "#d64545" if c >= o else "#2f9e6b"
        yg = v >= floor - 1e-9
        axv.bar(i, v, width=0.72, color=col, alpha=0.95 if yg else 0.35, zorder=2)
        if yg:
            axv.plot(i, v, "o", ms=9, mfc="none", mec="#2563eb", mew=1.8, zorder=6)
            axv.annotate(
                "一年級",
                xy=(i, v),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                color="#1d4ed8",
                fontsize=7,
                fontproperties=prop,
            )
    axv.axhline(floor, color="#ea580c", ls="--", lw=1.2)
    axv.text(
        0.01,
        0.92,
        f"一年級門檻 {floor:.0f}（年最大 {ymax:.0f}）",
        transform=axv.transAxes,
        color="#c2410c",
        fontsize=8,
        fontproperties=prop,
    )

    style_zh = STYLE_ZH.get(hit["style"], hit["style"])
    five_zh = "五波可定義" if tb.ok_five else ("有新開始／五波未過" if tb.ok_new_start else "今日未漲無新開始")
    title = f"{hit['stock_id']} {hit['stock_name']}｜{style_zh}｜{five_zh}"
    sub = (
        f"asof {hit.get('as_of','')}｜收 {hit['close']}｜距60低 {hit['dist_to_low_pct']}%｜"
        f"量/年最大 {hit['vol_ratio_year']}×｜{tb.note_zh or tb.fail_reason_zh}｜觀察非買訊"
    )
    ax.set_title(title, color="#1a1a1a", fontsize=13, pad=10, fontproperties=prop)
    ax.text(0.0, 1.02, sub, transform=ax.transAxes, color="#555", fontsize=8.2, fontproperties=prop)
    ax.legend(loc="upper left", fontsize=7.5, framealpha=0.92)
    ax.set_ylabel("價", fontproperties=prop)
    axv.set_ylabel("量", fontproperties=prop)
    step = max(1, len(bars) // 10)
    axv.set_xticks(xs[::step])
    axv.set_xticklabels([d[4:6] + "/" + d[6:8] for d in dates[::step]], fontsize=8)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=145, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return tb_d


def main() -> int:
    prop = _cjk_prop()
    payload = json.loads(HITS.read_text(encoding="utf-8"))
    asof = payload["as_of"]
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    paths = []
    enrich = []
    for hit in payload.get("hits") or []:
        hit = dict(hit)
        hit["as_of"] = asof
        bars = load_bars(con, hit["stock_id"], n=300)
        out = OUT / f"{hit['market']}_{hit['stock_id']}_{hit['style']}.png"
        tb = paint(hit, bars, prop, out)
        paths.append(str(out))
        enrich.append({"stock_id": hit["stock_id"], "tail_back": tb})
        print(
            "painted",
            hit["stock_id"],
            "new_start",
            tb.get("ok_new_start"),
            "five",
            tb.get("ok_five"),
            out,
        )

    # 教圖對照 2330／2383（即使不在命中也畫）
    for sid, name, style in (("2330", "台積電", "sediment"), ("2383", "台光電", "year_grade_consec")):
        bars = load_bars(con, sid, n=300)
        if not bars:
            continue
        vols = [b["volume"] for b in bars]
        floor, ymax = year_grade_floor(vols[-YEAR_LOOKBACK:])
        low60 = min(b["low"] for b in bars[-60:])
        hi120 = max(b["high"] for b in bars[-120:])
        c = bars[-1]["close"]
        h = {
            "stock_id": sid,
            "stock_name": name,
            "market": "TW",
            "style": style,
            "close": c,
            "low_60": low60,
            "dist_to_low_pct": round((c - low60) / low60 * 100, 2),
            "drawdown_pct": round((hi120 - c) / hi120 * 100, 2),
            "year_grade_floor": floor,
            "vol_year_max": ymax,
            "vol_ratio_year": round(bars[-1]["volume"] / ymax, 3) if ymax else 0,
            "as_of": asof,
        }
        out = OUT / f"TW_{sid}_teach_tailback.png"
        tb = paint(h, bars, prop, out)
        paths.append(str(out))
        enrich.append({"stock_id": sid, "tail_back": tb, "role": "teach_ref"})
        print("teach", sid, "five", tb.get("ok_five"), out)

    payload["tail_back_method_zh"] = (
        "先一年級大量；今日上漲則連回前幾日低點＝新開始；"
        "由該低往回試畫五波（起-1-2-3-4-終）。觀察定義用，非買訊／非話筒浪認證。"
    )
    payload["tail_back_enrich"] = enrich
    HITS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = HITS.parent / "biaoke_bottom_vol_observe_latest.json"
    latest.write_text(HITS.read_text(encoding="utf-8"), encoding="utf-8")

    (OUT / "manifest.json").write_text(
        json.dumps(
            {"as_of": asof, "charts": paths, "buy_signal": False, "method": "tail_back_five"},
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
