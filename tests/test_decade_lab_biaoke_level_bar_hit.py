# -*- coding: utf-8 -*-
"""位→官方柱對質：錯窗鎖死、角色判決、§13 下一鍵欄位。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    script = ROOT / "scripts" / "decade_lab_biaoke_level_bar_hit.py"
    spec = importlib.util.spec_from_file_location("decade_lab_biaoke_level_bar_hit", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_score_support_break_pressure_and_fwd_only():
    mod = _load()
    bars = [
        {"date": "20260101", "open": 100, "high": 101, "low": 99, "close": 100},
        {"date": "20260102", "open": 100, "high": 102, "low": 98, "close": 101},
        {"date": "20260103", "open": 101, "high": 103, "low": 100, "close": 102},
        {"date": "20260104", "open": 102, "high": 104, "low": 101, "close": 103},
        {"date": "20260105", "open": 103, "high": 105, "low": 102, "close": 104},
        {"date": "20260106", "open": 104, "high": 106, "low": 103, "close": 105},
    ]
    # 發文日 i0=0；fwd_only：後窗低≥支撐→對
    verd, ok = mod.score_level_vs_fwd(
        97.0, "support", bars, 0, fwd=5, tol_pct=0.0, include_day0=False
    )
    assert verd == "對" and ok is True
    # 後窗深破支撐且收不回→偏
    bars_brk = list(bars)
    bars_brk[2] = {"date": "20260103", "open": 90, "high": 91, "low": 88, "close": 89}
    verd2, ok2 = mod.score_level_vs_fwd(
        97.0, "support", bars_brk, 0, fwd=5, tol_pct=0.0, include_day0=False
    )
    assert verd2 == "偏" and ok2 is False
    # 錯窗對照：只有當日低碰到 99.2；fwd_only 看次日低=98 → 未破更高目標時仍可分岔
    # 這裡用 pressure：當日高=101 碰到 100.5；fwd=1 且 fwd_only 次日高=102 也碰——
    # 改用「當日才碰到、次日高未到」的壓力位
    verd_day0, ok_day0 = mod.score_level_vs_fwd(
        100.5, "pressure", bars, 0, fwd=1, tol_pct=0.0, include_day0=True
    )
    # 人造：次日高壓在 100 以下
    bars_cap = list(bars)
    bars_cap[1] = {"date": "20260102", "open": 99, "high": 100.0, "low": 98, "close": 99}
    verd_fwd, ok_fwd = mod.score_level_vs_fwd(
        100.5, "pressure", bars_cap, 0, fwd=1, tol_pct=0.0, include_day0=False
    )
    assert verd_day0 == "對" and ok_day0 is True  # 含當日高 101
    assert verd_fwd == "偏" and ok_fwd is False  # 次日高 100 未到 100.5
    # break：後窗低碰到
    verd3, ok3 = mod.score_level_vs_fwd(
        100.0, "break", bars, 0, fwd=5, tol_pct=0.01, include_day0=False
    )
    assert verd3 == "對" and ok3 is True
    # pressure：後窗高碰到
    verd4, ok4 = mod.score_level_vs_fwd(
        105.0, "pressure", bars, 0, fwd=5, tol_pct=0.01, include_day0=False
    )
    assert verd4 == "對" and ok4 is True
    # 窗未完
    verd5, ok5 = mod.score_level_vs_fwd(
        100.0, "touch", bars, 4, fwd=5, tol_pct=0.01, include_day0=False
    )
    assert verd5 == "未完" and ok5 is None
    # break 未碰到→偏（fwd_only，目標遠低於後窗）
    verd6, ok6 = mod.score_level_vs_fwd(
        50.0, "break", bars, 0, fwd=5, tol_pct=0.0, include_day0=False
    )
    assert verd6 == "偏" and ok6 is False


def test_role_infer_and_stock_leak():
    mod = _load()
    assert mod._explicit_role("回測19660支撐區") == "support"
    assert mod._explicit_role("必破22000") == "break"
    assert mod._explicit_role("要過前波高點47578") == "pressure"
    assert mod._infer_role("隨便一句", "down") == "break"
    assert mod._infer_role("隨便一句", "retest") == "support"
    assert mod._stock_leak("頎邦關鍵支撐價") is True
    assert mod._stock_leak("大盤回測19660支撐") is False


def test_variant_keys_and_score_rows():
    mod = _load()
    assert mod.VARIANT_CURRENT == "level_bar_fwd5_role_infer"
    assert mod.VARIANT_NEXT == "level_bar_vnext_explicit_hybrid"
    assert mod.VARIANT_CURRENT != mod.VARIANT_NEXT
    scored = mod._score_rows(
        [
            {"ok": True, "verdict": "對", "as_of": "20260102", "role": "support"},
            {"ok": False, "verdict": "偏", "as_of": "20260103", "role": "break"},
            {"ok": None, "verdict": "未完", "as_of": "20260104", "role": "pressure"},
        ]
    )
    assert scored["n_decided"] == 2
    assert scored["hit"] == 1
    assert scored["hit_rate"] == 0.5
    assert scored["gate_n20"] is False
    assert scored["n_days"] == 2
