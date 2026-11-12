"""麥可 11/12 台指期15分拆解（喝醉主文＋訂正）必須落檔；非買訊。"""

from __future__ import annotations

import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_michael_tx15_drunk_and_correction_locked():
    d = json.loads((LAB / "michael_tx15_drunk_correct_20261112.json").read_text(encoding="utf-8"))
    assert d.get("phone_sync") == "blocked"
    assert d.get("buy_signal") is False
    assert d.get("mix_into_biaoke_screen") is False
    posts = {p["id"]: p for p in d["source"]["posts"]}
    assert "188400106:c188400106-383" in posts
    assert "188400106:c188400106-383-5" in posts
    assert "不勝酒力" in posts["188400106:c188400106-383"]["text"]
    assert "15K\"10\"" in posts["188400106:c188400106-383-5"]["text"] or '15K"10"' in posts["188400106:c188400106-383-5"]["text"]
    canon = d["canon_after_correction_zh"]
    assert "15K10" in canon["rule2_zh"]
    assert "15K20" in canon["discard_zh"]
    ids = {m["id"] for m in d["methods"]}
    assert "M_TX15_four_bars_under_ma60" in ids
    assert "M_TX15_1100_close_under_ma10" in ids
    latest = json.loads((LAB / "michael_tx15_drunk_correct_latest.json").read_text(encoding="utf-8"))
    assert latest["source"]["posts"][0]["id"] == "188400106:c188400106-383"


def test_shared_ops_has_s7_tx15_day_verify():
    d = json.loads((LAB / "shared_biaoke_michael_ops_latest.json").read_text(encoding="utf-8"))
    ids = {x["id"] for x in d["usable_same"]}
    assert "S7_tx15_day_verify" in ids
