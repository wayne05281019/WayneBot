# -*- coding: utf-8 -*-
"""stock_spirit_soft_leader_fib618_vol_expand_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import crash_proxy_features
from scripts.decade_lab_stock_spirit_soft_leader_fib618_vol_expand_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    V106_REF,
    _beats,
    _beats_keep,
    _ymd,
    confirm_masks_fib618_vol_expand,
    vol_expand_mask,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "soft_leader_vol_expand_reclaim" in CONFIRM_NAMES
    assert "vol_expand_1p5" in CONFIRM_NAMES


def test_ymd_normalize():
    assert _ymd("2026-11-09") == "20261109"
    assert _ymd("bad") == ""


def test_vol_expand_mask_spike():
    n = 80
    close = np.linspace(80, 110, n)
    vol = np.full(n, 1000.0)
    vol[-1] = 5000.0  # >1.5× vol_ma20
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": vol,
        }
    )
    tech = tech_features(df)
    m15 = vol_expand_mask(tech, mult=1.5)
    m2 = vol_expand_mask(tech, mult=2.0)
    assert bool(m15.iloc[-1]) is True
    assert bool(m2.iloc[-1]) is True
    # 平量日不擴量
    assert bool(m15.iloc[-5]) is False


def test_confirm_masks_vol_expand_subset():
    n = 90
    rng = np.random.default_rng(19)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    close[-25:] = np.linspace(close[-25], close[-25] + 8, 25)
    vol = rng.integers(1000, 3000, size=n).astype(float)
    vol[-10:] = vol[-10:] * 3.0
    df = pd.DataFrame(
        {
            "date": [f"2025{(i + 1):04d}" for i in range(n)],
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": vol,
        }
    )
    pe = pd.Series(np.linspace(30, 20, n), index=df.index)
    crash = crash_proxy_features(df, pe=pe, is_leader=True)
    tech = tech_features(df)
    masks = confirm_masks_fib618_vol_expand(
        is_soft_leader=True,
        is_hard_leader=True,
        tech_feat=tech,
        crash_feat=crash,
    )
    assert bool(masks["plain"].all())
    assert int((masks["soft_leader_vol_expand_reclaim"] & ~masks["vol_expand_1p5"]).sum()) == 0
    assert int((masks["reclaim_and_vol_expand"] & ~masks["vol_expand_1p5"]).sum()) == 0
    soft_only = confirm_masks_fib618_vol_expand(
        is_soft_leader=True,
        is_hard_leader=False,
        tech_feat=tech,
        crash_feat=crash,
    )
    assert int(soft_only["hard_leader_vol_expand_reclaim"].sum()) == 0
    for banned in ("wave5", "wave9", "PHASE_wash"):
        assert banned not in masks


def test_beats_gate_helpers():
    base = {"n_unique_entry_days": 40, "win_rate": 0.80}
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.81}, base) is True
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.90}, V106_REF["early"]) is True
