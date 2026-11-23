# -*- coding: utf-8 -*-
"""BK-CORPUS 觀測原子抽取：可操作、有出處、社團後台、離開敘事不進核心。"""
from __future__ import annotations

import json
import os
import sqlite3

from biaoke_observe_atoms import (
    extract_atoms,
    load_corpus_rows,
    run_extract,
    _is_leave_only,
)


def test_leave_noise_not_core_only():
    assert _is_leave_only("不想再發文 壓力很大")
    assert not _is_leave_only("夜盤穿刺 40816 之後大盤確認，不想再發文")


def test_extract_three_layer_and_iron_with_provenance(tmp_path):
    rows = [
        {
            "id": "p1",
            "date": "2026-07-29",
            "time": "17:54",
            "kind": "post",
            "text": "台指期夜盤過第一關 40816；明早大盤觀察是否確認。1-4重疊才算下跌趨勢化解。",
            "club": False,
            "source": "t",
        },
        {
            "id": "p2",
            "date": "2024-07-24",
            "time": "10:00",
            "kind": "post",
            "text": "有關大盤可去看費城半導體技術線圖，頭肩頂右肩形成中。",
            "club": False,
            "source": "t",
        },
        {
            "id": "c1",
            "date": "2025-06-05",
            "time": "12:00",
            "kind": "post",
            "text": "介入買點首先量先價行，爆大量那一天最高價當壓力、最低價當支撐。",
            "club": True,
            "source": "club",
        },
        {
            "id": "leave1",
            "date": "2025-07-10",
            "time": "09:00",
            "kind": "reply",
            "text": "本來早盤已經教了看盤心法，不想再發文。",
            "club": False,
            "source": "t",
        },
    ]
    atoms = extract_atoms(rows)
    themes = {a["theme"] for a in atoms}
    assert "three_layer" in themes
    assert "iron_rule" in themes
    assert "sox" in themes
    assert "pv_structure" in themes

    three = [a for a in atoms if a["theme"] == "three_layer" and a.get("core")]
    assert three
    assert three[0]["provenance"][0]["post_id"] == "p1"
    assert "2026-07-29" in three[0]["provenance"][0]["taipei"]
    assert three[0]["provenance"][0]["excerpt"]

    club_atoms = [a for a in atoms if a.get("source") == "club_backend"]
    assert club_atoms
    assert all(not a.get("core") for a in club_atoms)

    leave = [a for a in atoms if a.get("leave_noise") or "leave" in str(a.get("atom_id"))]
    assert leave
    assert all(not a.get("core") for a in leave)
    ids = [a["atom_id"] for a in atoms]
    assert len(ids) == len(set(ids))


def test_db_overlay_merge(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE biaoke_posts("
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, parent TEXT, "
        "layer INTEGER, kind TEXT, text TEXT)"
    )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?)",
        (
            "overlay1",
            "2026-11-20",
            "21:10",
            "",
            0,
            "post",
            "夜盤下降壓未破，明早台指開盤確認後再看現貨加權。",
        ),
    )
    conn.commit()
    conn.close()
    rows, meta = load_corpus_rows(db_path=str(db), include_club=False)
    assert meta["archive_n"] >= 1700
    assert any(r["id"] == "overlay1" for r in rows)
    atoms = extract_atoms([r for r in rows if r["id"] == "overlay1"])
    assert any(a["theme"] == "three_layer" for a in atoms)


def test_run_extract_writes_files(tmp_path):
    out_json = tmp_path / "atoms_latest.json"
    out_md = tmp_path / "ATOMS_INDEX.md"
    # 用極小合成列走完整寫檔；略過全語料以省時——直接呼叫 write 路徑
    from biaoke_observe_atoms import write_atoms_index_md, write_atoms_json

    payload = {
        "track": "BK-CORPUS",
        "generated_at_taipei": "2026-11-23 12:00:00",
        "warning": "試標",
        "corpus": {
            "archive_n": 1,
            "archive_replies": 0,
            "db_n": 0,
            "club_n": 0,
            "club_replies": 0,
            "merged_n": 1,
            "from": "2026-01-01",
            "to": "2026-01-01",
        },
        "atom_n": 1,
        "coverage": {
            "by_theme": {"three_layer": 1},
            "core_by_theme": {"three_layer": 1},
            "gaps": ["demo"],
            "core_n": 1,
            "attach_n": 0,
        },
        "atoms": [
            {
                "atom_id": "three_layer.night_to_spot",
                "theme": "three_layer",
                "theme_label": "三層觀測（夜盤→早盤TX→現貨）",
                "rule": "夜盤先看",
                "core": True,
                "source": "self",
                "levels": ["40816"],
                "provenance": [
                    {
                        "post_id": "x",
                        "taipei": "2026-07-29 17:54",
                        "kind": "post",
                        "club": False,
                        "excerpt": "夜盤過 40816",
                    }
                ],
                "hit_n": 1,
            }
        ],
    }
    write_atoms_json(payload, str(out_json))
    write_atoms_index_md(payload, str(out_md))
    blob = json.loads(out_json.read_text(encoding="utf-8"))
    assert blob["atom_n"] == 1
    md = out_md.read_text(encoding="utf-8")
    assert "three_layer.night_to_spot" in md
    assert "缺料" in md


def test_run_extract_smoke_no_buy_signal_touch(tmp_path):
    """全語料抽取煙測：產出有原子、不寫入買訊模組。"""
    out_json = tmp_path / "atoms_latest.json"
    out_md = tmp_path / "ATOMS_INDEX.md"
    payload = run_extract(
        db_path="",
        out_json=str(out_json),
        out_md=str(out_md),
        include_club=True,
    )
    assert int(payload.get("atom_n") or 0) >= 20
    assert (payload.get("coverage") or {}).get("core_n", 0) >= 10
    themes = set((payload.get("coverage") or {}).get("by_theme") or {})
    for need in ("three_layer", "iron_rule", "level", "pv_structure"):
        assert need in themes
    # 社團核心必須為假
    for a in payload.get("atoms") or []:
        if a.get("source") == "club_backend":
            assert a.get("core") is False
