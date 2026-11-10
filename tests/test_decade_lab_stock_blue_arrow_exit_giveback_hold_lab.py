# -*- coding: utf-8 -*-
"""blue_arrow exit giveback/hold：純函式煙測（不改 leave_zero／不上話筒）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_blue_arrow_exit_giveback_hold_lab import (
    ASSIST_CANDIDATE_KEYS,
    BUY_SIGNAL,
    ENTRY_TAG,
    EXIT_MODES,
    GIVEBACK,
    KEEP,
    MIN_HOLD_USED,
    MIN_N_DAYS,
    PHONE_SYNC,
    SOFT_LEADER_INVENT_OFF,
    _beats_status,
    _mode_flags,
    _simulate_exit_mode,
)


def test_phone_flags_blocked_keep_v106():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert ENTRY_TAG == "leave_zero_blue_tri"
    assert KEEP == "v106"
    assert SOFT_LEADER_INVENT_OFF["status"] == "off"
    assert GIVEBACK == 0.08
    assert MIN_HOLD_USED == 2
    assert "phone_stack" in EXIT_MODES and "random_exit" in EXIT_MODES
    assert "hold_max" in EXIT_MODES
    assert "giveback_only" in EXIT_MODES
    assert "phone_stack_nogb" in EXIT_MODES
    assert "first_hi20_giveback" in EXIT_MODES
    assert "sell_desync_giveback" in EXIT_MODES
    assert "first_hi20_mh2" in EXIT_MODES
    assert set(ASSIST_CANDIDATE_KEYS).issubset(set(EXIT_MODES))
    assert "first_hi20" not in ASSIST_CANDIDATE_KEYS  # confront 單符只對照


def test_beats_requires_both_wr_and_expectancy():
    base = {"n_unique_entry_days": 40, "win_rate": 0.50, "expectancy": 0.0}
    assert _beats_status({"n_unique_entry_days": 25, "win_rate": 0.51, "expectancy": 0.01}, base) is True
    assert _beats_status({"n_unique_entry_days": 25, "win_rate": 0.50, "expectancy": 0.01}, base) is False
    assert _beats_status({"n_unique_entry_days": 25, "win_rate": 0.51, "expectancy": 0.0}, base) is False
    assert _beats_status({"n_unique_entry_days": 19, "win_rate": 0.99, "expectancy": 0.5}, base) is False
    assert MIN_N_DAYS == 20


def test_mode_flags_giveback_and_min_hold():
    assert _mode_flags("phone_stack")["use_giveback"] is True
    assert _mode_flags("phone_stack_nogb")["use_giveback"] is False
    assert _mode_flags("giveback_only")["use_giveback"] is True
    assert _mode_flags("giveback_only")["use_hi20"] is False
    assert _mode_flags("first_hi20_mh2")["min_hold"] == 2
    assert _mode_flags("first_hi20")["min_hold"] == 0
    assert _mode_flags("first_hi20_giveback")["use_hi20"] is True
    assert _mode_flags("first_hi20_giveback")["use_giveback"] is True


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


def test_giveback_only_fires_on_peak_drawdown():
    df = _toy_ohlc()
    # force a peak then 8%+ giveback
    df.loc[12, "high"] = 120.0
    df.loc[12, "close"] = 118.0
    df.loc[13, "high"] = 119.0
    df.loc[13, "close"] = 100.0  # << 120 * 0.92
    df.loc[13, "low"] = 99.0
    entry = pd.Series(False, index=df.index)
    entry.iloc[5] = True
    hl = pd.Series([""] * len(df), index=df.index)
    temp = pd.Series([""] * len(df), index=df.index)
    trades = _simulate_exit_mode(
        df,
        entry,
        hl=hl,
        temp_label=temp,
        sid="2330",
        exit_mode="giveback_only",
        rng=np.random.default_rng(0),
    )
    assert trades[0]["exit_reason"] == "giveback_8pct"


def test_phone_stack_nogb_skips_giveback():
    df = _toy_ohlc()
    df.loc[12, "high"] = 120.0
    df.loc[12, "close"] = 118.0
    df.loc[13, "high"] = 119.0
    df.loc[13, "close"] = 100.0
    df.loc[13, "low"] = 99.0
    entry = pd.Series(False, index=df.index)
    entry.iloc[5] = True
    hl = pd.Series([""] * len(df), index=df.index)
    temp = pd.Series([""] * len(df), index=df.index)
    with_gb = _simulate_exit_mode(
        df,
        entry,
        hl=hl,
        temp_label=temp,
        sid="2330",
        exit_mode="phone_stack",
        rng=np.random.default_rng(0),
    )
    no_gb = _simulate_exit_mode(
        df,
        entry,
        hl=hl,
        temp_label=temp,
        sid="2330",
        exit_mode="phone_stack_nogb",
        rng=np.random.default_rng(0),
    )
    assert with_gb[0]["exit_reason"] == "giveback_8pct"
    assert no_gb[0]["exit_reason"] != "giveback_8pct"


def test_min_hold2_blocks_early_hi20():
    df = _toy_ohlc()
    entry = pd.Series(False, index=df.index)
    entry.iloc[5] = True
    # entry_i=6; day j=7 is held=1 < 2 → mh2 should ignore
    hl = pd.Series([""] * len(df), index=df.index)
    hl.iloc[7] = "20高"
    hl.iloc[10] = "20高"
    temp = pd.Series([""] * len(df), index=df.index)
    early = _simulate_exit_mode(
        df,
        entry,
        hl=hl,
        temp_label=temp,
        sid="2330",
        exit_mode="first_hi20",
        rng=np.random.default_rng(0),
    )
    delayed = _simulate_exit_mode(
        df,
        entry,
        hl=hl,
        temp_label=temp,
        sid="2330",
        exit_mode="first_hi20_mh2",
        rng=np.random.default_rng(0),
    )
    assert early[0]["exit_reason"] == "first_hi20"
    assert early[0]["hold_days"] == 2  # exit at j+1=8 → hold 8-6=2
    assert delayed[0]["exit_reason"] == "first_hi20"
    assert delayed[0]["hold_days"] >= 3  # fires at j=10 (held=4) → exit 11 → hold≥3
