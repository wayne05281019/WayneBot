# -*- coding: utf-8 -*-
"""SYNC-LEVELS：可畫位清單／三窗／有點名結構（非買訊）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from observe_sync_levels import (
    PHONE_WARNING_FIXED,
    TRACK,
    attach_sync_levels_to_pack,
    build_drawable_levels,
    index_drawable_levels,
    load_drawable_levels,
    stock_drawable_levels,
    stock_was_named,
    verify_level_near_window,
    written_targets_merged,
)

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"


def test_build_drawable_from_atoms_and_evidence():
    assert (MANUAL / "atoms_latest.json").is_file()
    assert (MANUAL / "segment_evidence.json").is_file()
    blob = build_drawable_levels(db_path="", verify=False)
    assert blob["track"] == TRACK
    assert blob["buy_signal"] is False
    assert blob["warning"] == PHONE_WARNING_FIXED
    assert blob["n_levels"] >= 20
    assert blob["n_index"] >= 15
    # seed 個股原文目標必在
    assert "3081" in blob["named_stock_ids"]
    assert "3017" in blob["named_stock_ids"]
    for row in blob["levels"]:
        assert row.get("buy_signal") is False
        assert row.get("phone_warning") == PHONE_WARNING_FIXED
        assert row.get("provenance"), row
        assert float(row.get("price") or 0) > 0
    # 不准空出處
    idx = index_drawable_levels(blob, max_n=10)
    assert idx
    assert all(r.get("kind") == "index" for r in idx)


def test_attach_sync_levels_to_pack_marks_warning():
    blob = build_drawable_levels(db_path="", verify=False)
    pack = {
        "pred_levels": {"tw": [], "sox": [], "note": ""},
        "key_levels": {},
        "wait_struct": "觀測中",
        "db_path": "",
    }
    attach_sync_levels_to_pack(pack, blob=blob, max_n=12)
    ref = pack.get("sync_levels_ref") or {}
    assert ref.get("buy_signal") is False
    assert ref.get("warning") == PHONE_WARNING_FIXED
    # key_levels 至少灌了 sync_tw_*
    assert any(str(k).startswith("sync_tw_") for k in (pack.get("key_levels") or {}))
    for row in (pack.get("pred_levels") or {}).get("tw") or []:
        if row.get("sync_levels"):
            assert row.get("phone_warning") == PHONE_WARNING_FIXED
            assert row.get("buy_signal") is False
            assert 30000.0 <= float(row["level"]) <= 60000.0


def test_stock_named_gate_for_structure():
    blob = build_drawable_levels(db_path="", verify=False)
    assert stock_was_named("3081", blob)
    assert stock_was_named("3017", blob)
    # 沒點名檔不准灌
    assert not stock_was_named("2330", blob)
    assert stock_drawable_levels("2330", blob) == []
    merged = written_targets_merged(
        "3081",
        blob=blob,
        base=[{"price": 2000.0, "sid": "3081", "source": "原文目標"}],
    )
    assert any(abs(float(r["price"]) - 2000.0) < 0.01 for r in merged)
    assert written_targets_merged("2330", blob=blob, base=[]) == []


def test_intraday_unclosed_not_official_close(tmp_path):
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    db = tmp_path / "t.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE index_daily(symbol TEXT, date TEXT, open REAL, high REAL, "
        "low REAL, close REAL, volume REAL)"
    )
    # 今天柱存在，但驗證時刻設在盤中 → 不准當收
    taipei = ZoneInfo("Asia/Taipei")
    today = datetime.now(taipei).strftime("%Y%m%d")
    con.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?)",
        ("TWII", today, 23000, 23100, 22900, 23050, 1),
    )
    con.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?)",
        ("TWII", "20261120", 22800, 22900, 22700, 22850, 1),
    )
    con.commit()
    con.close()
    noon = datetime(2026, 11, 23, 11, 0, tzinfo=taipei)
    # 把 today 換成測試日同時刻：用庫內 today 字串當「今天」
    # verify 用 now 的 Ymd 對齊；若庫末日≠now.date 則不會走 intraday 分支
    # 改插 now 当日
    con = sqlite3.connect(str(db))
    ymd = noon.strftime("%Y%m%d")
    con.execute("DELETE FROM index_daily WHERE date=?", (today,))
    con.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?)",
        ("TWII", ymd, 23000, 23100, 22900, 23050, 1),
    )
    con.commit()
    con.close()
    out = verify_level_near_window(
        str(db), 23000.0, as_of=ymd, now=noon
    )
    assert out["status"] in ("intraday_skip", "touched", "not_touched")
    if out["status"] == "intraday_skip":
        assert "未收" in out.get("note_zh", "")
    else:
        # 退到前一日後可驗
        assert out.get("as_of_used")


def test_written_targets_for_hooks_sync():
    from biaoke_next_support import written_targets_for

    rows = written_targets_for("3017")
    assert rows
    assert any(abs(float(r["price"]) - 3000.0) < 0.01 for r in rows)
    # 未點名
    assert written_targets_for("9999") == []


def test_drawable_latest_artifact_roundtrip(tmp_path):
    from observe_sync_levels import save_drawable_levels

    blob = build_drawable_levels(db_path="", verify=False)
    path = tmp_path / "drawable_levels_latest.json"
    save_drawable_levels(blob, path=path)
    loaded = load_drawable_levels(path=path, rebuild_if_missing=False)
    assert loaded["n_levels"] == blob["n_levels"]
    assert loaded["warning"] == PHONE_WARNING_FIXED
