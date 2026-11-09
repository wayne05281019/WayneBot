# -*- coding: utf-8 -*-
"""stock_inst_filter_lab：純函式煙測（不拉 spirit 全堆、不改買訊）。"""
from __future__ import annotations

import pandas as pd

from scripts.decade_lab_stock_inst_filter_lab import (
    BUY_SIGNAL,
    PHONE_SYNC,
    SELL_MODE,
    V106_REF,
    _beats,
    _beats_keep,
    _ymd,
    align_market_bfi,
    align_stock_inst,
    inst_filter_masks,
)


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_MODE == "hi20_or_desync"


def test_ymd_normalize():
    assert _ymd("2026-11-09") == "20261109"
    assert _ymd("20261109") == "20261109"
    assert _ymd("bad") == ""


def test_inst_filter_masks_share_nets_only():
    df = pd.DataFrame({"date": ["20260102", "20260103", "20260106", "20260107"]})
    stock = align_stock_inst(
        df,
        {
            "20260102": {"foreign": 10, "trust": 5, "dealer": -1, "three": 14, "has_row": 1},
            "20260103": {"foreign": -3, "trust": 0, "dealer": 0, "three": -3, "has_row": 1},
            # 20260106 缺官方列
            "20260107": {"foreign": 2, "trust": 1, "dealer": 0, "three": 3, "has_row": 1},
        },
    )
    mkt = align_market_bfi(
        df,
        {
            "20260102": {"foreign_yi": 1.0, "trust_yi": 0.5, "dealer_yi": -0.2, "three_yi": 1.3},
            "20260103": {"foreign_yi": -2.0, "trust_yi": 0.1, "dealer_yi": 0.0, "three_yi": -1.9},
            "20260107": {"foreign_yi": 0.5, "trust_yi": 0.2, "dealer_yi": 0.1, "three_yi": 0.8},
        },
    )
    masks = inst_filter_masks(stock, mkt)
    assert bool(masks["plain"].all())
    assert list(masks["stock_three_gt0"].astype(bool)) == [True, False, False, True]
    assert list(masks["stock_ft_both_gt0"].astype(bool)) == [True, False, False, True]
    assert list(masks["mkt_three_gt0"].astype(bool)) == [True, False, False, True]
    assert list(masks["stock_three_x_mkt_three"].astype(bool)) == [True, False, False, True]
    # 缺列日子不准假裝有法人買超
    assert bool(masks["stock_foreign_gt0"].iloc[2]) is False


def test_beats_requires_n20_and_strict_wr():
    base = {"n_unique_entry_days": 40, "win_rate": 0.80}
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.81}, base) is True
    assert _beats({"n_unique_entry_days": 25, "win_rate": 0.80}, base) is False
    assert _beats({"n_unique_entry_days": 19, "win_rate": 0.99}, base) is False


def test_beats_keep_uses_sealed_v106():
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.90}, V106_REF["early"]) is True
    assert _beats_keep({"n_unique_entry_days": 50, "win_rate": 0.70}, V106_REF["early"]) is False
    assert _beats_keep({"n_unique_entry_days": 10, "win_rate": 0.99}, V106_REF["fast"]) is False
