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


def test_nav_volume_soft_cap_keeps_low_days_visible():
    """3081 類：中間有暴量，低量日線性全高會被壓成看不到。"""
    vols = [800.0] * 40 + [12000.0, 11000.0] + [700.0] * 40
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert not missing.any()
    assert ylim < 12000.0  # 軟頂低於尖峰
    # 低量日柱高至少約面板 4%
    assert float(heights[0]) >= ylim * 0.04 - 1e-9
    # 尖峰裁到 ylim，不是發明更大的量
    assert float(heights[40]) == ylim
    assert float(heights[40]) <= 12000.0


def test_nav_volume_missing_no_fake_bar():
    vols = pd.Series([1000.0, np.nan, 0.0, 500.0])
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert bool(missing[1]) is True
    assert float(heights[1]) == 0.0
    assert float(heights[2]) == 0.0  # 真 0 不抬假量
    assert float(heights[0]) > 0.0
    assert float(heights[3]) > 0.0
    assert ylim >= 1.0


def test_nav_volume_all_missing():
    heights, ylim, missing = nav_volume_bar_heights([math.nan, None])
    assert missing.all()
    assert float(heights.sum()) == 0.0
    assert ylim == 1.0
