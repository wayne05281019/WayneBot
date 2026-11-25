# -*- coding: utf-8 -*-
"""preferred 三態對質軌：非買訊、phone_sync=blocked。"""
from __future__ import annotations

import json
from pathlib import Path

import observe_sync_fwd as sf
import wave_pref_path_confront as pc

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_classify_1124_gap_reclaim():
    eod = json.loads((LAB / "wave_eod_verify_20261124.json").read_text(encoding="utf-8"))
    row = sf.classify_miss(
        as_of="20261124",
        preferred=eod.get("preferred_was"),
        miss=eod["miss_analysis"],
    )
    assert row["kind"] == "gap_reclaim_hold_elevate_w4"
    assert row["actionable"] is True
    assert "WR-FWD-GAP-RECLAIM-HOLD" in row["rule_ids"]
    assert row["prefer_path_id"] == "W4_reclaim_418_427_band"
    assert "FB_gap_reclaim_hold" in row["segment_labels"]
    assert row["buy_signal"] is False
    assert row["phone_sync"] == "blocked"


def test_fwd_next_variant_is_v4_intraday():
    assert sf.VARIANT_CURRENT == "bk_fwd_v1_miss_map"
    assert sf.VARIANT_NEXT == "bk_fwd_v4_intraday_break_close_reclaim"
    assert sf.VARIANT_CURRENT != sf.VARIANT_NEXT


def test_classify_1125_intraday_break():
    eod = json.loads((LAB / "wave_eod_verify_20261125.json").read_text(encoding="utf-8"))
    row = sf.classify_miss(
        as_of="20261125",
        preferred=eod.get("preferred_was"),
        miss=eod["miss_analysis"],
    )
    assert row["kind"] == "intraday_break_close_reclaim_elevate_hold"
    assert row["actionable"] is True
    assert "WR-FWD-INTRADAY-BREAK-CLOSE-RECLAIM" in row["rule_ids"]
    assert row["prefer_path_id"] == "FB_hold_above_37837"
    assert row["buy_signal"] is False
    assert row["phone_sync"] == "blocked"


def test_pref_3state_scores_1124_hit():
    eod = json.loads((LAB / "wave_eod_verify_20261124.json").read_text(encoding="utf-8"))
    row = pc.score_eod(eod, source="wave_eod_verify_20261124.json")
    assert row["preferred_id"] == "FB_reclaim_37837_watch"
    assert row["state"] == "hit"
    assert row["hit"] is True
    assert row["decided"] is True
    assert row["buy_signal"] is False
    assert row["phone_sync"] == "blocked"


def test_pref_3state_scores_1125_w4_fail():
    eod = json.loads((LAB / "wave_eod_verify_20261125.json").read_text(encoding="utf-8"))
    row = pc.score_eod(eod, source="wave_eod_verify_20261125.json")
    assert row["preferred_id"] == "W4_reclaim_418_427_band"
    assert row["state"] == "fail"
    assert row["hit"] is False
    assert row["decided"] is True
    assert row["fail_retract"] is True


def test_pref_3state_suite_gate_fields():
    payload = pc.run_suite()
    assert payload["track"] == "wave_pref_path_3state"
    assert payload["current_variant"] == "pref_3state_v1_verdict_map"
    assert payload["next_variant"]["variant"] == "pref_3state_v2_intraday_break_hold"
    assert payload["buy_signal"] is False
    assert payload["phone_sync"] == "blocked"
    g = payload["gate"]
    assert "n_decided" in g and "gate_n20" in g and g["replace"] is False
    assert g["WAVE_NEURONS_MATCH"] is False
    # 至少要吃到 1124
    asofs = {r.get("as_of") for r in payload["rows"]}
    assert "20261124" in asofs


def test_ensure_gap_card_present():
    cards = {"cards": [], "n_cards": 0, "gap_vs_live_wave_code": {"items": []}}
    blob, added = sf.ensure_fwd_cards(cards)
    ids = {c["id"] for c in blob["cards"]}
    assert "WR-FWD-GAP-RECLAIM-HOLD" in ids
    assert "WR-FWD-GAP-RECLAIM-HOLD" in added or "WR-FWD-GAP-RECLAIM-HOLD" in ids
