# -*- coding: utf-8 -*-
"""導航／壓力圖量柱：資料層＝官方量；畫圖層開方起伏；缺量不准造假；不准挖洞。"""
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from wayne_navigator import (
    LOOKUP_VOL_DISPLAY_POWER,
    LOOKUP_VOL_FLOOR_FACE,
    LOOKUP_VOL_FLOOR_FRAC,
    LOOKUP_VOL_MIN_VISIBLE_FRAC,
    format_nav_volume_label,
    lookup_vol_from_display,
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
    """資料層柱高＝官方量；最高＝ylim；真 0／缺＝0。畫圖層才開方。"""
    vols = [294.0] * 20 + [13426.0, 12000.0] + [598.0] * 20 + [0.0, float("nan")]
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert ylim == 13426.0
    assert float(heights[20]) == 13426.0
    assert abs(float(heights[21]) / ylim - 12000.0 / 13426.0) < 1e-9
    assert abs(float(heights[0]) / ylim - 294.0 / 13426.0) < 1e-9
    assert abs(float(heights[22]) / ylim - 598.0 / 13426.0) < 1e-9
    # 低量彼此仍有比例（更大的量柱更高）
    assert float(heights[22]) > float(heights[0])
    # 真 0／缺量不准假柱（資料層）；畫圖層另用貼底短柱佔槽
    assert float(heights[-2]) == 0.0
    assert float(heights[-1]) == 0.0
    assert bool(missing[-1]) is True
    # 資料層不准 soft-cap／平方根把尖峰裁矮或把低量抬高
    assert float(heights[0]) < ylim * 0.12


def test_lookup_vol_display_sqrt_texture():
    """開方顯示：爆大量仍最高；一般量日彼此可分，不准齊頭平線。"""
    assert abs(LOOKUP_VOL_DISPLAY_POWER - 0.5) < 1e-12
    vmax = 13426.0
    low, mid = 294.0, 598.0
    d_low, d_mid, d_max = lookup_vol_to_display([low, mid, vmax], vmax)
    assert abs(float(d_max) - vmax) < 1e-6
    assert float(d_mid) > float(d_low) > 0
    # 相對線性：低量被抬高可見，但仍低於中量、尖峰
    assert float(d_low) / vmax > low / vmax
    assert float(d_low) / vmax < 0.25
    assert float(d_mid) / vmax < float(d_max) / vmax
    # 反變換還原真量（軸標用）
    assert abs(lookup_vol_from_display(float(d_low), vmax) - low) < 1e-4
    assert abs(lookup_vol_from_display(float(d_mid), vmax) - mid) < 1e-4
    assert abs(lookup_vol_from_display(vmax, vmax) - vmax) < 1e-4


def test_nav_volume_missing_no_fake_bar():
    vols = pd.Series([1000.0, np.nan, 0.0, 500.0])
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert bool(missing[1]) is True
    assert float(heights[1]) == 0.0
    assert float(heights[2]) == 0.0  # 真 0 不抬假量
    assert ylim == 1000.0
    assert float(heights[0]) == 1000.0
    assert float(heights[3]) == 500.0


def test_nav_volume_all_missing():
    heights, ylim, missing = nav_volume_bar_heights([math.nan, None])
    assert missing.all()
    assert float(heights.sum()) == 0.0
    assert ylim == 1.0


def test_nav_volume_proportional_pair():
    """資料層：兩倍量＝兩倍柱高。"""
    heights, ylim, _ = nav_volume_bar_heights([100.0, 200.0, 50.0])
    assert ylim == 200.0
    assert float(heights[1]) == 200.0
    assert float(heights[0]) == 100.0
    assert float(heights[2]) == 50.0


def test_paint_lookup_volume_sqrt_keeps_relative_texture():
    """暴量撐軸後低正量仍見柱且彼此高度不同；資料層 heights 仍官方量。"""
    fig, ax = plt.subplots(figsize=(4, 1.2))
    xs = list(range(4))
    vols = [13426.0, 426.0, 500.0, 0.0]
    up = [True, False, True, False]
    heights, ylim, missing = paint_lookup_volume_bars(ax, xs, vols, up, halt=[False] * 4)
    assert float(ylim) == 13426.0
    assert float(heights[1]) == 426.0
    assert float(heights[2]) == 500.0
    draw_at = {}
    for p in ax.patches:
        cx = int(round(float(p.get_x()) + float(p.get_width()) / 2.0))
        draw_at[cx] = max(draw_at.get(cx, 0.0), float(p.get_height()))
    # 尖峰滿高；426 vs 500 開方後仍可分（不准夾成同一 min_h）
    assert abs(draw_at[0] - 13426.0) < 1e-6
    assert draw_at[2] > draw_at[1] > 0
    exp1 = float(lookup_vol_to_display([426.0], ylim)[0])
    exp2 = float(lookup_vol_to_display([500.0], ylim)[0])
    assert abs(draw_at[1] - exp1) < 1e-6
    assert abs(draw_at[2] - exp2) < 1e-6
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
    assert float(heights[1]) == 0.0  # 資料層不抬假量
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
    assert len(floor_rects) == 3  # idx 1 halt/0、2 nan、4 zero
    assert occupied == {0, 1, 2, 3, 4, 5}
    # 灰短柱要比正量開方柱矮
    pos_h = [
        float(p.get_height())
        for p in ax.patches
        if float(p.get_height()) > float(ylim) * LOOKUP_VOL_FLOOR_FRAC + 1e-6
    ]
    assert pos_h and min(pos_h) > float(ylim) * LOOKUP_VOL_FLOOR_FRAC
    plt.close(fig)


def test_min_visible_frac_not_flat_clamp():
    """最低可視不准再回到舊的 0.10 齊頭夾。"""
    assert LOOKUP_VOL_MIN_VISIBLE_FRAC <= 0.05
    assert LOOKUP_VOL_FLOOR_FRAC < LOOKUP_VOL_MIN_VISIBLE_FRAC
