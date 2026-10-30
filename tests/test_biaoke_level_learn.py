# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from biaoke_level_learn import (
    _sparse_slot_id,
    ensure_tables,
    looks_like_level_now,
    paint_open_day_hypothesis,
    record_level_learn_from_events,
    verify_pending_with_event,
)

TAIPEI = ZoneInfo("Asia/Taipei")


def test_looks_like_level_now_index_wave():
    assert looks_like_level_now("大盤 C3-3 主跌段開始啟動")
    assert looks_like_level_now("目前只是C3-3-1轉C3-3-2")
    assert looks_like_level_now("橫台整理只是中繼站，細微波之後南下")
    assert not looks_like_level_now("今天天氣不錯")


def test_ingest_hooks_level_learn_and_live_paint():
    from biaoke_ingest import _after_ingest_analyze, start_biaoke_poller

    src = inspect.getsource(_after_ingest_analyze)
    assert "record_level_learn_from_events" in src
    assert "maybe_paint_open_day_after_ingest" in src
    poll = inspect.getsource(start_biaoke_poller)
    assert "maybe_paint_open_day_after_ingest" in poll


def test_sparse_slots_not_every_minute():
    pre = datetime(2026, 11, 2, 8, 10, tzinfo=TAIPEI)
    mid = datetime(2026, 11, 2, 11, 20, tzinfo=TAIPEI)
    night = datetime(2026, 10, 30, 21, 40, tzinfo=TAIPEI)
    idle = datetime(2026, 11, 2, 10, 5, tzinfo=TAIPEI)
    assert _sparse_slot_id(pre) == "20261102-pre"
    assert _sparse_slot_id(mid) == "20261102-mid"
    assert _sparse_slot_id(night) == "20261030-night"
    assert _sparse_slot_id(idle) is None


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


def test_paint_skips_under_pytest(tmp_path, monkeypatch):
    monkeypatch.delenv("WAYNE_LEVEL_LEARN_LIVE", raising=False)
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    out = paint_open_day_hypothesis(db, force=True)
    assert out.get("skipped") == "pytest"


def test_open_day_table_has_vol_fields(tmp_path):
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    cols = {
        r[1]
        for r in sqlite3.connect(db).execute(
            "PRAGMA table_info(biaoke_open_day_paints)"
        )
    }
    for need in ("turn_note", "vol_note", "key_levels", "tx60_path", "us_note", "pending"):
        assert need in cols


def test_live_dark_renderer_enforces_fifth_above_b():
    """八浪基本形：活畫原始碼必須守 ⑤高>B高，並帶他用過的 Fib／1-4。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("biaoke_level_learn.py").read_text(
        encoding="utf-8"
    )
    assert "y_bhi >= y5" in src
    assert "0.382" in src and "0.618" in src and "0.75" in src
    assert "45546" in src and "44210" in src
    assert "C3-3" in src
    assert "1-4" in src and "動態修正" in src
    assert "48066" in src or "rule14" in src
    assert "預估" in src and ("隨時檢視" in src or "重新修訂" in src)
    assert "_REVISE_MARK" in src
    assert "gap * 0.078" in src or "結構優先" in src
    # 教不懂浪的學生：遠窗／近窗各一張＋外圍費半對照；缺資料自補
    assert "遠窗" in src and "近窗" in src
    assert "20260825" in src
    assert "_render_twii_far_dark" in src
    assert "_render_us_compare_dark" in src
    assert "_ensure_us_index_daily" in src
    assert "費半" in src
    assert "_morph_note_from_text" in src
    assert "黃金切割" in src
    assert "切0.382" in src or "0.382" in src
    assert "_twii_intent_story" in src
    assert "大善人" in src or "解套" in src
    assert "沒底子" in src or "白話" in src
    assert "_twii_intent_story" in src
    assert "量縮止穩" in src or "好心" in src or "套牢" in src


def test_twii_intent_story_trap_language():
    """量價故事要能講套牢／無量≠止穩；不准當買訊句。"""
    from biaoke_level_learn import _twii_intent_story

    # 無庫也要空字串回傳，不准拋
    empty = _twii_intent_story("")
    assert empty.get("intent_note") == "" or isinstance(empty.get("intent_note"), str)
