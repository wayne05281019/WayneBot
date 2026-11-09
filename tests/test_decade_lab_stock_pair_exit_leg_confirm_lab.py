# -*- coding: utf-8 -*-
"""stock_pair_exit_leg_confirm_lab：純函式煙測（不拉 spirit 全堆、不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
    BUY_SIGNAL,
    PHONE_SYNC,
    SELL_KEEP,
    V106_REF,
    _beats,
    _beats_keep,
    _ymd,
    align_pe_ffill,
    confirm_masks,
    crash_proxy_features,
    leader_self_sids,
)


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"


def test_ymd_normalize():
    assert _ymd("2026-11-09") == "20261109"
    assert _ymd("20261109") == "20261109"
    assert _ymd("bad") == ""


def test_align_pe_ffill_no_lookahead():
    df = pd.DataFrame({"date": ["20260102", "20260103", "20260106", "20260107"]})
    pe = align_pe_ffill(df, {"20260103": 20.0, "20260107": 18.0})
    assert np.isnan(pe.iloc[0])
    assert float(pe.iloc[1]) == 20.0
    assert float(pe.iloc[2]) == 20.0  # ffill from 01-03; no peek 01-07
    assert float(pe.iloc[3]) == 18.0


def test_crash_proxy_confirm_masks_restatable_no_wave_labels():
    n = 80
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    # force near-low window at end
    close[-5:] = close[-20:-15].min() * np.array([1.01, 1.02, 1.03, 1.04, 1.05])
    df = pd.DataFrame(
        {
            "date": [f"2025{(i+1):04d}" for i in range(n)],
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.integers(1000, 5000, size=n).astype(float),
        }
    )
    pe_vals = np.linspace(40, 25, n)
    pe = pd.Series(pe_vals, index=df.index)
    feat = crash_proxy_features(df, pe=pe, is_leader=True)
    assert "dist_low60" in feat.columns and "pe_vs_min" in feat.columns
    masks = confirm_masks(feat)
    assert bool(masks["plain"].all())
    assert bool(masks["leader_tag"].all())
    assert "leader_pe_near_low60" in masks
    # no wave-label keys scored
    for banned in ("abc_done", "near_14", "wave5", "wave9", "abc"):
        assert banned not in masks


def test_leader_self_sids_includes_known_leaders():
    s = leader_self_sids()
    # may be empty if biaoke_judge missing in bare pytest path; then skip soft
    if not s:
        return
    assert "2330" in s or "2383" in s or "3363" in s


def test_beats_requires_n20_and_strict_wr():
    base = {"n_unique_entry_days": 40, "win_rate": 0.80}
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.81}, base) is True
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.80}, base) is False
    assert _beats({"n_unique_entry_days": 19, "win_rate": 0.99}, base) is False


def test_beats_keep_uses_sealed_v106():
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.90}, V106_REF["early"]) is True
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.70}, V106_REF["early"]) is False
    assert _beats_keep({"n_unique_entry_days": 10, "win_rate": 0.99}, V106_REF["fast"]) is False
