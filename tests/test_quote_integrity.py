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


def test_limit_up_lock_is_official_not_stub():
    """安瑞-KY 9/2 官方漲停鎖死：開高低收同價、+9.88%，要留下。"""
    assert is_suspect_stub_bar(8.34, 8.34, 8.34, 8.34, 132, 9.88) is False
    assert quote_tuple_trusted(8.34, 8.34, 8.34, 8.34, 132, 9.88) is True


def test_flat_limit_bar_like_2454_kept_as_official_shape():
    """漲停鎖死與舊「2454 假K」長一樣，官方列不能刪；錯價靠官方覆寫。"""
    assert is_suspect_stub_bar(4315, 4315, 4315, 4315, 4931, 9.94) is False
    assert quote_tuple_trusted(4315, 4315, 4315, 4315, 4931, 9.94) is True


def test_stub_bar_micro_volume_official_thin_print_kept():
    """冷門／KY 單價成交 1～2 張、約 1% 是官方列，不是平盤假 K。"""
    assert is_suspect_stub_bar(18.1, 18.1, 18.1, 18.1, 2, -1.1) is False
    assert quote_tuple_trusted(18.1, 18.1, 18.1, 18.1, 2, -1.1) is True


def test_halt_bar_volume_zero_trusted():
    assert quote_tuple_trusted(18.1, 18.1, 18.1, 18.1, 0, 0.0) is True


def test_limit_up_flat_bar_not_stub_when_pct_small():
    assert is_suspect_stub_bar(100, 100, 100, 100, 50000, 0.5) is False


def test_filter_trusted_keeps_limit_up_tuple():
    row = (
        "20260902",
        "3664",
        "安瑞-KY",
        "TWO",
        8.34,
        8.34,
        8.34,
        8.34,
        132,
        1100.88,
        9.88,
        8.34,
        0,
        0,
        0,
    )
    kept, dropped = filter_trusted_quote_tuples([row])
    assert dropped == 0
    assert len(kept) == 1


def test_filter_trusted_keeps_valid_tuple():
    row = (
        "20260902",
        "2330",
        "台積電",
        "TW",
        2400.0,
        2450.0,
        2390.0,
        2440.0,
        45000,
        100000.0,
        1.46,
        2420.0,
        100,
        50,
        20,
    )
    kept, dropped = filter_trusted_quote_tuples([row])
    assert len(kept) == 1
    assert dropped == 0
    assert quote_tuple_trusted(row[4], row[5], row[6], row[7], row[8], row[10])


def test_scrub_does_not_delete_limit_up_lock(tmp_path, monkeypatch):
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
        ('20260902','3664','安瑞-KY','TWO',8.34,8.34,8.34,8.34,132,1100,9.88,8.34,0,0,0)"""
    )
    conn.commit()
    conn.close()

    stats = scrub_untrusted_quotes(str(db), now=None)
    assert stats["stub_bar"] == 0

    conn = sqlite3.connect(db)
    ky = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE stock_id='3664' AND date='20260902'"
    ).fetchone()[0]
    good = conn.execute(
        "SELECT close FROM daily_quotes WHERE stock_id='2454' AND date='20260828'"
    ).fetchone()
    conn.close()
    assert ky == 1
    assert float(good[0]) == 3985.0


def test_repair_pct_change_from_prior(tmp_path):
    db = tmp_path / "pct.db"
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
        ('20260831','3105','穩懋','TWO',440,450,430,447.5,1000,0,1.94,447.5,0,0,0),
        ('20260901','3105','穩懋','TWO',450,500,440,492,1000,0,99.0,492,0,0,0)"""
    )
    conn.commit()
    conn.close()

    from quote_integrity import repair_pct_change_from_prior

    fixed = repair_pct_change_from_prior(str(db))
    assert fixed >= 1
    conn = sqlite3.connect(db)
    pct = conn.execute(
        "SELECT pct_change FROM daily_quotes WHERE stock_id='3105' AND date='20260901'"
    ).fetchone()[0]
    conn.close()
    assert abs(float(pct) - 9.94) < 0.05


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
    assert before["stub_bar"] == 0
    ensure_quote_integrity(str(db))
    after = audit_untrusted_quotes(str(db))
    assert after["stub_bar"] == 0
