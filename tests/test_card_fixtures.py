# -*- coding: utf-8 -*-
"""依使用者傳過的高低卡範本列（OCR 校準）— 海選驗收用。"""
from decision_card_signals import (
    card_row_leave_zero,
    leave_zero_screen_ok,
    parse_profit_display,
    profit_left_zero_highlight,
)


def test_parse_profit_display():
    assert parse_profit_display("0.0%") == 0.0
    assert parse_profit_display("10.0%") == 10.0
    assert parse_profit_display("No") is None


def test_template_2420_8_28_not_leave_zero():
    """範本卡：獲利已 10.0% — 不是起漲（你回饋的誤收型）。"""
    ok, _ = leave_zero_screen_ok(9.5, 10.0)
    assert not ok


def test_template_profit_green_cell():
    """色票範本：昨 0.0% → 今 0.9% 實綠。"""
    assert profit_left_zero_highlight(0.0, 0.9)
    hit, tag = card_row_leave_zero(0.0, 0.9)
    assert hit and "實綠" in tag
    ok, _ = leave_zero_screen_ok(0.0, 0.9)
    assert ok


def test_template_not_green_after_step():
    """色票範本：昨 0.9% → 今 1.5% 白底，不算剛離零。"""
    assert not profit_left_zero_highlight(0.9, 1.5)
    hit, _ = card_row_leave_zero(0.9, 1.5)
    assert not hit
