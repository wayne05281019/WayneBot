# -*- coding: utf-8 -*-
"""blue_arrow exit-assist confront：純函式煙測（不改 leave_zero／不上話筒）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_blue_arrow_exit_assist_confront_lab import (
    BUY_SIGNAL,
    ENTRY_TAG,
    EXIT_MODES,
    KEEP,
    MIN_N_DAYS,
    PHONE_SYNC,
    SOFT_LEADER_INVENT_OFF,
    _beats_status,
    _simulate_exit_mode,
)


def test_phone_flags_blocked_keep_v106():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert ENTRY_TAG == "leave_zero_blue_tri"
    assert KEEP == "v106"
    assert SOFT_LEADER_INVENT_OFF["status"] == "off"
    assert "first_hi20" in EXIT_MODES and "sell_desync_cut" in EXIT_MODES
    assert "phone_stack" in EXIT_MODES and "random_exit" in EXIT_MODES


def test_beats_requires_n20_and_expectancy():
    base = {"n_unique_entry_days": 40, "win_rate": 0.50, "expectancy": 0.0}
    assert _beats_status({"n_unique_entry_days": 25, "win_rate": 0.51, "expectancy": 0.01}, base) is True
    assert _beats_status({"n_unique_entry_days": 25, "win_rate": 0.51, "expectancy": 0.0}, base) is False
    assert _beats_status({"n_unique_entry_days": 19, "win_rate": 0.99, "expectancy": 0.5}, base) is False
    assert MIN_N_DAYS == 20


def _toy_ohlc(n: int = 90) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 0.8, size=n))
    high = close + rng.uniform(0.2, 1.5, size=n)
    low = close - rng.uniform(0.2, 1.5, size=n)
    open_ = close + rng.normal(0, 0.3, size=n)
    return pd.DataFrame(
        {
            "date": [f"2025{i+1:04d}" for i in range(n)],
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1000, 9000, size=n).astype(float),
        }
    )


def test_simulate_hold_max_and_random_exit_produce_trades():
    df = _toy_ohlc()
    entry = pd.Series(False, index=df.index)
    entry.iloc[10] = True
    entry.iloc[40] = True
    hl = pd.Series([""] * len(df), index=df.index)
    temp = pd.Series([""] * len(df), index=df.index)
    rng = np.random.default_rng(1)
    hold = _simulate_exit_mode(
        df, entry, hl=hl, temp_label=temp, sid="2330", exit_mode="hold_max", rng=rng
    )
    rnd = _simulate_exit_mode(
        df, entry, hl=hl, temp_label=temp, sid="2330", exit_mode="random_exit", rng=rng
    )
    assert len(hold) >= 1
    assert all(t["exit_reason"] == "max_hold_60" for t in hold)
    assert len(rnd) >= 1
    assert all(t["exit_reason"] == "random_exit" for t in rnd)
    assert all(t["entry_tag"] == ENTRY_TAG for t in hold)


def test_first_hi20_triggers_on_label():
    df = _toy_ohlc()
    entry = pd.Series(False, index=df.index)
    entry.iloc[5] = True
    hl = pd.Series([""] * len(df), index=df.index)
    hl.iloc[8] = "20高"
    temp = pd.Series([""] * len(df), index=df.index)
    trades = _simulate_exit_mode(
        df,
        entry,
        hl=hl,
        temp_label=temp,
        sid="2330",
        exit_mode="first_hi20",
        rng=np.random.default_rng(0),
    )
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "first_hi20"


def test_sell_desync_uses_action_series_not_scalar():
    """減碼◆必須吃序列動作；單根字串會誤判成字元。"""
    df = _toy_ohlc()
    entry = pd.Series(False, index=df.index)
    entry.iloc[5] = True
    hl = pd.Series([""] * len(df), index=df.index)
    temp = pd.Series([""] * len(df), index=df.index)
    acts = [""] * len(df)
    acts[8] = "直接減碼"
    trades = _simulate_exit_mode(
        df,
        entry,
        hl=hl,
        temp_label=temp,
        sid="2330",
        exit_mode="sell_desync_cut",
        rng=np.random.default_rng(0),
        sell_acts=acts,
    )
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "sell_desync_cut"
