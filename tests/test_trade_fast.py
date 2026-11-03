import sqlite3

import pytest


def _mk_db(path: str):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            stock_id TEXT, stock_name TEXT, market TEXT, date TEXT,
            close REAL, volume INTEGER, turnover_k REAL, pct_change REAL,
            foreign_net REAL, trust_net REAL, dealer_net REAL, avg_price REAL
        )
        """
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES ('2330','台積電','TW','20260828',900,50000,0,0,0,0,0,0)"
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES ('3105','穩懋','TW','20260828',500,8000,0,0,0,0,0,0)"
    )
    conn.commit()
    conn.close()


def test_load_bucket_rows_reads_morning_bucket(tmp_path):
    from screen_sessions import ensure_screen_session_table, load_bucket_rows, save_screen_session

    db = str(tmp_path / "t.db")
    ensure_screen_session_table(db)
    save_screen_session(
        db,
        "20260828",
        "morning",
        {
            "day_trade": [
                {
                    "stock_id": "3105",
                    "stock_name": "穩懋",
                    "close": 500,
                    "entry_price": 500,
                    "hi20_close": 520,
                }
            ]
        },
    )
    rows = load_bucket_rows(db, "day_trade", "20260828")
    assert len(rows) == 1
    assert rows[0]["stock_id"] == "3105"


def test_screen_session_has_data(tmp_path):
    from screen_sessions import ensure_screen_session_table, save_screen_session, screen_session_has_data

    db = str(tmp_path / "t.db")
    assert not screen_session_has_data(db, "20260831")
    ensure_screen_session_table(db)
    save_screen_session(
        db,
        "20260831",
        "morning",
        {"day_trade": [{"stock_id": "3105", "stock_name": "穩懋", "close": 500}]},
    )
    assert screen_session_has_data(db, "20260831")


def test_screen_daytrade_uses_cache_not_full_scan(tmp_path, monkeypatch):
    from screening_engine import ScreeningEngine

    db = str(tmp_path / "t.db")
    _mk_db(db)
    from screen_sessions import ensure_screen_session_table, save_screen_session

    ensure_screen_session_table(db)
    save_screen_session(
        db,
        "20260828",
        "morning",
        {"day_trade": [{"stock_id": "3105", "stock_name": "穩懋", "close": 500}]},
    )

    def boom(*_a, **_k):
        raise AssertionError("不應跑全市場掃描")

    monkeypatch.setattr(ScreeningEngine, "load_market_data", boom)
    eng = ScreeningEngine(db_path=db)
    monkeypatch.setattr(eng, "get_latest_trading_date", lambda: "20260828")
    rows = eng.screen_daytrade("20260828")
    assert len(rows) == 1
    assert rows[0]["code"] == "3105"


def test_screen_daytrade_empty_without_full_scan(tmp_path, monkeypatch):
    from screening_engine import ScreeningEngine

    db = str(tmp_path / "t.db")
    _mk_db(db)

    def boom(*_a, **_k):
        raise AssertionError("不應跑全市場掃描")

    monkeypatch.setattr(ScreeningEngine, "load_market_data", boom)
    eng = ScreeningEngine(db_path=db)
    monkeypatch.setattr(eng, "get_latest_trading_date", lambda: "20260828")
    assert eng.screen_daytrade("20260828") == []


def test_enrich_prefers_target_day_official_close_over_stale_pick(tmp_path, monkeypatch):
    """舊海選 pick_close 不准蓋掉目標日官方收（否則漲跌％是今日、價卻是舊日）。"""
    from screening_engine import ScreeningEngine
    from screen_sessions import ensure_screen_session_table, save_screen_session

    db = str(tmp_path / "t.db")
    _mk_db(db)
    conn = sqlite3.connect(db)
    # 目標日新收；上一開市日 session 仍鎖 282.5
    conn.execute(
        "INSERT INTO daily_quotes VALUES ('3006','晶豪科','TW','20261103',242.5,15631,3933181.38,-7.09,64,6,-418,251.62)"
    )
    conn.commit()
    conn.close()
    ensure_screen_session_table(db)
    save_screen_session(
        db,
        "20261102",
        "morning",
        {
            "day_trade": [
                {
                    "stock_id": "3006",
                    "stock_name": "晶豪科",
                    "close": 282.5,
                    "entry_price": 282.5,
                    "hi20_close": 286.0,
                }
            ]
        },
    )

    eng = ScreeningEngine(db_path=db)
    monkeypatch.setattr(eng, "get_latest_trading_date", lambda: "20261103")
    rows = eng.screen_daytrade("20261103")
    assert len(rows) == 1
    assert float(rows[0]["close"]) == 242.5
    assert float(rows[0]["entry_price"]) == 242.5
    assert float(rows[0]["pct_change"]) == pytest.approx(-7.09)


def test_screen_daytrade_rejects_multi_day_stale_blank_fallback(tmp_path, monkeypatch):
    """今日無海選時，不准空白回退到隔很多天的舊當沖名單。"""
    from screening_engine import ScreeningEngine
    from screen_sessions import ensure_screen_session_table, save_screen_session

    db = str(tmp_path / "t.db")
    _mk_db(db)
    ensure_screen_session_table(db)
    save_screen_session(
        db,
        "20261029",
        "morning",
        {
            "day_trade": [
                {
                    "stock_id": "3006",
                    "stock_name": "晶豪科",
                    "close": 282.5,
                    "entry_price": 282.5,
                }
            ]
        },
    )

    eng = ScreeningEngine(db_path=db)
    monkeypatch.setattr(eng, "get_latest_trading_date", lambda: "20261103")
    assert eng.screen_daytrade("20261103") == []


def test_leave_zero_rejects_multi_day_stale_blank_fallback(tmp_path, monkeypatch):
    """剛離零同樣不准空白回退到隔很多天的舊 leave_zero／golden_buy。"""
    from screening_engine import ScreeningEngine
    from screen_sessions import ensure_screen_session_table, save_screen_session

    db = str(tmp_path / "t.db")
    _mk_db(db)
    ensure_screen_session_table(db)
    save_screen_session(
        db,
        "20261029",
        "morning",
        {
            "leave_zero": [
                {"stock_id": "3105", "stock_name": "穩懋", "close": 500}
            ],
            "golden_buy": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 900}
            ],
        },
    )

    eng = ScreeningEngine(db_path=db)
    monkeypatch.setattr(eng, "get_latest_trading_date", lambda: "20261103")
    monkeypatch.setattr(
        "live_quote.is_live_merge_window", lambda: False
    )
    assert eng.screen_leave_zero_now("20261103") == []


def test_live_vol_rank_120_batch():
    import sqlite3

    from live_quote import live_vol_rank_120_batch

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, volume INTEGER)")
    for i in range(5):
        conn.execute(
            "INSERT INTO daily_quotes VALUES ('2330', ?, ?)",
            (f"2026082{i}", 1000 + i * 100),
        )
    conn.commit()
    conn.close()
    # reuse in-memory path by writing to temp - batch opens its own connection
    # simpler: use temp file
    pytest.importorskip("os")
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, volume INTEGER)")
        for i in range(5):
            c.execute(
                "INSERT INTO daily_quotes VALUES ('2330', ?, ?)",
                (f"2026082{i}", 1000 + i * 100),
            )
        c.commit()
        c.close()
        ranks = live_vol_rank_120_batch(path, {"2330": 5000})
        assert ranks["2330"] == 1
    finally:
        os.unlink(path)
