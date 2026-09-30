# -*- coding: utf-8 -*-
"""有股價出圖：查詢當下台北時間；一般股 13:30／興櫃 15:00 收盤標籤分開。"""
from __future__ import annotations

import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

from decision_card_signals import (
    board_close_clock_label,
    format_card_query_stamp,
    format_produced_clock,
    stamp_emerging_flag,
)


def test_regular_vs_emerging_close_labels():
    assert board_close_clock_label(emerging=False) == "13:30收盤"
    assert board_close_clock_label(emerging=True) == "15:00收盤"
    assert stamp_emerging_flag(quote_source="emerging_quotes")
    assert stamp_emerging_flag(listing="興櫃")
    assert not stamp_emerging_flag(listing="上市 半導體")


def test_regular_session_and_close():
    tz = ZoneInfo("Asia/Taipei")
    live = datetime(2026, 9, 4, 11, 8, tzinfo=tz)
    _, clock = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=live
    )
    assert clock == "盤中 11:08"
    after = datetime(2026, 9, 4, 13, 30, tzinfo=tz)
    _, clock = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=after
    )
    assert clock == "13:30收盤"


def test_emerging_between_1330_and_1500_is_query_now():
    tz = ZoneInfo("Asia/Taipei")
    mid = datetime(2026, 9, 4, 14, 45, tzinfo=tz)
    _, reg = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=mid, emerging=False
    )
    assert reg == "13:30收盤"
    _, em = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=mid, emerging=True
    )
    assert em == "盤中 14:45"
    _, em2 = format_card_query_stamp(
        is_live=False,
        latest_date="20260904",
        generated_at=mid,
        quote_source="emerging_quotes",
    )
    assert em2 == "盤中 14:45"
    assert "13:30" not in em2
    closed = datetime(2026, 9, 4, 15, 1, tzinfo=tz)
    _, em3 = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=closed, emerging=True
    )
    assert em3 == "15:00收盤"
    assert format_produced_clock(generated_at=mid, emerging=True) == "盤中 14:45"


def test_priced_chart_paths_pass_emerging_or_stock_id():
    import biaoke_chart
    import chips
    import industry_card
    import kline_hop
    import vol_zone_chart
    import wayne_navigator

    nav_src = inspect.getsource(wayne_navigator.draw_from_ohlc)
    assert "quote_source" in nav_src or "stock_id=" in nav_src
    card_src = inspect.getsource(wayne_navigator.render_decision_card_png)
    assert "emerging=" in card_src or "_card_is_emerging" in card_src
    glance_src = inspect.getsource(wayne_navigator.render_first_glance_png)
    assert "emerging=" in glance_src or "_card_is_emerging" in glance_src
    vz = inspect.getsource(vol_zone_chart._paint_volume_zone)
    assert "stock_id=" in vz or "quote_source" in vz
    hop = inspect.getsource(kline_hop)
    assert 'emerging=(market == "興櫃")' in hop or "emerging=" in hop
    assert "stock_id=" in inspect.getsource(biaoke_chart.render_biaoke_structure_png)
    assert "stock_id" in inspect.getsource(chips._chips_header_stamp)
    assert "stock_id=" in inspect.getsource(industry_card._flow_lines)
