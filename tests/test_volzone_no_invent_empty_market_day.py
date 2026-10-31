# -*- coding: utf-8 -*-
"""全市場無官方列的開市日不准發明停價空柱（3595 倒數第 4 根量棒）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def _seed_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net REAL, trust_net REAL, dealer_net REAL, source TEXT
        );
        CREATE TABLE emerging_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net REAL, trust_net REAL, dealer_net REAL, source TEXT
        );
        CREATE TABLE tw_holidays (
            ymd TEXT PRIMARY KEY, kind TEXT, name_zh TEXT, source TEXT, fetched_at TEXT
        );
        INSERT INTO tw_holidays VALUES
            ('20261026', 'full_close', '光復節補假', 'twse', '2026-10-28');
        """
    )
    # listed：10/22、10/27；刻意無 10/23（全市場空）
    con.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "20261022",
            "2330",
            "台積電",
            "TWSE",
            100,
            101,
            99,
            100,
            10,
            0,
            0,
            100,
            0,
            0,
            0,
            "twse",
        ),
    )
    con.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "20261027",
            "2330",
            "台積電",
            "TWSE",
            100,
            101,
            99,
            100,
            11,
            0,
            0,
            100,
            0,
            0,
            0,
            "twse",
        ),
    )
    # 興櫃 3595 同窗：也無 10/23
    con.execute(
        "INSERT INTO emerging_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "20261022",
            "3595",
            "山太士",
            "EM",
            900,
            910,
            890,
            900,
            400,
            0,
            0,
            900,
            0,
            0,
            0,
            "tpex",
        ),
    )
    con.execute(
        "INSERT INTO emerging_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "20261027",
            "3595",
            "山太士",
            "EM",
            880,
            890,
            870,
            880,
            500,
            0,
            0,
            880,
            0,
            0,
            0,
            "tpex",
        ),
    )
    con.commit()
    con.close()


def test_market_wide_empty_open_days_flags_1023(tmp_path, monkeypatch):
    from trading_calendar import clear_tw_open_days_cache
    import tw_holidays

    db = tmp_path / "mkt.db"
    _seed_db(db)
    monkeypatch.setenv("WAYNE_DB_PATH", str(db))
    clear_tw_open_days_cache()
    tw_holidays.clear_tw_holiday_row_cache(str(db))

    from vol_zone_chart import market_wide_empty_open_days

    empty = market_wide_empty_open_days(str(db), "20261020", "20261029")
    assert "20261023" in empty
    assert "20261022" not in empty
    assert "20261027" not in empty
    assert "20261026" not in empty  # 休市不在開市日軸


def test_official_work_emerging_skips_market_empty_invent(tmp_path, monkeypatch):
    """興櫃無 sid confirmed_absent 時，仍不准發明全市場空日的量 0 假柱。"""
    from trading_calendar import clear_tw_open_days_cache
    import tw_holidays
    from wayne_navigator import clear_align_ohlc_cache

    db = tmp_path / "mkt.db"
    _seed_db(db)
    monkeypatch.setenv("WAYNE_DB_PATH", str(db))
    clear_tw_open_days_cache()
    clear_align_ohlc_cache()
    tw_holidays.clear_tw_holiday_row_cache(str(db))

    from vol_zone_chart import official_work

    raw = pd.DataFrame(
        [
            {
                "date": "20261022",
                "stock_id": "3595",
                "stock_name": "山太士",
                "open": 900.0,
                "high": 910.0,
                "low": 890.0,
                "close": 900.0,
                "volume": 400.0,
            },
            {
                "date": "20261027",
                "stock_id": "3595",
                "stock_name": "山太士",
                "open": 880.0,
                "high": 890.0,
                "low": 870.0,
                "close": 880.0,
                "volume": 500.0,
            },
        ]
    )
    work = official_work(raw)
    assert work is not None
    dates = [str(d) for d in work["date"].tolist()]
    assert "20261023" not in dates
    assert "20261022" in dates and "20261027" in dates
    assert not any(bool(x) for x in work.get("no_trade_fill", pd.Series(dtype=bool)).tolist())
