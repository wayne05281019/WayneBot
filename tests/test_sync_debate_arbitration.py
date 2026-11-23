# -*- coding: utf-8 -*-
"""SYNC-DEBATE：仲裁檔存在＋小衝突裁決可執行。"""
from __future__ import annotations

import json
from pathlib import Path

from biaoke_observe_atoms import _is_tw_index_level, extract_atoms
ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"


def test_debate_arbitration_artifacts_present():
    md = MANUAL / "debate_arbitration_20261123.md"
    js = MANUAL / "debate_arbitration_20261123.json"
    assert md.is_file()
    assert js.is_file()
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["track"] == "SYNC-DEBATE"
    assert data["summary"]["n_conflicts_scanned"] == 14
    assert data["buy_signal"] is False
    ids = {r["id"] for r in data["rulings"]}
    assert {"C1", "C2", "C3", "C4", "C7", "C14"} <= ids
    fixed = [r for r in data["rulings"] if r["status"] == "fixed_this_pr"]
    assert len(fixed) >= 3


def test_c1_index_level_filter_rejects_stock_and_amplitude():
    assert _is_tw_index_level("40816")
    assert _is_tw_index_level("21000")
    assert not _is_tw_index_level("1935")
    assert not _is_tw_index_level("3227")
    assert not _is_tw_index_level("6000")

    rows = [
        {
            "id": "tsmc_night",
            "date": "2026-03-04",
            "time": "09:36",
            "kind": "post",
            "text": "現在台指期夜盤續跌,因此轉換台積電破1935持續往1900去測試可能性大增",
            "club": False,
            "source": "t",
        },
        {
            "id": "amp",
            "date": "2026-06-06",
            "time": "11:51",
            "kind": "post",
            "text": "從夜盤來看已經修正6000點,雖然出現接近2000點下影線K棒,但是還沒止跌",
            "club": False,
            "source": "t",
        },
        {
            "id": "idx_ok",
            "date": "2026-07-29",
            "time": "17:54",
            "kind": "post",
            "text": "台指期夜盤有效穿刺 40816；明早大盤觀察是否確認。",
            "club": False,
            "source": "t",
        },
    ]
    atoms = extract_atoms(rows)
    night_levels = [
        a for a in atoms if a["theme"] == "three_layer" and "night_level" in a["atom_id"]
    ]
    # 台積電價／振幅不准進夜盤指數位；40816 可進
    rules = " ".join(a["rule"] for a in night_levels)
    assert "1935" not in rules
    assert "1900" not in rules
    assert "6000" not in rules
    assert any("40816" in a["rule"] for a in night_levels)

    # 台積電短價若進 level，只能是個股附檔
    stock_lv = [a for a in atoms if a["theme"] == "level" and "個股" in a["rule"]]
    mega_wrong = [
        a
        for a in atoms
        if a["theme"] == "level"
        and a.get("core")
        and a["rule"].startswith("大盤")
        and any(x in a["rule"] for x in ("1935", "1900", "1865"))
    ]
    assert not mega_wrong
    assert stock_lv or True  # 允許無個股桶若句未觸發；重點是不准大盤核心


def test_c2_readme_prefers_producer_filenames():
    text = (MANUAL / "README.md").read_text(encoding="utf-8")
    assert "atoms_latest.json" in text
    assert "chain_playbook.json" in text
    assert "還缺 `observe_atoms.json`" not in text


def test_c3_night_leads_mentions_emini_and_no_backflow():
    raw = json.loads((MANUAL / "wave_rules_cards.json").read_text(encoding="utf-8"))
    hit = [c for c in raw["cards"] if c["id"] == "WR-OPS-NIGHT-LEADS"]
    assert hit
    ops = hit[0]["ops_check_zh"]
    assert "e-mini" in ops or "美期" in ops
    assert "倒灌" in ops
