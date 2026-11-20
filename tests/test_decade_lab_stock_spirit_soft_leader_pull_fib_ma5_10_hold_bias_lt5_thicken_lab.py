# -*- coding: utf-8 -*-
"""stock_spirit_soft_leader_pull_fib_ma5_10_hold_bias_lt5_thicken_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_spirit_soft_leader_pull_fib_ma5_10_hold_bias_lt5_thicken_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    FOCUS_VARIANT,
    KEEP_PROMOTE_LABEL,
    PHONE_SYNC,
    SELL_KEEP,
    V106_REF,
    _beats,
    _beats_keep,
    _chrono_folds,
    _ymd,
    confirm_masks_ma5_10_hold_bias_lt5_thicken,
    ma5_10_hold_mask,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert FOCUS_VARIANT == "soft_leader_reclaim_ma5_10_hold_bias_lt5"
    assert FOCUS_VARIANT in CONFIRM_NAMES
    assert "soft_leader_reclaim_ma5_10_hold" in CONFIRM_NAMES
    assert KEEP_PROMOTE_LABEL == "v107"
    # 不准再堆 sell／desync 變體
    for banned in (
        "sell_vol_fade",
        "desync_mfe8",
        "sell_desync",
        "near_low60",
        "hard_leader_reclaim_ma5_10_hold",
        "vol_expand",
    ):
        assert banned not in CONFIRM_NAMES


def test_ymd_normalize():
    assert _ymd("2026-11-09") == "20261109"
    assert _ymd("bad") == ""


def test_chrono_folds_include_half_and_wf():
    dates = [f"{20200101 + i}" for i in range(200)]
    folds = _chrono_folds(dates, n_folds=3)
    names = [f["name"] for f in folds]
    assert "half_split" in names
    assert sum(1 for n in names if n.startswith("wf_expand_")) >= 2
    for f in folds:
        assert f["train"] and f["test"]
        assert f["train"].isdisjoint(f["test"])


def test_ma5_10_hold_mask_trend():
    n = 80
    close = np.linspace(80, 120, n)  # 強升 → 收應站上短均
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(n, 1000.0),
        }
    )
    tech = tech_features(df)
    hold = ma5_10_hold_mask(tech)
    assert bool(hold.iloc[-1]) is True


def test_confirm_masks_focus_subset_of_base():
    n = 90
    rng = np.random.default_rng(23)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    vol = rng.integers(1000, 3000, size=n).astype(float)
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
    tech = tech_features(df)
    soft = confirm_masks_ma5_10_hold_bias_lt5_thicken(is_soft_leader=True, tech_feat=tech)
    hard_only = confirm_masks_ma5_10_hold_bias_lt5_thicken(is_soft_leader=False, tech_feat=tech)
    assert set(soft) == set(CONFIRM_NAMES)
    assert bool(soft["plain"].all())
    base = soft["soft_leader_reclaim_ma5_10_hold"]
    focus = soft[FOCUS_VARIANT]
    assert int((focus & ~base).sum()) == 0
    assert int(hard_only[FOCUS_VARIANT].sum()) == 0
    for banned in ("wave5", "wave9", "PHASE_wash"):
        assert banned not in soft


def test_beats_gate_helpers():
    base = {"n_unique_entry_days": 40, "win_rate": 0.80}
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.81}, base) is True
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.90}, V106_REF["early"]) is True
    assert _beats_keep({"n_unique_entry_days": 10, "win_rate": 0.99}, V106_REF["early"]) is False
