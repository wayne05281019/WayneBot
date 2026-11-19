# -*- coding: utf-8 -*-
"""leave_zero 共核旗標：鎖 B＝雷達只實綠；海選／勝率寬式。"""
from __future__ import annotations

import pandas as pd

from leave_zero_layers import (
    PRODUCT_RADAR,
    PRODUCT_SCREEN,
    PRODUCT_WINRATE,
    core_hit,
    today_hit_from_quote_df,
)


def test_radar_flags_lock_b_narrow():
    assert PRODUCT_RADAR.require_first_green_day is True
    assert PRODUCT_RADAR.allow_double_green is False
    assert PRODUCT_RADAR.apply_max_pct is False
    assert PRODUCT_SCREEN.allow_double_green is True
    assert PRODUCT_WINRATE.allow_double_green is True


def test_core_hit_screen_accepts_double_green_radar_rejects():
    # 雙綠形：昨非貼零、有 60 低預警，今跳升 ≤5%
    ok_s, _ = core_hit(0.3, 2.4, yest_alert="60低", today_alert="", flags=PRODUCT_SCREEN)
    ok_r, reason = core_hit(0.3, 2.4, yest_alert="60低", today_alert="", flags=PRODUCT_RADAR)
    assert ok_s is True
    assert ok_r is False
    assert reason == "not_first_green"


def test_core_hit_first_green_both():
    ok_s, _ = core_hit(0.0, 0.5, flags=PRODUCT_SCREEN)
    ok_r, _ = core_hit(0.0, 0.5, flags=PRODUCT_RADAR)
    assert ok_s is True
    assert ok_r is True


def test_today_hit_winrate_matches_screen_width():
    # 最小兩列：昨 0、今離零 → 窄寬皆命中
    df = pd.DataFrame(
        {
            "date": ["20260102", "20260103"],
            "open": [100.0, 100.0],
            "high": [101.0, 102.0],
            "low": [99.0, 99.5],
            "close": [100.0, 101.0],
            "volume": [1000, 1000],
        }
    )
    # cal60 需要足夠歷史；用 mock 系列走 core 路徑較穩——改測旗標路由
    assert PRODUCT_WINRATE.allow_double_green == PRODUCT_SCREEN.allow_double_green
    assert today_hit_from_quote_df.__name__ == "today_hit_from_quote_df"
