# -*- coding: utf-8 -*-
"""導航／壓力圖量柱：視窗內高度 ∝ 官方量；缺量不准造假。"""
import math

import numpy as np
import pandas as pd

from wayne_navigator import format_nav_volume_label, nav_volume_bar_heights


def test_format_nav_volume_label_missing_is_que():
    assert format_nav_volume_label(None) == "量 缺"
    assert format_nav_volume_label(float("nan")) == "量 缺"
    assert format_nav_volume_label(1798) == "量 1,798張"
    assert format_nav_volume_label(0) == "量 0張"


def test_nav_volume_linear_to_window_max():
    """視窗內柱高 ∝ 官方量；最高＝滿高；真 0／缺＝平坦。"""
    vols = [294.0] * 20 + [13426.0, 12000.0] + [598.0] * 20 + [0.0, float("nan")]
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert ylim == 13426.0
    assert float(heights[20]) == 13426.0
    assert abs(float(heights[21]) / ylim - 12000.0 / 13426.0) < 1e-9
    assert abs(float(heights[0]) / ylim - 294.0 / 13426.0) < 1e-9
    assert abs(float(heights[22]) / ylim - 598.0 / 13426.0) < 1e-9
    # 低量彼此仍有比例（更大的量柱更高）
    assert float(heights[22]) > float(heights[0])
    # 真 0／缺量不准假柱
    assert float(heights[-2]) == 0.0
    assert float(heights[-1]) == 0.0
    assert bool(missing[-1]) is True
    # 不准 soft-cap／平方根把尖峰裁矮或把低量抬高
    assert float(heights[0]) < ylim * 0.12


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
    """兩倍量＝兩倍柱高。"""
    heights, ylim, _ = nav_volume_bar_heights([100.0, 200.0, 50.0])
    assert ylim == 200.0
    assert float(heights[1]) == 200.0
    assert float(heights[0]) == 100.0
    assert float(heights[2]) == 50.0
