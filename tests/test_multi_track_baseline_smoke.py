# -*- coding: utf-8 -*-
"""多軌底線腳本 smoke：dedup／留白切點（不跑全庫）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts" / "multi_track_baseline_backtest.py"
    name = "multi_track_baseline_backtest"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_dedup_indices_gap():
    mod = _load()
    assert mod.dedup_indices([1, 2, 3, 10, 11, 20], n=5) == [1, 10, 20]


def test_holdout_cut_last_20pct():
    mod = _load()
    days = [f"202601{i:02d}" for i in range(1, 11)]
    assert mod.holdout_cut(days) == "20260109"


def test_script_file_exists():
    assert (ROOT / "scripts" / "multi_track_baseline_backtest.py").is_file()
