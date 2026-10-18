# -*- coding: utf-8 -*-
"""台股大盤日K：只疊飆大本人在 2026-10-16／10-17 還沒收回的位。

個股情境預估不走這裡。沒有把他沒寫的浪號、價、日期補進去。
「還有約 4000 點」沒有換成價。56000 是他 10/07 的測距，10/17 已當誤判，不上這張的現況區。
45000＝他 10/17 14:25 說「不是簡單45000就能止跌」，不是目標價。

視覺借 DC 情境預估臉（虛線未走路徑、浪標、粉 pin、演化帶、關鍵日豎線、右側紅價標）；
折線／位階／日期只認他自己說的，不准抄 DC 個股目標到大盤。

硬規則：演化標籤／帶／線不准壓到縮圖 K（一律 x > 最後一根）。
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

# DC 視覺臉（對齊 scenario_forecast_chart v4 配色；路徑內容仍是飆大）
_ZONE = "#ce93d8"
_CHANNEL = "#ba68c8"
_LINE = "#6a1b9a"
_INK = "#311b92"
_WAVE_PROJ = "#ffffff"
_WAVE_EDGE = "#1b5e20"  # 跌綠：未走下降虛線描邊（台股慣例）
_PIN = "#ff4081"
_TAG_HOT = "#e53935"
_DATE_RED = "#c62828"

# 演化區起點：最後一根右側，標籤／帶不准回蓋 K
_ZONE_PAD = 0.85


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
        "C-4 他改口 10/26 起或之後（折返・無高點）",
        "殺完他說多頭一年；過年後再下＝他沒說",
        "虛線＝未走（DC臉・走法是他的）",
    )


def _biaoke_dc_proj_path(
    last_i: float, last_close: float, steps: int | None
) -> list[tuple[float, float]]:
    """未走虛線折點：只經他自己點過的整數價＋官方最後收。不准發明中間價／反彈高。

    現況＝C-3-5（或 C-3-3）下行中 → 約45000不止跌 → 約39000（不見得破）收束未走。
    C-4 只有日期、沒有他給的反彈高，所以折線不往上拐（避免假價）。
    「過年後再往下」大盤句他沒說，不畫。
    """
    s = float(steps if steps is not None else 8)
    x0 = last_i + _ZONE_PAD
    x_nf = last_i + max(s * 0.55, 3.0)
    x_end = last_i + s + max(s * 1.15, 10.0)
    y0 = float(last_close)
    # 路徑從演化區起點接出（不從 K 棒心長標籤）
    pts: list[tuple[float, float]] = [(x0, y0)]
    if y0 > BROKE_LEVEL + 50.0:
        pts.append((last_i + max(s * 0.18, 1.2), float(BROKE_LEVEL)))
    pts.append((max(x_nf, x0 + 1.0), float(NOT_FLOOR)))
    pts.append((max(x_end, x0 + 2.0), float(ZONE_LO)))
    return pts


def _draw_map_pin(ax, x: float, y: float) -> None:
    ax.plot(x, y, marker="o", ms=7, color=_PIN, zorder=9, clip_on=True)
    ax.plot(
        x,
        y,
        marker="v",
        ms=11,
        color=_PIN,
        markeredgecolor="#c2185b",
        markeredgewidth=0.6,
        zorder=9,
        clip_on=True,
    )


def _draw_wave_dot(ax, x: float, y: float, label: str, *, fp, color: str) -> None:
    ax.plot(x, y, "o", ms=11.0, color=color, mfc="#fafafa", mew=1.55, zorder=8, clip_on=True)
    ax.annotate(
        label,
        xy=(x, y),
        xytext=(0, 11),
        textcoords="offset points",
        color=color,
        fontproperties=fp,
        ha="center",
        va="bottom",
        zorder=9,
        clip_on=True,
    )


def paint_biaoke_market_marks(ax, work) -> None:
    """演化／研發區只在最後一根右側。標籤不准壓縮圖 K。"""
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
    # 五月短窗：演化／研發區加寬；最後收右側＝研發區
    gutter = 22.0 if steps is None else float(max(steps + 20, 30))
    x_right = last_i + gutter
    lo = min(float(ax.get_ylim()[0]), ZONE_LO - 900.0)
    hi = max(float(ax.get_ylim()[1]), ZONE_HI + 2800.0)
    ax.set_ylim(lo, hi)
    ax.set_xlim(-0.8, x_right)

    x0 = last_i + _ZONE_PAD
    # 淡紫演化帶：只右側，不准蓋 K
    ax.fill_between(
        [x0, x_right - 0.25],
        [ZONE_LO, ZONE_LO],
        [ZONE_HI, ZONE_HI],
        color=_ZONE,
        alpha=0.22,
        zorder=1,
    )
    # 約39000 灰帶也只在右側
    ax.fill_between(
        [x0, x_right - 0.25],
        [ZONE_LO - 200.0, ZONE_LO - 200.0],
        [ZONE_LO + 900.0, ZONE_LO + 900.0],
        color="#9e9e9e",
        alpha=0.14,
        zorder=1,
    )

    from wayne_navigator import _fp

    fp = _fp(8, "bold")
    fp_s = _fp(7.5, "bold")
    fp_w = _fp(9.5, "bold")
    fp_d = _fp(7.2, "bold")

    # —— DC 未走虛線路徑（只經他的價；路徑在右側）——
    proj = _biaoke_dc_proj_path(last_i, last_close, steps)
    if len(proj) >= 2:
        # 細線從最後收接到演化區起點（無標籤），標籤只出現在 x>=x0
        ax.plot(
            [last_i, proj[0][0]],
            [last_close, proj[0][1]],
            color=_WAVE_EDGE,
            lw=0.9,
            ls=(0, (3, 3)),
            zorder=5,
            alpha=0.45,
            clip_on=True,
        )
        px = [p[0] for p in proj]
        py = [p[1] for p in proj]
        amp = max((max(py) - min(py)) * 0.10, abs(py[-1]) * 0.012)
        ax.fill_between(px, [y - amp for y in py], [y + amp for y in py], color=_CHANNEL, alpha=0.14, zorder=4)
        ax.plot(px, py, color="#212121", lw=2.55, ls=(0, (5, 3)), zorder=5, alpha=0.45, clip_on=True)
        ax.plot(px, py, color=_WAVE_PROJ, lw=1.75, ls=(0, (5, 3)), zorder=5, alpha=0.98, clip_on=True)
        ax.plot(px, py, color=_WAVE_EDGE, lw=1.05, ls=(0, (5, 3)), zorder=5, alpha=0.55, clip_on=True)

        # 浪標：整段落在右側（mid 至少 x0+1.2）
        a, b = proj[0], proj[1]
        mid_x = max((a[0] + b[0]) * 0.5, x0 + 1.2)
        mid_y = (a[1] + b[1]) * 0.5
        _draw_wave_dot(ax, mid_x, mid_y, "C-3-5", fp=fp_w, color=_INK)
        ax.text(
            mid_x + 1.15,
            mid_y - abs(hi - lo) * 0.028,
            "也可能C-3-3",
            color=_INK,
            fontproperties=fp_s,
            ha="left",
            va="top",
            zorder=8,
            clip_on=True,
            bbox=dict(boxstyle="round,pad=0.10", facecolor="#ffffff", edgecolor=_LINE, linewidth=0.5, alpha=0.92),
        )
        pin_450 = next((p for p in proj if abs(p[1] - NOT_FLOOR) < 1.0), None)
        if pin_450 is not None and pin_450[0] >= x0:
            _draw_map_pin(ax, pin_450[0], float(NOT_FLOOR))
        if proj[-1][0] >= x0:
            _draw_map_pin(ax, proj[-1][0], float(ZONE_LO))

    # 說明文案在研發區中段右側；紅價貼最右
    note_x = max(last_i + gutter * 0.48, x0 + 2.0)
    level_rows = (
        (ZONE_HI, "台指期48240　未站上仍空方"),
        (BROKE_LEVEL, "約47500　10/15他說破壞"),
        (NOT_FLOOR, "約45000　他說不止跌"),
        (ZONE_LO, "約39000　C不見得破"),
    )
    for price, text in level_rows:
        ax.plot(
            [x0, x_right - 0.4],
            [price, price],
            color=_LINE,
            lw=1.0,
            ls=(0, (4, 3)),
            zorder=6,
            clip_on=True,
        )
        ax.text(
            note_x,
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
        ax.text(
            x_right - 0.15,
            price,
            f"{int(price)}",
            color="#ffffff",
            fontproperties=fp_d,
            ha="right",
            va="center",
            zorder=8,
            clip_on=True,
            bbox=dict(boxstyle="round,pad=0.18", facecolor=_TAG_HOT, edgecolor="none", alpha=0.95),
        )

    if steps is not None:
        x_d = last_i + float(steps)
        if x_d >= x0:
            ax.axvline(x_d, color=_DATE_RED, lw=1.35, ls=(0, (3, 3)), zorder=6, clip_on=True)
            # 日期標在豎線右側（研發區內），不准往左壓 K
            ax.text(
                x_d + 0.35,
                (float(ZONE_HI) + float(BROKE_LEVEL)) * 0.5,
                "10/26\nC-4起或之後",
                color="#ffffff",
                fontproperties=fp,
                ha="left",
                va="center",
                zorder=7,
                clip_on=True,
                bbox=dict(boxstyle="round,pad=0.16", facecolor=_DATE_RED, edgecolor="none", alpha=0.95),
            )

    lines = market_wave_caption_lines(last_ymd)
    ax.text(
        x0 + 0.15,
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
