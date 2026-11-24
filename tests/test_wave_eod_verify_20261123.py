"""20261123 日盤收對 forward M3/FB/W4/N1/M2 必須落檔（非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_eod_verify_20261123_touched_35579_then_bounce():
    d = json.loads((LAB / "wave_eod_verify_20261123.json").read_text(encoding="utf-8"))
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert float(d["official"]["twii"]["v"]) > 0
    assert float(d["official"]["twii"]["c"]) == 36811.89
    assert float(d["official"]["twii"]["l"]) < 35579.0
    assert float(d["official"]["twii"]["h"]) < 37837.05
    ids = {p["id"] for p in d["paths"]}
    assert "M3_extend_toward_35579" in ids
    assert "FB_reclaim_37837_watch" in ids
    assert "W4_reclaim_418_427_band" in ids
    assert "N1_follow_through_below_band" in ids
    assert "M2_dead_reclaim_watch" in ids
    assert "miss_analysis" in d
    assert "部分成立" in (d["paths"][0].get("verdict") or "")
    assert d.get("preferred_was") == "M3_extend_toward_35579"


def test_forward_20261124_prefers_fb_reclaim_after_bounce():
    d = json.loads((LAB / "wave_forward_infer_20261124.json").read_text(encoding="utf-8"))
    assert d.get("preferred_infer") == "FB_reclaim_37837_watch"
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert d["paths"][0]["id"] == "FB_reclaim_37837_watch"
    assert d["infer_for"] == "20261124"
