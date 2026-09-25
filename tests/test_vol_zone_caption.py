# -*- coding: utf-8 -*-
"""第三張大量區圖說：收盤口吻位置句，不改如何賣。"""
from __future__ import annotations

from vol_zone_chart import (
    VOL_ZONE_CAPTION_HEAD,
    vol_zone_photo_caption,
    vol_zone_position_line,
)

_NO_HOLD_SELL = ("持有", "出售", "減碼", "先出", "不急", "該買", "該賣", "抱著")

_ZONE = {"high": 210, "low": 195.5, "volume": 15188}
_CHI_BARS = [
    {"high": 194.5, "low": 190.0, "close": 191.0, "volume": 4394},
    {"high": 210.0, "low": 195.5, "close": 203.0, "volume": 15188},
    {"high": 209.0, "low": 201.0, "close": 204.0, "volume": 7475},
    {"high": 207.5, "low": 199.5, "close": 206.5, "volume": 4855},
]


def _card_heat(trend: str) -> dict:
    return {"table": [{"date": "20260924", "升降": trend}]}


def test_chi_yuan_close_voice():
    line = vol_zone_position_line(_ZONE, _CHI_BARS[-1], _card_heat("升溫"), bars=_CHI_BARS)
    assert "今天是第三天站在支撐線上" in line
    assert "三天收盤價持續攀高" in line
    assert "低點" not in line
    assert "收盤仍沒有突破210上緣壓力" in line
    assert "今天成交量對比前次大量那天是量縮" in line
    assert "但溫度上升中" in line
    assert "看起來不錯！" in line
    assert "買訊" not in line
    for w in _NO_HOLD_SELL:
        assert w not in line


def test_close_above_press_not_nice():
    bars = list(_CHI_BARS)
    bars[-1] = {"high": 216, "low": 208, "close": 214, "volume": 9000}
    line = vol_zone_position_line(_ZONE, bars[-1], _card_heat("最高溫"), bars=bars)
    assert "收盤已過壓210上緣" in line
    assert "不是買訊" in line
    assert "看起來不錯" not in line


def test_broke_support_no_nice():
    last = {"high": 194, "low": 188, "close": 190, "volume": 4000}
    line = vol_zone_position_line(_ZONE, last, None, bars=[last])
    assert "收盤跌破撐195.5" in line
    assert "這根大量區撐先不當還在" in line
    assert "看起來不錯" not in line


def test_photo_caption_keeps_head():
    cap = vol_zone_photo_caption(
        zone=_ZONE, last=_CHI_BARS[-1], bars=_CHI_BARS, card=_card_heat("升溫")
    )
    assert cap.startswith(VOL_ZONE_CAPTION_HEAD)
    assert "第三天站在支撐線上" in cap
    assert "非買訊" in cap
    for w in _NO_HOLD_SELL:
        assert w not in cap.split("\n", 1)[-1]


def test_lookup_sell_caption_unchanged_on_card():
    from bot_servers import _decision_card_photo_caption, _glance_photo_caption

    card = {
        "stock_id": "3035",
        "stock_name": "智原",
        "sell_action": "直接減碼",
        "sell_why": "不同步（最高價但非最高溫）",
        "table": [{"date": "20260924", "高低": "20高", "升降": "升溫", "預警": ""}],
    }
    glance = _glance_photo_caption("當日K＋籌碼價量", card)
    decision = _decision_card_photo_caption(card, "3035")
    assert "Ai建議" in glance or "Ai建議" in decision
    vz = vol_zone_photo_caption(zone=_ZONE, last=_CHI_BARS[-1], bars=_CHI_BARS, card=card)
    assert "Ai建議" not in vz
    assert "如何賣" not in vz


