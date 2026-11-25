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
    assert payload["buy_signal"] is False
    assert payload["phone_sync"] == "blocked"
    assert payload["WAVE_NEURONS_MATCH"] is False
    assert payload["gate"]["replace"] is False
    assert any(
        t.get("id") == "gap_reclaim_then_intraday_break"
        for t in (payload.get("chain_tags") or [])
    )
    cm = payload.get("cross_mine") or {}
    assert isinstance(cm.get("n_dig_worth"), int)
    assert cm.get("n_dig_worth", -1) >= 0
    assert "wave_strengthen_hints" in cm


def test_1126_preflight_not_buy():
    pre = wd.build_1126_preflight()
    assert pre["as_of"] == "20261126"
    assert pre["preferred_infer"] == "FB_hold_above_37837"
    assert pre["buy_signal"] is False
    assert pre["phone_sync"] == "blocked"
    assert pre["WAVE_NEURONS_MATCH"] is False
    assert pre["watch_levels"]["hold_37837"] == 37837.05
