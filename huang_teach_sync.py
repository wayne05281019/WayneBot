"""台北 14:30：抓黃培碩當日片（若有）→對讀飆大口頭→重渲教導三窗畫線。

約束（最高指令）：
- 時區 Asia/Taipei；只開市日跑
- 話筒價位／題旨仍跟飆大口頭；黃培碩＝60分方法映到日K，不是買訊
- 不准發明報價；無片也仍可用既有日界＋飆大題旨重渲（有片再記 meta）
- 不寄話筒推播（畫線進教導三窗／大盤頁；推播閘另開）
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.huang_teach")

TAIPEI = ZoneInfo("Asia/Taipei")
PIPELINE_PREFIX = "huang-teach-"
# 台北 14:30 準點；補跑到 15:20 前仍算這檔
SLOT_MINUTE = 14 * 60 + 30
CATCHUP_UNTIL = 15 * 60 + 20


def _ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def pipeline_key(ymd: str) -> str:
    return f"{PIPELINE_PREFIX}{str(ymd or '').strip()}"


def ensure_tables(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS huang_teach_runs (
                as_of TEXT NOT NULL PRIMARY KEY,
                status TEXT NOT NULL,
                video_id TEXT DEFAULT '',
                video_title TEXT DEFAULT '',
                note TEXT DEFAULT '',
                paint_ok INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _stamp() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _already_success(db_path: str, ymd: str) -> bool:
    key = pipeline_key(ymd)
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT status FROM pipeline_runs WHERE run_date=?", (key,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row and str(row[0] or "") == "success")


def _mark_pipeline(db_path: str, ymd: str, status: str, notes: str) -> None:
    key = pipeline_key(ymd)
    try:
        from wayne_db import connect

        conn = connect(db_path)
    except Exception:
        conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs "
            "(run_date, status, notes, finished_at) VALUES (?, ?, ?, ?)",
            (key, status, (notes or "")[:500], _stamp()),
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_run(db_path: str, row: Dict[str, Any]) -> None:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO huang_teach_runs(
                as_of, status, video_id, video_title, note, paint_ok, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(as_of) DO UPDATE SET
                status=excluded.status,
                video_id=excluded.video_id,
                video_title=excluded.video_title,
                note=excluded.note,
                paint_ok=excluded.paint_ok,
                updated_at=excluded.updated_at
            """,
            (
                str(row.get("as_of") or ""),
                str(row.get("status") or ""),
                str(row.get("video_id") or ""),
                str(row.get("video_title") or ""),
                str(row.get("note") or "")[:800],
                1 if row.get("paint_ok") else 0,
                _stamp(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _is_open_day(dt: datetime, db_path: str) -> bool:
    try:
        from trading_calendar import is_tw_open_calendar_day

        return bool(is_tw_open_calendar_day(dt.strftime("%Y%m%d")))
    except Exception:
        try:
            from tw_holidays import closed_tw_session

            return closed_tw_session(now=dt, db_path=db_path) is None and dt.weekday() < 5
        except Exception:
            return dt.weekday() < 5


def find_huang_video_hint(as_of_ymd: str) -> Dict[str, str]:
    """找當日黃培碩片提示（環境／本機快取）；沒有就空，不准假造 file id。

    Render 常駐通常沒有 Drive MCP；有設 HUANG_TEACH_VIDEO_ID／TITLE 才記入。
    檔名慣例含 YYYYMMDD 或 YYYY-MM-DD／黃培碩。
    """
    out = {"video_id": "", "video_title": "", "source": ""}
    vid = (os.getenv("HUANG_TEACH_VIDEO_ID") or "").strip()
    title = (os.getenv("HUANG_TEACH_VIDEO_TITLE") or "").strip()
    ymd = str(as_of_ymd or "").strip()
    if vid and title:
        if ymd and (ymd in title or f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" in title):
            return {"video_id": vid, "video_title": title, "source": "env"}
        if not ymd:
            return {"video_id": vid, "video_title": title, "source": "env"}
    # 本機／artifact 旁註（agent 抓片後可落這檔）
    hint_paths = (
        os.path.join("data", "huang_teach_hint.json"),
        os.path.join("/opt/cursor/artifacts", f"huang-hint-{ymd}.json"),
        os.path.join("/opt/cursor/artifacts", "huang-oral-chart-pair.md"),
    )
    for hp in hint_paths:
        if not os.path.isfile(hp):
            continue
        try:
            if hp.endswith(".json"):
                raw = json.loads(open(hp, encoding="utf-8").read())
                t = str(raw.get("video_title") or raw.get("title") or "")
                i = str(raw.get("video_id") or raw.get("fileId") or "")
                if ymd and t and ymd not in t and f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" not in t:
                    continue
                if i or t:
                    return {
                        "video_id": i,
                        "video_title": t,
                        "source": f"file:{os.path.basename(hp)}",
                    }
            else:
                # markdown 對讀：有當日字樣就算有材料
                text = open(hp, encoding="utf-8").read()
                if ymd and ymd not in text and f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" not in text:
                    # 允許口播對讀檔只寫 2026-11-10 格式
                    dash = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                    if dash not in text:
                        continue
                m = re.search(r"Drive\s+([A-Za-z0-9_-]{20,})", text)
                return {
                    "video_id": m.group(1) if m else "",
                    "video_title": "huang-oral-chart-pair",
                    "source": "oral_pair_md",
                }
        except Exception:
            logger.debug("huang hint 讀取略過 %s", hp, exc_info=True)
    return out


def run_huang_teach_sync(
    db_path: Optional[str] = None,
    *,
    skip_if_done: bool = True,
    now: Optional[datetime] = None,
    force_paint: bool = True,
) -> Dict[str, Any]:
    """開市日 14:30 檔：吸飆大 →（有則記黃片）→ 重渲教導三窗。不是買訊。"""
    from config import get_db_path

    path = str(db_path or get_db_path() or "").strip()
    out: Dict[str, Any] = {
        "ok": False,
        "skipped": "",
        "as_of": "",
        "paint_ok": False,
        "video_id": "",
        "status": "",
    }
    if not path:
        out["skipped"] = "no_db"
        return out
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    ymd = _ymd(dt)
    out["as_of"] = ymd
    if not _is_open_day(dt, path):
        out["skipped"] = "closed"
        out["status"] = "closed"
        return out
    ensure_tables(path)
    if skip_if_done and _already_success(path, ymd):
        out["skipped"] = "done"
        out["status"] = "done"
        out["ok"] = True
        return out

    # 先吸飆大，畫線才對得上當日口頭
    try:
        from biaoke_ingest import run_biaoke_ingest_quiet

        run_biaoke_ingest_quiet()
    except Exception:
        logger.exception("huang_teach：飆大匯入略過（不擋畫線）")

    hint = find_huang_video_hint(ymd)
    out["video_id"] = hint.get("video_id") or ""
    note_bits = [
        "黃培碩60分映日K＋飆大口頭；非買訊",
        f"hint={hint.get('source') or 'none'}",
    ]
    if hint.get("video_title"):
        note_bits.append(f"title={hint.get('video_title')[:80]}")

    paint_ok = False
    if force_paint:
        try:
            from biaoke_level_learn import paint_open_day_hypothesis

            painted = paint_open_day_hypothesis(path, force=True, panels="trio") or {}
            paint_ok = bool(painted.get("ok") or painted.get("far_path") or painted.get("path"))
            if painted.get("slot_id"):
                note_bits.append(f"slot={painted.get('slot_id')}")
        except Exception:
            logger.exception("huang_teach：教導三窗重渲失敗")
            paint_ok = False

    out["paint_ok"] = paint_ok
    status = "success" if paint_ok else "paint_failed"
    if not hint.get("video_id") and not hint.get("video_title"):
        # 無片仍可依既有日界＋飆大重渲；記 no_video 但不擋 success
        note_bits.append("no_video_yet")
        if paint_ok:
            status = "success"
        else:
            status = "pending_no_video"
    out["status"] = status
    _upsert_run(
        path,
        {
            "as_of": ymd,
            "status": status,
            "video_id": hint.get("video_id") or "",
            "video_title": hint.get("video_title") or "",
            "note": "；".join(note_bits),
            "paint_ok": paint_ok,
        },
    )
    _mark_pipeline(path, ymd, status if status == "success" else "error", "；".join(note_bits))
    out["ok"] = status == "success"
    return out


def due_for_catchup(now: Optional[datetime] = None) -> bool:
    """補跑門檻：開市日已過 14:30 且未滿 CATCHUP_UNTIL（之後仍可 skip_if_done 補）。"""
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    mins = dt.hour * 60 + dt.minute
    return mins >= SLOT_MINUTE
