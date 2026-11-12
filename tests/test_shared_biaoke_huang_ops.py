"""飆大／黃培碩綜合：看法同向、大浪名稱定位不同（非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"


def _load(name: str) -> dict:
    return json.loads((LAB / name).read_text(encoding="utf-8"))


def test_huang_biaoke_same_direction_degree4():
    d = _load("shared_biaoke_huang_ops_20261112.json")
    assert d.get("not_buy_signal") is True
    assert d.get("phone_sync") == "blocked"
    ids = {x["id"] for x in d["same_direction"]}
    assert "H1_degree4_family" in ids
    assert "H2_no_easy_fifth_leg" in ids
    assert "H3_lower_band_overlap" in ids
    roles = {x["role"] for x in d["name_map"]}
    assert "當前大級數『4』" in roles
    latest = _load("shared_biaoke_huang_ops_latest.json")
    assert latest.get("title_zh")
    assert "看法一致" in (d.get("user_lock_zh") or "") or "名稱" in (d.get("user_lock_zh") or "")


def test_forward_points_huang_combine():
    d = _load("wave_forward_infer_20261113.json")
    assert d.get("shared_biaoke_huang_file") == "shared_biaoke_huang_ops_20261112.json"
    assert "huang_biaoke_align_zh" in d
    assert d.get("not_buy_signal") is True
