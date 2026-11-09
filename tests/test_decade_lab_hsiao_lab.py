# -*- coding: utf-8 -*-
"""蕭氏實驗室 V7 單元測試（不上話筒、不是買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.decade_lab_hsiao_backtest import (
    compare_long_only_vs_long_short,
    get_tw_tick_size,
    position_weight,
    run_single_backtest,
)
from scripts.decade_lab_hsiao_data_preprocessor import (
    corporate_action_sanitizer,
    prepare_ohlcv,
)
from scripts.decade_lab_hsiao_predictor import assert_lab_isolation, log_fib_targets, run_hsiao_lab_predict
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_wave_engine import ElliottHsiaoEngine, WaveState, _log_len, _log_retrace


def _synth(n=320, seed=7, start="2014-01-02"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    rets = rng.normal(0.0008, 0.018, n)
    close = 100 * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    vol = rng.integers(2e5, 9e5, n).astype(float)
    adj = close.copy()
    df = pd.DataFrame(
        {
            "Open": open_,
            "High": np.maximum(high, np.maximum(open_, close)),
            "Low": np.minimum(low, np.minimum(open_, close)),
            "Close": close,
            "Volume": vol,
            "Adj Close": adj,
        },
        index=idx,
    )
    return df


def test_tick_size_brackets():
    assert get_tw_tick_size(5) == 0.01
    assert get_tw_tick_size(25) == 0.05
    assert get_tw_tick_size(80) == 0.1
    assert get_tw_tick_size(200) == 0.5
    assert get_tw_tick_size(800) == 1.0
    assert get_tw_tick_size(1500) == 5.0


def test_corporate_action_sanitizer_joins_gap():
    idx = pd.bdate_range("2016-01-04", periods=10)
    c = pd.Series([100, 101, 102, 103, 20.0, 20.5, 21.0, 21.2, 21.5, 22.0], index=idx)
    o = c.copy()
    o.iloc[4] = 20.0  # 減資跳空
    h, low = c * 1.01, c * 0.99
    o2, h2, l2, c2, _, events = corporate_action_sanitizer(o, h, low, c)
    assert len(events) >= 1
    # 接合後 t-1 收 ≈ t 開（相對尺度）
    assert abs(float(c2.iloc[3]) / float(o2.iloc[4]) - 1.0) < 0.02


def test_prepare_continuous_and_isolation():
    df = _synth()
    out = prepare_ohlcv(df)
    assert "Continuous_Close" in out.columns
    assert out.attrs["phone_sync"] == "blocked"
    assert out.attrs["not_buy_signal"] is True


def test_features_limit_regime_and_trough():
    df = _synth(n=400, start="2014-01-02")
    prep = prepare_ohlcv(df)
    feat = compute_hsiao_features(prep)
    assert "is_limit_up" in feat.columns
    assert "is_trough_vol" in feat.columns
    assert "intraday_range" in feat.columns
    assert "K" in feat.columns and "MACD_HIST" in feat.columns
    assert "weekly_trend_bullish" in feat.columns
    assert feat.attrs["phone_sync"] == "blocked"
    # 2015 前後門檻不同
    pre = feat.loc[feat.index < "2015-06-01", "bull_ret_thresh"]
    post = feat.loc[feat.index >= "2015-06-01", "bull_ret_thresh"]
    if len(pre) and len(post):
        assert float(pre.iloc[0]) == 0.025
        assert float(post.iloc[0]) == 0.035


def test_log_fib_and_retrace():
    t = log_fib_targets(100, 120, 110)
    assert np.isfinite(t["target_1618"])
    assert t["target_2618"] > t["target_1618"]
    r = _log_retrace(120, 100, 108)
    assert 0 < r < 1


def test_wave_engine_runs_isolated():
    df = _synth(n=400)
    prep = prepare_ohlcv(df)
    feat = compute_hsiao_features(prep)
    eng = ElliottHsiaoEngine()
    labeled = eng.run(feat, already_featured=True)
    assert "state_name" in labeled.columns
    assert labeled.attrs["phone_sync"] == "blocked"
    assert labeled.attrs["engine_version"] == "hsiao_v7"
    assert WaveState.WAVE_X_REBOUND.value == 10


def test_predictor_isolation():
    df = _synth()
    r = run_hsiao_lab_predict(df)
    assert_lab_isolation(r)
    assert r["summary"]["phone_sync"] == "blocked"


def test_position_weight_caps():
    w = position_weight(100, 90)  # 10% stop
    assert 0 < w <= 0.20
    w2 = position_weight(100, 99.5)  # 極窄 → 用下限 3.5%
    assert w2 <= 0.20


def test_backtest_long_vs_ls():
    df = _synth(n=400)
    cmp = compare_long_only_vs_long_short(df, symbol="TEST")
    assert cmp["phone_sync"] == "blocked"
    assert cmp["not_buy_signal"] is True
    assert "long_only" in cmp["report"]
    assert "long_short" in cmp["report"]
    bt = run_single_backtest(df, symbol="TEST", allow_short=False)
    assert bt.summary["phone_sync"] == "blocked"


def test_pipeline_smoke(tmp_path):
    from scripts.decade_lab_hsiao_main_pipeline import run_pipeline

    df = _synth(n=350)
    out = run_pipeline(df, symbol="SMOKE", do_walk_forward=False, out_dir=tmp_path)
    assert out["phone_sync"] == "blocked"
    assert out["not_buy_signal"] is True
    assert (tmp_path / "hsiao_pipeline_SMOKE_latest.json").exists()


def test_a4_index_soft_preset_is_lab_only():
    from scripts.decade_lab_hsiao_wave_engine import ENTRY_PRESETS, ElliottHsiaoEngine

    assert "A4_index_soft" in ENTRY_PRESETS
    eng = ElliottHsiaoEngine(entry_preset="A4_index_soft")
    assert eng.entry_preset == "A4_index_soft"
    # 合成窗至少能跑完且隔離旗標仍關
    df = _synth(n=360)
    bt = run_single_backtest(df, symbol="IDX", entry_preset="A4_index_soft")
    assert bt.summary["phone_sync"] == "blocked"
    assert bt.summary.get("not_buy_signal") is True
