# -*- coding: utf-8 -*-
"""各靜默軌獨立成功／失敗戳：融合 success 不准蓋掉後面失敗。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from silent_track_runs import (
    CORE_AFTER_FUSE,
    PIPE_PREFIX,
    failed_or_missing_tracks,
    mark_track,
    pipeline_key,
    run_tracked,
    silent_tracks_health,
    track_status,
)


def _seed_pipeline_db(tmp_path: Path) -> str:
    db = str(tmp_path / "wayne_market.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE pipeline_runs (
            run_date TEXT PRIMARY KEY,
            finished_at TEXT,
            status TEXT,
            notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def test_pipeline_key_shape():
    assert pipeline_key("screen-buckets", "20261016") == "sv-screen-buckets-20261016"
    assert pipeline_key("book_hold", "2026-10-16") == "sv-book-hold-20261016"
    assert PIPE_PREFIX == "sv-"


def test_run_tracked_success_and_error_stamps(tmp_path):
    db = _seed_pipeline_db(tmp_path)
    day = "20261016"
    ok = run_tracked(db, "pressure", day, lambda: {"n": 3}, note_ok="n=3")
    assert ok["ok"] is True
    hit = track_status(db, "pressure", day)
    assert hit and hit["status"] == "success"
    assert hit["run_date"] == "sv-pressure-20261016"

    def _boom():
        raise RuntimeError("inject fail")

    bad = run_tracked(db, "fear", day, _boom)
    assert bad["ok"] is False
    hit2 = track_status(db, "fear", day)
    assert hit2 and hit2["status"] == "error"
    assert "inject fail" in (hit2.get("notes") or "")


def test_fuse_success_does_not_hide_track_failure(tmp_path):
    """融合 success 與靜默軌 error 並存；健檢要亮軌失敗。"""
    db = _seed_pipeline_db(tmp_path)
    day = "20261016"
    mark_track(db, "screen-buckets", day, "success", "n=1")
    mark_track(db, "streak", day, "error", "boom")
    # 模擬融合本身 success（裸 YYYYMMDD 鍵）
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (day, "2026-10-16T17:09:00", "success", "increment ok"),
    )
    conn.commit()
    conn.close()

    fuse = track_status(db, "screen-buckets", day)
    assert fuse and fuse["status"] == "success"
    bad = failed_or_missing_tracks(db, day, tracks=("screen-buckets", "streak", "fear"))
    kinds = {r["track"] for r in bad}
    assert "streak" in kinds
    assert "fear" in kinds  # missing
    assert "screen-buckets" not in kinds

    health = silent_tracks_health(db, day, tracks=("screen-buckets", "streak"))
    assert health["ok"] is False
    assert any("連買" in r or "streak" in r for r in health["reasons"])


def test_core_tracks_cover_report_list():
    # 巡檢報告「掛在盤後融合後面」的核心軌都要有獨立鍵
    for t in (
        "screen-buckets",
        "streak",
        "dongzhu",
        "market-aux",
        "pressure",
        "volzone-ma60",
        "buy-exclude",
        "winrate-vz-filter",
        "lookup-chart",
        "stabilize",
        "biaoke-diverge",
        "fear",
        "foreign-sell-escalate",
        "foreign-sell-extreme",
        "foreign-sell-calm",
        "book-hold",
        "book-watch",
        "book-buy",
    ):
        assert t in CORE_AFTER_FUSE


def test_snapshot_button_lists_stamps_screen_buckets(tmp_path, monkeypatch):
    from judge_tape import snapshot_button_lists
    from screen_sessions import save_screen_session

    db = str(tmp_path / "wayne_market.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market_type TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY(date, stock_id)
        );
        CREATE TABLE pipeline_runs (
            run_date TEXT PRIMARY KEY, finished_at TEXT, status TEXT, notes TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260915", "1101", "台泥", "TW", 50, 51, 49, 50.4, 8000),
    )
    conn.commit()
    conn.close()
    save_screen_session(
        db,
        "20260915",
        "morning",
        {"leave_zero": [{"stock_id": "1101", "stock_name": "台泥", "close": 50.4}]},
    )
    # 避免外網／重模組：壓撐路徑在 pytest 下本就跳過
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    stats = snapshot_button_lists(db, "20260915")
    assert stats.get("leave_zero") == 1
    hit = track_status(db, "screen-buckets", "20260915")
    assert hit and hit["status"] == "success"


def test_snapshot_marks_error_when_streak_raises(tmp_path, monkeypatch):
    from judge_tape import snapshot_button_lists

    db = str(tmp_path / "wayne_market.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE pipeline_runs (
            run_date TEXT PRIMARY KEY, finished_at TEXT, status TEXT, notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")

    def _boom(*_a, **_k):
        raise RuntimeError("streak down")

    monkeypatch.setattr("judge_tape._freeze_streak", _boom)
    snapshot_button_lists(db, "20260915")
    hit = track_status(db, "streak", "20260915")
    assert hit and hit["status"] == "error"
    assert "streak down" in (hit.get("notes") or "")


def test_pipeline_expectations_surfaces_silent_fail(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from automation_health import pipeline_expectations_met

    db = _seed_pipeline_db(tmp_path)
    day = "20261016"
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO pipeline_runs VALUES (?,?,?,?)",
        (day, "2026-10-16T17:09:00", "success", "increment"),
    )
    conn.commit()
    conn.close()
    mark_track(db, "pressure", day, "error", "rank boom")

    now = datetime(2026, 10, 16, 18, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("config.taipei_now", lambda: now)
    monkeypatch.setattr("config.taipei_today_str", lambda: day)
    monkeypatch.setattr("trading_calendar.is_trading_weekday", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "trading_calendar.fuse_end_trading_date", lambda *_a, **_k: day
    )
    # 避開早報路徑；本測只鎖靜默軌失敗會亮
    monkeypatch.setattr("config.scheduler_owns", lambda *_a, **_k: False)

    rep = pipeline_expectations_met(db, cap=day)
    assert rep.get("ok") is False
    joined = "；".join(rep.get("reasons") or [])
    assert "靜默軌" in joined
    assert rep.get("silent_tracks", {}).get("ok") is False
