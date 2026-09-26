# -*- coding: utf-8 -*-
"""決策卡股價顯示：千元以上不帶小數，避免版面擠爆。"""
from wayne_navigator import (
    _fmt_price,
    _fmt_price_signed,
    _trend_note_short,
    format_nav_volume_label,
    quote_limit_chip_colors,
    quote_limit_side,
)


def test_fmt_price_no_decimals_for_thousand_plus():
    assert _fmt_price(17460) == "17,460"
    assert _fmt_price(17460.00) == "17,460"
    assert _fmt_price(15115.00) == "15,115"
    assert _fmt_price(1000) == "1,000"
    assert _fmt_price(999.5) == "999.5"
    assert _fmt_price(446.50) == "446.5"
    assert _fmt_price(446.0) == "446"
    assert _fmt_price(45.25) == "45.25"
    assert _fmt_price_signed(-390) == "-390"
    assert _fmt_price_signed(12.5) == "+12.5"


def test_trend_note_short():
    assert _trend_note_short("價未新低") == "未新低"
    assert _trend_note_short("價溫背離") == "背離"
    assert _trend_note_short("") == ""


def test_nav_volume_label_is_lots_not_k():
    """導航圖量是張。冷門 2 張不能寫成 0.00K。"""
    assert format_nav_volume_label(2) == "量 2張"
    assert format_nav_volume_label(14090) == "量 14,090張"
    assert format_nav_volume_label(0) == "量 0張"
    assert format_nav_volume_label(None) == "量 缺"


def test_quote_limit_side_only_limit_up_down():
    """3441 +10% 漲停；普通大漲不是。安瑞-KY 9.88% 一檔內算漲停。"""
    assert quote_limit_side(143, 130, 10.0) == "up"
    assert quote_limit_side(117, 130, -10.0) == "down"
    assert quote_limit_side(140, 130, 7.69) is None
    assert quote_limit_side(131, 130, 0.77) is None
    assert quote_limit_side(109.5, 100, 9.5) is None
    assert quote_limit_side(8.34, 7.59, 9.88) == "up"
    assert quote_limit_side(143, None, 10.0) == "up"
    assert quote_limit_side(143, None, 3.2) is None


def test_quote_limit_chip_colors_square_fill():
    up = quote_limit_chip_colors("up")
    dn = quote_limit_chip_colors("down")
    assert up[1] == "#FFFFFF"
    assert dn[1] == "#FFFFFF"
    assert up[0] != dn[0]
    assert quote_limit_chip_colors(None) is None


def test_paint_close_right_limit_chip_in_source():
    import inspect
    from wayne_navigator import _paint_close_right

    src = inspect.getsource(_paint_close_right)
    assert "_paint_limit_square_right" in src
    assert "quote_limit_chip_colors" in src
    assert "較昨日" in src
    assert "今K" in src
    assert "chg_y, move_body" not in src
