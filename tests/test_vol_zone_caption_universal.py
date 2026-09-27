# -*- coding: utf-8 -*-
"""大量區圖說／壓撐：跨情境通用對質（不准硬編碼單檔）。"""
from __future__ import annotations

import pandas as pd

from vol_zone_chart import (
    find_volume_zone,
    official_work,
    vol_zone_position_line,
    _stand_streak,
    _px,
)


def _card(trend: str = "升溫") -> dict:
    return {"table": [{"date": "20260924", "升降": trend}]}


def test_zone_pick_max_volume_with_press_overhead():
    """近窗爆大量：壓還在頭上取最大量；壓＝日高、撐＝日低。"""
    rows = []
    # filler
    for i, d in enumerate(
        ["20260801", "20260804", "20260805", "20260806", "20260807", "20260808"]
    ):
        rows.append(
            {
                "date": d,
                "open": 100,
                "high": 102,
                "low": 99,
                "close": 101,
                "volume": 1000 + i,
                "is_halt": False,
            }
        )
    # smaller volume but later
    rows.append(
        {
            "date": "20260910",
            "open": 110,
            "high": 115,
            "low": 108,
            "close": 112,
            "volume": 5000,
            "is_halt": False,
        }
    )
    # true spike — press still overhead vs last close 120
    rows.append(
        {
            "date": "20260917",
            "open": 118,
            "high": 130,
            "low": 105,
            "close": 120,
            "volume": 20000,
            "is_halt": False,
        }
    )
    rows.append(
        {
            "date": "20260918",
            "open": 121,
            "high": 125,
            "low": 118,
            "close": 122,
            "volume": 8000,
            "is_halt": False,
        }
    )
    # last bar excluded from pick
    rows.append(
        {
            "date": "20260924",
            "open": 119,
            "high": 123,
            "low": 117,
            "close": 120,
            "volume": 90000,
            "is_halt": False,
        }
    )
    work = official_work(pd.DataFrame(rows))
    zone = find_volume_zone(work)
    assert zone is not None
    assert zone["date"] == "20260917"
    assert float(zone["high"]) == 130.0
    assert float(zone["low"]) == 105.0
    assert float(zone["volume"]) == 20000.0
    assert zone["active"] is True


def test_limit_up_above_press_caption():
    zone = {"date": "20260910", "high": 100.0, "low": 90.0, "volume": 10000}
    bars = [
        {"date": "20260923", "high": 98, "low": 92, "close": 95, "volume": 3000},
        {"date": "20260924", "high": 110, "low": 100, "close": 110, "volume": 12000},
    ]
    line = vol_zone_position_line(zone, bars[-1], _card(), bars=bars)
    assert "收盤已過壓100上緣" in line
    assert "不是買訊" in line
    assert "站在支撐" not in line


def test_just_broke_support_caption():
    zone = {"date": "20260910", "high": 100.0, "low": 90.0, "volume": 10000}
    bars = [
        {"date": "20260923", "high": 95, "low": 91, "close": 92, "volume": 3000},
        {"date": "20260924", "high": 91, "low": 85, "close": 88, "volume": 4000},
    ]
    line = vol_zone_position_line(zone, bars[-1], _card(), bars=bars)
    assert "收盤跌破撐90" in line
    assert "這根大量區撐先不當還在" in line


def test_oscillate_in_band_not_rising():
    zone = {"date": "20260910", "high": 100.0, "low": 90.0, "volume": 10000}
    bars = [
        {"close": 92, "high": 94, "low": 91, "volume": 2000},
        {"close": 96, "high": 97, "low": 93, "volume": 2500},
        {"close": 94, "high": 96, "low": 93, "volume": 2200},
    ]
    line = vol_zone_position_line(zone, bars[-1], _card(), bars=bars)
    assert "第三天站在支撐線上" in line
    assert "沒有持續攀高" in line
    assert "看起來不錯" not in line


def test_broke_press_then_back_still_counts_support_streak():
    """過壓又回：中間收＞壓不重數；連站只認收≥撐。"""
    zone = {"date": "20260917", "high": 100.0, "low": 90.0, "volume": 20000}
    bars = [
        {"date": "20260916", "close": 88, "high": 89, "low": 85, "volume": 3000},
        {"date": "20260917", "close": 95, "high": 100, "low": 90, "volume": 20000},
        {"date": "20260918", "close": 98, "high": 99, "low": 94, "volume": 8000},
        {"date": "20260921", "close": 105, "high": 108, "low": 101, "volume": 9000},
        {"date": "20260922", "close": 97, "high": 102, "low": 95, "volume": 5000},
        {"date": "20260923", "close": 98, "high": 99, "low": 96, "volume": 4000},
        {"date": "20260924", "close": 99, "high": 100, "low": 97, "volume": 3500},
    ]
    streak = _stand_streak(bars, 90.0, 100.0)
    assert len(streak) == 6  # from 09/17；09/16 收88破撐
    line = vol_zone_position_line(zone, bars[-1], _card(), bars=bars)
    assert "第六天站在支撐線上" in line
    assert "第三天" not in line
    assert "沒有持續攀高" in line
    assert "100" in line and ("上緣" in line or "壓力" in line)
    assert "已過壓" not in line
    assert "量縮" in line


def test_emerging_like_bars_same_caption_path():
    """興櫃也走同一條圖說；不准另開硬編碼。"""
    zone = {"date": "20260814", "high": 30.5, "low": 28.1, "volume": 5000}
    bars = [
        {"date": "20260922", "close": 30.4, "high": 30.5, "low": 29.8, "volume": 800},
        {"date": "20260923", "close": 30.4, "high": 30.6, "low": 30.0, "volume": 700},
        {"date": "20260924", "close": 30.22, "high": 30.4, "low": 30.0, "volume": 600},
    ]
    line = vol_zone_position_line(zone, bars[-1], _card("持平"), bars=bars)
    assert "第三天站在支撐線上" in line
    assert "比昨天低" in line
    assert "量縮" in line
    for w in ("該買", "該賣", "買訊", "持有"):
        assert w not in line


def test_stand_streak_only_breaks_below_support():
    rows = [
        {"close": 50},
        {"close": 120},  # 遠高於壓
        {"close": 95},
        {"close": 96},
    ]
    assert [_px(r["close"]) for r in _stand_streak(rows, 90.0, 100.0)] == [120, 95, 96]
    rows2 = [{"close": 85}, {"close": 95}, {"close": 96}]
    assert [_px(r["close"]) for r in _stand_streak(rows2, 90.0, 100.0)] == [95, 96]
