"""20261124 日盤收對 forward FB/M3/W4/N1/M2 必須落檔（非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_eod_verify_20261124_fb_gap_reclaim_37837():
    d = json.loads((LAB / "wave_eod_verify_20261124.json").read_text(encoding="utf-8"))
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert float(d["official"]["twii"]["v"]) > 0
    assert float(d["official"]["twii"]["c"]) == 40122.35
    assert float(d["official"]["twii"]["l"]) > 37837.05
    assert float(d["official"]["twii"]["h"]) > 37837.05
    assert float(d["official"]["twii"]["h"]) < 41800.0
    ids = {p["id"] for p in d["paths"]}
    assert "FB_reclaim_37837_watch" in ids
    assert "M3_resume_toward_35000" in ids
    assert "W4_reclaim_418_427_band" in ids
    assert "N1_follow_through_below_band" in ids
    assert "M2_dead_reclaim_watch" in ids
    assert "miss_analysis" in d
    fb = next(p for p in d["paths"] if p["id"] == "FB_reclaim_37837_watch")
    assert "成立" in (fb.get("verdict") or "")
    assert d.get("preferred_was") == "FB_reclaim_37837_watch"


def test_forward_20261125_prefers_w4_after_fb():
    d = json.loads((LAB / "wave_forward_infer_20261125.json").read_text(encoding="utf-8"))
    assert d.get("preferred_infer") == "W4_reclaim_418_427_band"
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert d["paths"][0]["id"] == "W4_reclaim_418_427_band"
    assert d["infer_for"] == "20261125"
