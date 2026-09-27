# -*- coding: utf-8 -*-
"""開市日軸連續：不准挖洞、不准編假 K／假量。"""
import pandas as pd

from trading_calendar import iter_tw_open_days
from wayne_navigator import align_ohlc_to_tw_open_days, format_nav_volume_label


def test_iter_tw_open_days_skips_weekend():
    days = iter_tw_open_days("20260918", "20260922")
    assert "20260918" in days
    assert "20260919" not in days  # Sat
    assert "20260920" not in days  # Sun
    assert "20260922" in days


def test_align_fills_missing_open_day_with_prev_close_zero_vol():
    """開市日庫無列＝前收停價＋量0＋is_halt；不准編高低振幅。"""
    df = pd.DataFrame(
        [
            {"date": "20260812", "open": 69.0, "high": 70.0, "low": 68.0, "close": 69.11, "volume": 2.0},
            # 20260813 開市但缺列
            {"date": "20260814", "open": 69.11, "high": 70.5, "low": 70.5, "close": 70.5, "volume": 2.0},
        ]
    )
    out = align_ohlc_to_tw_open_days(df)
    dates = out["date"].tolist()
    assert "20260813" in dates
    row = out.loc[out["date"] == "20260813"].iloc[0]
    assert float(row["close"]) == 69.11
    assert float(row["open"]) == 69.11
    assert float(row["high"]) == 69.11
    assert float(row["low"]) == 69.11
    assert float(row["volume"]) == 0.0
    assert bool(row["is_halt"]) is True
    assert bool(row["no_trade_fill"]) is True
    # 週末不進軸
    assert "20260815" not in dates and "20260816" not in dates


def test_align_keeps_real_thin_volume():
    """有官方薄量＝照畫，不准抬成假爆量、也不准變 0。"""
    df = pd.DataFrame(
        [
            {"date": "20260617", "open": 67.0, "high": 68.9, "low": 67.2, "close": 67.98, "volume": 0.185},
            {"date": "20260618", "open": 67.98, "high": 69.0, "low": 67.5, "close": 68.5, "volume": 3.0},
        ]
    )
    out = align_ohlc_to_tw_open_days(df)
    thin = out.loc[out["date"] == "20260617"].iloc[0]
    assert abs(float(thin["volume"]) - 0.185) < 1e-9
    assert bool(thin["is_halt"]) is False


def test_format_nav_volume_label_thin_shows_shares():
    assert format_nav_volume_label(0.185) == "量 185股"
    assert format_nav_volume_label(0) == "量 0張"
    assert format_nav_volume_label(12) == "量 12張"
