# -*- coding: utf-8 -*-
"""排程死人開關（dead man's switch）＋行程存活心跳。

分工刻意分開：
* `/health` 只回答「這個行程還能不能服務」——資料過期**不會**讓它變紅，
  因為 Render 健檢失敗會重啟，而重啟修不了資料管線，只會弄掉互動 bot。
* 「排程沒跑」「資料沒進來」改由本模組在超過死線時主動推 Telegram，
  這才是半夜真正找得到人的路徑。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 排程死線（台灣時間，當日 00:00 起算的分鐘數）。
# 死線 = 預定時間 + 緩衝，緩衝要蓋得住 GHA 排隊與重試。
JOB_SPECS: Dict[str, Dict[str, Any]] = {
    "increment": {
        "label": "盤後融合",
        "scheduled": "16:30",
        "due_minutes": 18 * 60 + 30,
        "key": "today",
    },
    "morning_screen": {
        "label": "早上海選",
        "scheduled": "06:30",
        "due_minutes": 8 * 60,
        "key": "screen",
    },
}

HEARTBEAT_POLLING = "telegram_polling"
_POLLING_STALE_SECONDS = 900


def watchdog_enabled() -> bool:
    raw = (os.getenv("WAYNE_WATCHDOG_ENABLED") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def ensure_ops_tables(db_path: str) -> None:
    """心跳與告警去重表；與 pipeline_runs 並存，不改動既有排程紀錄。"""
    path = str(db_path or "").strip()
    if not path:
        return
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000;")
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
        conn.commit()
    finally:
        conn.close()


def record_heartbeat(db_path: str, kind: str, note: str = "") -> None:
    """由事件迴圈內呼叫才有意義：迴圈卡死時心跳自然變舊。"""
    path = str(db_path or "").strip()
    if not path:
        return
    try:
        ensure_ops_tables(path)
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute(
                "INSERT OR REPLACE INTO ops_heartbeat(kind, beat_at, note) VALUES (?, ?, ?)",
                (str(kind), datetime.now().isoformat(timespec="seconds"), str(note or "")),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.debug("心跳寫入失敗 kind=%s", kind, exc_info=True)


def heartbeat_age_seconds(db_path: str, kind: str, *, now: Optional[datetime] = None) -> Optional[float]:
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT beat_at FROM ops_heartbeat WHERE kind=?", (str(kind),)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    try:
        beat = datetime.fromisoformat(str(row[0]))
    except ValueError:
        return None
    ref = now or datetime.now()
    return max(0.0, (ref - beat).total_seconds())


def polling_alive(db_path: str, *, now: Optional[datetime] = None) -> Optional[bool]:
    """None＝沒有心跳紀錄（未啟用輪詢或剛開機）；False＝心跳過舊。"""
    age = heartbeat_age_seconds(db_path, HEARTBEAT_POLLING, now=now)
    if age is None:
        return None
    return age <= _POLLING_STALE_SECONDS


def _pipeline_status(db_path: str, run_date: str) -> str:
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return ""
    try:
        conn = sqlite3.connect(path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT status FROM pipeline_runs WHERE run_date = ?", (str(run_date),)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row and row[0] else ""


def _expected_run_keys(db_path: str, now: datetime) -> Dict[str, str]:
    """每個排程今天該留下的 pipeline_runs 鍵值。"""
    today = now.strftime("%Y%m%d")
    keys = {"increment": today}
    try:
        from trading_calendar import morning_screen_pipeline_key

        keys["morning_screen"] = morning_screen_pipeline_key(db_path, now=now)
    except Exception:
        keys["morning_screen"] = "screen-none"
    return keys


def missed_jobs(db_path: str, *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """已過死線但今天沒有 success 紀錄的排程。"""
    try:
        from config import taipei_now
    except Exception:
        taipei_now = datetime.now  # type: ignore

    ref = now or taipei_now()
    if ref.weekday() >= 5:
        return []
    minutes = ref.hour * 60 + ref.minute
    keys = _expected_run_keys(db_path, ref)
    out: List[Dict[str, Any]] = []
    for kind, spec in JOB_SPECS.items():
        if minutes < int(spec["due_minutes"]):
            continue
        run_key = keys.get(kind) or ""
        if not run_key or run_key.endswith("-none"):
            continue
        status = _pipeline_status(db_path, run_key)
        if status == "success":
            continue
        out.append(
            {
                "kind": kind,
                "label": str(spec["label"]),
                "scheduled": str(spec["scheduled"]),
                "run_date": run_key,
                "status": status or "無紀錄",
            }
        )
    return out


def release_asset_age_days(*, now: Optional[datetime] = None, timeout: float = 10.0) -> Optional[float]:
    """Release zip 距今幾天更新。這是從常駐端唯一看得到「GHA 還活著」的訊號。

    None＝問不到（離線／私有庫），呼叫端要當成「不知道」而非「壞了」。
    """
    try:
        import email.utils

        import requests

        from config import get_github_release_url
    except Exception:
        return None
    try:
        resp = requests.head(get_github_release_url(), timeout=timeout, allow_redirects=True)
        stamp = resp.headers.get("Last-Modified") or ""
        if not stamp:
            return None
        modified = email.utils.parsedate_to_datetime(stamp)
    except Exception:
        return None
    ref = now or datetime.now(modified.tzinfo)
    if ref.tzinfo is None and modified.tzinfo is not None:
        modified = modified.replace(tzinfo=None)
    try:
        return max(0.0, (ref - modified).total_seconds() / 86400.0)
    except TypeError:
        return None


def gha_pipeline_stale(*, max_age_days: float = 4.0, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Release 太久沒更新＝GHA 資料管線（或額度）掛了。"""
    age = release_asset_age_days(now=now)
    if age is None:
        return {"known": False, "stale": False, "age_days": None}
    return {"known": True, "stale": age > float(max_age_days), "age_days": round(age, 2)}


