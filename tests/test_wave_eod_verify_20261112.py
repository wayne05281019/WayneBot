"""20261112 日盤收對 forward M1/M2/M3 必須落檔（非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_eod_verify_20261112_has_m_paths_and_official_vol():
    d = json.loads((LAB / "wave_eod_verify_20261112.json").read_text(encoding="utf-8"))
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert float(d["official"]["twii"]["v"]) > 0
    assert float(d["official"]["twii"]["c"]) == 43091.87
    ids = {p["id"] for p in d["paths"]}
    assert "M1_retest_43135_as_support" in ids
    assert "M2_hold_or_extend_above_43135" in ids
    assert "M3_lose_43135_then_41760_friday" in ids
    assert "miss_analysis" in d


def test_forward_20261113_prefers_41760_after_fail():
    d = json.loads((LAB / "wave_forward_infer_20261113.json").read_text(encoding="utf-8"))
    assert d.get("preferred_infer") == "M1_retest_41760_after_43135_fail"
    assert d.get("phone_sync") == "blocked"
    assert d["paths"][0]["id"] == "M1_retest_41760_after_43135_fail"
