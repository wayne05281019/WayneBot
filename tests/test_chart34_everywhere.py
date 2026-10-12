# -*- coding: utf-8 -*-
"""第三／四張新版面全面套用：話筒路徑不准殘留舊旗／舊入口。"""
from __future__ import annotations

import inspect


def test_volzone_default_ma5_ma10_on():
    from vol_zone_chart import render_lookup_vol_result, render_volume_zone_result

    sig = inspect.signature(render_volume_zone_result)
    assert sig.parameters["with_ma5_ma10"].default is True
    lookup = inspect.getsource(render_lookup_vol_result)
    assert "with_ma5_ma10=True" in lookup
    assert "lookup_portrait=False" in lookup


def test_phone_volzone_entries_share_new_face():
    """查股／壓撐／勝率／大盤：同一新臉（5／10 開或走 lookup 共用入口）。"""
    from bot_servers import WayneTelegramBot
    from index_kline_chart import build_market_vol_zone_chart
    from winrate_buypoint import render_page_pairs

    locked = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "render_lookup_vol_result" in locked
    assert "render_lookup_structure_result" in locked

    pressure = inspect.getsource(WayneTelegramBot._run_pressure_support)
    assert "render_lookup_vol_result" in pressure
    assert "with_ma5_ma10=False" not in pressure

    trio = inspect.getsource(WayneTelegramBot._send_pressure_stock_trio)
    assert "render_lookup_vol_result" in trio
    assert "with_ma5_ma10=False" not in trio

    wr = inspect.getsource(render_page_pairs)
    assert "with_ma5_ma10=True" in wr

    mkt = inspect.getsource(build_market_vol_zone_chart)
    assert "with_ma5_ma10=True" in mkt
    assert "render_volume_zone_result" in mkt


def test_structure_entries_share_figsize_and_dpi():
    """查股／飆大／三合一內嵌：同一 figsize＋VOL_ZONE_DPI。"""
    from biaoke_chart import build_biaoke_structure_chart
    from three_in_one_chart import render_lookup_structure_result
    import three_in_one_chart as tio

    lookup = inspect.getsource(render_lookup_structure_result)
    assert "render_biaoke_structure_png" in lookup
    assert "_STRUCTURE_LOOKUP_FIG" in lookup
    assert "VOL_ZONE_DPI" in lookup

    build = inspect.getsource(build_biaoke_structure_chart)
    assert "render_biaoke_structure_png" in build
    assert "_STRUCTURE_LOOKUP_FIG" in build
    assert "VOL_ZONE_DPI" in build
    assert "dpi=" in build

    compose = inspect.getsource(tio._apply_patches_and_render)
    assert "render_biaoke_structure_png" in compose
    assert "_STRUCTURE_LOOKUP_FIG" in compose
    assert "VOL_ZONE_DPI" in compose
    assert "dpi=" in compose


def test_chart_batch_paint_defaults_ma5_ma10():
    from chart_batch import paint_volume_zones_serial, render_volume_zones_two_phase

    sig = inspect.signature(paint_volume_zones_serial)
    assert sig.parameters["with_ma5_ma10"].default is True
    src = inspect.getsource(paint_volume_zones_serial)
    assert "with_ma5_ma10=with_ma5_ma10" in src
    tw = inspect.getsource(render_volume_zones_two_phase)
    assert "with_ma5_ma10=with_ma5_ma10" in tw
