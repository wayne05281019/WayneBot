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
)
from import_health import MIN_TWO, MIN_TW
from wayne_db import ensure_core_schema


def test_quote_filter_regression_ok():
    r = quote_filter_regression_ok()
    assert r["ok"] is True
    assert r["kept"] == 1
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
