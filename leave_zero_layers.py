# -*- coding: utf-8 -*-
"""leave_zero 共核＋產品後置旗標（公式本體仍在 decision_card_signals）。

2026-11-19 使用者鎖 B：話筒「剛脫離零」＝只認實綠首日（拒雙綠、離零當日不卡 5%）。
海選／勝率仍吃寬母閘 leave_zero_screen_ok（含雙綠＋≤5%）。
三套產品層不准互判定義壞；靜默下一版用新 kind，不准覆寫 pick=0／rule。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class LeaveZeroLayerFlags:
    """產品後置旗標；改旗標＝新靜默軌，不准默默改現況鍵。"""

    allow_double_green: bool
    apply_max_pct: bool
    require_first_green_day: bool
    # 以下為產品臉說明／對質分層用；本模組 core_hit 不強制執行全部
    vol_or_l20_gate: bool = False
    trend_hard_gate: bool = False
    block_short_high5: bool = False
    radar_quality: bool = False
    apply_buy_exclude: bool = False
    require_chart_paint: bool = False
    ai_ecosystem_only: bool = False
    include_emerging: bool = False
    listed_4digit_only: bool = False


# 海選黃金買點桶（寬共核＋量／趨勢／短高）
PRODUCT_SCREEN = LeaveZeroLayerFlags(
    allow_double_green=True,
    apply_max_pct=True,
    require_first_green_day=False,
    vol_or_l20_gate=True,
    trend_hard_gate=True,
    block_short_high5=True,
    listed_4digit_only=True,
)

# 剛脫離零雷達（鎖 B：窄＝實綠首日）
PRODUCT_RADAR = LeaveZeroLayerFlags(
    allow_double_green=False,
    apply_max_pct=False,
    require_first_green_day=True,
    radar_quality=True,
    apply_buy_exclude=True,
    include_emerging=True,
)

# 勝率買點（寬共核＋圖▲＋exclude＋AI）
PRODUCT_WINRATE = LeaveZeroLayerFlags(
    allow_double_green=True,
    apply_max_pct=True,
    require_first_green_day=False,
    apply_buy_exclude=True,
    require_chart_paint=True,
    ai_ecosystem_only=True,
    include_emerging=True,
)

# 靜默下一版 kind（未過閘不准改話筒）
SILENT_KIND_SCREEN = "lz_layer_screen_vnext"
SILENT_KIND_RADAR = "lz_layer_radar_vnext"
SILENT_KIND_WINRATE = "lz_layer_winrate_vnext"


def core_hit(
    yest_profit: float,
    today_profit: float,
    *,
    yest_alert: str = "",
    today_alert: str = "",
    flags: LeaveZeroLayerFlags,
) -> Tuple[bool, str]:
    """獲利母閘：依旗標走實綠首日或海選寬式。"""
    from decision_card_signals import leave_zero_screen_ok, profit_left_zero_highlight

    if flags.require_first_green_day or not flags.allow_double_green:
        if not profit_left_zero_highlight(yest_profit, today_profit):
            return False, "not_first_green"
        return True, "first_green"
    return leave_zero_screen_ok(
        yest_profit,
        today_profit,
        yest_alert=yest_alert,
        today_alert=today_alert,
    )


def today_hit_from_quote_df(
    df: pd.DataFrame,
    *,
    flags: LeaveZeroLayerFlags,
) -> bool:
    """DataFrame 末日是否命中母閘（寬＝leave_zero_from_quote_df；窄＝實綠首日）。"""
    from decision_card_signals import (
        leave_zero_from_quote_df,
        profit_left_zero_highlight,
        profit_pct_cal60_series,
    )

    if df is None or len(df) < 2:
        return False
    if flags.require_first_green_day or not flags.allow_double_green:
        profits = profit_pct_cal60_series(df)
        if profits is None or len(profits) < 2:
            return False
        try:
            prev = float(profits.iloc[-2])
            cur = float(profits.iloc[-1])
        except (TypeError, ValueError, IndexError):
            return False
        return bool(profit_left_zero_highlight(prev, cur))
    return bool(leave_zero_from_quote_df(df))


def flags_for_product(name: str) -> Optional[LeaveZeroLayerFlags]:
    key = str(name or "").strip().lower()
    return {
        "screen": PRODUCT_SCREEN,
        "leave_zero": PRODUCT_SCREEN,
        "radar": PRODUCT_RADAR,
        "leave-zero-picks": PRODUCT_RADAR,
        "winrate": PRODUCT_WINRATE,
        "winrate_buypoint": PRODUCT_WINRATE,
    }.get(key)
