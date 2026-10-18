# -*- coding: utf-8 -*-
"""台股大盤日K：只疊飆大本人在 2026-10-16／10-17 還沒收回的位。

個股情境預估不走這裡。沒有把他沒寫的浪號、價、日期補進去。
「還有約 4000 點」沒有換成價。56000 是他 10/07 的測距，10/17 已當誤判，不上這張的現況區。
45000＝他 10/17 14:25 說「不是簡單45000就能止跌」，不是目標價。
"""
from __future__ import annotations

from datetime import datetime, timedelta

# 他寫出來的整數。39000＝「39000左右」。48240 他註明是台指期。
ZONE_LO = 39000.0
ZONE_HI = 48240.0
BROKE_LEVEL = 47500.0
# 10/17 14:25：不是簡單45000就能止跌（回「急殺比緩跌好」）
NOT_FLOOR = 45000.0
DATE_YMD = "20261026"
_ZONE = "#ce93d8"
_LINE = "#6a1b9a"
_INK = "#311b92"


def weekday_steps(start_ymd: str, end_ymd: str) -> int | None:
    """start 之後、到 end 為止的週一到週五天數。對不上就不要畫豎線。"""
    try:
        start = datetime.strptime(str(start_ymd)[:8], "%Y%m%d")
        end = datetime.strptime(str(end_ymd)[:8], "%Y%m%d")
    except ValueError:
        return None
    if end <= start:
        return None
    n = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
        if n > 40:
            return None
    return n or None


def market_wave_caption_lines(session_ymd: str) -> tuple[str, ...]:
    stamp = ""
    raw = str(session_ymd or "")[:8]
    if len(raw) == 8 and raw.isdigit():
        stamp = f"{raw[:4]}/{raw[4:6]}/{raw[6:8]}"
    head = f"官方日K至 {stamp}" if stamp else "官方日K"
    return (
        head,
        "他說 10/17　C-3-5 行進中",
        "5 還沒止跌；也可能還在 C-3-3",
        "C-4 他改口 10/26 起或之後",
    )


def paint_biaoke_market_marks(ax, work) -> None:
    """演化區畫在最後一根的右側，不蓋 K 棒上的價。加權收盤不在大盤區間就不畫。"""
    if work is None or len(work) < 2:
        return
    try:
        last_close = float(work["close"].iloc[-1])
    except (TypeError, ValueError, KeyError):
        return
    if not (20000.0 <= last_close <= 80000.0):
        return
    n = len(work)
    last_i = float(n - 1)
    last_ymd = str(work["date"].iloc[-1])[:8]
    steps = weekday_steps(last_ymd, DATE_YMD)
    gutter = 16.0 if steps is None else float(max(steps + 10, 16))
    x_right = last_i + gutter
    lo = min(float(ax.get_ylim()[0]), ZONE_LO - 700.0)
    hi = max(float(ax.get_ylim()[1]), ZONE_HI + 3200.0)
    ax.set_ylim(lo, hi)
    ax.set_xlim(-0.8, x_right)

    x0 = last_i + 0.55
    ax.fill_between(
        [x0, x_right - 0.25],
        [ZONE_LO, ZONE_LO],
        [ZONE_HI, ZONE_HI],
        color=_ZONE,
        alpha=0.28,
        zorder=1,
    )
    from wayne_navigator import _fp

    fp = _fp(8, "bold")
    fp_s = _fp(7.5, "bold")
    label_x = (last_i + float(steps) + 0.6) if steps is not None else (x0 + 1.2)
    for price, text in (
        (ZONE_HI, "台指期48240　未站上仍空方"),
        (BROKE_LEVEL, "約47500　10/15他說破壞"),
        (NOT_FLOOR, "約45000　他說不止跌"),
        (ZONE_LO, "約39000　C不見得破"),
    ):
        ax.plot(
            [x0, x_right - 0.4],
            [price, price],
            color=_LINE,
            lw=1.0,
            ls=(0, (4, 3)),
            zorder=6,
        )
        ax.text(
            label_x,
            price,
            text,
            color=_INK,
            fontproperties=fp_s,
            va="bottom",
            ha="left",
            zorder=7,
            clip_on=True,
            bbox=dict(boxstyle="round,pad=0.12", facecolor="#f3e5f5", edgecolor="none", alpha=0.94),
        )
    if steps is not None:
        x_d = last_i + float(steps)
        ax.axvline(x_d, color="#546e7a", lw=1.15, ls=(0, (3, 3)), zorder=6)
        ax.text(
            x_d,
            ZONE_HI + 1400.0,
            "10/26",
            color="#37474f",
            fontproperties=fp,
            ha="center",
            va="bottom",
            zorder=7,
            clip_on=True,
            bbox=dict(boxstyle="round,pad=0.12", facecolor="#ffffff", edgecolor="none", alpha=0.92),
        )
    try:
        last_high = float(work["high"].iloc[-1])
    except (TypeError, ValueError, KeyError):
        last_high = last_close
    if ZONE_HI > last_high + 400:
        tag_y = (last_high + ZONE_HI) / 2.0
    else:
        tag_y = last_high + 280.0
    ax.text(
        x0,
        tag_y,
        "C-3-5",
        color=_INK,
        fontproperties=fp,
        ha="left",
        va="center",
        zorder=8,
        clip_on=True,
        bbox=dict(boxstyle="round,pad=0.12", facecolor="#ffffff", edgecolor=_LINE, linewidth=0.6),
    )
    lines = market_wave_caption_lines(last_ymd)
    ax.text(
        x0,
        hi - (hi - lo) * 0.01,
        "\n".join(lines),
        color=_INK,
        fontproperties=fp_s,
        ha="left",
        va="top",
        zorder=8,
        clip_on=True,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="#f3e5f5", edgecolor="#ce93d8", linewidth=0.6),
    )
