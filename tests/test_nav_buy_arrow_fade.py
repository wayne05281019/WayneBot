# -*- coding: utf-8 -*-
"""導航買點：同一段剛離零帶第一根清楚、後續淡（不改 leave_zero 公式）。"""
from __future__ import annotations

import inspect

import wayne_navigator as wn


def test_nav_buy_band_first_full_follow_faded():
    alphas = wn._nav_buy_arrow_alphas([10, 11, 12, 50, 51, 80])
    assert alphas[10][0] == wn._NAV_BUY_ARROW_ALPHA_FIRST
    assert alphas[11][0] == wn._NAV_BUY_ARROW_ALPHA_FOLLOW
    assert alphas[12][0] == wn._NAV_BUY_ARROW_ALPHA_FOLLOW
    assert alphas[50][0] == wn._NAV_BUY_ARROW_ALPHA_FIRST
    assert alphas[51][0] == wn._NAV_BUY_ARROW_ALPHA_FOLLOW
    assert alphas[80][0] == wn._NAV_BUY_ARROW_ALPHA_FIRST
    # 後續紅框略濃於本體，仍同種藍▲紅框
    assert alphas[11][1] == wn._NAV_BUY_ARROW_EDGE_ALPHA_FOLLOW
    assert wn._NAV_BUY_ARROW_ALPHA_FOLLOW < wn._NAV_BUY_ARROW_ALPHA_FIRST
    assert wn._NAV_BUY_ARROW_ALPHA_FOLLOW >= 0.38  # 再淡仍可辨；紅框另濃
    assert wn._NAV_BUY_ARROW_EDGE_ALPHA_FOLLOW > wn._NAV_BUY_ARROW_ALPHA_FOLLOW
    assert 0.75 <= wn._NAV_BUY_ARROW_FOLLOW_H_MULT < 1.0  # 後續略矮、首根主位


def test_paint_nav_buy_arrows_uses_band_alphas():
    src = inspect.getsource(wn._paint_nav_buy_arrows)
    assert "_nav_buy_arrow_alphas" in src
    assert "edge_alpha" in src
    assert "不改公式" in src
    arrow = inspect.getsource(wn._nav_arrow)
    assert "edge_alpha" in arrow
    # 公式本體仍在 decision_card_signals／buy_exclude，不在 paint
    marks = inspect.getsource(wn._nav_trade_marks)
    assert "paint_leave_zero_indices" in marks or "leave_zero_bar_indices" in marks
