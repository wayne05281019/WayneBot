# -*- coding: utf-8 -*-
"""stock_revenue_lead_proxy_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_revenue_lead_proxy_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    _ymd,
    confirm_masks_revenue_lead,
    revenue_available_from_ymd,
    revenue_lead_masks_for_dates,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "rev_yoy_accel" in CONFIRM_NAMES
    assert "rev_yoy_accel_pre_print" in CONFIRM_NAMES


def test_ymd_and_available_from():
    assert _ymd("2026-11-10") == "20261110"
    assert revenue_available_from_ymd("202609") == "20261010"
    assert revenue_available_from_ymd("202612") == "20270110"


def test_accel_mask_respects_publish_date():
    # 9月營收 10/10 才可用；10/9 不該看到 9月加速
    rows = [
        {"yyyymm": "202607", "yoy_pct": 10.0, "mom_pct": 1.0, "revenue": 1.0, "available_from": "20260810"},
        {"yyyymm": "202608", "yoy_pct": 20.0, "mom_pct": 1.0, "revenue": 1.0, "available_from": "20260910"},
        {"yyyymm": "202609", "yoy_pct": 35.0, "mom_pct": 1.0, "revenue": 1.0, "available_from": "20261010"},
    ]
    dates = ["20261009", "20261010", "20261105"]
    m = revenue_lead_masks_for_dates(dates, rows)
    assert bool(m["rev_yoy_accel"].iloc[0]) is True  # 只用到 7→8
    assert bool(m["rev_yoy_accel"].iloc[1]) is True  # 8→9 加速
    assert bool(m["rev_yoy_accel_pre_print"].iloc[2]) is True  # 11/5 在 1～10 窗


def test_confirm_masks_keys():
    n = 60
    close = np.linspace(80, 100, n)
    df = pd.DataFrame(
        {
            "date": [f"202610{str(i+1).zfill(2)}" if i < 9 else f"202611{str(i-8).zfill(2)}" for i in range(n)],
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(n, 2000.0),
        }
    )
    # fix invalid dates simply
    df["date"] = pd.date_range("2026-08-01", periods=n, freq="B").strftime("%Y%m%d")
    rows = [
        {
            "yyyymm": "202606",
            "yoy_pct": 5.0,
            "mom_pct": 0.0,
            "revenue": 1.0,
            "available_from": revenue_available_from_ymd("202606"),
        },
        {
            "yyyymm": "202607",
            "yoy_pct": 12.0,
            "mom_pct": 0.0,
            "revenue": 1.0,
            "available_from": revenue_available_from_ymd("202607"),
        },
        {
            "yyyymm": "202608",
            "yoy_pct": 25.0,
            "mom_pct": 0.0,
            "revenue": 1.0,
            "available_from": revenue_available_from_ymd("202608"),
        },
    ]
    tech = tech_features(df)
    masks = confirm_masks_revenue_lead(df=df, rev_rows=rows, tech_feat=tech)
    assert set(CONFIRM_NAMES) <= set(masks.keys())
    assert bool(masks["plain"].all())
