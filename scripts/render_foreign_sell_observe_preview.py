#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本機試渲：外資觀察標（測試版橘六角）對圖。不碰 Telegram。"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd


def _fake_bars(n: int = 90, end: str = "20261014") -> list:
    from datetime import datetime, timedelta

    end_d = datetime.strptime(end, "%Y%m%d")
    rows = []
    px = 100.0
    for i in range(n):
        d = end_d - timedelta(days=n - 1 - i)
        # 略過週末
        while d.weekday() >= 5:
            d -= timedelta(days=1)
            end_d = d if i == n - 1 else end_d
        o = px
        c = px + (1.2 if i % 3 else -0.8)
        h = max(o, c) + 1.5
        lo = min(o, c) - 1.2
        rows.append(
            {
                "date": d.strftime("%Y%m%d"),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(lo, 2),
                "close": round(c, 2),
                "volume": 5000 + i * 10,
                "is_halt": False,
            }
        )
        px = c
    # 重新標連續交易日
    out = []
    px = 100.0
    day = datetime.strptime(end, "%Y%m%d")
    calendar = []
    while len(calendar) < n:
        if day.weekday() < 5:
            calendar.append(day.strftime("%Y%m%d"))
        day -= timedelta(days=1)
    calendar = list(reversed(calendar))
    for i, d in enumerate(calendar):
        o = px
        c = px + (1.2 if i % 3 else -0.8)
        h = max(o, c) + 1.5
        lo = min(o, c) - 1.2
        out.append(
            {
                "date": d,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(lo, 2),
                "close": round(c, 2),
                "volume": 5000 + i * 10,
                "is_halt": False,
            }
        )
        px = c
    return out


def main() -> int:
    out_dir = os.environ.get(
        "FS_PREVIEW_OUT",
        "/opt/cursor/artifacts/foreign-sell-observe-preview",
    )
    os.makedirs(out_dir, exist_ok=True)

    # 畫 mark 對照：直接用 navigator paint
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from foreign_sell_display import OBSERVE_LABEL, display_mode_banner
    from wayne_navigator import (
        _fp,
        _paint_foreign_sell_observe_marks,
        _paint_stabilize_marks,
    )

    bars = _fake_bars(80)
    df = pd.DataFrame(bars)
    n = len(df)
    xs = np.arange(n, dtype=float)
    fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
    for i in range(n):
        o, h, lo, c = (
            float(df["open"].iloc[i]),
            float(df["high"].iloc[i]),
            float(df["low"].iloc[i]),
            float(df["close"].iloc[i]),
        )
        color = "#e53935" if c >= o else "#43a047"
        ax.plot([xs[i], xs[i]], [lo, h], color=color, lw=1.0)
        ax.plot([xs[i], xs[i]], [o, c], color=color, lw=3.2)
    span = float(df["high"].max() - df["low"].min())
    gap = span * 0.034
    # 止穩◆ 在倒數第 5；外資觀察六角在最新
    _paint_stabilize_marks(ax, df, [n - 5], xs, arrow_gap=gap, span=span)
    _paint_foreign_sell_observe_marks(ax, df, [n - 1], xs, arrow_gap=gap, span=span)
    ax.set_title(
        f"外資觀察標對照（測試）　{OBSERVE_LABEL}六角 vs 止穩◆　非買訊\n{display_mode_banner()}",
        fontproperties=_fp(11, "bold"),
    )
    ax.set_xlim(-1, n)
    path = os.path.join(out_dir, "observe-mark-vs-stabilize.png")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print("wrote", path)

    # 文案預覽
    from foreign_sell_display import (
        market_env_section_lines,
        morning_observe_line_html,
    )

    text_path = os.path.join(out_dir, "copy-preview.txt")
    with open(text_path, "w", encoding="utf-8") as f:
        f.write("=== 早報一行（無 tape → 今無）===\n")
        f.write(morning_observe_line_html(":memory:", "20261014") + "\n\n")
        f.write("=== 大盤環境段（空庫）===\n")
        f.write("\n".join(market_env_section_lines(":memory:", "20261014")) + "\n")
    print("wrote", text_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
