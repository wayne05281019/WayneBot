#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飆客大盤／細微波：用庫內指數＋台指期畫圖存檔，對照他口述的位階。"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 飆客口述位階（台指期點數；現貨加權約低 50～150 點）
BIAOKE_LEVELS: Dict[str, Tuple[float, str]] = {
    "46746": (46746.0, "穿刺才不走9段（更正）"),
    "46300": (46300.0, "夜盤突破帶上緣"),
    "46250": (46250.0, "夜盤突破帶下緣／橫盤分界"),
    "45415": (45415.0, "前波低／修正目標"),
    "45450": (45450.0, "大盤現貨對應約略"),
    "44210": (44210.0, "更深前低（9段走完才清楚）"),
}


def _load_series(db_path: str, table: str, symbol: str) -> List[Tuple[str, float, float, float]]:
    conn = sqlite3.connect(db_path)
    try:
        if table == "futures_daily":
            rows = conn.execute(
                """
                SELECT date, close, high, low FROM futures_daily
                WHERE symbol=? AND session='regular' ORDER BY date
                """,
                (symbol,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT date, close, close, close FROM index_daily
                WHERE symbol=? ORDER BY date
                """,
                (symbol,),
            ).fetchall()
    finally:
        conn.close()
    out = []
    for d, c, h, lo in rows:
        out.append((str(d), float(c or 0), float(h or c or 0), float(lo or c or 0)))
    return out


def _zigzag_swings(
    rows: List[Tuple[str, float, float, float]],
    *,
    min_move_pct: float = 1.2,
) -> List[Dict[str, Any]]:
    """簡化 zigzag：交替高低點，供「段數」粗估（非艾略特認證）。"""
    if len(rows) < 3:
        return []
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    pivots: List[Dict[str, Any]] = [{"i": 0, "date": dates[0], "price": closes[0], "kind": "start"}]
    direction = 0  # 1 up leg, -1 down leg
    last_pivot_price = closes[0]
    last_pivot_i = 0
    for i in range(1, len(closes)):
        chg = (closes[i] - last_pivot_price) / last_pivot_price * 100.0 if last_pivot_price else 0
        if direction >= 0 and chg <= -min_move_pct:
            pivots.append({"i": i, "date": dates[i], "price": closes[i], "kind": "low"})
            direction = -1
            last_pivot_price = closes[i]
            last_pivot_i = i
        elif direction <= 0 and chg >= min_move_pct:
            pivots.append({"i": i, "date": dates[i], "price": closes[i], "kind": "high"})
            direction = 1
            last_pivot_price = closes[i]
            last_pivot_i = i
        elif direction > 0 and closes[i] > last_pivot_price:
            last_pivot_price = closes[i]
            pivots[-1] = {"i": i, "date": dates[i], "price": closes[i], "kind": "high"}
        elif direction < 0 and closes[i] < last_pivot_price:
            last_pivot_price = closes[i]
            pivots[-1] = {"i": i, "date": dates[i], "price": closes[i], "kind": "low"}
    if pivots[-1]["i"] != len(closes) - 1:
        pivots.append(
            {"i": len(closes) - 1, "date": dates[-1], "price": closes[-1], "kind": "last"}
        )
    return pivots


def _count_down_legs(pivots: List[Dict[str, Any]], lookback: int = 12) -> int:
    """最近 lookback 個轉折裡，連續下跌腿數（收→收為負的區間）。"""
    if len(pivots) < 2:
        return 0
    sub = pivots[-lookback:]
    down = 0
    for a, b in zip(sub, sub[1:]):
        if float(b["price"]) < float(a["price"]):
            down += 1
    return down


def render_chart(
    db_path: str,
    out_path: str,
    *,
    days: int = 60,
    title_suffix: str = "",
) -> Dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    fut = _load_series(db_path, "futures_daily", "TX")[-days:]
    idx = _load_series(db_path, "index_daily", "TWII")[-days:]
    if not fut:
        raise RuntimeError("futures_daily 無資料，請先 sync_futures_daily")

    pivots = _zigzag_swings(fut)
    down_legs = _count_down_legs(pivots)

    # 中文字型
    for fam in ("Noto Sans CJK TC", "WenQuanYi Micro Hei", "DejaVu Sans"):
        if fam in {f.name for f in font_manager.fontManager.ttflist} or fam == "DejaVu Sans":
            plt.rcParams["font.sans-serif"] = [fam, "DejaVu Sans"]
            break
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)
    x_f = [datetime.strptime(d, "%Y%m%d") for d, *_ in fut]
    y_f = [c for _, c, _, _ in fut]
    ax.plot(x_f, y_f, color="#1f77b4", linewidth=1.8, label="台指近月收盤 (TX)")

    if idx:
        x_i = [datetime.strptime(d, "%Y%m%d") for d, *_ in idx]
        y_i = [c for _, c, _, _ in idx]
        ax.plot(x_i, y_i, color="#ff7f0e", linewidth=1.2, alpha=0.85, label="加權現貨 (TWII)")

    colors = {
        "46746": "#d62728",
        "46300": "#d62728",
        "46250": "#ff9896",
        "45415": "#2ca02c",
        "45450": "#98df8a",
        "44210": "#9467bd",
    }
    for key, (price, note) in BIAOKE_LEVELS.items():
        ax.axhline(price, color=colors.get(key, "#888"), linestyle="--", linewidth=0.9, alpha=0.75)
        ax.text(
            x_f[0],
            price,
            f" {key} {note}",
            fontsize=7,
            va="bottom",
            color=colors.get(key, "#444"),
        )

    for p in pivots[-10:]:
        if p["kind"] in ("high", "low"):
            dt = datetime.strptime(p["date"], "%Y%m%d")
            ax.scatter([dt], [p["price"]], s=28, c="#333", zorder=5)

    ax.set_title(f"飆客大盤位階對照｜庫內官方融合{title_suffix}")
    ax.set_ylabel("點數")
    ax.legend(loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.25)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)

    last_f = fut[-1]
    meta = {
        "as_of_futures": last_f[0],
        "futures_close": last_f[1],
        "zigzag_down_legs_recent": down_legs,
        "pivot_count": len(pivots),
        "biaoke_claimed_down_legs": 7,
        "note": "zigzag 段數僅粗估，需與飆客圖手動對齊",
    }
    return meta


def main() -> None:
    import sys

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    parser.add_argument("--out", default="docs/expert_notes/飆客/charts/index_levels_latest.png")
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    from config import get_db_path

    db = args.db or get_db_path()
    meta = render_chart(db, args.out, days=args.days)
    print(args.out)
    for k, v in meta.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
