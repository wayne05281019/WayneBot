# -*- coding: utf-8 -*-
"""導航／壓力圖量柱：資料層＝官方量；畫圖層分段縮放；缺量不准造假；不准挖洞。"""
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from wayne_navigator import (
    LOOKUP_VOL_FLOOR_FACE,
    LOOKUP_VOL_FLOOR_FRAC,
    LOOKUP_VOL_HINGE_PANEL_FRAC,
    LOOKUP_VOL_MIN_VISIBLE_FRAC,
    configure_lookup_vol_axis,
    format_nav_volume_label,
    lookup_vol_from_display,
    lookup_vol_hinge,
    lookup_vol_to_display,
    nav_volume_bar_heights,
    paint_lookup_volume_bars,
)


def test_format_nav_volume_label_missing_is_que():
    assert format_nav_volume_label(None) == "量 缺"
    assert format_nav_volume_label(float("nan")) == "量 缺"
    assert format_nav_volume_label(1798) == "量 1,798張"
    assert format_nav_volume_label(0) == "量 0張"


def test_nav_volume_linear_to_window_max():
    """資料層柱高＝官方量；最高＝ylim；真 0／缺＝0。畫圖層才分段。"""
    vols = [294.0] * 20 + [13426.0, 12000.0] + [598.0] * 20 + [0.0, float("nan")]
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert ylim == 13426.0
    assert float(heights[20]) == 13426.0
    assert abs(float(heights[21]) / ylim - 12000.0 / 13426.0) < 1e-9
    assert abs(float(heights[0]) / ylim - 294.0 / 13426.0) < 1e-9
    assert abs(float(heights[22]) / ylim - 598.0 / 13426.0) < 1e-9
    assert float(heights[22]) > float(heights[0])
    assert float(heights[-2]) == 0.0
    assert float(heights[-1]) == 0.0
    assert bool(missing[-1]) is True
    assert float(heights[0]) < ylim * 0.12


def test_lookup_vol_hinge_texture_and_even_axis():
    """分段：一般量線性可分；尖峰最高；軸標均勻真張數不擠。"""
    vmax = 13426.0
    vols = [294.0] * 30 + [598.0] * 30 + [2000.0] * 20 + [vmax, 12000.0]
    hinge = lookup_vol_hinge(vols, vmax)
    assert hinge < vmax * 0.92
    d_low = float(lookup_vol_to_display([294.0], vmax, hinge=hinge)[0])
    d_mid = float(lookup_vol_to_display([598.0], vmax, hinge=hinge)[0])
    d_hi = float(lookup_vol_to_display([2000.0], vmax, hinge=hinge)[0])
    d_max = float(lookup_vol_to_display([vmax], vmax, hinge=hinge)[0])
    assert d_max == vmax
    assert d_hi > d_mid > d_low > 0
    # 一般量落在下段面板內，相對線性
    panel_lo = LOOKUP_VOL_HINGE_PANEL_FRAC * vmax
    assert d_hi <= panel_lo + 1e-6
    assert abs(d_mid / d_low - 598.0 / 294.0) < 1e-6
    assert abs(lookup_vol_from_display(d_low, vmax, hinge=hinge) - 294.0) < 1e-4

    fig, ax = plt.subplots(figsize=(4, 1.5))
    configure_lookup_vol_axis(ax, vmax, hinge=hinge)
    ax.set_ylim(0, vmax * 1.1)
    ticks = list(ax.get_yticks())
    # 一般量區刻度顯示間距應大致均勻（不准 2k～7k 擠一團）
    main = [t for t in ticks if t <= panel_lo * 1.01]
    assert len(main) >= 3
    gaps = [main[i + 1] - main[i] for i in range(len(main) - 1)]
    assert max(gaps) / max(min(gaps), 1e-9) < 2.5
    labels = [t.get_text() for t in ax.get_yticklabels()]
    assert "0" in labels
    plt.close(fig)


def test_nav_volume_missing_no_fake_bar():
    vols = pd.Series([1000.0, np.nan, 0.0, 500.0])
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert bool(missing[1]) is True
    assert float(heights[1]) == 0.0
    assert float(heights[2]) == 0.0
    assert ylim == 1000.0
    assert float(heights[0]) == 1000.0
    assert float(heights[3]) == 500.0


