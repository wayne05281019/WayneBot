"""20261125 日盤收對 forward W4/FB/M3/N1/M2 必須落檔（非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_eod_verify_20261125_w4_fail_fb_partial():
    d = json.loads((LAB / "wave_eod_verify_20261125.json").read_text(encoding="utf-8"))
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert float(d["official"]["twii"]["v"]) > 0
    assert float(d["official"]["twii"]["c"]) == 38195.43
    assert float(d["official"]["twii"]["l"]) < 37837.05
    assert float(d["official"]["twii"]["h"]) < 41800.0
    assert float(d["official"]["twii"]["c"]) > 37837.05
    ids = {p["id"] for p in d["paths"]}
    assert "W4_reclaim_418_427_band" in ids
    assert "FB_hold_above_37837" in ids
    assert "M3_resume_toward_35000" in ids
    assert "N1_fail_back_below_37837" in ids
    assert "M2_dead_reclaim_watch" in ids
    assert "miss_analysis" in d
    w4 = next(p for p in d["paths"] if p["id"] == "W4_reclaim_418_427_band")
    assert "否決" in (w4.get("verdict") or "")
    fb = next(p for p in d["paths"] if p["id"] == "FB_hold_above_37837")
    assert "部分" in (fb.get("verdict") or "")
    assert d.get("preferred_was") == "W4_reclaim_418_427_band"
    assert "FB_intraday_break_close_reclaim" in (d["miss_analysis"].get("rule_patch") or "")


def test_forward_20261126_prefers_fb_hold_after_w4_miss():
    d = json.loads((LAB / "wave_forward_infer_20261126.json").read_text(encoding="utf-8"))
    assert d.get("preferred_infer") == "FB_hold_above_37837"
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert d["paths"][0]["id"] == "FB_hold_above_37837"
    assert d["infer_for"] == "20261126"