def claim_alert(db_path: str, kind: str, run_date: str) -> bool:
    """同一排程同一天只告警一次；搶到才回 True。"""
    path = str(db_path or "").strip()
    if not path:
        return False
    try:
        ensure_ops_tables(path)
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
            cur = conn.execute(
                "INSERT OR IGNORE INTO ops_alerts(kind, run_date, alerted_at) VALUES (?, ?, ?)",
                (str(kind), str(run_date), datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except Exception:
        logger.debug("告警去重失敗 kind=%s", kind, exc_info=True)
        return False


def format_watchdog_alert(missed: List[Dict[str, Any]]) -> str:
    if not missed:
        return ""
    lines = ["⏰ <b>排程未完成</b>"]
    for m in missed:
        lines.append(
            f"• {m['label']}（預定 {m['scheduled']}）：{m['status']}　<code>{m['run_date']}</code>"
        )
    lines.append("")
    lines.append("<i>若今日為國定假日／停市，可忽略此提醒。</i>")
    return "\n".join(lines)


def release_check_enabled() -> bool:
    raw = (os.getenv("WAYNE_WATCHDOG_RELEASE") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _release_missed(now: Optional[datetime]) -> List[Dict[str, Any]]:
    if not release_check_enabled():
        return []
    stale = gha_pipeline_stale(now=now)
    if not stale.get("known") or not stale.get("stale"):
        return []
    day = (now or datetime.now()).strftime("%Y%m%d")
    return [
        {
            "kind": "release_publish",
            "label": "GHA 資料管線（Release zip）",
            "scheduled": "16:30",
            "run_date": f"release-{day}",
            "status": f"已 {stale.get('age_days')} 天未更新",
        }
    ]


def watchdog_scan(
    db_path: str,
    *,
    now: Optional[datetime] = None,
    claim: bool = True,
    check_release: bool = True,
) -> Dict[str, Any]:
    """回傳需要告警的排程；claim=True 時同時完成當日去重。"""
    if not watchdog_enabled():
        return {"enabled": False, "missed": [], "alerts": []}
    missed = missed_jobs(db_path, now=now)
    if check_release:
        missed = missed + _release_missed(now)
    alerts = []
    for m in missed:
        if not claim or claim_alert(db_path, str(m["kind"]), str(m["run_date"])):
            alerts.append(m)
    return {"enabled": True, "missed": missed, "alerts": alerts}


def watchdog_payload(db_path: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """給 /ready 與巡檢用的唯讀快照（不寫告警去重、不打外部網路）。"""
    missed = missed_jobs(db_path, now=now) if watchdog_enabled() else []
    alive = polling_alive(db_path, now=None)
    return {
        "enabled": watchdog_enabled(),
        "missed": missed,
        "missed_n": len(missed),
        "polling_alive": alive,
        "polling_age_s": heartbeat_age_seconds(db_path, HEARTBEAT_POLLING),
    }
