# -*- coding: utf-8 -*-
"""導航圖量柱：有官方量要畫得出；缺量不准造假。"""
import math

import numpy as np
import pandas as pd

from wayne_navigator import format_nav_volume_label, nav_volume_bar_heights


def test_format_nav_volume_label_missing_is_que():
    assert format_nav_volume_label(None) == "量 缺"
    assert format_nav_volume_label(float("nan")) == "量 缺"
    assert format_nav_volume_label(1798) == "量 1,798張"
    assert format_nav_volume_label(0) == "量 0張"


def test_nav_volume_every_positive_day_at_least_12pct():
    """有官方正量＝肉眼可見（至少面板 12%）；暴量日不把低量壓沒。"""
    vols = [294.0] * 20 + [13426.0, 12000.0] + [598.0] * 20 + [0.0, float("nan")]
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert ylim < 13426.0
    pos = [i for i, v in enumerate(vols) if v == v and v > 0]
    for i in pos:
        assert float(heights[i]) >= ylim * 0.12 - 1e-9, (i, heights[i], ylim)
    # 尖峰日最高（裁到頂）
    assert float(heights[20]) == ylim
    # 真 0／缺量不准假柱
    assert float(heights[-2]) == 0.0
    assert float(heights[-1]) == 0.0
    assert bool(missing[-1]) is True
    # 低量彼此仍有比例（更大的量柱更高）
    assert float(heights[22]) > float(heights[0])


def test_nav_volume_missing_no_fake_bar():
    vols = pd.Series([1000.0, np.nan, 0.0, 500.0])
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert bool(missing[1]) is True
    assert float(heights[1]) == 0.0
    assert float(heights[2]) == 0.0  # 真 0 不抬假量
    assert float(heights[0]) >= ylim * 0.12 - 1e-9
    assert float(heights[3]) >= ylim * 0.12 - 1e-9
    assert ylim >= 1.0


def test_nav_volume_all_missing():
    heights, ylim, missing = nav_volume_bar_heights([math.nan, None])
    assert missing.all()
    assert float(heights.sum()) == 0.0
    assert ylim == 1.0
