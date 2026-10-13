# -*- coding: utf-8 -*-
"""導航／壓力圖量柱：資料層＝官方量；畫圖層開方；軸標稀疏真張數；不准挖洞。"""
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from wayne_navigator import (
    LOOKUP_VOL_AXIS_MAX_TICKS,
    LOOKUP_VOL_DISPLAY_POWER,
    LOOKUP_VOL_FLOOR_FACE,
    LOOKUP_VOL_FLOOR_FRAC,
    LOOKUP_VOL_MIN_VISIBLE_FRAC,
    configure_lookup_vol_axis,
    format_nav_volume_label,
    lookup_vol_axis_true_ticks,
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
    vols = [294.0] * 20 + [13426.0, 12000.0] + [598.0] * 20 + [0.0, float("nan")]
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert ylim == 13426.0
    assert float(heights[20]) == 13426.0
    assert float(heights[22]) > float(heights[0])
    assert float(heights[-2]) == 0.0
    assert bool(missing[-1]) is True
    assert float(heights[0]) < ylim * 0.12


def test_lookup_vol_sqrt_texture():
    assert abs(LOOKUP_VOL_DISPLAY_POWER - 0.5) < 1e-12
    vmax = 9962.0
    d_low = float(lookup_vol_to_display([294.0], vmax)[0])
    d_mid = float(lookup_vol_to_display([2000.0], vmax)[0])
    d_max = float(lookup_vol_to_display([vmax], vmax)[0])
    assert abs(d_max - vmax) < 1e-6
    assert d_mid > d_low > 0
    assert abs(lookup_vol_from_display(d_mid, vmax) - 2000.0) < 1e-3


def test_lookup_vol_axis_sparse_flexible_ticks():
    """量大＝1/3/5/7/9千 或 2/4/6/8/1萬；不准 0/1k/2k/3k/4k 每千一檔。"""
    for vmax in (9962.0, 9073.0, 6757.0):
        ticks = lookup_vol_axis_true_ticks(vmax)
        assert ticks[0] == 0.0
        assert abs(ticks[-1] - vmax) < 1e-6
        assert 3 <= len(ticks) <= LOOKUP_VOL_AXIS_MAX_TICKS
        mids = [v for v in ticks if 0 < v < vmax * 0.98]
        assert mids
        steps = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
        if steps:
            assert min(steps) >= 2000 - 1e-6
        oddish = all(int(round(v)) % 2000 == 1000 for v in mids)
        evenish = all(int(round(v)) % 2000 == 0 for v in mids)
        assert oddish or evenish, (vmax, ticks)
        disp = [float(lookup_vol_to_display([v], vmax)[0]) for v in ticks]
        gaps = [disp[i + 1] - disp[i] for i in range(len(disp) - 1)]
        assert min(gaps) >= vmax * 0.15 - 1e-9, (vmax, ticks, min(gaps) / vmax)
    ticks = lookup_vol_axis_true_ticks(9962.0)

    small = lookup_vol_axis_true_ticks(450.0)
    assert small[0] == 0.0
    assert 3 <= len(small) <= LOOKUP_VOL_AXIS_MAX_TICKS
    assert max(small) == 450.0

    fig, ax = plt.subplots(figsize=(3, 1.5))
    configure_lookup_vol_axis(ax, 9962.0)
    ax.set_ylim(0, 9962.0 * 1.2)
    labels = [t.get_text() for t in ax.get_yticklabels() if t.get_text()]
    assert "0" in labels
    assert len(labels) <= LOOKUP_VOL_AXIS_MAX_TICKS
    assert "2,000" not in labels or "4,000" in labels  # 若有偶千就成對疏列
    assert not ({"1,000", "2,000", "3,000", "4,000"} <= set(labels))
    plt.close(fig)


def test_nav_volume_missing_no_fake_bar():
    vols = pd.Series([1000.0, np.nan, 0.0, 500.0])
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert bool(missing[1]) is True
    assert float(heights[1]) == 0.0
    assert float(heights[2]) == 0.0
    assert ylim == 1000.0


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


def test_paint_lookup_volume_sqrt_keeps_relative_texture():
    fig, ax = plt.subplots(figsize=(4, 1.2))
    xs = list(range(5))
    vols = [13426.0, 426.0, 500.0, 2000.0, 0.0]
    up = [True, False, True, False, True]
    heights, ylim, missing = paint_lookup_volume_bars(ax, xs, vols, up, halt=[False] * 5)
    assert float(ylim) == 13426.0
    assert float(heights[1]) == 426.0
    draw_at = {}
    for p in ax.patches:
        cx = int(round(float(p.get_x()) + float(p.get_width()) / 2.0))
        draw_at[cx] = max(draw_at.get(cx, 0.0), float(p.get_height()))
    assert abs(draw_at[0] - 13426.0) < 1e-6
    assert draw_at[3] > draw_at[2] > draw_at[1] > 0
    assert draw_at[1] > float(ylim) * LOOKUP_VOL_FLOOR_FRAC
    labels = [t.get_text() for t in ax.get_yticklabels() if t.get_text()]
    assert len(labels) <= LOOKUP_VOL_AXIS_MAX_TICKS
    plt.close(fig)


def test_paint_lookup_volume_floor_bars_no_holes():
    fig, ax = plt.subplots(figsize=(4, 1.2))
    xs = list(range(6))
    vols = [1000.0, 0.0, float("nan"), 500.0, 0.0, 800.0]
    up = [True, False, True, False, True, False]
    halt = [False, True, False, False, False, False]
    heights, ylim, missing = paint_lookup_volume_bars(ax, xs, vols, up, halt=halt)
    assert float(ylim) == 1000.0
    assert float(heights[1]) == 0.0
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
    plt.close(fig)


def test_min_visible_frac_not_flat_clamp():
    assert LOOKUP_VOL_MIN_VISIBLE_FRAC <= 0.05
    assert LOOKUP_VOL_FLOOR_FRAC < LOOKUP_VOL_MIN_VISIBLE_FRAC
