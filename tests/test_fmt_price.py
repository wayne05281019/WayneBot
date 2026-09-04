# -*- coding: utf-8 -*-
"""決策卡股價顯示：千元以上不帶小數，避免版面擠爆。"""
from wayne_navigator import _fmt_price, _fmt_price_signed, _trend_note_short


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
