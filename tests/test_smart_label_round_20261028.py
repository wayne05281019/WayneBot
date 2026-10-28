"""2026-10-28 智能標籤：昨收誤導／壓撐擋尾K／爆大量擋紫箭／淡灰藍趨勢線。"""
from __future__ import annotations

import inspect


def test_close_tag_clearance_widened_for_prev_close():
    from biaoke_chart import _CLOSE_TAG_CANDLE_CLEAR, _close_tags_lower_right_y

    assert float(_CLOSE_TAG_CANDLE_CLEAR) >= 11.0
    # 6213 級中價：錨點必須明顯低於現價，不准落在 750 現價帶
    ay = _close_tags_lower_right_y(350.0, 1000.0, avoid_price=778.0)
    assert ay < 620.0
    assert abs(ay - 778.0) >= 140.0


def test_structure_skips_near_end_spike_vline():
    import biaoke_chart as bc

    src = inspect.getsource(bc.render_biaoke_structure_png)
    assert "n) - 6" in src or "n - 6" in src
    assert "當日價" in src or "尾端虛線" in src
    # 量圖末日豎虛線已刪（貼昨收會誤導）
    assert "ax2.axvline(n - 0.45" not in src


def test_structure_prev_close_gutter_hline():
    from biaoke_chart import _place_right_notes

    src = inspect.getsource(_place_right_notes)
    assert "true_prev_y" in src
    assert "短水平虛線" in src or "真昨收價" in src
    assert "gutter_x0" in src


def test_volzone_tail_crush_and_short_zone_sep():
    from vol_zone_chart import _paint_key_zone_smart_tags

    src = inspect.getsource(_paint_key_zone_smart_tags)
    assert "tail0" in src
    assert "4.2" in src
    assert "短大量區" in src or "need * 0.55" in src
    assert "不准預設釘末日右溝" in src or "偏左" in src


def test_volzone_ochre_keeps_below_signal_row():
    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "_vol_callout_cap" in src
    assert "clip_on=True" in src
    assert "紫箭" in src or "訊號列" in src


def test_stock_quiet_trend_rail_constants():
    from vol_zone_chart import (
        _STOCK_TREND_RAIL_COLOR,
        _STOCK_TREND_RAIL_DASH,
        _STOCK_TREND_RAIL_LW,
        paint_vol_zone_parallel_channel,
        render_lookup_vol_result,
    )

    assert _STOCK_TREND_RAIL_COLOR == "#8aa0b4"
    assert float(_STOCK_TREND_RAIL_LW) <= 1.2
    assert isinstance(_STOCK_TREND_RAIL_DASH, tuple)
    assert "with_parallel_channel=True" in inspect.getsource(render_lookup_vol_result)
    psrc = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "quiet_rails" in psrc
    assert "draw_markers=False" in psrc
