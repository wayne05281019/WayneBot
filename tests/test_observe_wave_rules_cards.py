# -*- coding: utf-8 -*-
"""BK-WAVE 浪則卡／段號證據桶自測（非買訊）。"""
from __future__ import annotations

import json
from pathlib import Path

from observe_wave_rules import (
    PHONE_WARNING_FIXED,
    attach_wave_rules_ref,
    cards_by_id,
    evidence_index_by_rule,
    load_segment_evidence,
    load_wave_rules_cards,
    summarize_cards_md,
    summarize_evidence_md,
)

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"


def test_wave_rules_cards_load_and_provenance():
    data = load_wave_rules_cards()
    # SYNC-FWD 回寫後可增 WR-FWD-TOUCH-BOUNCE-RECLAIM／PENDING-NOT-VETO
    assert data["n_cards"] >= 22
    assert data["buy_signal"] is False
    assert data["phone_warning_fixed"] == PHONE_WARNING_FIXED
    by = cards_by_id(data)
    assert "WR-IRON-14-OVERLAP" in by
    assert "WR-IRON-W3-NOT-SHORTEST" in by
    assert "WR-SEGMENT-TRIAL-WARN" in by
    # every card: provenance + source_kind; trial cards must declare trial
    for c in data["cards"]:
        assert c.get("provenance"), c.get("id")
        sk = c.get("source_kind")
        assert sk in ("his_words", "his_words+chart", "trial_infer", "chart"), c.get("id")
        if sk == "trial_infer":
            assert c.get("trial_note_zh") or c.get("phone_warning")
        else:
            assert c.get("his_words"), c.get("id")
        assert c.get("not_buy_signal") is True
    # no invent claim: EXT-7-9 hard forbid present
    assert "不准發明" in (by["WR-EXT-7-9"].get("hard_forbid_zh") or "")
    md = summarize_cards_md(data)
    assert "WR-IRON-14-OVERLAP" in md
    assert (MANUAL / "wave_rules_cards.json").is_file()


def test_segment_evidence_scale_and_bars():
    ev = load_segment_evidence()
    assert ev["n_samples"] >= 60
    assert ev["n_with_official_twii"] >= 50
    assert ev["n_trial_infer"] >= 1
    assert ev["n_biaoke_oral"] >= 1
    assert ev["buy_signal"] is False
    assert ev["phone_warning_fixed"] == PHONE_WARNING_FIXED
    by_cards = cards_by_id()
    for s in ev["samples"]:
        for rid in s["rule_ids"]:
            assert rid in by_cards, f"{s['id']} -> missing card {rid}"
        if s.get("has_official_twii"):
            tw = (s.get("official_bars") or {}).get("twii") or {}
            assert tw.get("l") is not None or tw.get("c") is not None
    idx = evidence_index_by_rule(ev)
    assert "WR-IRON-14-OVERLAP" in idx
    assert len(idx["WR-IRON-14-OVERLAP"]) >= 5
    md = summarize_evidence_md(ev)
    assert "段號證據桶" in md


def test_attach_wave_rules_ref_marks_trial_warning():
    payload = {
        "phone_sync": "blocked",
        "buy_signal": True,  # must be forced off
        "paths": [
            {
                "id": "demo",
                "segments_provisional": [
                    {"label": "C3-5", "role": "demo"},
                    {"label": "B-a", "status": "進行中"},
                ],
            }
        ],
    }
    out = attach_wave_rules_ref(payload)
    assert out["buy_signal"] is False
    assert out["wave_rules_ref"]["phone_warning_fixed"] == PHONE_WARNING_FIXED
    assert "WR-FWD-LOOP" in out["wave_rules_ref"]["rule_ids"]
    for seg in out["paths"][0]["segments_provisional"]:
        assert seg["phone_warning"] == PHONE_WARNING_FIXED
        assert "試標" in (seg.get("status") or "")


def test_manual_md_files_exist_and_match_counts():
    cards = json.loads((MANUAL / "wave_rules_cards.json").read_text(encoding="utf-8"))
    ev = json.loads((MANUAL / "segment_evidence.json").read_text(encoding="utf-8"))
    cards_md = (MANUAL / "wave_rules_cards.md").read_text(encoding="utf-8")
    ev_md = (MANUAL / "segment_evidence.md").read_text(encoding="utf-8")
    assert f"**{cards['n_cards']}**" in cards_md or str(cards["n_cards"]) in cards_md
    assert str(ev["n_samples"]) in ev_md
    assert PHONE_WARNING_FIXED in cards_md
    assert PHONE_WARNING_FIXED in ev_md