def test_closes_not_rising_skips_climb_phrase():
    bars = [
        {"high": 210, "low": 196, "close": 205, "volume": 8000},
        {"high": 208, "low": 198, "close": 202, "volume": 5000},
        {"high": 207, "low": 199, "close": 204, "volume": 4000},
    ]
    line = vol_zone_position_line(_ZONE, bars[-1], _card_heat("升溫"), bars=bars)
    assert "今天是第三天站在支撐線上" in line
    assert "收盤價持續攀高" not in line
    assert "沒有持續攀高" in line
    assert "看起來不錯" not in line


def test_first_day_on_support():
    last = {"high": 200, "low": 196, "close": 198, "volume": 4000}
    line = vol_zone_position_line(_ZONE, last, _card_heat("升溫"), bars=[last])
    assert "今天剛站在支撐線上" in line
    assert "第三天" not in line
    assert "看起來不錯" not in line


def test_today_close_down_not_climb():
    bars = [
        {"high": 208, "low": 196, "close": 203, "volume": 8000},
        {"high": 209, "low": 198, "close": 206, "volume": 6000},
        {"high": 207, "low": 197, "close": 201, "volume": 4000},
    ]
    line = vol_zone_position_line(_ZONE, bars[-1], _card_heat("降溫"), bars=bars)
    assert "今天是第三天站在支撐線上" in line
    assert "但今天收盤 201 比昨天低" in line
    assert "看起來不錯" not in line


def test_tsmc_fourth_day_still_on_support_line():
    zone = {"high": 2505, "low": 2460, "volume": 28931}
    bars = [
        {"high": 2485, "low": 2445, "close": 2480, "volume": 16086},
        {"high": 2510, "low": 2460, "close": 2460, "volume": 22009},
        {"high": 2505, "low": 2475, "close": 2500, "volume": 22817},
        {"high": 2490, "low": 2470, "close": 2475, "volume": 14557},
    ]
    card = {
        "table": [
            {"date": "20260923", "升降": "最高溫", "temp_num": 48.8},
            {"date": "20260924", "升降": "降溫", "temp_num": 26.2},
        ]
    }
    line = vol_zone_position_line(zone, bars[-1], card, bars=bars)
    assert "今天是第四天站在支撐線上" in line
    assert "但今天收盤 2,475 比昨天低" in line
    assert "昨天盤中高點有碰到上緣 2,505" in line
    assert "這四天收盤價沒有持續攀高" in line
    assert "還是少了點" in line
    assert "且溫度比昨天低" in line
    assert "但溫度比昨天低" not in line
    assert "看起來不錯" not in line


def test_wick_test_press_not_breakout():
    bars = [
        {"high": 204, "low": 196, "close": 200, "volume": 5000},
        {"high": 210, "low": 198, "close": 205, "volume": 4000},
    ]
    line = vol_zone_position_line(_ZONE, bars[-1], _card_heat("升溫"), bars=bars)
    assert "測壓不是站上" in line
    assert "看起來不錯" not in line


def test_gap_into_zone_does_not_count_days_above_band():
    """2542 類：人在 45 不算站 39 撐；缺口砸進帶才開始數。"""
    zone = {"date": "20260923", "high": 40.45, "low": 39.0, "volume": 47140}
    bars = [{"high": 46.8, "low": 45.4, "close": 45.45, "volume": 22311}]
    bars.extend(
        {"high": 48.0, "low": 47.0, "close": 47.5, "volume": 8000} for _ in range(40)
    )
    bars.append(
        {"date": "20260923", "high": 40.45, "low": 39.0, "close": 39.55, "volume": 47140}
    )
    bars.append(
        {"date": "20260924", "high": 39.5, "low": 38.8, "close": 39.5, "volume": 12468}
    )
    line = vol_zone_position_line(zone, bars[-1], _card_heat("持平"), bars=bars)
    assert "今天是第二天站在支撐線上" in line
    assert "106" not in line
    assert "第百" not in line
    assert "但今天收盤 39.5 比昨天低" in line
    assert "碰到上緣" not in line
    assert "這兩天收盤價沒有持續攀高" in line
    assert "看起來不錯" not in line


