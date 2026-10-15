# -*- coding: utf-8 -*-
"""極端大賣→D+1～D+5：單位張、續危分標。"""
from __future__ import annotations

from foreign_sell_extreme import (
    ExtremeTrack,
    hit_continue_extreme,
    hit_price_dd,
    lit_extreme_day,
    price_drawdown_from_anchor,
    sync_same_day_crash,
    units_banner,
)


def test_units_lots():
    u = units_banner()
    assert u["lots_per_share"] == 1000
    assert u["volume_unit"] == "張"


def test_lit_lots_and_share():
    t = ExtremeTrack("lots", 1000)
    assert lit_extreme_day(
        t, foreign_net=-2500, volume=5000, foreign_nets_hist=[-2500], foreign_nets_10=[-2500]
    )
    t2 = ExtremeTrack("share", 0.2)
    assert lit_extreme_day(
        t2, foreign_net=-300, volume=1000, foreign_nets_hist=[-300], foreign_nets_10=[-300]
    )


def test_price_dd_hit():
    dd = price_drawdown_from_anchor(100.0, [99.0, 94.0, 96.0])
    assert dd is not None and abs(dd - (-0.06)) < 1e-9
    h = hit_price_dd(100.0, [99.0, 94.0, 96.0, 95.0, 97.0], k=5, thr_dd=-0.05)
    assert h["hit"] is True and h["tag"] == "cont_price_dd"
    h2 = hit_price_dd(100.0, [99.5, 99.0, 98.5, 99.0, 99.2], k=5, thr_dd=-0.05)
    assert h2["hit"] is False


def test_continue_extreme_and_sync():
    h = hit_continue_extreme([False, True, False], k=3)
    assert h["hit"] is True and h["hit_day_offset"] == 2
    h2 = hit_continue_extreme([False, False, False, False, False], k=5)
    assert h2["hit"] is False
    assert sync_same_day_crash(open_=100, close=94) is True
    assert sync_same_day_crash(open_=100, close=98) is False
