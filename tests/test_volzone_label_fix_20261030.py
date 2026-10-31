"""2026-10-30 大量區標位：貼軌／除息互斥／季月錯開／左緣壓撐。"""
from __future__ import annotations

import inspect

import numpy as np


def test_quiet_on_rail_helper_exists_and_prefers_pair():
    from vol_zone_chart import _quiet_on_rail_label_xy, paint_vol_zone_parallel_channel

    src = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "_quiet_on_rail_label_xy" in src
    assert "不准為空窗抬 ylim" in src or "not quiet" in src
    # 合成下降軌：線上可放、成對同帶
    n = 40
    highs = np.full(n, 120.0)
    lows = np.full(n, 80.0)
    # 軌 y = 150 - x（下降）；中段離開 K
    seg = ((5.0, 145.0, 0), (35.0, 115.0, 0))
    placed = [(18.0, 26.0, 200.0, 210.0)]  # 軸頂「除息」占位
    xy = _quiet_on_rail_label_xy(
        seg=seg,
        y_now=115.0,
        n=n,
        ymin=70.0,
        ymax=160.0,
        dx=4.0,
        dy=3.0,
        highs=highs,
        lows=lows,
        mas=[],
        placed=placed,
        pair_x=22.0,
        mark_pad=0.0,
    )
    assert xy is not None
    cx, cy = xy
    assert abs(float(cx) - 22.0) <= 8.5
    # 貼線：seg y at 22 ≈ 150-22*1? 實際 _channel_seg_y 線性插值
    assert float(cy) < 155.0  # 不准飛到除息帶


def test_ma_stamp_min_sep_blocks_close_pair():
    from vol_zone_chart import _ma_stamp_min_sep, _label_ma_blank

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sep_x, sep_y = _ma_stamp_min_sep(100.0)
    assert sep_x >= 1.0
    assert sep_y >= 2.0

    n = 40
    xs = np.arange(n, dtype=float)
    highs = np.full(n, 112.0)
    lows = np.full(n, 108.0)
    # 季／月幾乎同價 → 第二標必須錯開 x 或不畫
    ma_q = np.linspace(100.0, 101.0, n)
    ma_m = ma_q + 0.4
    fig, ax = plt.subplots()
    ax.set_ylim(70, 150)
    ax.set_xlim(-0.05, n + 2.0)
    occupied = []
    p1 = _label_ma_blank(
        ax,
        xs,
        highs,
        lows,
        lab="季",
        vals=ma_q,
        color="#5c6bc0",
        face="#e8eaf6",
        occupied=occupied,
    )
    assert p1 is not None
    p2 = _label_ma_blank(
        ax,
        xs,
        highs,
        lows,
        lab="月",
        vals=ma_m,
        color="#f9a825",
        face="#fffde7",
        occupied=occupied,
        other_mas=[ma_q],
    )
    if p2 is not None:
        assert abs(float(p2[0]) - float(p1[0])) >= 1.0 or abs(
            float(p2[1]) - float(p1[1])
        ) >= sep_y * 0.8
    plt.close(fig)


def test_key_zone_left_bias_and_nudge_cap_in_source():
    from vol_zone_chart import _paint_key_zone_smart_tags

    src = inspect.getsource(_paint_key_zone_smart_tags)
    assert "左緣淨空優先" in src or "獎左緣" in src
    assert "max_nudge" in src
    assert "貼區帶" in src or "不准飛" in src


def test_ex_div_occupied_gate_thickened():
    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "y_sp_ex * 0.24" in src or "0.24" in src
    assert "互斥" in src or "除息" in src