def test_photo_caption_keeps_zone_date_skips_own_rim():
    from vol_zone_chart import VOL_ZONE_CAPTION_HEAD, vol_zone_photo_caption

    zone = {"date": "20260923", "high": 40.45, "low": 39.0, "volume": 47140}
    bars = [
        {"date": "20260922", "high": 46.8, "low": 45.4, "close": 45.45, "volume": 22311},
        {"date": "20260923", "high": 40.45, "low": 39.0, "close": 39.55, "volume": 47140},
        {"date": "20260924", "high": 39.5, "low": 38.8, "close": 39.5, "volume": 12468},
    ]
    cap = vol_zone_photo_caption(zone=zone, last=bars[-1], bars=bars, card=_card_heat("持平"))
    assert cap.startswith(VOL_ZONE_CAPTION_HEAD)
    assert "第二天" in cap
    assert "碰到上緣" not in cap


def test_rising_with_real_volume():
    bars = [
        {"high": 204, "low": 196, "close": 200, "volume": 8000},
        {"high": 206, "low": 198, "close": 203, "volume": 12000},
        {"high": 208, "low": 199, "close": 206, "volume": 11000},
    ]
    line = vol_zone_position_line(_ZONE, bars[-1], _card_heat("升溫"), bars=bars)
    assert "收盤價持續攀高" in line
    assert "仍真" in line
    assert "看起來不錯！" in line
    assert "量縮" not in line


def test_ex_div_cuts_pre_ex_volume_and_caption():
    """除息後不准拿除息前爆量高去壓除息後的收；圖說要自己講息差。"""
    import pandas as pd

    from vol_zone_chart import find_volume_zone, vol_zone_photo_caption

    work = pd.DataFrame(
        [
            {
                "date": "20260910",
                "open": 47.7,
                "high": 48.0,
                "low": 46.4,
                "close": 46.5,
                "volume": 80000,
                "is_halt": False,
            },
            {
                "date": "20260922",
                "open": 46.8,
                "high": 46.8,
                "low": 45.4,
                "close": 45.45,
                "volume": 22311,
                "is_halt": False,
            },
            {
                "date": "20260923",
                "open": 40.0,
                "high": 40.45,
                "low": 39.0,
                "close": 39.55,
                "volume": 47140,
                "is_halt": False,
            },
            {
                "date": "20260924",
                "open": 38.9,
                "high": 39.5,
                "low": 38.8,
                "close": 39.5,
                "volume": 12468,
                "is_halt": False,
            },
        ]
    )
    ev = {
        "ex_date": "20260923",
        "kind": "息",
        "close_before": 45.45,
        "ref_price": 41.45,
        "right_plus_div": 4.0,
        "source": "TWT49U",
    }
    raw = find_volume_zone(work)
    assert raw["date"] == "20260910"
    zone = find_volume_zone(work, ex_events=[ev])
    assert zone["date"] == "20260923"
    assert float(zone["high"]) == 40.45
    assert float(zone["low"]) == 39.0
    bars = work.to_dict("records")
    cap = vol_zone_photo_caption(
        zone=zone, last=bars[-1], bars=bars, card=_card_heat("持平"), ex_events=[ev]
    )
    assert "09/23除息4元" in cap
    assert "前收45.45" in cap
    assert "參考價41.45" in cap
    assert "息差不是崩" in cap
    assert "圖是官方原柱" in cap
    assert "除息後支撐" in cap
    assert "崩盤" not in cap


def test_unexplained_gap_is_called_out():
    from vol_zone_chart import _ex_gap_note

    note = _ex_gap_note([], ["20260923"], "20260924", "20260923", voice="zone")
    assert "跳空超過五％" in note
    assert "不當崩" in note
    assert "測壓" in note


def test_render_mentions_ex_div_not_crash():
    import inspect

    from vol_zone_chart import render_volume_zone_png

    src = inspect.getsource(render_volume_zone_png)
    assert "息差不是崩" in src
    assert "原柱不還原" in src
