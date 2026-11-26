# -*- coding: utf-8 -*-
"""波浪靜默加深：非買訊、phone_sync=blocked。"""
from __future__ import annotations

import json
from pathlib import Path

import wave_silent_deepen as wd

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_chain_includes_1124_to_1125():
    eods = wd.load_eods()
    chains = wd.chain_consecutive(eods)
    hit = [
        c
        for c in chains
        if c.get("from_as_of") == "20261124" and c.get("to_as_of") == "20261125"
    ]
    assert hit
    assert hit[0]["from_preferred"] == "FB_reclaim_37837_watch"
    assert hit[0]["from_state"] == "hit"
    assert hit[0]["to_preferred"] == "W4_reclaim_418_427_band"
    assert hit[0]["to_state"] == "fail"
    assert hit[0]["buy_signal"] is False
    assert hit[0]["phone_sync"] == "blocked"


def test_secondary_paths_1125_has_partial_fb():
    eod = json.loads((LAB / "wave_eod_verify_20261125.json").read_text(encoding="utf-8"))
    rows = wd.score_secondary_paths(eod)
    by_id = {r["id"]: r for r in rows}
    assert by_id["W4_reclaim_418_427_band"]["state"] == "fail"
    assert by_id["W4_reclaim_418_427_band"]["is_preferred"] is True
    assert by_id["FB_hold_above_37837"]["state"] == "partial"
    assert by_id["FB_hold_above_37837"]["is_preferred"] is False


def test_run_deepen_gate_fields():
    payload = wd.run_deepen()
    assert payload["track"] == "wave_silent_deepen"
    assert payload["variant"].startswith("deepen_v3")
    assert payload.get("next_variant") == "deepen_v4_hold_chain_paint_2026"
    assert payload["buy_signal"] is False
    assert payload["phone_sync"] == "blocked"
    assert payload["WAVE_NEURONS_MATCH"] is False
    assert payload["gate"]["replace"] is False
    tags = {t.get("id") for t in (payload.get("chain_tags") or [])}
    assert "gap_reclaim_then_intraday_break" in tags
    assert "intraday_break_then_hold_pass" in tags
    cm = payload.get("cross_mine") or {}
    assert isinstance(cm.get("n_dig_worth"), int)
    assert cm.get("n_dig_worth", -1) >= 0
    assert "wave_strengthen_hints" in cm
    assert "paint_practice" in payload
    assert payload["paint_practice"]["buy_signal"] is False
    assert payload["paint_practice"]["phone_sync"] == "blocked"


def test_1126_preflight_not_buy():
    pre = wd.build_1126_preflight()
    assert pre["as_of"] == "20261126"
    assert pre["preferred_infer"] == "FB_hold_above_37837"
    assert pre["buy_signal"] is False
    assert pre["phone_sync"] == "blocked"
    assert pre["WAVE_NEURONS_MATCH"] is False
    assert pre["watch_levels"]["hold_37837"] == 37837.05


def test_next_preflight_1127_fb_hold():
    pre = wd.build_next_preflight()
    assert pre["as_of"] == "20261127"
    assert pre["preferred_infer"] == "FB_hold_above_37837"
    assert pre["buy_signal"] is False
    assert pre["phone_sync"] == "blocked"
    assert pre["WAVE_NEURONS_MATCH"] is False
    assert pre.get("next_variant") == "deepen_v4_hold_chain_paint_2026"


def test_chain_includes_1125_to_1126_hold_pass():
    eods = wd.load_eods()
    chains = wd.chain_consecutive(eods)
    hit = [
        c
        for c in chains
        if c.get("from_as_of") == "20261125" and c.get("to_as_of") == "20261126"
    ]
    assert hit
    assert hit[0]["from_preferred"] == "W4_reclaim_418_427_band"
    assert hit[0]["from_state"] == "fail"
    assert hit[0]["to_preferred"] == "FB_hold_above_37837"
    assert hit[0]["to_state"] == "hit"
    assert hit[0]["buy_signal"] is False
    assert hit[0]["phone_sync"] == "blocked"
