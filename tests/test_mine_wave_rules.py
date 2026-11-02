# -*- coding: utf-8 -*-
"""mine_wave_rules：擴延 161.8%／前端傾斜重疊純函式。"""
from __future__ import annotations

from mine_wave_rules import (
    EXT_RATIO,
    check_w1_w4_overlap,
    detect_extension_1618,
    leading_diagonal_flags,
    lengths_from_pivots,
    price_ranges_overlap,
    wave_price_length,
)


def test_wave_price_length_abs():
    assert wave_price_length(100, 261.8) == 161.8
    assert wave_price_length(261.8, 100) == 161.8
    assert wave_price_length("x", 1) is None


def test_extension_pass_when_longest_ge_1618_of_second():
    # L3=1618, L1=1000 → ratio 1.618 exactly
    r = detect_extension_1618({"1": 1000, "3": 1618, "5": 800})
    assert r["pass"] is True
    assert r["longest"] == "3"
    assert r["second"] == "1"
    assert abs(r["ratio"] - EXT_RATIO) < 1e-9
    assert r["variant"] is None


def test_extension_fail_and_rare_ending_variant():
    # ③最長但 <1.618×①，⑤<③
    r = detect_extension_1618({"1": 1000, "3": 1500, "5": 900})
    assert r["pass"] is False
    assert r["longest"] == "3"
    assert r["variant"] == "rare_ending_motive_variant"


def test_extension_rare_w1_longest():
    r = detect_extension_1618({"1": 1500, "3": 1000, "5": 800})
    assert r["pass"] is False
    assert r["longest"] == "1"
    assert r["variant"] == "rare_motive_variant_w1_longest"


def test_extension_insufficient_legs():
    r = detect_extension_1618({"3": 2000})
    assert r["pass"] is False
    assert r["variant"] == "insufficient_legs"


def test_w1_w4_overlap_true_for_leading_diagonal_shape():
    # ① 100→200；④ 回落到 150（進入① 價區）
    ov = check_w1_w4_overlap(100, 200, 250, 150)
    assert ov["overlap"] is True


def test_w1_w4_no_overlap_standard_impulse():
    # ① 100→200；④ 280→240（全程在① 之上）
    ov = check_w1_w4_overlap(100, 200, 280, 240)
    assert ov["overlap"] is False


def test_price_ranges_overlap_none_on_bad_input():
    assert price_ranges_overlap(1, 2, None, 4) is None


def test_leading_diagonal_flags_candidate_vs_confirmed():
    only_ov = leading_diagonal_flags(w1_w4_overlap=True)
    assert only_ov["candidate"] is True
    assert only_ov["confirmed"] is False
    assert only_ov["implication"] == "continuation"

    full = leading_diagonal_flags(
        w1_w4_overlap=True, position_ok=True, structure_53535=True
    )
    assert full["confirmed"] is True

    no = leading_diagonal_flags(w1_w4_overlap=False, position_ok=True, structure_53535=True)
    assert no["candidate"] is False
    assert no["confirmed"] is False


def test_lengths_from_pivots():
    # 0→100→40→200 → legs 100, 60, 160
    d = lengths_from_pivots([(0,), (100,), (40,), (200,)])
    assert d == {"1": 100.0, "2": 60.0, "3": 160.0}
    # motive 1/3/5 only for extension gate in callers
    r = detect_extension_1618({"1": d["1"], "3": d["3"], "5": 50.0})
    assert r["pass"] is False  # 160/100=1.6 < 1.618
