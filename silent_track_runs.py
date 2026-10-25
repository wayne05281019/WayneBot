# -*- coding: utf-8 -*-
"""盤後靜默落檔各軌獨立成功／失敗戳。

融合（increment）成功只代表官方柱齊了，不准再當「後面每一軌都寫進庫」的證明。
各軌分開落檔、分開記成功／失敗；勝率不准混（AGENTS §7／§13）。
時區 Asia/Taipei。失敗不擋其他軌、不改黃金買點／買訊文案。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# pipeline_runs 鍵：sv-{track}-{YYYYMMDD}（與 screen-／winrate-bp-／dc-sf-silent- 並列）
PIPE_PREFIX = "sv-"

# 掛在盤後融合後面的軌（與巡檢報告對齊）。label 給健檢／pipeline 看。
TRACK_LABELS: Dict[str, str] = {
    "screen-buckets": "海選各舊桶",
    "streak": "連買三類",
    "emerging": "興櫃海選桶",
    "dongzhu": "洞燭落檔",
    "dongzhu-refresh": "洞燭盤後走查",
    "market-aux": "大盤佐證",
    "leave-zero-picks": "剛離零雷達",
    "pressure": "壓撐觀察",
    "volzone-ma60": "大量區均線",
    "intraday-lz": "盤中剛離零對質",
    "buy-exclude": "買點排除",
    "winrate-vz-filter": "勝率大量區再篩",
    "lookup-chart": "查股結構精確度",
    "stabilize": "止穩觀察",
    "biaoke-diverge": "飆大分軌",
    "biaoke-vol-next-sup": "破撐下一撐",
    "fear": "開盤前恐懼",
    "foreign-sell-escalate": "外資賣超升級",
    "foreign-sell-extreme": "外資賣超極端",
    "foreign-sell-calm": "外資賣超 Calm",
    "money-flow": "資金輪動落檔",
    "book-hold": "持股對照",
    "book-watch": "觀察對照",
    "book-buy": "記買入對照",
    "ai-desk": "AI倉落檔",
    "biaoke-named": "飆大點名檔",
    "biaoke-levels": "飆大點名點位",
    "winrate-buypoint": "勝率買點靜默凍",
    "score-live": "當下判斷打分",
    "twii-forecast": "大盤默默落檔",
    "screen-review": "海選復盤對帳",
}

# 融合後必跑的核心軌（缺／錯＝健檢要亮）
CORE_AFTER_FUSE: Tuple[str, ...] = (
    "screen-buckets",
    "streak",
    "dongzhu",
    "market-aux",
    "pressure",
    "volzone-ma60",
    "buy-exclude",
    "winrate-vz-filter",
    "lookup-chart",
    "stabilize",
    "biaoke-diverge",
    "fear",
    "foreign-sell-escalate",
    "foreign-sell-extreme",
    "foreign-sell-calm",
    "money-flow",
    "book-hold",
    "book-watch",
    "book-buy",
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def pipeline_key(track: str, as_of: str) -> str:
    """單軌 pipeline_runs 鍵。"""
    tid = str(track or "").strip().lower().replace("_", "-")
    day = _ymd(as_of)
    if not tid or not day:
        return ""
    return f"{PIPE_PREFIX}{tid}-{day}"


def track_label(track: str) -> str:
    tid = str(track or "").strip().lower().replace("_", "-")
    return TRACK_LABELS.get(tid) or tid


def _stamp() -> str:
    try:
        from config import taipei_stamp

        return str(taipei_stamp())
    except Exception:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%dT%H:%M:%S")


def ensure_pipeline_table(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_date TEXT PRIMARY KEY,
                finished_at TEXT,
                status TEXT,
                notes TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def mark_track(
    db_path: str,
    track: str,
    as_of: str,
    status: str,
    notes: str = "",
) -> str:
    """寫入／覆蓋該軌成功或失敗戳。回傳 pipeline 鍵（空＝沒寫）。"""
    path = str(db_path or "").strip()
    key = pipeline_key(track, as_of)
    st = str(status or "").strip().lower() or "error"
    if not path or not key:
        return ""
    try:
        ensure_pipeline_table(path)
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_runs
                    (run_date, finished_at, status, notes)
                VALUES (?, ?, ?, ?)
                """,
                (key, _stamp(), st, str(notes or "")[:800]),
            )
            conn.commit()
        finally:
            conn.close()
        return key
    except Exception:
        logger.exception("靜默軌戳寫入失敗 track=%s as_of=%s", track, as_of)
        return ""


