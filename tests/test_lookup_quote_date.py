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


def test_lookup_mixed_code_name_and_fullwidth(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    _insert_quote(conn, "20260828", 4310.0, 0.12)
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    for q in ("2454聯發科", "聯發科2454", "2454 聯發科", "２４５４"):
        hits = lookup_stocks(db, q)
        assert len(hits) == 1, q
def test_lookup_etf_active_passive_leveraged(monkeypatch, tmp_path):
    db = str(tmp_path / "etf.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    rows = [
        ("0050", "元大台灣50", 110.1),
        ("00962", "台新AI優息動能", 15.66),
        ("00706L", "期元大S&P日圓正2", 19.59),
        ("00990A", "主動元大AI新經濟", 12.3),
        ("00411A", "主動統一前沿科技", 8.8),
        ("00632R", "元大台灣50反1", 5.2),
    ]
    for sid, name, close in rows:
        conn.execute(
            """INSERT OR REPLACE INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES ('20260828', ?, ?, 'TW', ?, ?, ?, ?, 1000, 1000, 1.0, ?)""",
            (sid, name, close, close, close, close, close),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    cases = {
        "0050": "0050",
        "00962": "00962",
        "00706L": "00706L",
        "00706l": "00706L",
        "00990A": "00990A",
        "00990a": "00990A",
        "00411A": "00411A",
        "00632R": "00632R",
        "00706L期元大": "00706L",
    }
    for q, sid in cases.items():
        hits = lookup_stocks(db, q)
        assert len(hits) == 1, q
        assert hits[0]["stock_id"] == sid
