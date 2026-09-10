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


def test_repair_pct_uses_ex_rights_ref_not_unadjusted_prev(tmp_path):
    """除權息日：神達 91.3→81.8 是參考價 80.27，不是跌停。"""
    db = tmp_path / "xr.db"
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
        """CREATE TABLE ex_rights (
            stock_id TEXT, ex_date TEXT, stock_name TEXT, market TEXT, kind TEXT,
            close_before REAL, ref_price REAL, right_plus_div REAL, factor REAL,
            source TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO daily_quotes VALUES
        ('20260908','3706','神達','TW',92.7,92.7,91.1,91.3,16006,0,-1.4,91.3,0,0,0),
        ('20260909','3706','神達','TW',81.6,82.3,81.1,81.8,17193,0,0.0,81.6,0,0,0)"""
    )
    conn.execute(
        """INSERT INTO ex_rights VALUES
        ('3706','20260909','神達','TW','權息',91.3,80.27,0,0.879,'twse','t')"""
    )
    conn.commit()
    conn.close()
    from quote_integrity import repair_pct_change_from_prior

    repair_pct_change_from_prior(str(db))
    conn = sqlite3.connect(db)
    pct = conn.execute(
        "SELECT pct_change FROM daily_quotes WHERE stock_id='3706' AND date='20260909'"
    ).fetchone()[0]
    conn.close()
    assert abs(float(pct) - 1.91) < 0.05
    assert float(pct) > 0


def test_repair_pct_keeps_halt_copy_flat(tmp_path):
    """無量複製列官方平盤，不能拿缺日上一根算出漲跌。"""
    db = tmp_path / "halt.db"
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
        ('20260908','2035','唐榮','TWO',26.35,26.4,26.3,26.35,10,0,0.19,26.35,0,0,0),
        ('20260909','2035','唐榮','TWO',26.4,26.4,26.4,26.4,0,0,0.0,26.4,0,0,0)"""
    )
    conn.commit()
    conn.close()
    from quote_integrity import repair_pct_change_from_prior

    repair_pct_change_from_prior(str(db))
    conn = sqlite3.connect(db)
    pct = conn.execute(
        "SELECT pct_change FROM daily_quotes WHERE stock_id='2035' AND date='20260909'"
    ).fetchone()[0]
    conn.close()
    assert float(pct) == 0.0


def test_repair_pct_walks_every_stock_not_just_first(tmp_path):
    """同一 cursor 不能邊掃 DISTINCT 邊 SELECT；第二檔也要修到。"""
    db = tmp_path / "two.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER
        )"""
    )
    conn.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("20260831", "1101", "台泥", "TW", 30, 31, 29, 30, 100, 0, 0, 30, 0, 0, 0),
            ("20260901", "1101", "台泥", "TW", 31, 33, 30, 33, 100, 0, 0.0, 33, 0, 0, 0),
            ("20260831", "3105", "穩懋", "TWO", 440, 450, 430, 447.5, 1000, 0, 1.94, 447.5, 0, 0, 0),
            ("20260901", "3105", "穩懋", "TWO", 450, 500, 440, 492, 1000, 0, 99.0, 492, 0, 0, 0),
        ],
    )
    conn.commit()
    conn.close()
    from quote_integrity import repair_pct_change_from_prior

    repair_pct_change_from_prior(str(db))
    conn = sqlite3.connect(db)
    a = conn.execute("SELECT pct_change FROM daily_quotes WHERE stock_id='1101' AND date='20260901'").fetchone()[0]
    b = conn.execute("SELECT pct_change FROM daily_quotes WHERE stock_id='3105' AND date='20260901'").fetchone()[0]
    conn.close()
    assert abs(float(a) - 10.0) < 0.05
    assert abs(float(b) - 9.94) < 0.05


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
