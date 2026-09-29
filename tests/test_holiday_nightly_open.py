# -*- coding: utf-8 -*-
"""休市年曆＋深夜 03:00 查明日開盤＋早報 skip／push 回歸。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import sqlite3

TW = ZoneInfo("Asia/Taipei")

_TWSE_ROWS = [
    {"Name": "中秋節", "Date": "1150925", "Description": "依規定放假1日。"},
    {"Name": "教師節", "Date": "1150928", "Description": "依規定放假1日。"},
    {"Name": "勞動節", "Date": "1150501", "Description": "依規定放假1日。"},
    {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150212", "Description": ""},
]


def test_persist_tw_seed_and_yearly_refresh(tmp_path, monkeypatch):
    from tw_holidays import (
        load_tw_open_check,
        lookup_tw_session,
        persist_tw_seed_holidays,
        refresh_yearly_holiday_calendars,
        run_nightly_tomorrow_open_check,
    )
    from us_holidays import lookup_us_session, persist_us_seed_holidays

    db = str(tmp_path / "cal.db")
    seed = persist_tw_seed_holidays(db)
    assert seed["ok"]
    assert seed["inserted"] >= 10
    assert lookup_tw_session("20260925", db)["kind"] == "full_close"
    assert lookup_tw_session("20260925", db)["source"] == "seed"

    us = persist_us_seed_holidays(db)
    assert us["ok"]
    assert lookup_us_session("20260907", db)["kind"] == "full_close"

    monkeypatch.setattr(
        "tw_holidays.fetch_twse_holiday_rows",
        lambda *a, **k: _TWSE_ROWS,
    )
    monkeypatch.setattr(
        "us_holidays.fetch_nyse_calendar_html",
        lambda *a, **k: "<html></html>",
    )
    monkeypatch.setattr(
        "tw_holidays.fetch_dgpa_nds_html",
        lambda *a, **k: (
            "<div class='Header_YMD'>115年 9月 24日</div>"
            "<h2>無停班停課訊息。</h2>"
        ),
    )
    out = refresh_yearly_holiday_calendars(db)
    assert out["seed"]["ok"]
    # TWSE mock 夠列 → ok；美股 HTML 空 → us ok False，整體 ok False 但不擋
    assert out["tw"].get("ok") is True


def test_nightly_marks_mid_autumn_tomorrow_closed(tmp_path, monkeypatch):
    from tw_holidays import load_tw_open_check, run_nightly_tomorrow_open_check

    db = str(tmp_path / "night.db")
    monkeypatch.setattr(
        "tw_holidays.fetch_twse_holiday_rows",
        lambda *a, **k: _TWSE_ROWS,
    )
    monkeypatch.setattr(
        "us_holidays.fetch_nyse_calendar_html",
        lambda *a, **k: "<html></html>",
    )
    monkeypatch.setattr(
        "tw_holidays.fetch_dgpa_nds_html",
        lambda *a, **k: (
            "<div class='Header_YMD'>115年 9月 24日</div>"
            "<h2>無停班停課訊息。</h2>"
        ),
    )
    # 中秋前一晚 03:00 → 明日 09/25 休市
    now = datetime(2026, 9, 25, 3, 0, tzinfo=TW) - __import__("datetime").timedelta(days=1)
    out = run_nightly_tomorrow_open_check(db, now=now)
    assert out["status"]["target_ymd"] == "20260925"
    assert out["status"]["is_open"] is False
    assert out["status"]["kind"] == "full_close"
    rec = load_tw_open_check("20260925", db)
    assert rec is not None
    assert rec["is_open"] is False
    assert "中秋" in (rec.get("name_zh") or "")


def test_nightly_marks_first_open_after_holiday_open(tmp_path, monkeypatch):
    from tw_holidays import load_tw_open_check, run_nightly_tomorrow_open_check

    db = str(tmp_path / "open.db")
    monkeypatch.setattr(
        "tw_holidays.fetch_twse_holiday_rows",
        lambda *a, **k: _TWSE_ROWS,
    )
    monkeypatch.setattr(
        "us_holidays.fetch_nyse_calendar_html",
        lambda *a, **k: "<html></html>",
    )
    monkeypatch.setattr(
        "tw_holidays.fetch_dgpa_nds_html",
        lambda *a, **k: (
            "<div class='Header_YMD'>115年 9月 28日</div>"
            "<h2>無停班停課訊息。</h2>"
        ),
    )
    # 教師節當日深夜 03:00 → 明日 09/29 開市（連假後第一個開市日）
    now = datetime(2026, 9, 28, 3, 0, tzinfo=TW)
    out = run_nightly_tomorrow_open_check(db, now=now)
    assert out["status"]["target_ymd"] == "20260929"
    assert out["status"]["is_open"] is True
    rec = load_tw_open_check("20260929", db)
    assert rec["is_open"] is True


def test_nightly_fail_soft_on_network(tmp_path, monkeypatch):
    from tw_holidays import load_tw_open_check, run_nightly_tomorrow_open_check

    db = str(tmp_path / "soft.db")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("tw_holidays.fetch_twse_holiday_rows", _boom)
    monkeypatch.setattr("us_holidays.fetch_nyse_calendar_html", _boom)
    monkeypatch.setattr("tw_holidays.fetch_dgpa_nds_html", _boom)
    # 種子仍能判斷 09/25 休市
    now = datetime(2026, 9, 24, 3, 0, tzinfo=TW)
    out = run_nightly_tomorrow_open_check(db, now=now)
    assert out["status"]["target_ymd"] == "20260925"
    assert out["status"]["is_open"] is False
    assert load_tw_open_check("20260925", db)["is_open"] is False


def test_runner_nightly_writes_pipeline_and_skip_if_done(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    db = str(tmp_path / "pipe.db")
    ensure_core_schema(db)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = db
    marks = []

    monkeypatch.setattr(
        "tw_holidays.run_nightly_tomorrow_open_check",
        lambda *a, **k: {
            "ok": True,
            "status": {
                "target_ymd": "20260925",
                "is_open": False,
                "kind": "full_close",
                "name_zh": "中秋節",
            },
        },
    )
    monkeypatch.setattr(
        "tw_holidays.load_tw_open_check",
        lambda *a, **k: {
            "target_ymd": "20260925",
            "is_open": False,
            "kind": "full_close",
            "name_zh": "中秋節",
        },
    )

    def _mark(status, notes="", run_date=None):
        marks.append((status, notes, run_date))

    def _status(run_date=None):
        for st, _n, rd in marks:
            if rd == run_date:
                return st
        return ""

    runner._mark_pipeline = _mark  # type: ignore
    runner.pipeline_status = _status  # type: ignore
    now = datetime(2026, 9, 24, 3, 0, tzinfo=TW)
    assert runner.run_nightly_open_check(now=now, skip_if_done=True) is True
    assert marks[-1][2] == "open-check-20260925"
    assert marks[-1][0] == "success"
    n_before = len(marks)
    assert runner.run_nightly_open_check(now=now, skip_if_done=True) is True
    assert len(marks) == n_before  # skip_if_done


def test_morning_closed_after_nightly_uses_screen_closed(tmp_path, monkeypatch):
    """連假休市日：深夜記 closed → 今早仍 screen-closed-*，不准假 success 擋開市日。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema
    from tw_holidays import record_tw_open_check

    path = str(tmp_path / "morn.db")
    ensure_core_schema(path)
    record_tw_open_check(
        "20260928",
        is_open=False,
        kind="full_close",
        name_zh="教師節",
        source="seed",
        notes="nightly-03:00",
        db_path=path,
    )
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260928"
    marks = []
    monkeypatch.setattr(
        "tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {"ok": True}
    )
    monkeypatch.setattr(
        "tw_holidays.closed_tw_session",
        lambda **_k: {"ymd": "20260928", "zh": "教師節", "kind": "full_close"},
    )

    def _mark(status, notes="", run_date=None):
        marks.append((status, notes, run_date))

    runner._mark_pipeline = _mark  # type: ignore
    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    assert marks == [
        (
            "success",
            "tw closed 20260928 教師節 skip morning",
            "screen-closed-20260928",
        )
    ]