def track_status(db_path: str, track: str, as_of: str) -> Optional[Dict[str, Any]]:
    """讀單軌戳。"""
    path = str(db_path or "").strip()
    key = pipeline_key(track, as_of)
    if not path or not key or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT run_date, finished_at, status, notes FROM pipeline_runs WHERE run_date=?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return {
        "run_date": row[0],
        "finished_at": row[1],
        "status": row[2],
        "notes": row[3] or "",
        "track": str(track or "").strip().lower().replace("_", "-"),
        "label": track_label(track),
        "as_of": _ymd(as_of),
    }


def run_tracked(
    db_path: str,
    track: str,
    as_of: str,
    fn: Callable[[], Any],
    *,
    note_ok: str = "",
) -> Dict[str, Any]:
    """跑一軌：成功／失敗各自蓋戳。例外吞掉並回 ok=False，不准擋其他軌。"""
    day = _ymd(as_of)
    tid = str(track or "").strip().lower().replace("_", "-")
    out: Dict[str, Any] = {
        "ok": False,
        "track": tid,
        "as_of": day,
        "key": pipeline_key(tid, day),
        "result": None,
        "error": "",
    }
    if not db_path or not tid or not day:
        out["error"] = "missing db/track/as_of"
        return out
    try:
        result = fn()
        note = note_ok
        if note == "" and result is not None:
            if isinstance(result, dict):
                note = ",".join(f"{k}={result[k]}" for k in list(result.keys())[:8])
            elif isinstance(result, (int, float)):
                note = f"n={int(result)}"
            else:
                note = str(type(result).__name__)
        mark_track(db_path, tid, day, "success", note or "ok")
        out["ok"] = True
        out["result"] = result
        return out
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        logger.error("靜默軌失敗 %s as_of=%s: %s", tid, day, err, exc_info=True)
        mark_track(db_path, tid, day, "error", err[:800])
        out["error"] = err
        return out


def list_tracks_for_day(
    db_path: str,
    as_of: str,
    *,
    tracks: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """列出當日各軌戳（缺＝missing）。"""
    day = _ymd(as_of)
    tids = [str(t).strip().lower().replace("_", "-") for t in (tracks or CORE_AFTER_FUSE)]
    tids = [t for t in tids if t]
    out: List[Dict[str, Any]] = []
    if not day:
        return out
    for tid in tids:
        hit = track_status(db_path, tid, day)
        if hit:
            out.append(hit)
        else:
            out.append(
                {
                    "run_date": pipeline_key(tid, day),
                    "finished_at": "",
                    "status": "missing",
                    "notes": "",
                    "track": tid,
                    "label": track_label(tid),
                    "as_of": day,
                }
            )
    return out


def failed_or_missing_tracks(
    db_path: str,
    as_of: str,
    *,
    tracks: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """失敗或尚未寫入的軌（融合成功不能蓋掉這些）。"""
    rows = list_tracks_for_day(db_path, as_of, tracks=tracks)
    bad: List[Dict[str, Any]] = []
    for row in rows:
        st = str(row.get("status") or "").strip().lower()
        if st in ("success", "computed"):
            # computed＝明確略過（例如休市），不當失敗
            continue
        bad.append(row)
    return bad


def needs_rerun(db_path: str, as_of: str, track: str) -> bool:
    """該軌沒有 success 就該重跑（含 missing／error／running）。"""
    hit = track_status(db_path, track, as_of)
    if not hit:
        return True
    return str(hit.get("status") or "").strip().lower() != "success"


def silent_tracks_health(
    db_path: str,
    as_of: str,
    *,
    tracks: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """給 /automation-health：各軌狀態＋失敗理由。融合 success 不影響本結果。"""
    day = _ymd(as_of)
    rows = list_tracks_for_day(db_path, day, tracks=tracks)
    bad = [r for r in rows if str(r.get("status") or "") not in ("success", "computed")]
    reasons: List[str] = []
    for r in bad:
        lab = r.get("label") or r.get("track")
        st = r.get("status") or "missing"
        note = str(r.get("notes") or "").strip()
        if st == "missing":
            reasons.append(f"靜默軌 {lab} 尚無成功戳")
        else:
            suffix = f"（{note[:80]}）" if note else ""
            reasons.append(f"靜默軌 {lab} {st}{suffix}")
    return {
        "ok": not bad,
        "as_of": day,
        "tracks": rows,
        "failed": bad,
        "reasons": reasons,
    }


__all__ = [
    "PIPE_PREFIX",
    "TRACK_LABELS",
    "CORE_AFTER_FUSE",
    "pipeline_key",
    "track_label",
    "mark_track",
    "track_status",
    "run_tracked",
    "list_tracks_for_day",
    "failed_or_missing_tracks",
    "needs_rerun",
    "silent_tracks_health",
]
