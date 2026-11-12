"""麥可 11/13 夜盤15K機率表必須落檔；有參考價值；非買訊。"""

from __future__ import annotations

import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_michael_night_15k_scenarios_locked():
    d = json.loads((LAB / "michael_night_15k_scenarios_20261113.json").read_text(encoding="utf-8"))
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert d.get("mix_into_biaoke_screen") is False
    assert "有參考價值" in (d.get("user_lock_zh") or "")
    posts = {p["id"]: p for p in d["source"]["posts"]}
    assert "188400106:c188400106-440" in posts
    assert "15K120" in posts["188400106:c188400106-440"]["text"]
    assert "65%" in posts["188400106:c188400106-440"]["text"] or "至少65%" in posts["188400106:c188400106-440"]["text"]
    canon = d["canon_zh"]
    assert "15K120" in canon["focus_that_night_zh"]
    assert "65%" in canon["scenario_a_zh"] or "≈65%" in canon["scenario_a_zh"]
    ids = {m["id"] for m in d["methods"]}
    assert "M_TX15_NIGHT_FOCUS_MA120" in ids
    assert "M_TX15_NIGHT_RANGE_120_60" in ids
    assert "M_TX15_NIGHT_EDGE_RULE" in ids
    latest = json.loads((LAB / "michael_night_15k_scenarios_latest.json").read_text(encoding="utf-8"))
    assert latest["source"]["posts"][0]["id"] == "188400106:c188400106-440"


def test_shared_ops_has_s9_night_path():
    d = json.loads((LAB / "shared_biaoke_michael_ops_latest.json").read_text(encoding="utf-8"))
    ids = {x["id"] for x in d["usable_same"]}
    assert "S9_night_path_then_day_check" in ids
    assert d.get("buy_signal") is False
