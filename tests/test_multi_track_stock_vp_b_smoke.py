# -*- coding: utf-8 -*-
"""個股裸 K＋量 B 條腳本 smoke（不跑全庫；只鎖已凍結 B1–B6／B9／B10）。"""
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
    path = ROOT / "scripts" / "multi_track_stock_vp_b.py"
    name = "multi_track_stock_vp_b"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_locked_scope_no_b7_b8_no_reopen_r1():
    mod = _load()
    assert "B1" in mod.B_LOCKED and "B10" in mod.B_LOCKED
    assert "B7" in mod.B_SKIP and "B8" in mod.B_SKIP
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "不重開 R1e" in src or "no_reopen" in src
    assert "B7" in src and "B8" in src
    # 不准把均線當主條件
    assert "不准均線" in src or "裸 K" in src


def test_b1_confirm_vs_no():
    mod = _load()
    n = 10
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
        }
    )
    # S=5 收 100；S+1 收 102 確認 → 進場 7
    df.loc[5, "close"] = 100.0
    df.loc[5, "high"] = 101.0
    df.loc[6, "close"] = 102.0
    assert mod.b1_confirm_entry(df, 5) == 7
    assert mod.b1_no_confirm(df, 5) is False
    df.loc[6, "close"] = 99.0
    assert mod.b1_confirm_entry(df, 5) is None
    assert mod.b1_no_confirm(df, 5) is True


def test_b4_platform_break_and_fake():
    mod = _load()
    n = 80
    close = [100.0] * n
    high = [101.0] * n
    low = [99.0] * n
    vol = [1000.0] * n
    # 箱體後爆量跌破
    for i in range(20, 60):
        close[i] = 100.0
        high[i] = 102.0
        low[i] = 98.0
        vol[i] = 1000.0
    close[70] = 95.0
    high[70] = 99.0
    low[70] = 94.0
    vol[70] = 9000.0
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": vol})
    assert mod.b4_break_platform(df, 70) is True
    # 假跌破：兩日內收復
    df.loc[71, "close"] = 99.0
    df.loc[72, "close"] = 99.5
    assert mod.b4_fake_break(df, 70) is True


def test_b9_valid_vs_pierce():
    mod = _load()
    n = 50
    close = [100.0 + (i % 5) * 0.1 for i in range(n)]
    high = [c + 1 for c in close]
    low = [c - 1 for c in close]
    vol = [1000.0] * n
    # 前波高約 105
    for i in range(10, 20):
        close[i] = 100 + (i - 10)
        high[i] = close[i] + 0.5
        low[i] = close[i] - 0.5
    # 刺穿：高破前波收未站上
    high[-1] = 120.0
    close[-1] = 108.0
    vol[-1] = 800.0
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": vol})
    assert mod.b9_pierce_only(df, n - 1) is True
    # 有效突破
    close2 = list(close)
    high2 = list(high)
    vol2 = list(vol)
    close2[-1] = 116.0
    high2[-1] = 117.0
    vol2[-1] = 5000.0
    df2 = pd.DataFrame(
        {"open": close2, "high": high2, "low": low, "close": close2, "volume": vol2}
    )
    assert mod.b9_valid_breakout(df2, n - 1) is True


def test_b10_key_bar_and_r1e_split_helpers():
    mod = _load()
    n = 120
    close = [100.0] * n
    high = [101.0] * n
    low = [99.0] * n
    vol = [1000.0] * n
    # 極端振幅＋量
    high[-1] = 130.0
    low[-1] = 90.0
    close[-1] = 100.0
    vol[-1] = 20000.0
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": vol})
    assert mod.b10_key_bar(df, n - 1, look=90) is True
    # 長上影倒貨形（非必要與 B10 同時）
    df2 = df.copy()
    df2.loc[n - 1, "open"] = 100.0
    df2.loc[n - 1, "high"] = 120.0
    df2.loc[n - 1, "low"] = 99.0
    df2.loc[n - 1, "close"] = 103.0
    df2.loc[n - 1, "volume"] = 20000.0
    assert isinstance(mod.r1e1_at(df2, n - 1), bool)


def test_b5_kill_volume():
    mod = _load()
    n = 40
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
        }
    )
    # 放量長陰
    df.loc[30, "open"] = 100.0
    df.loc[30, "high"] = 100.5
    df.loc[30, "low"] = 92.0
    df.loc[30, "close"] = 93.0
    df.loc[30, "volume"] = 8000.0
    assert mod.kill_volume_day(df, 30) is True
