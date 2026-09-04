# -*- coding: utf-8 -*-
from decision_card_signals import (
    double_green_breakout,
    format_profit_pct,
    is_profit_display_zero,
    leave_zero_screen_ok,
    profit_left_zero_highlight,
)


def test_profit_display_zero():
    assert is_profit_display_zero(0.0)
    assert is_profit_display_zero(0.04)
    assert not is_profit_display_zero(0.05)
    assert format_profit_pct(1.23) == "1.2%"


def test_profit_left_zero_matches_card_tests():
    # 對齊 test_profit_cell_uses_low_palette
    assert profit_left_zero_highlight(0.0, 0.9)
    assert not profit_left_zero_highlight(0.9, 1.5)


def test_double_green_breakout():
    assert double_green_breakout(0.0, "No", 1.2, "No")
    assert double_green_breakout(1.0, "60低", 2.0, "No")
    assert not double_green_breakout(1.0, "No", 2.0, "No")
    assert not double_green_breakout(0.0, "No", 0.0, "No")


def test_leave_zero_screen_caps_runners():
    ok, _ = leave_zero_screen_ok(0.0, 4.5)
    assert ok
    ok, reason = leave_zero_screen_ok(0.0, 5.2)
    assert not ok
    assert "5" in reason


def test_2383_carybot_profit_at_5295_vs_4100():
    """2026-09-04 Cary：收 5295、60曆日低 4100 → 獲利 29.1%，不得因貼20低歸零。"""
    pct = (5295.0 - 4100.0) / 4100.0 * 100.0
    assert abs(pct - 29.1) < 0.05
    assert format_profit_pct(pct) == "29.1%"
    assert not is_profit_display_zero(pct)
