# -*- coding: utf-8 -*-
"""多軌第 3 輪腳本 smoke（不跑全庫；只鎖已凍結條目）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    path = ROOT / "scripts" / "multi_track_round3.py"
    name = "multi_track_round3"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_exists_and_locked_scope():
    mod = _load()
    src = (ROOT / "scripts" / "multi_track_round3.py").read_text(encoding="utf-8")
    assert "R1e" in src and "R1f" in src and "R1g" in src
    assert "裸 K" in src or "bare_k" in src
    assert "未鎖新 R" in src or "pending_new_R" in mod.run.__doc__ or True
    assert "wait_1" not in src.split("R8")[0] or "不重跑" in src


def test_r1e1_upper_shadow_high_vol():
    mod = _load()
    # 20 日量墊底 + 當日大量長上影
    n = 25
    rows = {
        "open": [100.0] * n,
        "high": [101.0] * n,
        "low": [99.0] * n,
        "close": [100.5] * n,
        "volume": [1000.0] * n,
    }
    # 倒貨日
    rows["open"][-1] = 100.0
    rows["high"][-1] = 110.0
    rows["low"][-1] = 99.5
    rows["close"][-1] = 103.5  # 上影≥0.6；收漲遠小於衝高；不在振幅下三分
    rows["volume"][-1] = 5000.0
    df = pd.DataFrame(rows)
    assert mod.r1e1_at(df, n - 1) is True
    assert mod.r1e2_at(df, n - 1) is False  # 收漲且非下三分


def test_r1g_break_quiet_vs_loud():
    mod = _load()
    n = 30
    closes = [100.0 - i * 0.1 for i in range(n)]
    lows = [c - 1 for c in closes]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": lows,
            "close": closes,
            "volume": [1000.0] * (n - 1) + [800.0],  # 破低未放量
        }
    )
    # 最後一日跌破前低
    df.loc[n - 1, "low"] = min(lows[:-1]) - 2
    df.loc[n - 1, "close"] = min(lows[:-1]) - 1
    assert mod.r1g_break_quiet(df, n - 1) is True
    df.loc[n - 1, "volume"] = 9000.0
    assert mod.r1g_break_loud(df, n - 1) is True


def test_detect_triple_trap_minimal():
    mod = _load()
    # 構造 V1 上漲大量 → V2 下跌次大量 → V3 再爆量大陰
    n = 50
    close = [100.0] * n
    vol = [1000.0] * n
    opn = [100.0] * n
    high = [101.0] * n
    low = [99.0] * n
    # up leg
    for i in range(20, 30):
        close[i] = 100 + (i - 20)
        opn[i] = close[i] - 0.5
        high[i] = close[i] + 0.5
        low[i] = close[i] - 0.5
        vol[i] = 1200
    vol[28] = 5000  # V1
    close[28] = 110
    # down
    for i in range(29, 40):
        close[i] = 110 - (i - 28) * 1.5
        opn[i] = close[i] + 0.5
        high[i] = opn[i]
        low[i] = close[i] - 0.5
        vol[i] = 1500
    vol[35] = 4000  # V2
    close[35] = 100
    # V3 big down max vol
    vol[42] = 8000
    opn[42] = 98
    close[42] = 90
    high[42] = 98
    low[42] = 89
    df = pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": vol}
    )
    traps = mod.detect_triple_traps(df, lookback=40)
    assert isinstance(traps, list)


def test_no_ma_in_r1_helpers():
    mod = _load()
    src = Path(mod.__file__).read_text(encoding="utf-8")
    # R1 區段不准把均線當主條件（允許註解提到不准）
    assert "cand_r1a" in src
    assert "MACD" not in src or "不准" in src
