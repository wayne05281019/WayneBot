# -*- coding: utf-8 -*-
"""大盤加權大量壓／撐：與個股同一套；不疊買訊、不混海選。"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest


def _seed_twii(db: str, n: int = 50, spike_i: int = 35) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TWII',
            close REAL NOT NULL,
            volume REAL DEFAULT 0,
            pct_change REAL DEFAULT 0,
            ma20 REAL,
            ma60 REAL,
            regime TEXT,
            updated_at TEXT NOT NULL DEFAULT '',
            open REAL,
            high REAL,
            low REAL,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    base = 27000.0
    for i in range(n):
        # 20260801 起連號（測用假曆，只求開高低收＋量齊）
        d = f"2026{8 + i // 28:02d}{i % 28 + 1:02d}"
        vol = 2.5e7 if i == spike_i else 4e6 + i * 1e3
        hi = base + 180 + (80 if i == spike_i else 0)
        lo = base - 90
        op = base
        cl = base + 10 if i < n - 1 else base - 40
        conn.execute(
            "INSERT OR REPLACE INTO index_daily("
            "date,symbol,open,high,low,close,volume,pct_change,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "TWII", op, hi, lo, cl, vol, 0.1, "t"),
        )
    conn.commit()
    conn.close()


def test_load_official_ohlc_twii_from_index_daily(tmp_path):
    from vol_zone_chart import load_official_ohlc

    db = str(tmp_path / "wayne_market.db")
    _seed_twii(db)
    df = load_official_ohlc("TWII", db, 40)
    assert len(df) >= 40
    assert str(df["quote_source"].iloc[-1]) == "index_daily"
    assert str(df["stock_name"].iloc[-1]) == "加權"
    caret = load_official_ohlc("^TWII", db, 20)
    assert len(caret) >= 20


def test_prepare_volume_zone_twii_same_algo(tmp_path):
    from vol_zone_chart import (
        find_volume_zone,
        load_official_ohlc,
        official_work,
        prepare_volume_zone,
    )

    db = str(tmp_path / "wayne_market.db")
    _seed_twii(db, n=50, spike_i=35)
    pack = prepare_volume_zone("TWII", "加權", db, str(tmp_path / "prep.png"))
    assert pack is not None
    assert pack["sid"] == "TWII"
    assert pack["hi"] > pack["lo"] > 0
    work = official_work(load_official_ohlc("TWII", db, 180))
    zone = find_volume_zone(work)
    assert zone is not None
    assert abs(float(pack["hi"]) - float(zone["high"])) < 1e-6
    assert abs(float(pack["lo"]) - float(zone["low"])) < 1e-6


def test_snapshot_market_keeps_zone_fields(tmp_path):
    from judge_tape import _snapshot_market, store_path

    db = str(tmp_path / "wayne_market.db")
    _seed_twii(db, n=50, spike_i=35)
    conn = sqlite3.connect(db)
    last = conn.execute(
        "SELECT date FROM index_daily WHERE symbol='TWII' ORDER BY date DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()
    n = _snapshot_market(db, last)
    assert n == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    sid, px, extra_raw = conn.execute(
        "SELECT sid, px, extra FROM live_judge WHERE kind='market' AND sid='TWII'"
    ).fetchone()
    conn.close()
    assert sid == "TWII"
    assert float(px) > 0
    extra = json.loads(extra_raw)
    assert extra.get("zone_date")
    assert float(extra["zone_high"]) > float(extra["zone_low"]) > 0
    assert float(extra["zone_volume"]) > 0
    assert "zone_active" in extra
    # 不混海選 kind
    assert extra.get("src") == "market"


def test_market_vol_zone_no_buy_signals_in_builder():
    import inspect

    from index_kline_chart import build_market_vol_zone_chart

    src = inspect.getsource(build_market_vol_zone_chart)
    assert "with_nav_signals=False" in src
    assert "with_parallel_channel=True" in src
    assert "leave_zero" not in src
    assert "ma60_lower" not in src
