# -*- coding: utf-8 -*-
"""自動化管線巡檢：過濾器、日K、基準日、缺口。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from automation_health import (
    format_automation_audit_plain,
    pipeline_expectations_met,
    quote_filter_regression_ok,
    run_automation_audit,
    verify_release_snapshot,
)
from import_health import MIN_TWO, MIN_TW
from wayne_db import ensure_core_schema


def test_quote_filter_regression_ok():
    r = quote_filter_regression_ok()
    assert r["ok"] is True
    assert r["kept"] == 2
    assert r["dropped"] >= 1


def test_run_automation_audit_fails_without_db():
    report = run_automation_audit("/nonexistent/path.db", cap="20260902")
    assert report["ok"] is False
    assert any("資料庫" in r for r in report["reasons"])
    assert report["checks"]["quote_filter"]["ok"] is True


def _seed_day(conn: sqlite3.Connection, ymd: str) -> None:
    for i in range(MIN_TW):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,10,0,0)""",
            (ymd, f"{1000+i:04d}", "TW", "TW"),
        )
    for i in range(MIN_TWO):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,50,0,0)""",
            (ymd, f"{6000+i:04d}", "上櫃", "TWO"),
        )


def test_pipeline_expectations_skips_empty_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        r = pipeline_expectations_met(path, cap="20260902")
        assert r.get("skipped") is True
        assert r.get("ok") is True
    finally:
        os.remove(path)


def _seed_pipeline_row(path: str, run_date: str = "20260909") -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs(run_date, finished_at, status, notes) VALUES (?,?,?,?)",
        (run_date, "2026-09-09T16:40:00", "success", "increment"),
    )
    conn.commit()
    conn.close()


def test_pipeline_expectations_skips_morning_on_gha_zip(monkeypatch):
    """GHA 巡檢的是 Release zip，不能當今早海選有沒有寄。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        _seed_pipeline_row(path)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
        now = datetime(2026, 9, 10, 8, 43, tzinfo=ZoneInfo("Asia/Taipei"))
        monkeypatch.setattr("config.taipei_now", lambda: now)
        monkeypatch.setattr("config.taipei_today_str", lambda: "20260910")
        r = pipeline_expectations_met(path, cap="20260909")
        assert r.get("ok") is True
        assert r.get("skipped") is True
        assert r.get("reasons") == []
    finally:
        os.remove(path)


def test_pipeline_expectations_requires_morning_on_resident(monkeypatch):
    """常駐碟 07:00 後沒有 screen success，巡檢必須紅。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        _seed_pipeline_row(path)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
        now = datetime(2026, 9, 10, 8, 43, tzinfo=ZoneInfo("Asia/Taipei"))
        monkeypatch.setattr("config.taipei_now", lambda: now)
        monkeypatch.setattr("config.taipei_today_str", lambda: "20260910")
        monkeypatch.setattr(
            "trading_calendar.morning_screen_pipeline_key",
            lambda *_a, **_k: "screen-20260909",
        )
        r = pipeline_expectations_met(path, cap="20260909")
        assert r.get("ok") is False
        assert any("早上海選 screen-20260909 未成功" == x for x in r.get("reasons") or [])
    finally:
        os.remove(path)


def test_pipeline_expectations_resident_ok_when_screen_success(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        _seed_pipeline_row(path)
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs(run_date, finished_at, status, notes) VALUES (?,?,?,?)",
            ("screen-20260909", "2026-09-10T06:32:00", "success", "sent"),
        )
        conn.commit()
        conn.close()
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
        now = datetime(2026, 9, 10, 8, 43, tzinfo=ZoneInfo("Asia/Taipei"))
        monkeypatch.setattr("config.taipei_now", lambda: now)
        monkeypatch.setattr("config.taipei_today_str", lambda: "20260910")
        monkeypatch.setattr(
            "trading_calendar.morning_screen_pipeline_key",
            lambda *_a, **_k: "screen-20260909",
        )
        r = pipeline_expectations_met(path, cap="20260909")
        assert r.get("ok") is True, r
        assert r.get("reasons") == []
    finally:
        os.remove(path)


def test_pipeline_expectations_skips_morning_on_weekend(monkeypatch):
    """週六不寄早報；即使 cap 仍是上周五，也不該為 screen 假紅。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        _seed_pipeline_row(path)
        conn = sqlite3.connect(path)
        # 上周五盤後融合已成功；週六不應再追早上海選
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs(run_date, finished_at, status, notes) VALUES (?,?,?,?)",
            ("20260911", "2026-09-11T16:40:00", "success", "increment"),
        )
        conn.commit()
        conn.close()
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
        now = datetime(2026, 9, 12, 17, 5, tzinfo=ZoneInfo("Asia/Taipei"))
        monkeypatch.setattr("config.taipei_now", lambda: now)
        monkeypatch.setattr("config.taipei_today_str", lambda: "20260912")
        monkeypatch.setattr(
            "trading_calendar.morning_screen_pipeline_key",
            lambda *_a, **_k: "screen-20260911",
        )
        r = pipeline_expectations_met(path, cap="20260911")
        assert r.get("ok") is True, r
        assert not any("早上海選" in str(x) for x in r.get("reasons") or [])
    finally:
        os.remove(path)


def test_verify_release_snapshot_passes_complete_day():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        conn = sqlite3.connect(path)
        _seed_day(conn, "20260902")
        conn.commit()
        conn.close()
        report = verify_release_snapshot(path)
        assert report["ok"] is True, report["reasons"]
        assert report["latest_complete"] == "20260902"
    finally:
        os.remove(path)


def test_run_automation_audit_passes_complete_day():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        conn = sqlite3.connect(path)
        _seed_day(conn, "20260902")
        conn.commit()
        conn.close()
        report = run_automation_audit(path, cap="20260902", max_gap_days=999)
        assert report["latest_complete"] == "20260902"
        assert report["checks"]["increment"]["ok"] is True
        text = format_automation_audit_plain(report)
        assert "過濾器回歸 OK" in text
    finally:
        os.remove(path)
