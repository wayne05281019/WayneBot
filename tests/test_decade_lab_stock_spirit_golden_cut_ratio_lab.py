# -*- coding: utf-8 -*-
"""stock_spirit_golden_cut_ratio_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_phone_spirit_masks import RETRACE_RATIOS, build_spirit_masks
from scripts.decade_lab_stock_spirit_golden_cut_ratio_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    _ymd,
    confirm_masks_golden_cut,
)


def test_phone_flags_and_ratios():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert RETRACE_RATIOS == (0.382, 0.5, 0.618, 0.786)
    assert "near_0382" in CONFIRM_NAMES
    assert "near_0618" in CONFIRM_NAMES
    assert "near_0786" in CONFIRM_NAMES
    assert _ymd("2026-11-10") == "20261110"


def test_spirit_masks_expose_500_786():
    n = 80
    close = np.linspace(100, 120, n) + np.sin(np.linspace(0, 6, n)) * 3
    high = close + 2
    low = close - 2
    df = pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1500.0),
        }
    )
    feat = pd.DataFrame(index=df.index)
    spirit = build_spirit_masks(df, feat)
    for k in ("FIB_near_382", "FIB_near_500", "FIB_near_618", "FIB_near_786", "FIB_near_any"):
        assert k in spirit
        assert len(spirit[k]) == n


def test_confirm_mask_keys_synthetic(monkeypatch):
    n = 60
    close = np.linspace(80, 100, n)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-01", periods=n, freq="B").strftime("%Y%m%d"),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(n, 2000.0),
        }
    )
    raw = df.copy()
    idx = df.index
    fake = {
        "near_0382": pd.Series([False] * n, index=idx),
        "near_0500": pd.Series([False] * n, index=idx),
        "near_0618": pd.Series([i % 5 == 0 for i in range(n)], index=idx),
        "near_0786": pd.Series(False, index=idx),
        "near_any": pd.Series([i % 5 == 0 for i in range(n)], index=idx),
        "near_0382_or_0618": pd.Series([i % 5 == 0 for i in range(n)], index=idx),
    }
    monkeypatch.setattr(
        "scripts.decade_lab_stock_spirit_golden_cut_ratio_lab.spirit_fib_ratio_masks",
        lambda _df, _raw: fake,
    )
    from scripts.decade_lab_stock_tech_confirm_lab import tech_features

    tech = tech_features(df)
    masks = confirm_masks_golden_cut(df=df, raw=raw, tech_feat=tech)
    assert set(CONFIRM_NAMES) <= set(masks.keys())
    assert bool(masks["plain"].all())
    assert int(masks["near_0618"].sum()) == sum(1 for i in range(n) if i % 5 == 0)
