"""學員法：有憑有據才准推論後驗證（S8；非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"


def _load(name: str) -> dict:
    return json.loads((LAB / name).read_text(encoding="utf-8"))


def test_s8_in_shared_ops():
    d = _load("shared_biaoke_michael_ops_20261112.json")
    ids = {x["id"] for x in d["usable_same"]}
    assert "S8_evidence_before_infer" in ids
    latest = _load("shared_biaoke_michael_ops_latest.json")
    assert any(x["id"] == "S8_evidence_before_infer" for x in latest["usable_same"])
    assert d.get("buy_signal") is False


def test_learner_lock_has_dual_evidence_example():
    d = _load("learner_evidence_infer_verify_20261112.json")
    assert d.get("not_buy_signal") is True
    assert d.get("phone_sync") == "blocked"
    ev = d["example"]["evidence"]
    kinds = {e["kind"] for e in ev}
    assert "official_bar" in kinds
    assert "fib_0_382_bull_correction" in kinds
    assert "his_named_band" in kinds
    assert any(e.get("level") == 41930.03 for e in ev)
    assert "次級四浪" in d["example"]["wave_label_status"] or "路人" in d["example"]["wave_label_status"]
    latest = _load("learner_evidence_infer_verify_latest.json")
    assert latest.get("ops_id") == "S8_evidence_before_infer"


def test_forward_has_evidence_gate():
    d = _load("wave_forward_infer_20261113.json")
    assert "evidence_gate_zh" in d
    assert d.get("preferred_infer") == "M1_retest_41760_after_43135_fail"
    assert isinstance(d.get("evidence_for_preferred"), list)
    assert len(d["evidence_for_preferred"]) >= 2
    assert d.get("not_buy_signal") is True
