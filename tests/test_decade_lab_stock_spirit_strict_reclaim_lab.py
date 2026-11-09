# -*- coding: utf-8 -*-
"""stock_spirit_strict_reclaim_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_spirit_strict_reclaim_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    V106_REF,
    _beats_keep,
    _ymd,
    confirm_masks_strict,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "reclaim_ma20" in CONFIRM_NAMES


def test_ymd_and_gate():
    assert _ymd("20261109") == "20261109"
    assert not _beats_keep({"n_unique_entry_days": 19, "win_rate": 0.99}, V106_REF["early"])


def test_confirm_masks():
    n = 80
    rng = np.random.default_rng(11)
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
    masks = confirm_masks_strict(tech_features(df))
    assert bool(masks["plain"].all())
    assert int((masks["reclaim_and_vol_1p5"] & ~masks["reclaim_ma20"]).sum()) == 0
