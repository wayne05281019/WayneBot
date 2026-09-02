# -*- coding: utf-8 -*-
"""排程死人開關與心跳。"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops_watchdog import (  # noqa: E402
    HEARTBEAT_POLLING,
    claim_alert,
    ensure_ops_tables,
    format_watchdog_alert,
    heartbeat_age_seconds,
    missed_jobs,
    polling_alive,
    record_heartbeat,
    watchdog_payload,
    watchdog_scan,
)


def _make_db(tmp_path, runs=None, quote_date="20260902"):
    path = str(tmp_path / "w.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE pipeline_runs (run_date TEXT PRIMARY KEY, finished_at TEXT, status TEXT, notes TEXT)"
    )
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, close REAL, volume INTEGER)"
    )
    for run_date, status in (runs or {}).items():
        conn.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?, ?, '')",
            (run_date, datetime.now().isoformat(timespec="seconds"), status),
        )
    conn.commit()
    conn.close()
    ensure_ops_tables(path)
    return path


def test_heartbeat_roundtrip(tmp_path):
    path = _make_db(tmp_path)
    assert heartbeat_age_seconds(path, HEARTBEAT_POLLING) is None
    assert polling_alive(path) is None

    record_heartbeat(path, HEARTBEAT_POLLING, "test")
    age = heartbeat_age_seconds(path, HEARTBEAT_POLLING)
    assert age is not None and age < 60
    assert polling_alive(path) is True


def test_heartbeat_goes_stale(tmp_path):
    path = _make_db(tmp_path)
    record_heartbeat(path, HEARTBEAT_POLLING)
    future = datetime.now() + timedelta(hours=2)
    assert polling_alive(path, now=future) is False


def test_heartbeat_missing_db_is_quiet(tmp_path):
    missing = str(tmp_path / "nope.db")
    assert heartbeat_age_seconds(missing, HEARTBEAT_POLLING) is None
    record_heartbeat("", HEARTBEAT_POLLING)


def test_missed_jobs_before_deadline_is_empty(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    # 週三 05:00：兩個死線都還沒到
    now = datetime(2026, 9, 2, 5, 0)
    assert missed_jobs(path, now=now) == []


def test_missed_jobs_flags_morning_screen(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    now = datetime(2026, 9, 2, 9, 0)  # 過了 08:00 死線
    missed = missed_jobs(path, now=now)
    kinds = {m["kind"] for m in missed}
    assert kinds == {"morning_screen"}
    assert missed[0]["status"] == "無紀錄"


def test_missed_jobs_success_clears(tmp_path, monkeypatch):
    path = _make_db(tmp_path, runs={"screen-20260902": "success"})
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    now = datetime(2026, 9, 2, 9, 0)
    assert missed_jobs(path, now=now) == []


def test_missed_jobs_incomplete_still_alerts(tmp_path, monkeypatch):
    path = _make_db(tmp_path, runs={"screen-20260902": "incomplete"})
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    now = datetime(2026, 9, 2, 9, 0)
    missed = missed_jobs(path, now=now)
    assert [m["status"] for m in missed] == ["incomplete"]


def test_missed_jobs_flags_both_after_evening(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    now = datetime(2026, 9, 2, 19, 0)  # 過了 18:30
    kinds = {m["kind"] for m in missed_jobs(path, now=now)}
    assert kinds == {"increment", "morning_screen"}


def test_missed_jobs_skips_weekend(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260904")
    saturday = datetime(2026, 9, 5, 19, 0)
    assert saturday.weekday() == 5
    assert missed_jobs(path, now=saturday) == []


def test_claim_alert_dedupes(tmp_path):
    path = _make_db(tmp_path)
    assert claim_alert(path, "increment", "20260902") is True
    assert claim_alert(path, "increment", "20260902") is False
    assert claim_alert(path, "increment", "20260903") is True
    assert claim_alert(path, "morning_screen", "20260902") is True


def test_watchdog_scan_alerts_once(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    now = datetime(2026, 9, 2, 19, 0)

    first = watchdog_scan(path, now=now, check_release=False)
    assert first["enabled"] is True
    assert len(first["alerts"]) == 2

    second = watchdog_scan(path, now=now, check_release=False)
    assert len(second["missed"]) == 2
    assert second["alerts"] == []


def test_watchdog_scan_disabled(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setenv("WAYNE_WATCHDOG_ENABLED", "false")
    now = datetime(2026, 9, 2, 19, 0)
    scan = watchdog_scan(path, now=now, check_release=False)
    assert scan["enabled"] is False
    assert scan["alerts"] == []


def test_watchdog_scan_no_claim_is_readonly(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    now = datetime(2026, 9, 2, 19, 0)
    a = watchdog_scan(path, now=now, claim=False, check_release=False)
    b = watchdog_scan(path, now=now, claim=False, check_release=False)
    assert len(a["alerts"]) == len(b["alerts"]) == 2


def test_format_watchdog_alert():
    assert format_watchdog_alert([]) == ""
    text = format_watchdog_alert(
        [{"label": "早上海選", "scheduled": "06:30", "run_date": "screen-20260902", "status": "無紀錄"}]
    )
    assert "早上海選" in text
    assert "06:30" in text
    assert "screen-20260902" in text
    assert "國定假日" in text


def test_watchdog_payload_shape(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    payload = watchdog_payload(path)
    assert set(payload) >= {"enabled", "missed", "missed_n", "polling_alive", "polling_age_s"}
    assert payload["missed_n"] == len(payload["missed"])


def test_ensure_ops_tables_idempotent(tmp_path):
    path = _make_db(tmp_path)
    ensure_ops_tables(path)
    ensure_ops_tables(path)
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"ops_heartbeat", "ops_alerts"} <= names


class _Resp:
    def __init__(self, last_modified):
        self.headers = {"Last-Modified": last_modified} if last_modified else {}


def _fake_head(last_modified):
    def _head(url, **kwargs):
        return _Resp(last_modified)

    return _head


def test_release_age_unknown_when_header_missing(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "head", _fake_head(None))
    from ops_watchdog import gha_pipeline_stale, release_asset_age_days

    assert release_asset_age_days() is None
    stale = gha_pipeline_stale()
    assert stale["known"] is False
    assert stale["stale"] is False


def test_release_fresh_is_not_stale(monkeypatch):
    import email.utils

    import requests

    fresh = email.utils.format_datetime(datetime.now().astimezone() - timedelta(hours=6))
    monkeypatch.setattr(requests, "head", _fake_head(fresh))
    from ops_watchdog import gha_pipeline_stale

    stale = gha_pipeline_stale()
    assert stale["known"] is True
    assert stale["stale"] is False
    assert stale["age_days"] < 1


def test_release_stale_is_flagged(monkeypatch):
    import email.utils

    import requests

    old = email.utils.format_datetime(datetime.now().astimezone() - timedelta(days=9))
    monkeypatch.setattr(requests, "head", _fake_head(old))
    from ops_watchdog import gha_pipeline_stale

    stale = gha_pipeline_stale()
    assert stale["known"] is True
    assert stale["stale"] is True
    assert stale["age_days"] > 8


def test_release_network_error_is_unknown(monkeypatch):
    import requests

    def _boom(url, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(requests, "head", _boom)
    from ops_watchdog import gha_pipeline_stale

    assert gha_pipeline_stale()["known"] is False


def test_watchdog_scan_alerts_on_stale_release(tmp_path, monkeypatch):
    import email.utils

    import requests

    path = _make_db(tmp_path, runs={"screen-20260902": "success", "20260902": "success"})
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    old = email.utils.format_datetime(datetime.now().astimezone() - timedelta(days=9))
    monkeypatch.setattr(requests, "head", _fake_head(old))

    now = datetime(2026, 9, 2, 19, 0)
    first = watchdog_scan(path, now=now)
    kinds = [a["kind"] for a in first["alerts"]]
    assert kinds == ["release_publish"]

    second = watchdog_scan(path, now=now)
    assert second["alerts"] == []


def test_watchdog_release_check_can_be_disabled(tmp_path, monkeypatch):
    import email.utils

    import requests

    path = _make_db(tmp_path, runs={"screen-20260902": "success", "20260902": "success"})
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")
    old = email.utils.format_datetime(datetime.now().astimezone() - timedelta(days=9))
    monkeypatch.setattr(requests, "head", _fake_head(old))
    monkeypatch.setenv("WAYNE_WATCHDOG_RELEASE", "false")

    now = datetime(2026, 9, 2, 19, 0)
    assert watchdog_scan(path, now=now)["alerts"] == []


def test_watchdog_payload_does_not_touch_network(tmp_path, monkeypatch):
    import requests

    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260902")

    def _boom(*a, **k):
        raise AssertionError("/ready 不該打外部網路")

    monkeypatch.setattr(requests, "head", _boom)
    watchdog_payload(path)


def test_missed_jobs_unresolved_screen_date_is_skipped(tmp_path, monkeypatch):
    path = _make_db(tmp_path)
    monkeypatch.setattr("trading_calendar.resolve_screen_as_of", lambda *a, **k: "")
    now = datetime(2026, 9, 2, 9, 0)
    kinds = {m["kind"] for m in missed_jobs(path, now=now)}
    assert "morning_screen" not in kinds
