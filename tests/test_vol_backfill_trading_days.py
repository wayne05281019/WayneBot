# -*- coding: utf-8 -*-
"""結構／大量區窗內開市日：缺官方量先補洞，不准發明假量。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def _schema(db: str) -> None:
    from wayne_db import ensure_core_schema

    ensure_core_schema(db)


def test_ensure_official_volume_fills_missing_open_day(tmp_path, monkeypatch):
    """庫缺開市日 → 呼叫 STOCK_DAY 月表 upsert 真柱；不准編造。"""
    from vol_zone_chart import (
        ensure_official_volume_window,
        missing_open_quote_days,
    )

    db = str(tmp_path / "t.db")
    _schema(db)
    conn = sqlite3.connect(db)
    # 20260812 / 20260814 有列；20260813 開市缺列
    conn.executemany(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                "20260812",
                "9081",
                "測A",
                "TW",
                10,
                11,
                9,
                10.5,
                100,
                0,
                0,
                10.5,
                0,
                0,
                0,
                "test",
                "t",
            ),
            (
                "20260814",
                "9081",
                "測A",
                "TW",
                10.5,
                12,
                10,
                11,
                120,
                0,
                0,
                11,
                0,
                0,
                0,
                "test",
                "t",
            ),
        ],
    )
    conn.commit()
    conn.close()

    before = missing_open_quote_days("9081", db, "20260812", "20260814")
    assert "20260813" in before

    fake_rows = [
        {
            "date": "20260812",
            "stock_id": "9081",
            "stock_name": "測A",
            "market": "TW",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 100,
            "pct_change": 0.0,
        },
        {
            "date": "20260813",
            "stock_id": "9081",
            "stock_name": "測A",
            "market": "TW",
            "open": 10.5,
            "high": 10.8,
            "low": 10.2,
            "close": 10.6,
            "volume": 55,
            "pct_change": 0.95,
        },
        {
            "date": "20260814",
            "stock_id": "9081",
            "stock_name": "測A",
            "market": "TW",
            "open": 10.5,
            "high": 12.0,
            "low": 10.0,
            "close": 11.0,
            "volume": 120,
            "pct_change": 3.8,
        },
    ]

    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", lambda *a, **k: list(fake_rows))
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TW")

    stats = ensure_official_volume_window(
        "9081", db, end_ymd="20260814", days=5, stock_name="測A"
    )
    assert "202608" in stats["months_ok"]
    after = missing_open_quote_days("9081", db, "20260812", "20260814")
    assert "20260813" not in after
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT volume, close FROM daily_quotes WHERE stock_id=? AND date=?",
        ("9081", "20260813"),
    ).fetchone()
    conn.close()
    assert row is not None
    assert float(row[0]) == 55.0
    assert float(row[1]) == 10.6
    assert "20260813" not in (stats.get("confirmed_absent") or [])


def test_ensure_marks_confirmed_absent_when_official_month_lacks_day(
    tmp_path, monkeypatch
):
    """官方月表成功但無該日 → confirmed_absent，不准發明量。"""
    from vol_zone_chart import ensure_official_volume_window

    db = str(tmp_path / "t2.db")
    _schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "20260812",
            "9082",
            "測B",
            "TW",
            10,
            11,
            9,
            10,
            80,
            0,
            0,
            10,
            0,
            0,
            0,
            "test",
            "t",
        ),
    )
    conn.execute(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "20260814",
            "9082",
            "測B",
            "TW",
            10,
            11,
            9,
            10.2,
            90,
            0,
            0,
            10.2,
            0,
            0,
            0,
            "test",
            "t",
        ),
    )
    conn.commit()
    conn.close()

    # 官方月表故意不含 20260813
    fake_rows = [
        {
            "date": "20260812",
            "stock_id": "9082",
            "stock_name": "測B",
            "market": "TW",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 80,
            "pct_change": 0.0,
        },
        {
            "date": "20260814",
            "stock_id": "9082",
            "stock_name": "測B",
            "market": "TW",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.2,
            "volume": 90,
            "pct_change": 2.0,
        },
    ]
    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", lambda *a, **k: list(fake_rows))
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TW")

    stats = ensure_official_volume_window(
        "9082", db, end_ymd="20260814", days=5, stock_name="測B"
    )
    assert "20260813" in (stats.get("confirmed_absent") or [])


def test_chart_window_no_missing_vol_when_official_has_data():
    """3081 結構／大量區近窗：開市日有官方量就不准再缺列（補洞後）。"""
    from trading_calendar import iter_tw_open_days
    from vol_zone_chart import (
        ensure_official_volume_window,
        load_official_ohlc,
        missing_open_quote_days,
        official_work,
        prepare_volume_zone,
    )

    db = get_db_path()
    if not Path(db).is_file():
        pytest.skip("no production db")
    stats = ensure_official_volume_window("3081", db, days=200, stock_name="聯亞")
    raw = load_official_ohlc("3081", db, 200)
    work = official_work(
        raw, skip_invent_dates=set(stats.get("confirmed_absent") or [])
    )
    assert work is not None and len(work) >= 40
    start = str(work["date"].iloc[0]).replace("-", "")[:8]
    end = str(work["date"].iloc[-1]).replace("-", "")[:8]
    # 窗內開市日：要嘛庫有真列，要嘛 confirmed_absent（官方無列＝非交易／休市）
    open_days = set(iter_tw_open_days(start, end))
    absent = set(stats.get("confirmed_absent") or [])
    still = set(stats.get("still_missing") or [])
    # 仍缺且官方有資料時不准過（still_missing 應空或僅網路失敗）
    holes = missing_open_quote_days("3081", db, start, end)
    invent_holes = [d for d in holes if d not in absent]
    assert invent_holes == [] or invent_holes == list(still), (
        invent_holes,
        still,
        stats,
    )
    # 畫面上的每根真列必須有非 NULL volume（0＝真停價可）
    for _, row in work.iterrows():
        assert row["volume"] == row["volume"], row["date"]  # not NaN
        assert float(row["volume"]) >= 0.0
        # 對齊發明的停價柱：若 skip 後不應再出現 no_trade_fill
        if bool(row.get("no_trade_fill", False)):
            d = str(row["date"]).replace("-", "")[:8]
            assert d not in absent
    # prepare 路徑也要跑過 ensure
    pack = prepare_volume_zone("3081", "聯亞", db, str(Path(db).parent / "_vz_probe.png"))
    assert pack is not None
    ve = pack.get("vol_ensure") or {}
    view = pack["view"]
    v_start = str(view["date"].iloc[0]).replace("-", "")[:8]
    v_end = str(view["date"].iloc[-1]).replace("-", "")[:8]
    view_holes = [
        d
        for d in missing_open_quote_days("3081", db, v_start, v_end)
        if d not in set(ve.get("confirmed_absent") or [])
    ]
    assert view_holes == [], (view_holes, ve)
