# -*- coding: utf-8 -*-
"""stock_tech_confirm_lab：純函式煙測（不拉 spirit 全堆、不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_tech_confirm_lab import (
    BUY_SIGNAL,
    PHONE_SYNC,
    SELL_KEEP,
    V106_REF,
    _beats,
    _beats_keep,
    _ymd,
    buy_confirm_masks,
    tech_features,
)


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"


def test_ymd_normalize():
    assert _ymd("2026-11-09") == "20261109"
    assert _ymd("20261109") == "20261109"
    assert _ymd("bad") == ""


def test_tech_features_and_buy_masks_restatable():
    n = 80
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    vol = rng.integers(1000, 5000, size=n).astype(float)
    # spike volume mid-window
    vol[50] = float(vol[40:60].mean() * 3)
    df = pd.DataFrame(
        {
            "date": [f"2025{i:04d}" for i in range(n)],
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": vol,
        }
    )
    feat = tech_features(df)
    assert "ma20" in feat.columns and "vol_ma20" in feat.columns
    assert "bias20" in feat.columns and "dist_low60" in feat.columns
    masks = buy_confirm_masks(feat)
    assert bool(masks["plain"].all())
    assert "vol_gt_ma20_1p5" in masks
    assert "bias20_lt8" in masks
    assert "reclaim_ma20" in masks
    # volume spike day should pass vol_gt_ma20_1p5 when vol_ma ready
    assert bool(masks["vol_gt_ma20_1p5"].iloc[50]) is True
    # combo is subset of vol filter
    assert int((masks["vol_1p5_and_bias_lt8"] & ~masks["vol_gt_ma20_1p5"]).sum()) == 0


def test_beats_requires_n20_and_strict_wr():
    base = {"n_unique_entry_days": 40, "win_rate": 0.80}
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.81}, base) is True
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.80}, base) is False
    assert _beats({"n_unique_entry_days": 19, "win_rate": 0.99}, base) is False


def test_beats_keep_uses_sealed_v106():
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.90}, V106_REF["early"]) is True
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.70}, V106_REF["early"]) is False
    assert _beats_keep({"n_unique_entry_days": 10, "win_rate": 0.99}, V106_REF["fast"]) is False
