# -*- coding: utf-8 -*-
"""盤後融合關卡：該有的數字不能是 0。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from import_health import (
    MIN_CHIPS_NONZERO,
    MIN_TWO,
    MIN_TW,
    increment_health_failures,
    increment_health_ok,
    verify_increment_import,
)
from main_runner import MainRunner
from wayne_db import ensure_core_schema


def test_increment_health_ok_rejects_any_zero_side():
    base = {"total": 2000, "chips_nonzero": 500}
    assert increment_health_ok({**base, "tw": 0, "two": 900}) is False
    assert increment_health_ok({**base, "tw": 900, "two": 0}) is False
    assert increment_health_ok({"total": 0, "tw": 900, "two": 900, "chips_nonzero": 500}) is False


def test_increment_health_ok_rejects_zero_chips_when_total_high():
    health = {"total": 2000, "tw": 900, "two": 700, "chips_nonzero": 0}
    assert increment_health_ok(health) is False
    assert any("法人" in r for r in increment_health_failures(health, cap="20260902"))


def test_increment_health_ok_passes_complete():
    health = {
        "total": 2000,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
    }
    assert increment_health_ok(health) is True
    assert increment_health_failures(health, cap="20260902") == []


def test_main_runner_increment_ok_uses_same_gate():
    runner = MainRunner.__new__(MainRunner)
    assert runner._increment_ok({"total": 0, "tw": 0, "two": 0}) is False
    assert runner._increment_ok(
        {"total": 2000, "tw": 900, "two": 700, "chips_nonzero": 500}
    ) is True


def _seed_complete_day(conn: sqlite3.Connection, ymd: str) -> None:
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


def test_verify_increment_import_fails_on_empty_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        report = verify_increment_import(path, cap="20260902")
        assert report["ok"] is False
        assert any("為 0" in r for r in report["reasons"])
    finally:
        os.remove(path)


def test_verify_increment_import_passes_when_sides_full():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        conn = sqlite3.connect(path)
        _seed_complete_day(conn, "20260902")
        conn.commit()
        conn.close()
        report = verify_increment_import(path, cap="20260902")
        assert report["ok"] is True, report["reasons"]
    finally:
        os.remove(path)
