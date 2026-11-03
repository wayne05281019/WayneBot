# -*- coding: utf-8 -*-
"""位階口語樣本回補：只插缺列、不洗判決、不渲圖。"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biaoke_level_learn import ensure_tables  # noqa: E402


def _load_backfill_mod():
    """用檔案路徑載入，不准把 scripts/ 插進 sys.path（會撞 biaoke_witness）。"""
    script = ROOT / "scripts" / "biaoke_level_sample_backfill.py"
    spec = importlib.util.spec_from_file_location(
        "biaoke_level_sample_backfill_testmod", script
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_posts(db: Path) -> None:
    con = sqlite3.connect(str(db))
    con.execute(
        """
        CREATE TABLE biaoke_posts(
            id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT,
            parent TEXT, layer INTEGER, kind TEXT, tags TEXT, text TEXT,
            updated_at TEXT, reply_to_text TEXT
        )
        """
    )
    rows = [
        ("a1", "2026-07-16", "10:00", "大盤 C3-3 主跌段開始啟動，細微波還在走"),
        ("a2", "2026-07-24", "18:00", "重新修訂波浪位階；先前預估偏了"),
        ("a3", "2026-07-29", "12:00", "大盤細微波確認 A 波低，C3-3 延續"),
    ]
    for pid, d, t, text in rows:
        con.execute(
            "INSERT INTO biaoke_posts(id,n,date,time,parent,layer,kind,tags,text,updated_at,reply_to_text) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, 1, d, t, "", 0, "main", "", text, "", ""),
        )
    con.commit()
    con.close()
    ensure_tables(str(db))


def test_insert_missing_and_verify_no_png(tmp_path):
    db = tmp_path / "t.db"
    _seed_posts(db)
    mod = _load_backfill_mod()
    items = [
        {
            "post_id": "a1",
            "as_of": "20260716",
            "post_date": "2026-07-16",
            "post_time": "10:00",
            "snippet": "大盤 C3-3 主跌段開始啟動，細微波還在走",
        },
        {
            "post_id": "a2",
            "as_of": "20260724",
            "post_date": "2026-07-24",
            "post_time": "18:00",
            "snippet": "重新修訂波浪位階；先前預估偏了",
        },
        {
            "post_id": "a3",
            "as_of": "20260729",
            "post_date": "2026-07-29",
            "post_time": "12:00",
            "snippet": "大盤細微波確認 A 波低，C3-3 延續",
        },
    ]
    r1 = mod.insert_missing_snaps(db, items)
    assert r1["inserted"] == 3
    r2 = mod.insert_missing_snaps(db, items)
    assert r2["inserted"] == 0
    assert r2["skipped_existing"] == 3
    ver = mod.verify_all_chronological(db)
    assert ver["marked"] >= 1
    con = sqlite3.connect(str(db))
    charts = con.execute(
        "SELECT COUNT(*) FROM biaoke_level_snaps WHERE IFNULL(chart_path,'')!=''"
    ).fetchone()[0]
    con.close()
    assert charts == 0


def test_scripts_not_on_sys_path_after_load():
    before = list(sys.path)
    _load_backfill_mod()
    scripts = str(ROOT / "scripts")
    # 載入後不准把 scripts 目錄插到 path 前端（避免遮蔽根目錄同名模組）
    assert sys.path[0] != scripts
    assert before[0] == sys.path[0] or scripts not in sys.path[:3]
