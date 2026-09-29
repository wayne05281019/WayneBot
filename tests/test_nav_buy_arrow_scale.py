# -*- coding: utf-8 -*-
"""買點藍向上箭＝原尺寸 1.5 倍（全圖一致）。"""
from __future__ import annotations

import inspect

import wayne_navigator as wn


def test_buy_arrow_scale_is_1_5x_original():
    assert wn._NAV_BUY_ARROW_H_MULT == 1.68  # 1.12 * 1.5
    assert wn._NAV_BUY_ARROW_HW == 1.32  # 0.88 * 1.5
    ov = inspect.getsource(wn.overlay_nav_marks_on_zone)
    paint = inspect.getsource(wn._paint_nav_on_axes)
    assert "_NAV_BUY_ARROW_H_MULT" in ov and "_NAV_BUY_ARROW_HW" in ov
    assert "_NAV_BUY_ARROW_H_MULT" in paint and "_NAV_BUY_ARROW_HW" in paint
    # 賣箭維持原尺寸
    assert "arrow_h * 1.12" in ov
    assert "arrow_h * 1.12" in paint
