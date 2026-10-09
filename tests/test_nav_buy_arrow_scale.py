# -*- coding: utf-8 -*-
"""買點藍向上箭＝原尺寸 1.5 倍（全圖一致）。"""
from __future__ import annotations

import inspect

import wayne_navigator as wn


def test_buy_arrow_scale_is_1_5x_original():
    assert wn._NAV_BUY_ARROW_H_MULT == 1.68  # 1.12 * 1.5
    assert wn._NAV_BUY_ARROW_HW == 1.05  # 寬略收，高仍 1.5×
    assert wn._NAV_BUY_ARROW_EDGE == "#C62828"
    assert wn._NAV_BUY_ARROW_EDGE_W >= 2.0  # 手機縮圖紅框要夠粗
    assert wn._NAV_BUY_ARROW_ALPHA_FIRST == 1.0
    assert 0.50 <= wn._NAV_BUY_ARROW_ALPHA_FOLLOW < 1.0
    # 導航／大量區共用 _paint_nav_buy_arrows；兩端只呼叫不再各寫常數
    shared = inspect.getsource(wn._paint_nav_buy_arrows)
    assert "_NAV_BUY_ARROW_H_MULT" in shared and "_NAV_BUY_ARROW_EDGE" in shared
    assert "_nav_buy_arrow_alphas" in shared
    ov = inspect.getsource(wn.overlay_nav_marks_on_zone)
    paint = inspect.getsource(wn._paint_nav_on_axes)
    assert "_paint_nav_buy_arrows" in ov
    assert "_paint_nav_buy_arrows" in paint
    # 賣箭／60 低維持原尺寸公式；買點只走常數
    assert "arrow_h * 1.12" in ov
    assert "arrow_h * 1.12" in paint
    arrow_src = inspect.getsource(wn._nav_arrow)
    assert "edgewidth" in arrow_src
    leg = inspect.getsource(wn._draw_nav_legend)
    assert "買點↑藍▲紅框" in leg
    assert "_NAV_BUY_ARROW_EDGE" in leg
    marks = inspect.getsource(wn._nav_trade_marks)
    assert "paint_leave_zero_indices" in marks or "leave_zero_bar_indices" in marks
    assert "should_exclude_buy" in marks or "paint_leave_zero_indices" in marks
    assert "buy_is" in marks