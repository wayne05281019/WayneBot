"""麥可夜盤三路徑→隔日勾選：固定覆盤欄；非買訊；不上話筒。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.decade_lab_michael_night_path_checklist import (
    SCHEMA,
    attach_official_bars,
    blank_checklist,
    build_and_write,
    coarse_day_hint,
    seed_20261113_oral,
    summarize,
)

LAB = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"


def test_blank_checklist_locked_fields():
    d = blank_checklist(night_asof="20261113", day_asof="20261113")
    assert d["schema"] == SCHEMA
    assert d["phone_sync"] == "blocked"
    assert d["buy_signal"] is False
    assert d["mix_into_biaoke_screen"] is False
    assert d["ops_id"] == "S9_night_path_then_day_check"
    ids = {p["id"] for p in d["paths"]}
    assert ids == {"A_range_120_60", "B_weak_below_ma10", "C_reclaim_ma120"}
    for p in d["paths"]:
        assert p["night_box"]["status"] == "pending"
        assert p["day_box"]["status"] == "pending"


def test_seed_1113_oral_and_write(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    doc = build_and_write(
        night_asof="20261113",
        day_asof="20261113",
        seed_oral_1113=True,
        coarse=False,
    )
    assert doc["preferred_path"] == "A_range_120_60"
    c = next(p for p in doc["paths"] if p["id"] == "C_reclaim_ma120")
    assert c["day_box"]["status"] == "hit"
    b = next(p for p in doc["paths"] if p["id"] == "B_weak_below_ma10")
    assert b["day_box"]["status"] == "miss"
    latest = json.loads((LAB / "michael_night_path_checklist_latest.json").read_text(encoding="utf-8"))
    dated = json.loads((LAB / "michael_night_path_checklist_20261113.json").read_text(encoding="utf-8"))
    assert latest["day_asof"] == "20261113"
    assert dated["source_post_id"] == "188400106:c188400106-440"
    assert dated["phone_sync"] == "blocked"


def test_coarse_strong_day_marks_c():
    d = blank_checklist(night_asof="20261113", day_asof="20261113")
    d["official"] = {
        "tx_night": {"o": 43180, "h": 44034, "l": 42371, "c": 43676, "v": 1},
        "tx_regular": {"o": 43925, "h": 44824, "l": 43692, "c": 43834, "v": 1},
    }
    d = coarse_day_hint(d)
    d = summarize(d)
    c = next(p for p in d["paths"] if p["id"] == "C_reclaim_ma120")
    assert c["day_box"]["status"] == "hit"
    b = next(p for p in d["paths"] if p["id"] == "B_weak_below_ma10")
    assert b["day_box"]["status"] == "miss"


def test_shared_ops_points_at_checklist_schema():
    # 覆盤欄落地後 shared 仍要有 S9；檔名由本測保證存在於源碼註
    shared = json.loads((LAB / "shared_biaoke_michael_ops_latest.json").read_text(encoding="utf-8"))
    ids = {x["id"] for x in shared["usable_same"]}
    assert "S9_night_path_then_day_check" in ids
    assert shared.get("buy_signal") is False
    src = (Path(__file__).resolve().parents[1] / "scripts" / "decade_lab_michael_night_path_checklist.py").read_text(
        encoding="utf-8"
    )
    assert "michael_night_path_checklist_" in src
    assert "phone_sync" in src
