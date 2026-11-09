# -*- coding: utf-8 -*-
"""labeled teach pass：只評他點名位；相位窗；換閘誠實。"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.decade_lab_wave_teach_aid_labeled import (
    CRASH_PHASE_TAGS,
    OUT_DIR,
    SCORE_MODES,
    _focus_phrases,
    _honest_flags,
    _infer_named_only,
    _matched_day_compare,
    _named_levels_from_posts,
    _night_lead_note,
    _replace_gate,
    _tag_phase,
    _adapt_paths_for_verify,
)
from scripts.decade_lab_wave_jan_replay import _verify_paths


def test_named_levels_filter_stock_prices():
    posts = [
        {
            "levels": [2330.0, 48240.0, 45546.0],  # 2330=股價噪音
            "waveish": True,
            "snip": "穿刺48240 否則空",
            "phrases": ["pierce"],
        }
    ]
    named = _named_levels_from_posts(posts, ref_px=47000.0)
    assert 2330.0 not in named["levels"]
    assert 48240.0 in named["levels"]
    assert 45546.0 in named["levels"]


def test_infer_named_only_no_swing_fallback():
    empty = _infer_named_only(
        day="20261015",
        named={"floors": [], "caps": [], "levels": []},
        ref_px=47000.0,
    )
    assert empty == []

    paths = _infer_named_only(
        day="20261015",
        named={"floors": [45546.0], "caps": [48240.0], "levels": [45546.0, 48240.0]},
        ref_px=47000.0,
    )
    ids = {p.id for p in paths}
    assert "P1_named_floor" in ids
    assert "P2_named_cap" in ids
    # 不准出現弱先驗 P3／擺盪補位
    assert not any("bias" in p.id for p in paths)


def test_night_lead_does_not_claim_day_score():
    note = _night_lead_note(
        txn={"o": 48000, "h": 48300, "l": 47000, "c": 47200},
        levels=[48240.0, 45546.0],
    )
    assert note is not None
    assert note["scores_day_bar"] is False
    assert 48240.0 in note["touched_named"]


def test_phase_tag_from_windows():
    windows = {
        "warn_start": {
            "phase_key": "warn_start",
            "phase_tag": "warn",
            "title_zh": "示警",
            "start": "20261012",
            "end": "20261015",
        },
        "crash_realized": {
            "phase_key": "crash_realized",
            "phase_tag": "crash",
            "title_zh": "急跌",
            "start": "20261022",
            "end": "20261103",
        },
    }
    assert _tag_phase("20261014", windows)["phase_tag"] == "warn"
    assert _tag_phase("20261025", windows)["phase_tag"] == "crash"
    assert _tag_phase("20260101", windows) is None


def test_labeled_touch_scores_via_adapted_ids():
    paths = _adapt_paths_for_verify(
        [
            {
                "id": "P1_named_floor",
                "levels": {"floor": 100.0},
                "segments_provisional": [{"label": "UNK"}],
            }
        ]
    )
    bar = {"o": 102, "h": 103, "l": 99.5, "c": 101}
    out = _verify_paths(paths, bar=bar, tx_day=None, prior_bars=[], score_mode="baseline")
    assert out["scoreable"] is True
    assert out["verdict"] == "對"


def test_replace_gate_blocks_without_clear_win():
    stats = {"n_decided": 50, "hit_rate": 0.40, "n_with_named": 40}
    matched_weak = {
        "delta_hit_rate_matched": -0.04,
        "labeled_hit_rate": 0.40,
        "loose_hit_rate": 0.44,
    }
    # baseline 0.3936 → headline delta < 2pp → 不換
    honest = _honest_flags(stats, baseline_hr=0.3936, matched=matched_weak)
    gate = _replace_gate(
        stats, baseline_hr=0.3936, honest=honest, matched=matched_weak, min_delta=0.02
    )
    assert gate["replace"] is False
    assert "not_clearly_better_than_loose_baseline" in gate["gate_flags"]

    # headline 贏但同日輸＝選樣膨脹，不准換
    stats_bias = {"n_decided": 50, "hit_rate": 0.45, "n_with_named": 40}
    matched_bias = {
        "delta_hit_rate_matched": -0.04,
        "labeled_hit_rate": 0.42,
        "loose_hit_rate": 0.46,
    }
    honest_bias = _honest_flags(
        stats_bias, baseline_hr=0.3936, matched=matched_bias, min_delta=0.02
    )
    gate_bias = _replace_gate(
        stats_bias,
        baseline_hr=0.3936,
        honest=honest_bias,
        matched=matched_bias,
        min_delta=0.02,
    )
    assert "headline_selection_bias_vs_matched" in honest_bias
    assert gate_bias["replace"] is False

    # 全窗＋同日都明顯更好且誠實 → replace
    stats2 = {"n_decided": 50, "hit_rate": 0.45, "n_with_named": 40}
    matched_ok = {
        "delta_hit_rate_matched": 0.03,
        "labeled_hit_rate": 0.45,
        "loose_hit_rate": 0.42,
    }
    honest2 = _honest_flags(
        stats2, baseline_hr=0.3936, matched=matched_ok, min_delta=0.02
    )
    gate2 = _replace_gate(
        stats2,
        baseline_hr=0.3936,
        honest=honest2,
        matched=matched_ok,
        min_delta=0.02,
        score_mode="baseline",
    )
    assert gate2["clearly_better"] is True
    assert gate2["matched_clearly_better"] is True
    assert honest2 == []
    assert gate2["replace"] is True

    # tight 對 loose＝非 drop-in，即使數字更好也不換
    gate_tight = _replace_gate(
        stats2,
        baseline_hr=0.3936,
        honest=[],
        matched=matched_ok,
        min_delta=0.02,
        score_mode="tight",
    )
    assert gate_tight["replace"] is False
    assert "cross_score_mode_not_drop_in_for_loose_baseline" in gate_tight["gate_flags"]

    # phrase_focus 亦非 drop-in
    gate_pf = _replace_gate(
        stats2,
        baseline_hr=0.3936,
        honest=[],
        matched=matched_ok,
        min_delta=0.02,
        score_mode="phrase_focus",
    )
    assert gate_pf["replace"] is False
    assert "cross_score_mode_not_drop_in_for_loose_baseline" in gate_pf["gate_flags"]

    # phrase_focus_crash 亦非 drop-in
    gate_crash = _replace_gate(
        stats2,
        baseline_hr=0.3936,
        honest=[],
        matched=matched_ok,
        min_delta=0.02,
        score_mode="phrase_focus_crash",
    )
    assert gate_crash["replace"] is False
    assert "cross_score_mode_not_drop_in_for_loose_baseline" in gate_crash["gate_flags"]

    # 命中過高＝不誠實
    stats3 = {"n_decided": 50, "hit_rate": 0.96, "n_with_named": 40}
    honest3 = _honest_flags(stats3, baseline_hr=0.39, matched=matched_ok)
    gate3 = _replace_gate(
        stats3,
        baseline_hr=0.39,
        honest=honest3,
        matched=matched_ok,
        min_delta=0.02,
        score_mode="baseline",
    )
    assert "hit_rate_suspiciously_high" in honest3
    assert gate3["replace"] is False


def test_matched_day_compare_counts():
    rows = [
        {"day": "20261015", "verify": {"scoreable": True, "verdict": "對"}},
        {"day": "20261016", "verify": {"scoreable": True, "verdict": "偏"}},
        {"day": "20261017", "verify": {"scoreable": False, "verdict": "觀望不計分"}},
    ]
    loose = {"20261015": "對", "20261016": "對"}
    m = _matched_day_compare(rows, loose)
    assert m["n_matched_decided"] == 2
    assert m["labeled_hit"] == 1
    assert m["loose_hit"] == 2
    assert m["delta_hit_rate_matched"] == -0.5


def test_seal_files_present_for_teach_aid():
    assert (OUT_DIR / "biaoke_crash_warning_to_tail_timeline_202611.json").exists()
    assert (OUT_DIR / "phone_wave_crash_timeline_teach_aid_lock.json").exists()
    lock = json.loads(
        (OUT_DIR / "phone_wave_crash_timeline_teach_aid_lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert lock.get("buy_signal") is False
    assert lock.get("WAVE_NEURONS_MATCH") is False
    assert lock.get("phone_sync") == "blocked"


def test_focus_phrases_keeps_hard_teach_tags_only():
    got = _focus_phrases(
        ["fake_breakdown", "empty_hand", "pierce", "noise", "overlap_14"]
    )
    assert got == ["fake_breakdown", "pierce", "overlap_14"]
    assert _focus_phrases(["empty_hand", "no_dip"]) == []


def test_phrase_focus_crash_mode_registered():
    assert "phrase_focus_crash" in SCORE_MODES
    assert "warn" in CRASH_PHASE_TAGS
    assert "crash" in CRASH_PHASE_TAGS
    assert "stock_hunt_note" not in CRASH_PHASE_TAGS
