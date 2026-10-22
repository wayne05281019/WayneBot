# -*- coding: utf-8 -*-
"""多軌第 2 步候選腳本 smoke（不跑全庫）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    # baseline 必須可被 step2 import
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    path = ROOT / "scripts" / "multi_track_step2_candidates.py"
    name = "multi_track_step2_candidates"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_candidate_specs_include_baseline_and_d1():
    mod = _load()
    names = [c[0] for c in mod.CANDIDATE_SPECS]
    assert "baseline" in names
    assert "hi_vol_shrink_down2" in names
    assert "pv_confirm_up_shrink" in names
    assert "wait_2" in names


def test_verdict_baseline_is_maintain():
    mod = _load()
    v = mod.verdict_for("A1", "baseline", {}, {})
    assert v["verdict"] == "維持"


def test_cand_wait_n_bounds():
    mod = _load()
    import pandas as pd

    df = pd.DataFrame(
        {
            "open": [10.0] * 10,
            "high": [11.0] * 10,
            "low": [9.0] * 10,
            "close": [10.0] * 10,
            "volume": [1000.0] * 10,
        }
    )
    assert mod.cand_wait_n(2)(df, 3) == 6
    assert mod.cand_wait_n(2)(df, 8) is None


def test_script_files_exist():
    assert (ROOT / "scripts" / "multi_track_step2_candidates.py").is_file()
    assert (ROOT / "scripts" / "multi_track_baseline_backtest.py").is_file()
