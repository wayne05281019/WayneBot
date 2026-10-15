# -*- coding: utf-8 -*-
"""恐懼開盤前靜默骨架：落檔／閘門／非買訊／缺美股不算。"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from fear_composite import FearParams
from fear_preopen_verify import (
    KIND,
    TAG_DUMP,
    gate_status,
    night_tick,
    optimize_status_one_liner,
    persist_day,
    recompute_rates,
    score_pending,
)
from us_overnight import ensure_us_overnight_table, save_us_overnight


def _seed_market(db: str) -> None:
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS index_daily(
            date TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT 'TWII',
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            pct_change REAL, updated_at TEXT DEFAULT '',
            PRIMARY KEY(date, symbol)
        );
        CREATE TABLE IF NOT EXISTS futures_daily(
            date TEXT NOT NULL, symbol TEXT NOT NULL, session TEXT NOT NULL,
            contract_month TEXT, open REAL, high REAL, low REAL, close REAL,
            settlement REAL, volume INTEGER, open_interest INTEGER,
            pct_change REAL, source TEXT,
            PRIMARY KEY(date, symbol, session)
        );
        CREATE TABLE IF NOT EXISTS daily_quotes(
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            turnover_k REAL, foreign_net REAL
        );
        CREATE TABLE IF NOT EXISTS ex_rights(
            stock_id TEXT, ex_date TEXT, kind TEXT DEFAULT '',
            PRIMARY KEY(stock_id, ex_date)
        );
        """
    )
    # 三日加權
    for d, o, c, pct in (
        ("20260901", 23000, 23100, 0.4),
        ("20260902", 23150, 22800, -1.3),
        ("20260903", 22600, 22500, -1.3),
        ("20260904", 22550, 22700, 0.9),
    ):
        conn.execute(
            "INSERT INTO index_daily(date,symbol,open,high,low,close,volume,pct_change)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (d, "TWII", o, max(o, c), min(o, c), c, 1e9, pct),
        )
    # TX 夜盤：0902 相對 0901 regular 結算大跌
    conn.execute(
        "INSERT INTO futures_daily(date,symbol,session,contract_month,open,high,low,close,"
        "settlement,volume,open_interest,pct_change,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260901", "TX", "regular", "202609", 23000, 23100, 22900, 23050, 23050, 1, 1, 0, "t"),
    )
    conn.execute(
        "INSERT INTO futures_daily(date,symbol,session,contract_month,open,high,low,close,"
        "settlement,volume,open_interest,pct_change,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260902", "TX", "night", "202609", 22800, 22800, 22600, 22650, 22650, 1, 1, -1.7, "t"),
    )
    conn.execute(
        "INSERT INTO futures_daily(date,symbol,session,contract_month,open,high,low,close,"
        "settlement,volume,open_interest,pct_change,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260902", "TX", "regular", "202609", 22600, 22800, 22500, 22800, 22800, 1, 1, -1.0, "t"),
    )
    # Top500 原料：多檔有額
    for i in range(1, 30):
        sid = f"{1000+i:04d}"
        for d, fn in (("20260901", -10), ("20260902", -500), ("20260903", 20)):
            px = 100.0 + i
            if i == 1 and d == "20260902":
                px = 1200.0  # 千金
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    d,
                    sid,
                    f"N{sid}",
                    "TW",
                    px,
                    px,
                    px,
                    px,
                    5000,
                    5000 * px,
                    fn,
                ),
            )
    conn.commit()
    conn.close()
    ensure_us_overnight_table(db)
    # 0902 美股大跌＋外圍
    save_us_overnight(
        db,
        "20260902",
        {
            "ok": True,
            "regime": "risk_off",
            "ixic_pct": -2.8,
            "sox_pct": -3.1,
            "spx_pct": -2.0,
            "dji_pct": -1.8,
            "vix": 28.0,
            "tsm_pct": -2.5,
            "nvda_pct": -2.2,
            "brent_pct": 0.5,
            "dx_f_pct": 0.5,
            "usdtwd_pct": 0.4,
            "fetched_at": "2026-09-02T12:00:00+08:00",
        },
    )
    # 0903 中性
    save_us_overnight(
        db,
        "20260903",
        {
            "ok": True,
            "regime": "ok",
            "ixic_pct": 0.3,
            "sox_pct": 0.2,
            "spx_pct": 0.2,
            "dji_pct": 0.1,
            "vix": 14.0,
            "tsm_pct": 0.4,
            "nvda_pct": 0.3,
            "fetched_at": "2026-09-03T12:00:00+08:00",
        },
    )


def test_persist_lit_day_and_gate_never_buy():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "m.db")
        _seed_market(db)
        out = persist_day(db, "20260902", params=FearParams(), persist_stocks=True)
        assert out["evaluable"] is True
        assert out["lit"] is True
        assert out["events"] >= 1
        g = gate_status(db)
        assert g["kind"] == KIND
        assert g["buy_signal"] is False
        assert g["promote_golden_buy"] is False
        assert g["promote_leave_zero"] is False
        line = optimize_status_one_liner(db)
        assert "恐懼" in line
        assert "非買訊" in line or "不改" in line


def test_missing_us_day_not_evaluable():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "m.db")
        _seed_market(db)
        # 0901 無 us_overnight
        out = persist_day(db, "20260901", params=FearParams(), persist_stocks=False)
        assert out["evaluable"] is False
        assert out["lit"] is False


def test_night_tick_scores_dump_split_tables():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "m.db")
        _seed_market(db)
        snap = night_tick(db, "20260902")
        assert snap.get("lit") is True
        n = score_pending(db)
        assert n >= 1
        rates = recompute_rates(db)
        # 必須有 lead/sync × dump 分鍵，不准只有一個混％
        keys = [k for k in rates if TAG_DUMP in k]
        assert any("lead" in k for k in keys)
        assert any("exclude_dump" in k or "dump_only" in k or "all" in k for k in keys)
