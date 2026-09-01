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
