# -*- coding: utf-8 -*-
"""schema 版本與遷移。

在這之前 schema 是靠散落的 CREATE TABLE IF NOT EXISTS 加臨時 ALTER 演進，
好幾處還包在 except Exception: pass 裡：升級做了什麼、成功了沒有，事後查不出來。
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_migrations  # noqa: E402
from db_migrations import (  # noqa: E402
    LATEST_VERSION,
    MIGRATIONS,
    applied_versions,
    current_version,
    ensure_migration_table,
    pending_migrations,
    record_schema_error,
    run_migrations,
    schema_errors,
    schema_health,
)


@pytest.fixture()
def fresh(tmp_path):
    path = str(tmp_path / "fresh.db")
    sqlite3.connect(path).close()
    return path


@pytest.fixture(autouse=True)
def _clear_recorded_errors():
    db_migrations._SCHEMA_ERRORS.clear()
    yield
    db_migrations._SCHEMA_ERRORS.clear()


def test_versions_are_unique_and_ordered():
    versions = [v for v, _, _ in MIGRATIONS]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions[0] == 1
    assert versions == list(range(1, len(versions) + 1)), "版本號不能跳號或重排"


def test_latest_version_matches_registry():
    assert LATEST_VERSION == max(v for v, _, _ in MIGRATIONS)


def test_every_migration_has_a_name():
    for version, name, fn in MIGRATIONS:
        assert name.strip(), f"遷移 {version} 沒有名稱"
        assert callable(fn)


def test_fresh_db_starts_at_zero(fresh):
    assert current_version(fresh) == 0
    assert len(pending_migrations(fresh)) == len(MIGRATIONS)


def test_run_migrations_applies_all(fresh):
    out = run_migrations(fresh)
    assert out["version"] == LATEST_VERSION
    assert out["applied"] == [v for v, _, _ in MIGRATIONS]
    assert pending_migrations(fresh) == []


def test_run_migrations_is_idempotent(fresh):
    run_migrations(fresh)
    second = run_migrations(fresh)
    assert second["applied"] == []
    assert second["version"] == LATEST_VERSION


def test_applied_versions_are_recorded_with_names(fresh):
    run_migrations(fresh)
    conn = sqlite3.connect(fresh)
    rows = conn.execute("SELECT version, name, applied_at FROM schema_migrations ORDER BY version").fetchall()
    conn.close()
    assert [r[0] for r in rows] == [v for v, _, _ in MIGRATIONS]
    for _, name, applied_at in rows:
        assert name.strip()
        assert applied_at.strip()


def test_migrations_skip_tables_that_do_not_exist(fresh):
    """空庫也要能跑完：建表歸 ensure_core_schema，遷移只管演進。"""
    out = run_migrations(fresh)
    assert out["version"] == LATEST_VERSION
    conn = sqlite3.connect(fresh)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "daily_quotes" not in names  # 遷移沒有偷偷建出核心表


def test_existing_production_db_is_baselined_without_rework(tmp_path):
    """既有生產庫已被舊的即時 ALTER 補過欄位：遷移應無動作但仍記上版本。"""
    path = str(tmp_path / "already.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, close REAL,"
        " source TEXT DEFAULT '', fetched_at TEXT DEFAULT '')"
    )
    conn.execute("INSERT INTO daily_quotes VALUES ('20260902', '2330', 1000, 'twse', 'x')")
    conn.commit()
    conn.close()

    run_migrations(path)

    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_quotes)")]
    row = conn.execute("SELECT source, fetched_at FROM daily_quotes").fetchone()
    conn.close()
    assert cols.count("source") == 1
    assert row == ("twse", "x")
    assert current_version(path) == LATEST_VERSION


def test_migration_adds_lineage_to_legacy_table(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, close REAL)")
    conn.execute("INSERT INTO daily_quotes VALUES ('20260902', '2330', 1000)")
    conn.commit()
    conn.close()

    run_migrations(path)

    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_quotes)")}
    n = conn.execute("SELECT COUNT(*) FROM daily_quotes").fetchone()[0]
    conn.close()
    assert {"source", "fetched_at"} <= cols
    assert n == 1, "遷移不能弄掉資料"


def test_watchdog_tables_come_from_a_migration(fresh):
    run_migrations(fresh)
    conn = sqlite3.connect(fresh)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"ops_heartbeat", "ops_alerts"} <= names


def test_failing_migration_raises_with_its_number(tmp_path, monkeypatch):
    """失敗不能再被靜默吞掉，而且要講清楚卡在哪一號。"""
    path = str(tmp_path / "boom.db")
    sqlite3.connect(path).close()

    def _boom(conn):
        raise sqlite3.OperationalError("刻意失敗")

    monkeypatch.setattr(db_migrations, "MIGRATIONS", ((1, "會炸的遷移", _boom),))

    with pytest.raises(RuntimeError) as err:
        run_migrations(path)
    assert "1" in str(err.value)
    assert "會炸的遷移" in str(err.value)
    assert current_version(path) == 0


def test_failed_migration_is_not_recorded_as_applied(tmp_path, monkeypatch):
    path = str(tmp_path / "partial.db")
    sqlite3.connect(path).close()

    def _ok(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS m1 (x INTEGER)")

    def _boom(conn):
        raise sqlite3.OperationalError("第二個炸")

    monkeypatch.setattr(db_migrations, "MIGRATIONS", ((1, "好的", _ok), (2, "壞的", _boom)))

    with pytest.raises(RuntimeError):
        run_migrations(path)
    assert applied_versions(path) == [1]


def test_migrations_resume_after_a_fix(tmp_path, monkeypatch):
    path = str(tmp_path / "resume.db")
    sqlite3.connect(path).close()

    def _ok(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS m1 (x INTEGER)")

    def _boom(conn):
        raise sqlite3.OperationalError("先炸一次")

    monkeypatch.setattr(db_migrations, "MIGRATIONS", ((1, "好的", _ok), (2, "壞的", _boom)))
    with pytest.raises(RuntimeError):
        run_migrations(path)

    def _fixed(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS m2 (x INTEGER)")

    monkeypatch.setattr(db_migrations, "MIGRATIONS", ((1, "好的", _ok), (2, "修好了", _fixed)))
    out = run_migrations(path)
    assert out["applied"] == [2]
    assert applied_versions(path) == [1, 2]


def test_schema_health_reports_pending(fresh):
    health = schema_health(fresh)
    assert health["ok"] is False
    assert health["version"] == 0
    assert health["latest"] == LATEST_VERSION
    assert len(health["pending"]) == len(MIGRATIONS)
    assert any("待套用遷移" in r for r in health["reasons"])


def test_schema_health_ok_after_migrating(fresh):
    run_migrations(fresh)
    health = schema_health(fresh)
    assert health["ok"] is True
    assert health["version"] == LATEST_VERSION
    assert health["pending"] == []


def test_schema_health_missing_db(tmp_path):
    health = schema_health(str(tmp_path / "nope.db"))
    assert health["ok"] is False
    assert health["version"] == 0


def test_schema_health_surfaces_recorded_build_errors(fresh):
    run_migrations(fresh)
    record_schema_error(fresh, "ex_rights", "no such module")
    health = schema_health(fresh)
    assert health["ok"] is False
    assert "ex_rights" in health["errors"]
    assert any("建表失敗" in r for r in health["reasons"])


def test_ensure_migration_table_is_idempotent(fresh):
    ensure_migration_table(fresh)
    ensure_migration_table(fresh)
    assert applied_versions(fresh) == []


def test_ensure_core_schema_records_step_failures(tmp_path, monkeypatch):
    """單一模組建表失敗時開機要繼續，但必須留下紀錄而非無聲。"""
    import wayne_db

    path = str(tmp_path / "steps.db")

    def _boom(p):
        raise RuntimeError("ex_rights 掛了")

    def _fake_steps():
        return (("ex_rights", _boom),)

    monkeypatch.setattr(wayne_db, "_schema_steps", _fake_steps)
    wayne_db._run_schema_steps(path)

    errors = schema_errors(path)
    assert "ex_rights" in errors
    assert "掛了" in errors["ex_rights"]


def test_ensure_core_schema_clears_error_once_step_recovers(tmp_path, monkeypatch):
    import wayne_db

    path = str(tmp_path / "recover.db")
    record_schema_error(path, "ex_rights", "舊的失敗")

    monkeypatch.setattr(wayne_db, "_schema_steps", lambda: (("ex_rights", lambda p: None),))
    wayne_db._run_schema_steps(path)

    assert "ex_rights" not in schema_errors(path)


def test_ensure_core_schema_reaches_latest_version(tmp_path):
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "core.db")
    ensure_core_schema(path)
    assert current_version(path) == LATEST_VERSION


def test_automation_audit_flags_pending_migrations(tmp_path, monkeypatch):
    """巡檢要抓到 schema 沒升級，而不是等奇怪的查詢錯誤浮現。"""
    from automation_health import run_automation_audit

    path = str(tmp_path / "audit.db")
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT NOT NULL, stock_id TEXT NOT NULL, stock_name TEXT NOT NULL,
            market TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, turnover_k REAL, pct_change REAL, avg_price REAL,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.commit()
    conn.close()

    report = run_automation_audit(path, cap="", max_gap_days=999)
    schema = (report.get("checks") or {}).get("schema") or {}
    assert schema.get("ok") is False
    assert any("schema" in r for r in report.get("reasons") or [])


def test_automation_audit_still_reports_on_broken_schema(tmp_path):
    """庫壞成查不動時，巡檢仍要吐出報告——這正是最需要它的時候。"""
    from automation_health import run_automation_audit

    path = str(tmp_path / "broken.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, close REAL)")
    conn.commit()
    conn.close()

    report = run_automation_audit(path, cap="20260902", max_gap_days=999)
    assert report.get("ok") is False
    assert report.get("reasons")


def test_m006_clears_journal_holdings_once(tmp_path):
    """手記持股一次清空；再記買入不會被第二次遷移刪掉。觀察清單不動。"""
    path = str(tmp_path / "hold.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE user_holdings (
            user_id TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            shares REAL NOT NULL,
            cost_price REAL NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, stock_code)
        );
        CREATE TABLE user_watchlist (
            user_id TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, stock_code)
        );
        INSERT INTO user_holdings VALUES
            ('8528875978','1303','南亞',1.0,210.6,'2026-08-30'),
            ('8528875978','6526','達發',0.439,631.6,'2026-08-30');
        INSERT INTO user_watchlist VALUES ('8528875978','3354','律勝','2026-08-30');
        """
    )
    conn.commit()
    conn.close()

    run_migrations(path)
    conn = sqlite3.connect(path)
    n_hold = conn.execute("SELECT COUNT(*) FROM user_holdings").fetchone()[0]
    n_watch = conn.execute("SELECT COUNT(*) FROM user_watchlist").fetchone()[0]
    conn.close()
    assert n_hold == 0
    assert n_watch == 1

    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO user_holdings VALUES ('8528875978','2330','台積電',1.0,1000,'2026-09-05')"
    )
    conn.commit()
    conn.close()
    second = run_migrations(path)
    assert second["applied"] == []
    conn = sqlite3.connect(path)
    left = conn.execute("SELECT stock_code FROM user_holdings").fetchall()
    conn.close()
    assert left == [("2330",)]
