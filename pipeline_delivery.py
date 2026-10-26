# Telegram 白名單寄出回執：pipeline_runs success 之外的第二證據。
# 寄出成功後立刻落檔；蓋戳失敗時 catch-up／force-morning 仍認已寄，不准重寄。
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("WayneBotRunner")

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_deliveries (
    run_date TEXT PRIMARY KEY,
    delivered_at TEXT NOT NULL,
    kind TEXT DEFAULT '',
    n_ok INTEGER DEFAULT 0,
    notes TEXT DEFAULT ''
);
"""


def _delivery_dir(db_path: str) -> Path:
    parent = Path(db_path).resolve().parent
    d = parent / "pipeline_deliveries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_path(db_path: str, run_date: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(run_date))
    return _delivery_dir(db_path) / f"{safe}.json"


def ensure_delivery_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def record_push_delivery(
    db_path: str,
    run_date: str,
    *,
    kind: str = "",
    n_ok: int = 0,
    notes: str = "",
    delivered_at: str = "",
    retries: int = 10,
) -> bool:
    """白名單寄出成功後立刻記一筆。DB＋檔雙寫；檔寫成即可當證據。"""
    key = str(run_date or "").strip()
    if not key:
        return False
    stamp = str(delivered_at or "").strip()
    if not stamp:
        try:
            from config import taipei_stamp

            stamp = taipei_stamp()
        except Exception:
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    payload: Dict[str, Any] = {
        "run_date": key,
        "delivered_at": stamp,
        "kind": str(kind or "")[:120],
        "n_ok": int(n_ok or 0),
        "notes": str(notes or "")[:500],
    }
    file_ok = False
    try:
        path = _file_path(db_path, key)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        file_ok = True
    except Exception:
        logger.exception("pipeline_delivery 檔寫失敗 key=%s", key)

    db_ok = False
    last_err: Optional[Exception] = None
    attempts = max(1, int(retries or 1))
    for attempt in range(attempts):
        try:
            ensure_delivery_schema(db_path)
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO pipeline_deliveries
                    (run_date, delivered_at, kind, n_ok, notes)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        payload["delivered_at"],
                        payload["kind"],
                        payload["n_ok"],
                        payload["notes"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            db_ok = True
            break
        except sqlite3.OperationalError as e:
            last_err = e
            msg = str(e).lower()
            if "locked" not in msg and "busy" not in msg:
                logger.exception("pipeline_delivery DB 寫入失敗 key=%s", key)
                break
            logger.warning(
                "pipeline_delivery DB busy（%s/%s）key=%s：%s",
                attempt + 1,
                attempts,
                key,
                e,
            )
            time.sleep(0.35 * (attempt + 1))
        except Exception as e:
            last_err = e
            logger.exception("pipeline_delivery DB 寫入失敗 key=%s", key)
            break
    if not db_ok and last_err is not None and not file_ok:
        logger.error("pipeline_delivery 雙寫皆失敗 key=%s：%s", key, last_err)
    return bool(db_ok or file_ok)


def push_delivery_recorded(db_path: str, run_date: str) -> bool:
    """是否已有寄出回執（表或檔）。"""
    key = str(run_date or "").strip()
    if not key:
        return False
    try:
        ensure_delivery_schema(db_path)
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute(
                "SELECT 1 FROM pipeline_deliveries WHERE run_date = ? LIMIT 1",
                (key,),
            ).fetchone()
            if row:
                return True
        finally:
            conn.close()
    except Exception:
        logger.debug("pipeline_delivery 查表略過 key=%s", key, exc_info=True)
    try:
        path = _file_path(db_path, key)
        if path.is_file() and path.stat().st_size > 2:
            return True
    except Exception:
        logger.debug("pipeline_delivery 查檔略過 key=%s", key, exc_info=True)
    return False


def load_push_delivery(db_path: str, run_date: str) -> Optional[Dict[str, Any]]:
    key = str(run_date or "").strip()
    if not key:
        return None
    try:
        ensure_delivery_schema(db_path)
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute(
                """
                SELECT run_date, delivered_at, kind, n_ok, notes
                FROM pipeline_deliveries WHERE run_date = ?
                """,
                (key,),
            ).fetchone()
            if row:
                return {
                    "run_date": str(row[0]),
                    "delivered_at": str(row[1] or ""),
                    "kind": str(row[2] or ""),
                    "n_ok": int(row[3] or 0),
                    "notes": str(row[4] or ""),
                }
        finally:
            conn.close()
    except Exception:
        logger.debug("pipeline_delivery load 表略過", exc_info=True)
    try:
        path = _file_path(db_path, key)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("pipeline_delivery load 檔略過", exc_info=True)
    return None


def delivery_taipei_ymd(delivered_at: str) -> str:
    """回執時戳 → 台北 YYYYMMDD；解析失敗回空字串。"""
    raw = str(delivered_at or "").strip()
    if not raw:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tw = ZoneInfo("Asia/Taipei")
        # 支援 2026-10-23T06:32:00+08:00／無時區／空白分隔
        s = raw.replace(" ", "T", 1) if " " in raw and "T" not in raw else raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tw)
        else:
            dt = dt.astimezone(tw)
        return dt.strftime("%Y%m%d")
    except Exception:
        digits = "".join(c for c in raw if c.isdigit())
        return digits[:8] if len(digits) >= 8 else ""


def clear_push_delivery(db_path: str, run_date: str, *, bak_suffix: str = "") -> bool:
    """刪回執表列＋檔（可選改名備份）。回 True＝有清到任一證據。"""
    key = str(run_date or "").strip()
    if not key:
        return False
    cleared = False
    try:
        ensure_delivery_schema(db_path)
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            cur = conn.execute(
                "DELETE FROM pipeline_deliveries WHERE run_date = ?", (key,)
            )
            conn.commit()
            if int(cur.rowcount or 0) > 0:
                cleared = True
        finally:
            conn.close()
    except Exception:
        logger.exception("pipeline_delivery 清表失敗 key=%s", key)
    try:
        path = _file_path(db_path, key)
        if path.is_file():
            if bak_suffix:
                bak = path.with_suffix(path.suffix + str(bak_suffix))
                try:
                    path.rename(bak)
                except Exception:
                    path.unlink(missing_ok=True)
            else:
                path.unlink(missing_ok=True)
            cleared = True
    except Exception:
        logger.exception("pipeline_delivery 清檔失敗 key=%s", key)
    return cleared
