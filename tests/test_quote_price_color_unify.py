# -*- coding: utf-8 -*-
"""查股四張圖：今收／昨收／漲跌／台股紅綠同源（含 ETF 0050／平盤）。"""
from __future__ import annotations

import inspect

from biaoke_chart import _px, _px_quote
from wayne_navigator import (
    LOOKUP_CANDLE_DN,
    LOOKUP_CANDLE_UP,
    LOOKUP_QUOTE_FLAT,
    _fmt_price,
    quote_move_ink,
)


def test_px_quote_keeps_etf_official_close():
    """0050 官方收 114.8：不准現股 0.5 跳動改寫成 115。"""
    assert _px(114.8) == "115"  # 舊跳動仍只服務演算軌
    assert _px_quote(114.8) == "114.8"
    assert _px_quote(114.80) == _fmt_price(114.80) == "114.8"
    assert _px_quote(114.95) == _fmt_price(114.95) == "115"
    # 一般股千元以上仍同源
    assert _px_quote(17460) == "17,460"
    assert _px_quote(233.5) == "233.5"


def test_quote_move_ink_up_down_flat():
    assert quote_move_ink(-0.15, close=114.8, prev=114.95) == LOOKUP_CANDLE_DN
    assert quote_move_ink(0.55, close=116.5, prev=115.95) == LOOKUP_CANDLE_UP
    assert quote_move_ink(0.0, close=100.0, prev=100.0) == LOOKUP_QUOTE_FLAT
    assert quote_move_ink(close=100.0, prev=100.0) == LOOKUP_QUOTE_FLAT
    assert quote_move_ink(pct=-0.13, close=114.8, prev=114.95) == LOOKUP_CANDLE_DN


def test_structure_spot_uses_px_quote_and_move_ink():
    import biaoke_chart as bc

    spot_src = inspect.getsource(bc._paint_spot)
    loc_src = inspect.getsource(bc._paint_locator_quote)
    for src in (spot_src, loc_src):
        assert "_px_quote(close)" in src
        assert "quote_move_ink" in src
        assert "candle_up_taiwan" not in src
    paint_src = inspect.getsource(bc.render_biaoke_structure_png)
    # 右軸當日價跟決策卡 quote 同源；盤中「現價」、收盤「今收」
    assert 'f"{close_tag} {_px_quote(last_c)}"' in paint_src
    assert 'f"昨收 {_px_quote(prev_c_axis)}"' in paint_src
    assert 'f"今收 {_px(last_c)}"' not in paint_src


def test_volzone_header_close_follows_move_ink_not_hard_red():
    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "quote_move_ink" in src
    assert "close_ink" in src
    assert "close_bit" in src
    # 不准再寫死 color=_UP 畫收字
    assert "color=_UP,\n            zorder=13" not in src


def test_lookup_entries_are_shared_new_face():
    """試渲／話筒第三四張：只認 render_lookup_*（橫式新版），不准另開舊直式臉。"""
    from three_in_one_chart import render_lookup_structure_result
    from vol_zone_chart import render_lookup_vol_result

    vol_src = inspect.getsource(render_lookup_vol_result)
    assert "lookup_portrait=False" in vol_src
    assert "with_ma5_ma10=True" in vol_src
    assert "with_nav_signals=True" in vol_src
    st_src = inspect.getsource(render_lookup_structure_result)
    assert "_STRUCTURE_LOOKUP_FIG" in st_src
    assert "render_biaoke_structure_png" in st_src
