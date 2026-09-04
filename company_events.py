"""官方公司行事：股東會（OpenAPI）+ 法說日期（重大訊息說明欄）。

法說日期只從官方「召開法人說明會之日期」子句抽出，不做關鍵字產品。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

log = logging.getLogger("wayne.events")

_load_lock = threading.Lock()
_loaded = False
_next_try = 0.0

TWSE_MEETING = "https://openapi.twse.com.tw/v1/opendata/t187ap41_L"
TWSE_MATERIAL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
TAIPEI = ZoneInfo("Asia/Taipei")

_DDL = """
CREATE TABLE IF NOT EXISTS company_events (
    stock_id TEXT NOT NULL,
    event_date TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (stock_id, event_date, kind, source)
)
"""
_IDX = "CREATE INDEX IF NOT EXISTS idx_company_events_date ON company_events(event_date)"

_IR_DATE = re.compile(
    r"召開法人說明會之日期[：:]\s*(\d{2,3})[/\-.](\d{1,2})[/\-.](\d{1,2})"
)


def ensure_schema(db_path: str | None = None) -> str:
    path = db_path or get_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_DDL)
    conn.execute(_IDX)
    conn.commit()
    conn.close()
    return path


def roc_compact_to_ymd(raw: str) -> str | None:
    s = re.sub(r"\D", "", str(raw or ""))
    if len(s) == 7:
        y, m, d = int(s[:3]) + 1911, int(s[3:5]), int(s[5:7])
    elif len(s) == 8:
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    else:
        return None
    try:
        date(y, m, d)
    except ValueError:
        return None
    return f"{y:04d}{m:02d}{d:02d}"


def parse_ir_date_from_explanation(text: str) -> str | None:
    m = _IR_DATE.search(str(text or ""))
    if not m:
        return None
    y = int(m.group(1))
    if y < 1911:
        y += 1911
    month, day = int(m.group(2)), int(m.group(3))
    try:
        date(y, month, day)
    except ValueError:
        return None
    return f"{y:04d}{month:02d}{day:02d}"


def _http_json(url: str, timeout: float = 45.0) -> Any:
    req = Request(url, headers={"User-Agent": "WayneBot/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ingest_shareholder_meetings(
    rows: list[dict[str, Any]], db_path: str | None = None
) -> int:
    if not rows:
        return 0
    path = ensure_schema(db_path)
    conn = sqlite3.connect(path)
    n = 0
    try:
        for row in rows:
            sid = str(row.get("公司代號") or "").strip()
            if not sid:
                continue
            kind_raw = str(
                row.get("股東常(臨時)會") or row.get("股東會種類") or ""
            ).strip() or "股東會"
            ymd = roc_compact_to_ymd(
                str(row.get("開會日期") or row.get("股東會日期") or "")
            )
            if not ymd:
                continue
            title = f"{kind_raw} {row.get('開會地點') or ''}".strip()
            conn.execute(
                """INSERT OR REPLACE INTO company_events
                   (stock_id, event_date, kind, title, source)
                   VALUES (?,?,?,?,?)""",
                (sid, ymd, kind_raw, title[:200], "t187ap41_L"),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def ingest_ir_from_material(
    rows: list[dict[str, Any]], db_path: str | None = None
) -> int:
    if not rows:
        return 0
    path = ensure_schema(db_path)
    conn = sqlite3.connect(path)
    n = 0
    try:
        for row in rows:
            sid = str(row.get("公司代號") or "").strip()
            expl = str(row.get("主旨及說明") or row.get("說明") or "")
            ymd = parse_ir_date_from_explanation(expl)
            if not sid or not ymd:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO company_events
                   (stock_id, event_date, kind, title, source)
                   VALUES (?,?,?,?,?)""",
                (sid, ymd, "法說", "法人說明會", "t187ap04_L"),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def sync_shareholder_meetings(db_path: str | None = None) -> int:
    try:
        data = _http_json(TWSE_MEETING)
    except Exception as exc:
        log.warning("t187ap41_L: %s", exc)
        return 0
    if not isinstance(data, list):
        return 0
    n = ingest_shareholder_meetings(data, db_path)
    log.info("company_events 股東會 %s 列", n)
    return n


def sync_ir_dates_from_material(db_path: str | None = None) -> int:
    try:
        data = _http_json(TWSE_MATERIAL)
    except Exception as exc:
        log.warning("t187ap04_L: %s", exc)
        return 0
    if not isinstance(data, list):
        return 0
    n = ingest_ir_from_material(data, db_path)
    log.info("company_events 法說 %s 列", n)
    return n


def sync_company_events(db_path: str | None = None) -> dict[str, int]:
    return {
        "meetings": sync_shareholder_meetings(db_path),
        "ir": sync_ir_dates_from_material(db_path),
    }


def reset_load_state_for_tests() -> None:
    global _loaded, _next_try
    _loaded = False
    _next_try = 0.0


def event_row_count(db_path: str | None = None) -> int:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM company_events").fetchone()[0]
        return int(n or 0)
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _autosync_enabled() -> bool:
    flag = str(os.getenv("WAYNE_EVENTS_AUTOSYNC") or "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return True


def ensure_events_loaded(db_path: str | None = None) -> int:
    """部署後表是空的才抓 OpenAPI。已有列或 pytest 預設不抓，避免每檔查股打爆。"""
    global _loaded, _next_try
    path = db_path or get_db_path()
    if _loaded:
        return event_row_count(path)
    if not _autosync_enabled():
        return event_row_count(path)
    now = time.time()
    if now < _next_try:
        return event_row_count(path)
    with _load_lock:
        if _loaded:
            return event_row_count(path)
        ensure_schema(path)
        n = event_row_count(path)
        if n > 0:
            _loaded = True
            return n
        log.info("company_events 空表，同步股東會／法說")
        try:
            sync_company_events(path)
        except Exception:
            log.warning("company_events 同步失敗", exc_info=True)
        n = event_row_count(path)
        if n > 0:
            _loaded = True
        else:
            _next_try = time.time() + 300
        return n


def nearest_company_event(
    stock_id: str,
    *,
    db_path: str | None = None,
    as_of: date | None = None,
    horizon_days: int = 180,
) -> dict[str, str] | None:
    sid = str(stock_id or "").strip()
    if not sid:
        return None
    as_of = as_of or datetime.now(TAIPEI).date()
    end = as_of.fromordinal(as_of.toordinal() + horizon_days)
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            """SELECT event_date, kind, title FROM company_events
               WHERE stock_id=? AND event_date>=? AND event_date<=?
               ORDER BY event_date ASC LIMIT 1""",
            (sid, as_of.strftime("%Y%m%d"), end.strftime("%Y%m%d")),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    if not row:
        return None
    ymd, kind, title = str(row[0]), str(row[1]), str(row[2] or "")
    return {
        "date": ymd,
        "kind": kind,
        "title": title,
        "label": f"{kind} {ymd[4:6]}/{ymd[6:8]}",
    }
