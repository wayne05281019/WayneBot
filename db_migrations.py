# -*- coding: utf-8 -*-
"""schema 版本與遷移。

在這之前，schema 是靠散在各處的 CREATE TABLE IF NOT EXISTS 加上臨時的
PRAGMA/ALTER 檢查演進的，而且好幾處包在 except Exception: pass 裡：
升級到底做了什麼、有沒有成功，事後查不出來，失敗也只會在很久之後
以奇怪的查詢錯誤浮現。

這裡把演進變成有版本、有記錄、失敗會講話的東西：

* 每個遷移都寫成可重複執行（先問 PRAGMA 再動手）。既有生產庫已經被
  舊的即時 ALTER 補過欄位，第一次跑到這裡會是無動作但仍記上版本，
  等於自動完成 baseline，不需要手動標記。
* 每個遷移各自一個 transaction，失敗就往外丟並指出是哪一號，
  不再靜默跳過。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)


def _columns(conn: sqlite3.Connection, table: str) -> set:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return bool(row)


def _add_columns(conn: sqlite3.Connection, table: str, specs: Tuple[Tuple[str, str], ...]) -> None:
    """表還不存在就跳過——建表歸 ensure_core_schema，這裡只管演進。"""
    if not _table_exists(conn, table):
        return
    have = _columns(conn, table)
    for name, spec in specs:
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")


def _m001_daily_quotes_lineage(conn: sqlite3.Connection) -> None:
    _add_columns(
        conn,
        "daily_quotes",
        (("source", "TEXT DEFAULT ''"), ("fetched_at", "TEXT DEFAULT ''")),
    )


def _m002_sector_flow_top_sell(conn: sqlite3.Connection) -> None:
    _add_columns(
        conn,
        "daily_sector_flow",
        (
            ("top_sell_id", "TEXT DEFAULT ''"),
            ("top_sell_name", "TEXT DEFAULT ''"),
            ("top_sell_three", "INTEGER DEFAULT 0"),
        ),
    )


def _m003_ai_fills_user_id(conn: sqlite3.Connection) -> None:
    _add_columns(conn, "ai_fills", (("user_id", "TEXT DEFAULT 'wayne_ai'"),))


def _m004_ai_nav_log_user_id(conn: sqlite3.Connection) -> None:
    _add_columns(conn, "ai_nav_log", (("user_id", "TEXT DEFAULT 'wayne_ai'"),))


def _m005_ops_watchdog_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_heartbeat (
            kind TEXT PRIMARY KEY,
            beat_at TEXT NOT NULL,
            note TEXT DEFAULT ''
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_alerts (
            kind TEXT NOT NULL,
            run_date TEXT NOT NULL,
            alerted_at TEXT NOT NULL,
            PRIMARY KEY (kind, run_date)
        );
        """
    )


# 只能往後加，不能改號、不能重排。
MIGRATIONS: Tuple[Tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "daily_quotes 加 source/fetched_at 溯源", _m001_daily_quotes_lineage),
    (2, "daily_sector_flow 加 top_sell_*", _m002_sector_flow_top_sell),
    (3, "ai_fills 加 user_id", _m003_ai_fills_user_id),
    (4, "ai_nav_log 加 user_id", _m004_ai_nav_log_user_id),
    (5, "排程心跳與告警去重表", _m005_ops_watchdog_tables),
)

LATEST_VERSION = max(v for v, _, _ in MIGRATIONS)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def ensure_migration_table(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def applied_versions(db_path: str) -> List[int]:
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return []
    try:
        conn = _connect(path)
        try:
            if not _table_exists(conn, "schema_migrations"):
                return []
            return [
                int(r[0])
                for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def current_version(db_path: str) -> int:
    versions = applied_versions(db_path)
    return max(versions) if versions else 0


def pending_migrations(db_path: str) -> List[Tuple[int, str]]:
    done = set(applied_versions(db_path))
    return [(v, name) for v, name, _ in MIGRATIONS if v not in done]


def run_migrations(db_path: str) -> Dict[str, Any]:
    """套用未執行的遷移。失敗會往外丟，並指出卡在哪一號。"""
    path = str(db_path or "").strip()
    if not path:
        return {"applied": [], "version": 0}

    ensure_migration_table(path)
    done = set(applied_versions(path))
    applied: List[int] = []

    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        conn = _connect(path)
        try:
            fn(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
            applied.append(version)
            logger.info("schema 遷移 %s 完成：%s", version, name)
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(f"schema 遷移 {version}（{name}）失敗：{exc}") from exc
        finally:
            conn.close()

    return {"applied": applied, "version": current_version(path)}


def schema_health(db_path: str) -> Dict[str, Any]:
    """給 /inventory 與巡檢：版本、待辦遷移、建表時被吞掉的錯。"""
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return {
            "ok": False,
            "version": 0,
            "latest": LATEST_VERSION,
            "pending": [],
            "reason": "資料庫不存在",
        }
    version = current_version(path)
    pending = pending_migrations(path)
    errors = schema_errors(path)
    reasons = []
    if pending:
        reasons.append("待套用遷移 " + "、".join(str(v) for v, _ in pending))
    if errors:
        reasons.append("建表失敗 " + "、".join(sorted(errors)))
    return {
        "ok": not reasons,
        "version": version,
        "latest": LATEST_VERSION,
        "pending": [{"version": v, "name": n} for v, n in pending],
        "errors": errors,
        "reasons": reasons,
    }


# ensure_core_schema 呼叫各模組建表時的失敗紀錄。維持開機不中斷，
# 但不能像以前那樣 except Exception: pass 完全消音。
_SCHEMA_ERRORS: Dict[str, Dict[str, str]] = {}


def record_schema_error(db_path: str, step: str, error: str) -> None:
    _SCHEMA_ERRORS.setdefault(str(db_path or ""), {})[str(step)] = str(error)
    logger.warning("schema 步驟 %s 失敗：%s", step, error)


def clear_schema_error(db_path: str, step: str) -> None:
    _SCHEMA_ERRORS.get(str(db_path or ""), {}).pop(str(step), None)


def schema_errors(db_path: str) -> Dict[str, str]:
    return dict(_SCHEMA_ERRORS.get(str(db_path or ""), {}))
