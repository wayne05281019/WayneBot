# -*- coding: utf-8 -*-
import sqlite3

from wayne_db import ensure_core_schema, lookup_stocks


def _insert_quote(conn, date: str, close: float, pct: float) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO daily_quotes
           (date, stock_id, stock_name, market, open, high, low, close, volume,
            turnover_k, pct_change, avg_price)
           VALUES (?, '2454', '聯發科', 'TW', ?, ?, ?, ?, 1000, 1000, ?, 100)""",
        (date, close, close, close, close, pct),
    )


def test_lookup_stocks_uses_db_as_of_not_max_date(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    _insert_quote(conn, "20260828", 4310.0, 0.12)
    _insert_quote(conn, "20260901", 4315.0, 9.94)
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )

    hits = lookup_stocks(db, "2454")
    assert len(hits) == 1
    assert float(hits[0]["close"]) == 4310.0
    assert float(hits[0]["pct_change"]) == 0.12
