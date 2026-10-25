# -*- coding: utf-8 -*-
"""止穩靜默對質：落檔／閘門／非買訊。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pandas as pd

from stabilize_verify import (
    KIND,
    TAG_CURRENT,
    TAG_NEXT,
    TAGS,
    gate_status,
    night_tick,
    optimize_status_one_liner,
    persist_tape,
    recompute_rates,
    score_pending,
    tags_for_frame,
)
from tests.test_stabilize_watch import _ohlc_stabilize


def test_tags_for_frame_current_and_not_buy():
    df = _ohlc_stabilize(extra_hold=4)
    tags = tags_for_frame(df)
    assert TAG_CURRENT in tags
    # HOLD_N_NEXT=5：extra_hold=4 → bars_held=4 < 5，tight 不命中
    assert TAG_NEXT not in tags


def test_tags_tight_when_held_longer():
    df = _ohlc_stabilize(extra_hold=6)
    tags = tags_for_frame(df)
    assert TAG_CURRENT in tags
    assert TAG_NEXT in tags


def test_gate_never_promotes_buy():
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        conn = sqlite3.connect(market)
        conn.execute(
            "CREATE TABLE daily_quotes("
            "stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,"
            "close REAL, volume REAL)"
        )
        conn.commit()
        conn.close()
        g = gate_status(market)
        assert g["kind"] == KIND
        assert g["buy_signal"] is False
        assert g["promote_golden_buy"] is False
        assert g["promote_paint"] is False
        line = optimize_status_one_liner(market)
        assert "止穩" in line
        assert "非買訊" in line or "不是買訊" in line or "不改買訊" in line


def test_persist_and_score_pending():
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        conn = sqlite3.connect(market)
        conn.execute(
            "CREATE TABLE daily_quotes("
            "stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,"
            "close REAL, volume REAL)"
        )
        # as_of 後兩根收
        conn.executemany(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?)",
            [
                ("2330", "20260301", 100, 101, 99, 100, 1000),
                ("2330", "20260302", 100, 102, 99, 101, 1000),
                ("2330", "20260303", 101, 103, 100, 102, 1000),
            ],
        )
        conn.commit()
        conn.close()
        persist_tape(
            market,
            [
                {
                    "as_of": "20260301",
                    "sid": "2330",
                    "tag": TAG_CURRENT,
                    "name": "台積電",
                    "close": 100.0,
                    "tagged_low": 94.0,
                    "bars_held": 4,
                }
            ],
        )
        n = score_pending(market)
        assert n >= 1
        rates = recompute_rates(market)
        assert f"{TAG_CURRENT}_h1" in rates


def test_catalog_has_stabilize():
    from button_silent_verify import BUTTON_CATALOG, coverage_counts

    row = next(r for r in BUTTON_CATALOG if r.get("btn") == "止穩觀察")
    assert "stabilize" in row["kinds"]
    assert "不是買訊" in row["note"] or "非買訊" in row["note"] or "觀察" in row["note"]
    counts = coverage_counts()
    assert counts["missing"] == 0


def test_night_tick_empty_db():
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        open(market, "wb").close()
        out = night_tick(market, as_of="20260301")
        assert out["buy_signal"] is False
        assert TAG_CURRENT in out["tags"]


def test_confront_summary_and_backfill_empty():
    from stabilize_verify import backfill_recent_days, confront_summary

    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        conn = sqlite3.connect(market)
        conn.execute(
            "CREATE TABLE daily_quotes("
            "stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,"
            "close REAL, volume REAL)"
        )
        conn.commit()
        conn.close()
        summary = confront_summary(market)
        assert summary["buy_signal"] is False
        assert summary["gate_ok"] is False
        assert "止穩" in summary["line"]
        bf = backfill_recent_days(market, trading_days=3)
        assert bf["buy_signal"] is False
        assert isinstance(bf.get("days"), list)
