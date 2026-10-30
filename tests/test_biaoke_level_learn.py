# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import os
import sqlite3

import pytest

from biaoke_level_learn import (
    ensure_tables,
    looks_like_level_now,
    record_level_learn_from_events,
    verify_pending_with_event,
)


def test_looks_like_level_now_index_wave():
    assert looks_like_level_now("大盤 C3-3 主跌段開始啟動")
    assert looks_like_level_now("目前只是C3-3-1轉C3-3-2")
    assert looks_like_level_now("橫台整理只是中繼站，細微波之後南下")
    assert not looks_like_level_now("今天天氣不錯")


def test_ingest_hooks_level_learn():
    from biaoke_ingest import _after_ingest_analyze

    src = inspect.getsource(_after_ingest_analyze)
    assert "record_level_learn_from_events" in src


def test_verify_pending_optimistic_then_crash(tmp_path):
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO biaoke_level_snaps(post_id, as_of, snippet, pending, created_at) "
        "VALUES ('a','20261028','大盤已經止跌，打第二隻腳',1,'t')"
    )
    conn.commit()
    conn.close()
    n = verify_pending_with_event(
        db, "b", "大盤 C3-3 主跌段開始啟動，跳空確認"
    )
    assert n == 1
    row = sqlite3.connect(db).execute(
        "SELECT pending, verdict FROM biaoke_level_snaps WHERE post_id='a'"
    ).fetchone()
    assert row[0] == 0 and row[1] == "偏"


def test_record_skips_under_pytest(tmp_path, monkeypatch):
    monkeypatch.delenv("WAYNE_LEVEL_LEARN_LIVE", raising=False)
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    stats = record_level_learn_from_events(
        db, [{"id": "x", "date": "20261030", "time": "09:18", "text": "大盤 C3-3 主跌"}]
    )
    assert stats.get("skipped") == "pytest"