def test_nav_volume_all_missing():
    heights, ylim, missing = nav_volume_bar_heights([math.nan, None])
    assert missing.all()
    assert float(heights.sum()) == 0.0
    assert ylim == 1.0


def test_nav_volume_proportional_pair():
    heights, ylim, _ = nav_volume_bar_heights([100.0, 200.0, 50.0])
    assert ylim == 200.0
    assert float(heights[1]) == 200.0
    assert float(heights[0]) == 100.0
    assert float(heights[2]) == 50.0


def test_paint_lookup_volume_hinge_keeps_relative_texture():
    """暴量撐軸後低正量仍見柱且彼此高度不同；資料層 heights 仍官方量。"""
    fig, ax = plt.subplots(figsize=(4, 1.2))
    xs = list(range(5))
    vols = [13426.0, 426.0, 500.0, 2000.0, 0.0]
    up = [True, False, True, False, True]
    heights, ylim, missing = paint_lookup_volume_bars(ax, xs, vols, up, halt=[False] * 5)
    assert float(ylim) == 13426.0
    assert float(heights[1]) == 426.0
    assert float(heights[2]) == 500.0
    hinge = float(getattr(ax, "_wayne_lookup_vol_hinge", ylim))
    draw_at = {}
    for p in ax.patches:
        cx = int(round(float(p.get_x()) + float(p.get_width()) / 2.0))
        draw_at[cx] = max(draw_at.get(cx, 0.0), float(p.get_height()))
    assert abs(draw_at[0] - 13426.0) < 1e-6
    assert draw_at[3] > draw_at[2] > draw_at[1] > 0
    # 426／500 若低於最低可視會進帶狀抬升，但仍保持相對高低，不准齊頭
    assert draw_at[2] - draw_at[1] > 1e-6
    floor_h = float(ylim) * LOOKUP_VOL_FLOOR_FRAC
    assert draw_at[1] > floor_h
    plt.close(fig)


def test_paint_lookup_volume_floor_bars_no_holes():
    """有槽必有柱：0 量／缺量／停價＝貼底灰短柱，不准挖洞。"""
    fig, ax = plt.subplots(figsize=(4, 1.2))
    xs = list(range(6))
    vols = [1000.0, 0.0, float("nan"), 500.0, 0.0, 800.0]
    up = [True, False, True, False, True, False]
    halt = [False, True, False, False, False, False]
    heights, ylim, missing = paint_lookup_volume_bars(ax, xs, vols, up, halt=halt)
    assert float(ylim) == 1000.0
    assert float(heights[1]) == 0.0
    assert bool(missing[2]) is True
    from matplotlib.colors import to_rgb

    floor_rgb = to_rgb(LOOKUP_VOL_FLOOR_FACE)
    floor_rects = []
    occupied = set()
    for p in ax.patches:
        if float(p.get_height()) <= 0:
            continue
        occupied.add(int(round(float(p.get_x()) + float(p.get_width()) / 2.0)))
        fc = p.get_facecolor()
        if isinstance(fc, tuple) and len(fc) >= 3:
            if all(abs(a - b) < 0.02 for a, b in zip(fc[:3], floor_rgb)):
                floor_rects.append(p)
                assert abs(float(p.get_height()) - float(ylim) * LOOKUP_VOL_FLOOR_FRAC) < 1e-6
    assert len(floor_rects) == 3
    assert occupied == {0, 1, 2, 3, 4, 5}
    pos_h = [
        float(p.get_height())
        for p in ax.patches
        if float(p.get_height()) > float(ylim) * LOOKUP_VOL_FLOOR_FRAC + 1e-6
    ]
    assert pos_h and min(pos_h) > float(ylim) * LOOKUP_VOL_FLOOR_FRAC
    plt.close(fig)


def test_min_visible_frac_not_flat_clamp():
    assert LOOKUP_VOL_MIN_VISIBLE_FRAC <= 0.05
    assert LOOKUP_VOL_FLOOR_FRAC < LOOKUP_VOL_MIN_VISIBLE_FRAC