def test_morning_first_open_day_pushes_despite_prior_closed_key(tmp_path, monkeypatch):
    """連假後第一個開市日：screen-closed-* 不擋 screen-{as_of} 真寄。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user
    from tw_holidays import record_tw_open_check

    path = str(tmp_path / "first_open.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (
            "screen-closed-20260928",
            "2026-09-28T03:05:00",
            "success",
            "tw closed 20260928 教師節 skip morning",
        ),
    )
    conn.commit()
    conn.close()
    record_tw_open_check(
        "20260929",
        is_open=True,
        kind="open",
        name_zh="",
        source="weekday",
        notes="nightly-03:00",
        db_path=path,
    )

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260929"
    runner.chat_id = "9001"
    runner.bot = type(
        "B", (), {"send_screening_report": staticmethod(lambda *a, **k: True)}
    )()
    runner._format_watch_radar_section = lambda uid="": ""
    runner._run_ai_desk = lambda *a, **k: {}
    runner.send_telegram_message = lambda *a, **k: None

    monkeypatch.setattr(
        "tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {"ok": True}
    )
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *_a, **_k: "20260924",
    )
    monkeypatch.setattr("config.fuse_end_date", lambda: "20260924")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {
            "status": "success",
            "payload": [{"html": "海選"}],
            "results": {},
        },
    )
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr("taiwan_market.sync_futures_inst_oi", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)
    monkeypatch.setattr("taiwan_market.format_taiwan_market_brief_html", lambda *_a, **_k: "")
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False})
    runner._refresh_official_sidecars = lambda: None
    runner.demote_premature_morning_screens = lambda: 0
    runner.demote_holiday_skip_morning_screens = lambda: 0

    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    assert runner.already_completed_today("screen-20260924") is True
    assert runner.pipeline_status("screen-closed-20260928") == "success"


def test_do_not_invent_fake_holidays():
    """沒官方／種子列的平日必須當開市，不准猜假日。"""
    from tw_holidays import lookup_tw_session

    assert lookup_tw_session("20260923")["kind"] == "open"  # 週三
    assert lookup_tw_session("20260310")["kind"] == "open"  # 週二、非種子休市
    assert lookup_tw_session("20260926")["kind"] == "weekend"  # 週六
