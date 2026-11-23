# -*- coding: utf-8 -*-
"""SYNC-FWD：miss→手冊回寫／浪則證據桶（非買訊）。"""
from __future__ import annotations

import json
from pathlib import Path

import observe_sync_fwd as sf
from observe_wave_rules import PHONE_WARNING_FIXED, load_segment_evidence, load_wave_rules_cards

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"


def test_classify_20261123_bounce_reclaim():
    eod = json.loads((LAB / "wave_eod_verify_20261123.json").read_text(encoding="utf-8"))
    row = sf.classify_miss(
        as_of="20261123",
        preferred=eod.get("preferred_was"),
        miss=eod["miss_analysis"],
    )
    assert row["kind"] == "target_touch_bounce_elevate_reclaim"
    assert row["actionable"] is True
    assert row["prefer_path_id"] == "FB_reclaim_37837_watch"
    assert "WR-FWD-TOUCH-BOUNCE-RECLAIM" in row["rule_ids"]
    assert "M3_touched_then_bounce" in row["segment_labels"]
    assert row["buy_signal"] is False
    assert row["phone_sync"] == "blocked"
    assert "①" in row["code_fix_zh"] or "五波" in row["code_fix_zh"]


def test_classify_20261120_broke_follow_band():
    eod = json.loads((LAB / "wave_eod_verify_20261120.json").read_text(encoding="utf-8"))
    row = sf.classify_miss(
        as_of="20261120",
        preferred=eod.get("preferred_was"),
        miss=eod["miss_analysis"],
    )
    assert row["kind"] == "level_broke_follow_oral_band"
    assert row["actionable"] is True
    assert "WR-OPS-FAKE-BREAK" in row["rule_ids"]
    assert row["not_buy_signal"] is True


def test_classify_pending_not_veto_2019ish():
    eod = json.loads((LAB / "wave_eod_verify_20261119.json").read_text(encoding="utf-8"))
    row = sf.classify_miss(
        as_of="20261119",
        preferred=eod.get("preferred_was"),
        miss=eod["miss_analysis"],
    )
    assert row["kind"] == "pending_not_veto"
    assert "WR-FWD-PENDING-NOT-VETO" in row["rule_ids"]


def test_variant_keys_section13():
    assert sf.VARIANT_CURRENT == "bk_fwd_v1_miss_map"
    assert sf.VARIANT_NEXT == "bk_fwd_v2_bounce_reclaim_priority"
    assert sf.VARIANT_CURRENT != sf.VARIANT_NEXT
    assert sf.PHONE_SYNC == "blocked"


def test_ensure_fwd_cards_idempotent(tmp_path: Path):
    cards = load_wave_rules_cards()
    n0 = cards["n_cards"]
    blob, added = sf.ensure_fwd_cards(dict(cards))
    assert "WR-FWD-TOUCH-BOUNCE-RECLAIM" in {c["id"] for c in blob["cards"]}
    assert "WR-FWD-PENDING-NOT-VETO" in {c["id"] for c in blob["cards"]}
    assert blob["n_cards"] == n0 + len(added) or blob["n_cards"] >= n0
    blob2, added2 = sf.ensure_fwd_cards(blob)
    assert added2 == []
    assert blob2["n_cards"] == blob["n_cards"]
    assert blob2["buy_signal"] is False
    assert blob2["phone_warning_fixed"] == PHONE_WARNING_FIXED


def test_evidence_sample_uses_nested_twii():
    eod = json.loads((LAB / "wave_eod_verify_20261123.json").read_text(encoding="utf-8"))
    mapped = sf.classify_miss(
        as_of="20261123",
        preferred=eod.get("preferred_was"),
        miss=eod["miss_analysis"],
    )
    samples = sf.build_evidence_samples_from_eod(eod, mapped=mapped)
    assert samples
    tw = (samples[0]["official_bars"]["twii"])
    assert tw["l"] == 35442.41
    assert tw["c"] == 36811.89
    assert samples[0]["phone_warning"] == PHONE_WARNING_FIXED
    assert samples[0]["buy_signal"] is False


def test_propose_forward_narrative_patch_keeps_not_buy():
    fwd = json.loads((LAB / "wave_forward_infer_20261124.json").read_text(encoding="utf-8"))
    wb = sf.build_writeback_payload()
    patched = sf.propose_forward_narrative_patch(fwd, writeback=wb)
    assert patched["buy_signal"] is False
    assert patched["not_buy_signal"] is True
    assert "sync_fwd_narrative_fix" in patched
    assert patched["sync_fwd_narrative_fix"]["prefer_path_id"] == "FB_reclaim_37837_watch"
    assert "SYNC-FWD" in (patched.get("phone_narrative_zh") or "")
    assert PHONE_WARNING_FIXED in (patched.get("phone_narrative_zh") or "")


def test_apply_writeback_roundtrip(tmp_path: Path, monkeypatch):
    # 用 repo 真實 lab／manual，但 write 到 tmp 複本
    man = tmp_path / "observe_manual"
    man.mkdir()
    for name in (
        "wave_rules_cards.json",
        "segment_evidence.json",
        "wave_rules_cards.md",
        "segment_evidence.md",
    ):
        src = MANUAL / name
        if src.is_file():
            (man / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(sf, "MANUAL", man)
    monkeypatch.setattr(sf, "CARDS_PATH", man / "wave_rules_cards.json")
    monkeypatch.setattr(sf, "EVIDENCE_PATH", man / "segment_evidence.json")
    monkeypatch.setattr(sf, "WRITEBACK_JSON", man / "fwd_miss_writeback_latest.json")
    monkeypatch.setattr(sf, "WRITEBACK_MD", man / "fwd_miss_writeback_latest.md")
    # observe_wave_rules paths used inside summarize — patch via rewriting files only
    payload = sf.apply_writeback(write=True, update_cards=True, update_evidence=True)
    assert payload["n_actionable"] >= 2
    assert (man / "fwd_miss_writeback_latest.json").is_file()
    assert (man / "fwd_miss_writeback_latest.md").is_file()
    cards = json.loads((man / "wave_rules_cards.json").read_text(encoding="utf-8"))
    ids = {c["id"] for c in cards["cards"]}
    assert "WR-FWD-TOUCH-BOUNCE-RECLAIM" in ids
    assert "WR-FWD-PENDING-NOT-VETO" in ids
    assert cards["buy_signal"] is False
    ev = json.loads((man / "segment_evidence.json").read_text(encoding="utf-8"))
    ev_ids = {s["id"] for s in ev["samples"]}
    assert any(i.startswith("SE-FWD-MISS-20261123") for i in ev_ids)
    assert ev["buy_signal"] is False
    blob = json.loads((man / "fwd_miss_writeback_latest.json").read_text(encoding="utf-8"))
    assert blob["current_variant"] == sf.VARIANT_CURRENT
    assert blob["next_variant"]["variant"] == sf.VARIANT_NEXT
    assert blob["phone_sync"] == "blocked"
