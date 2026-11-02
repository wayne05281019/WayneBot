# -*- coding: utf-8 -*-
"""序F 分軌／規則年切開。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decade_lab_seq_f_tracks import RULE_ERA_CUTS, _era_for, _score_track  # noqa: E402


def test_era_cut_monotonic():
    assert _era_for("2023-11") == "pre_2023-12"
    assert "裸K" in _era_for("2024-01")
    assert "細微波" in _era_for("2026-05")
    assert RULE_ERA_CUTS[0]["from"] < RULE_ERA_CUTS[-1]["from"]


def test_score_track_no_mix_and_no_replace():
    rows = [
        {"counted": True, "G": {"outcome": "對"}},
        {"counted": True, "G": {"outcome": "偏"}},
        {"counted": False, "G": {"outcome": "對"}},
    ]
    t = _score_track("unit", rows, "實驗室")
    assert t["n_counted"] == 2
    assert t["n_decided"] == 2
    assert t["replace_live"] is False
    assert t["gate_n20"] is False
