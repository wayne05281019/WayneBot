# -*- coding: utf-8 -*-
"""stock_spirit_fib618_reclaim_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_spirit_fib618_reclaim_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    V106_REF,
    _beats,
    _beats_keep,
    _ymd,
    confirm_masks_fib618,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "reclaim_and_vol_1p5" in CONFIRM_NAMES


def test_ymd_and_beats():
    assert _ymd("2026-11-09") == "20261109"
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.81}, {"n_unique_entry_days": 40, "win_rate": 0.80})
    assert not _beats_keep({"n_unique_entry_days": 19, "win_rate": 0.99}, V106_REF["early"])


def test_confirm_masks_keys():
    n = 80
    rng = np.random.default_rng(9)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    df = pd.DataFrame(
        {
            "date": [f"2025{(i + 1):04d}" for i in range(n)],
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.integers(1000, 8000, size=n).astype(float),
        }
    )
    tech = tech_features(df)
    masks = confirm_masks_fib618(tech_feat=tech)
    assert bool(masks["plain"].all())
    assert int((masks["reclaim_and_vol_1p5"] & ~masks["reclaim_ma20"]).sum()) == 0
    for banned in ("wave5", "wave9", "leader_tag"):
        assert banned not in masks
