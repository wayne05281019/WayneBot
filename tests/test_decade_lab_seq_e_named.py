# -*- coding: utf-8 -*-
"""序E 點名檔近窗：種子形狀＋報酬粗算。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decade_lab_seq_e_named import SEED_NAMED, _fwd_return, _ymd  # noqa: E402


def test_seed_unique_pairs_and_no_wave_claim():
    pairs = {(s["event_date"], s["stock_id"]) for s in SEED_NAMED}
    assert len(pairs) == len(SEED_NAMED)
    for s in SEED_NAMED:
        assert s["stock_id"].isdigit() or s["stock_id"].isalnum()
        assert "浪" not in (s.get("said") or "") or "細微" not in (s.get("said") or "")


def test_fwd_return_basic():
    pre = [{"close": 100.0}]
    post = [{"close": 110.0}, {"close": 120.0}]
    assert abs(_fwd_return(pre, post, 1) - 10.0) < 1e-9
    assert abs(_fwd_return(pre, post, 2) - 20.0) < 1e-9
    assert _ymd("2025-08-06") == "20250806"
