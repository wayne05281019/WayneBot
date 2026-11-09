# -*- coding: utf-8 -*-
"""stock_spirit_pull_fib_reclaim_bias_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import crash_proxy_features
from scripts.decade_lab_stock_spirit_pull_fib_reclaim_bias_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    V106_REF,
    _beats,
    _beats_keep,
    _ymd,
    confirm_masks_reclaim_bias,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "reclaim_ma20" in CONFIRM_NAMES
    assert "leader_reclaim_and_bias_lt8" in CONFIRM_NAMES


def test_ymd_normalize():
    assert _ymd("2026-11-09") == "20261109"
    assert _ymd("bad") == ""


def test_confirm_masks_reclaim_subset():
    n = 90
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    close[-25:] = np.linspace(close[-25], close[-25] + 8, 25)
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
    masks = confirm_masks_reclaim_bias(is_leader=True, tech_feat=tech, crash_feat=crash)
    assert bool(masks["plain"].all())
    assert int((masks["leader_and_reclaim_ma20"] & ~masks["reclaim_ma20"]).sum()) == 0
    assert int((masks["reclaim_and_bias_lt8"] & ~masks["reclaim_ma20"]).sum()) == 0
    for banned in ("abc", "wave5", "wave9", "PHASE_wash"):
        assert banned not in masks


def test_beats_gate_helpers():
    base = {"n_unique_entry_days": 40, "win_rate": 0.80}
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.81}, base) is True
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.90}, V106_REF["early"]) is True
