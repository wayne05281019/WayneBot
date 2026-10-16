# -*- coding: utf-8 -*-
"""飆大危險時段只寫自己的表。其他按鍵的程式不准讀。"""
import inspect
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import biaoke_danger_silent as danger


def test_record_keeps_one_row_per_variant_and_does_not_replace(tmp_path):
    db = str(tmp_path / "w.db")
    now = datetime(2026, 10, 16, 23, 50, tzinfo=ZoneInfo("Asia/Taipei"))
    assert danger.record_danger_window(db, now=now) == 2
    assert danger.record_danger_window(db, now=now) == 2
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM biaoke_danger_window").fetchone()[0]
    judgment = conn.execute(
        "SELECT judgment FROM biaoke_danger_window LIMIT 1"
    ).fetchone()[0]
    assert "聯亞已賣出" in judgment
    assert "聯亞還在" not in judgment
    assert "不在清倉" not in judgment
    keys = {
        r[0]
        for r in conn.execute("SELECT track_key FROM biaoke_danger_window")
    }
    status = {
        r[0]
        for r in conn.execute("SELECT status FROM biaoke_danger_window")
    }
    variants = {
        r[0]
        for r in conn.execute("SELECT variant FROM biaoke_danger_rules")
    }
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert n == 2
    assert keys == {danger.TRACK_KEY}
    assert status == {"collecting"}
    assert variants == {"current", "next"}
    assert "leave_zero" not in tables
    assert "live_judge" not in tables
    gate = danger.replace_if_gated(db)
    assert gate["replaced"] is False
    assert gate["n"] == 1
    assert gate["reason"] == "n_short"
    src = inspect.getsource(danger.replace_if_gated)
    assert "leave_zero" not in src
    assert "golden_buy" not in src


def test_other_posts_do_not_open_a_row(tmp_path):
    db = str(tmp_path / "w.db")
    n = danger.record_from_events(
        db,
        [{"id": "185883781", "kind": "post", "text": "別的主文"}],
    )
    assert n == 0
    assert not os.path.isfile(db) or danger.collected_days(db) == 0


def test_same_day_closed_bar_compares_his_price(tmp_path):
    db = str(tmp_path / "w.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE futures_daily("
        "date TEXT, symbol TEXT, session TEXT, open REAL, high REAL, low REAL,"
        "close REAL, volume INTEGER)"
    )
    conn.execute(
        "INSERT INTO futures_daily VALUES('20261016','TX','regular',47228,47634,47140,47242,63312)"
    )
    conn.commit()
    conn.close()
    now = datetime(2026, 10, 16, 15, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    lines = danger.official_lines(db, now=now)
    tx = [x for x in lines if x.startswith("官方柱：台指期")]
    tw = [x for x in lines if x.startswith("官方柱：加權")]
    assert tx and "高還沒到他說的48240" in tx[0]
    assert "47634" in tx[0]
    assert tw and "缺完整官方開高低收" in tw[0]
    assert "46969" not in "\n".join(lines)


def test_unclosed_bar_is_not_a_close(tmp_path):
    db = str(tmp_path / "w.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE index_daily("
        "date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)"
    )
    conn.execute(
        "INSERT INTO index_daily VALUES('20261016','TWII',1,2,0.5,1.5,10)"
    )
    conn.commit()
    conn.close()
    now = datetime(2026, 10, 16, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    lines = danger.official_lines(db, now=now)
    tw = [x for x in lines if "加權" in x][0]
    assert "盤中未收" in tw
    assert "開1" not in tw


def test_other_buttons_do_not_reference_this_track():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    allow = {
        "biaoke_danger_silent.py",
        "biaoke_reweave.py",
        "biaoke_ingest.py",
        os.path.join("tests", "test_biaoke_danger_silent.py"),
    }
    hits = []
    for dirpath, names, files in os.walk(root):
        if any(p in dirpath for p in (".git", ".venv", "data", "__pycache__")):
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            text = open(path, encoding="utf-8").read()
            if "biaoke_danger_silent" in text or "biaoke_danger_window" in text:
                if rel not in allow:
                    hits.append(rel)
    assert hits == []
