# -*- coding: utf-8 -*-
"""stock_spirit_mid_liq_family_pull_fib_reclaim_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import crash_proxy_features
from scripts.decade_lab_stock_spirit_mid_liq_family_pull_fib_reclaim_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    confirm_masks_mid_liq,
    mid_liq_family_sids,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert "mid_liq_and_reclaim" in CONFIRM_NAMES


def test_mid_liq_family_intersection():
    mid = mid_liq_family_sids(
        ["2330", "9999", "6442"],
        hard={"2330"},
        soft={"2330", "6442", "1111"},
    )
    assert mid == {"2330", "6442"}


def test_confirm_masks_mid_liq_subset():
    n = 90
    rng = np.random.default_rng(31)
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
    masks = confirm_masks_mid_liq(
        is_mid_liq=True, is_hard_leader=False, tech_feat=tech, crash_feat=crash
    )
    assert bool(masks["plain"].all())
    assert int(masks["hard_leader_and_reclaim"].sum()) == 0
