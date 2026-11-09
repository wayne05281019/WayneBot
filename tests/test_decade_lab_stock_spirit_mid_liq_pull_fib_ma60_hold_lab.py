# -*- coding: utf-8 -*-
"""stock_spirit_mid_liq_pull_fib_ma60_hold_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import crash_proxy_features
from scripts.decade_lab_stock_spirit_mid_liq_pull_fib_ma60_hold_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    confirm_masks_mid_liq_ma60,
    ma60_hold_mask,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "mid_liq_reclaim_ma60_hold" in CONFIRM_NAMES


def test_confirm_masks_mid_liq_ma60_subset():
    n = 90
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    close[-30:] = np.linspace(close[-30], close[-30] + 10, 30)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.integers(1000, 8000, size=n).astype(float),
        }
    )
    pe = pd.Series(np.linspace(25, 18, n), index=df.index)
    crash = crash_proxy_features(df, pe=pe, is_leader=True)
    tech = tech_features(df)
    masks = confirm_masks_mid_liq_ma60(
        is_mid_liq=True,
        is_hard_leader=False,
        tech_feat=tech,
        crash_feat=crash,
    )
    assert int((masks["mid_liq_reclaim_ma60_hold"] & ~ma60_hold_mask(tech)).sum()) == 0
    assert int(masks["hard_leader_reclaim_ma60_hold"].sum()) == 0
    for banned in ("wave5", "wave9"):
        assert banned not in masks
