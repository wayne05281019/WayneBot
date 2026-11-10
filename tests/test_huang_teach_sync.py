"""台北 14:30 黃培碩對讀飆大畫線排程。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def test_pipeline_key_and_slot_constants():
    from huang_teach_sync import CATCHUP_UNTIL, SLOT_MINUTE, pipeline_key

    assert pipeline_key("20261110") == "huang-teach-20261110"
    assert SLOT_MINUTE == 14 * 60 + 30
    assert CATCHUP_UNTIL > SLOT_MINUTE


def test_due_for_catchup_after_1430():
    from huang_teach_sync import due_for_catchup

    before = datetime(2026, 11, 10, 14, 29, tzinfo=TAIPEI)
    on = datetime(2026, 11, 10, 14, 30, tzinfo=TAIPEI)
    after = datetime(2026, 11, 10, 15, 0, tzinfo=TAIPEI)
    assert due_for_catchup(before) is False
    assert due_for_catchup(on) is True
    assert due_for_catchup(after) is True


def test_main_scheduler_has_huang_teach_1430():
    import inspect

    import main as m

    src = inspect.getsource(m.start_daily_scheduler)
    assert '(14, 30, "huang_teach")' in src
    run_src = inspect.getsource(m.run_scheduled_job)
    assert 'kind == "huang_teach"' in run_src
    catch = inspect.getsource(m.catch_up_missed_jobs)
    assert "need_huang" in catch
    assert "run_huang_teach_sync" in catch


def test_sparse_slot_huang_1430():
    from biaoke_level_learn import _sparse_slot_id

    dt = datetime(2026, 11, 10, 14, 30, tzinfo=TAIPEI)
    assert _sparse_slot_id(dt) == "20261110-huang"


def test_run_huang_teach_skips_closed(tmp_path, monkeypatch):
    from huang_teach_sync import run_huang_teach_sync

    db = str(tmp_path / "t.db")
    monkeypatch.setattr(
        "huang_teach_sync._is_open_day", lambda dt, db_path: False
    )
    out = run_huang_teach_sync(
        db,
        skip_if_done=False,
        now=datetime(2026, 11, 8, 14, 30, tzinfo=TAIPEI),  # Saturday
        force_paint=False,
    )
    assert out.get("skipped") == "closed"


def test_run_huang_teach_marks_success_without_video(tmp_path, monkeypatch):
    import sqlite3

    from huang_teach_sync import ensure_tables, pipeline_key, run_huang_teach_sync

    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE pipeline_runs("
        "run_date TEXT PRIMARY KEY, status TEXT, notes TEXT, finished_at TEXT)"
    )
    conn.commit()
    conn.close()
    ensure_tables(db)
    monkeypatch.setattr("huang_teach_sync._is_open_day", lambda dt, db_path: True)
    monkeypatch.setattr(
        "huang_teach_sync.find_huang_video_hint",
        lambda ymd: {"video_id": "", "video_title": "", "source": ""},
    )
    monkeypatch.setattr(
        "biaoke_ingest.run_biaoke_ingest_quiet", lambda: None, raising=False
    )

    def _paint(db_path, force=False, panels="full"):
        return {"ok": True, "slot_id": "force-20261110", "far_path": "/tmp/x.png"}

    monkeypatch.setattr(
        "biaoke_level_learn.paint_open_day_hypothesis", _paint, raising=False
    )
    # paint import path inside function
    import biaoke_level_learn as bll

    monkeypatch.setattr(bll, "paint_open_day_hypothesis", _paint)

    out = run_huang_teach_sync(
        db,
        skip_if_done=False,
        now=datetime(2026, 11, 10, 14, 30, tzinfo=TAIPEI),
        force_paint=True,
    )
    assert out.get("ok") is True
    assert out.get("paint_ok") is True
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status FROM pipeline_runs WHERE run_date=?",
        (pipeline_key("20261110"),),
    ).fetchone()
    conn.close()
    assert row and row[0] == "success"


def test_phone_wait_note_huang_window():
    from phone_update import phone_schedule_wait_note

    now = datetime(2026, 11, 10, 14, 35, tzinfo=TAIPEI)
    note = phone_schedule_wait_note(now=now)
    assert "黃培碩" in note


def test_classify_biaoke_before_huang_is_verify(tmp_path):
    """飆大發文在 14:30 前 → verify；之後 → compare。"""
    import sqlite3

    from huang_teach_sync import classify_biaoke_vs_huang

    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE biaoke_posts(id TEXT, date TEXT, time TEXT, text TEXT)"
    )
    conn.executemany(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?)",
        [
            ("a", "20261110", "09:15", "早盤看法"),
            ("b", "20261110", "11:00", "午前"),
            ("c", "20261110", "15:10", "黃片後補充"),
            ("d", "20261110", "14:30", "準點同刻＝比對側"),
        ],
    )
    conn.commit()
    conn.close()
    out = classify_biaoke_vs_huang(db, "20261110", video_hm="1430")
    assert out["verify_n"] == 2
    assert out["compare_n"] == 2
    assert out["mode"] == "verify+compare"
