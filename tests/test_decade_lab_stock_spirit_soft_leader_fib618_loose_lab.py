# -*- coding: utf-8 -*-
"""stock_spirit_soft_leader_fib618_loose_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import crash_proxy_features
from scripts.decade_lab_stock_spirit_soft_leader_fib618_loose_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    confirm_masks_loose,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert "soft_leader_and_reclaim" in CONFIRM_NAMES


def test_confirm_masks_loose_subset():
    n = 90
    rng = np.random.default_rng(23)
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
    pe = pd.Series(np.linspace(30, 20, n), index=df.index)
    crash = crash_proxy_features(df, pe=pe, is_leader=True)
    tech = tech_features(df)
    masks = confirm_masks_loose(
        is_soft_leader=True, is_hard_leader=True, tech_feat=tech, crash_feat=crash
    )
    assert bool(masks["plain"].all())
    assert int((masks["soft_leader_and_reclaim"] & ~masks["reclaim_ma20"]).sum()) == 0
