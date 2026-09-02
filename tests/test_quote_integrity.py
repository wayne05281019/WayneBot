# -*- coding: utf-8 -*-
import sqlite3

from quote_integrity import (
    audit_untrusted_quotes,
    ensure_quote_integrity,
    filter_trusted_quote_tuples,
    is_suspect_stub_bar,
    quote_tuple_trusted,
    scrub_untrusted_quotes,
)


def test_stub_bar_2454_pattern():
    assert is_suspect_stub_bar(4315, 4315, 4315, 4315, 4931, 9.94) is True


def test_stub_bar_micro_volume():
    assert is_suspect_stub_bar(25.8, 25.8, 25.8, 25.8, 1, -2.99) is True


def test_limit_up_flat_bar_not_stub_when_pct_small():
    assert is_suspect_stub_bar(100, 100, 100, 100, 50000, 0.5) is False


def test_filter_trusted_drops_stub_tuple():
    row = (
        "20260901",
        "2454",
        "聯發科",
        "TW",
        4315.0,
        4315.0,
        4315.0,
        4315.0,
        4931,
        1000.0,
        9.94,
        4315.0,
        0,
        0,
        0,
    )
    kept, dropped = filter_trusted_quote_tuples([row])
    assert kept == []
    assert dropped == 1


def test_scrub_removes_stub_from_db(tmp_path, monkeypatch):
    monkeypatch.setattr("import_health.sides_complete", lambda tw, two, **kw: True)
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER
        )"""
    )
    conn.execute(
        """INSERT INTO daily_quotes VALUES
        ('20260828','2454','聯發科','TW',3935,4000,3925,3985,5064,1000,3.1,3985,0,0,0),
        ('20260901','2454','聯發科','TW',4315,4315,4315,4315,4931,1000,9.94,4315,0,0,0)"""
    )
    conn.commit()
    conn.close()

    stats = scrub_untrusted_quotes(str(db), now=None)
    assert stats["stub_bar"] >= 1

    conn = sqlite3.connect(db)
    left = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE stock_id='2454' AND date='20260901'"
    ).fetchone()[0]
    good = conn.execute(
        "SELECT close FROM daily_quotes WHERE stock_id='2454' AND date='20260828'"
    ).fetchone()
    conn.close()
    assert left == 0
    assert float(good[0]) == 3985.0


def test_audit_reports_stub_without_mutating(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER
        )"""
    )
    conn.execute(
        """INSERT INTO daily_quotes VALUES
        ('20260901','2454','聯發科','TW',4315,4315,4315,4315,4931,1000,9.94,4315,0,0,0)"""
    )
    conn.commit()
    conn.close()

    before = audit_untrusted_quotes(str(db))
    assert before["stub_bar"] == 1
    ensure_quote_integrity(str(db))
    after = audit_untrusted_quotes(str(db))
    assert after["stub_bar"] == 0
