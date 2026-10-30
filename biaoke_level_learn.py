# -*- coding: utf-8 -*-
"""他一說大盤現況位階 → 立刻畫圖落檔 → 靜默準備下一句對質。

成長迴路（不是買訊、不進話筒）：
1. 抓文事件若像「現況浪級／細微／C 段／主跌／橫台位階」→ 渲加權位階圖
2. 寫入 biaoke_level_snaps（post_id／snippet／圖路徑／pending）
3. 下一則位階文或盤後 → 對前一筆 pending（對／偏／還沒走完）
不准發明 5／9；不准改黃金買點；失敗不擋抓文。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.biaoke_level_learn")
TAIPEI = ZoneInfo("Asia/Taipei")

# 現況位階／細微波說話（他講大盤走法時）
_LEVEL_NOW = re.compile(
    r"("
    r"波浪位階|細微波|主跌段|初跌段|末跌段|"
    r"C\s*波|C\d|C3-\d|B\s*波|B-[abc]|"
    r"橫台|中繼站|第[一二三四五1-5]波|第[1-5]小浪|"
    r"1-4\s*重疊|鐵律|破底翻|第二隻腳|第二支腳|"
    r"目前只是|目前是走|現在是走|確認.*發動|準備啟動"
    r")",
    re.I,
)
_INDEXISH = re.compile(r"(大盤|加權|台指|台指期|夜盤|TWII)")

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_level_snaps (
    post_id TEXT NOT NULL PRIMARY KEY,
    as_of TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    chart_path TEXT NOT NULL DEFAULT '',
    pending INTEGER NOT NULL DEFAULT 1,
    verdict TEXT NOT NULL DEFAULT '',
    next_post_id TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_biaoke_level_snaps_pending
    ON biaoke_level_snaps(pending, as_of);
"""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def ensure_tables(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def looks_like_level_now(text: str) -> bool:
    blob = str(text or "")
    if not blob.strip():
        return False
    if not _LEVEL_NOW.search(blob):
        return False
    # 大盤戰場；純個股位階不進這條（個股不發明浪）
    if _INDEXISH.search(blob):
        return True
    # 他有時只寫 C3-3／細微波不帶「大盤」二字，但同串在講台指
    if re.search(r"C3-\d|細微波|波浪位階|主跌段|橫台整理", blob):
        return True
    return False


def _snap_dir(db_path: str) -> str:
    root = os.path.dirname(os.path.abspath(db_path)) or "."
    path = os.path.join(root, "biaoke_level_snaps")
    os.makedirs(path, exist_ok=True)
    return path


def _render_snap(db_path: str, post_id: str, as_of: str) -> str:
    """渲加權位階圖；失敗回空，不准擋抓文。"""
    safe = re.sub(r"[^\w.\-]+", "_", str(post_id or "x"))[:80]
    day = _ymd(as_of) or datetime.now(TAIPEI).strftime("%Y%m%d")
    out = os.path.join(_snap_dir(db_path), f"{day}_{safe}.png")
    try:
        from biaoke_wave import render_twii_degree_png

        path = render_twii_degree_png(db_path, out)
        if path and os.path.isfile(path) and os.path.getsize(path) > 5000:
            return path
    except Exception:
        logger.exception("位階學習圖渲失敗 post=%s", post_id)
    return ""


def _upsert_snap(
    db_path: str,
    *,
    post_id: str,
    as_of: str,
    post_date: str,
    post_time: str,
    snippet: str,
    chart_path: str,
) -> None:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_level_snaps(
                post_id, as_of, post_date, post_time, snippet, chart_path,
                pending, verdict, next_post_id, checked_at, created_at
            ) VALUES (?,?,?,?,?,?,1,'','','',?)
            ON CONFLICT(post_id) DO UPDATE SET
                as_of=excluded.as_of,
                snippet=excluded.snippet,
                chart_path=CASE
                    WHEN excluded.chart_path!='' THEN excluded.chart_path
                    ELSE biaoke_level_snaps.chart_path END,
                pending=1
            """,
            (
                post_id,
                as_of,
                post_date,
                post_time,
                (snippet or "")[:400],
                chart_path or "",
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _pending_rows(db_path: str) -> List[Dict[str, Any]]:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM biaoke_level_snaps WHERE pending=1 "
            "ORDER BY as_of ASC, post_date ASC, post_time ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _mark_verdict(
    db_path: str, post_id: str, verdict: str, next_post_id: str = ""
) -> None:
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "UPDATE biaoke_level_snaps SET pending=0, verdict=?, next_post_id=?, "
            "checked_at=? WHERE post_id=?",
            (verdict, next_post_id or "", _now(), post_id),
        )
        conn.commit()
    finally:
        conn.close()


def _score_against_next(prev_snip: str, next_snip: str) -> str:
    """粗對質：下一句是否延續／改口／打臉。不是買訊。"""
    a = (prev_snip or "").lower()
    b = (next_snip or "").lower()
    if not a or not b:
        return "還沒走完"
    # 改口／重標
    if any(k in b for k in ("重新修訂", "動態修正", "穿刺原規劃", "改口")):
        return "偏"
    # 同向延續
    for k in ("c3-3", "主跌", "橫台", "中繼", "b波", "細微波"):
        if k in a.replace(" ", "") and k in b.replace(" ", ""):
            return "對"
    if ("必破" in a or "會破" in a) and ("已破" in b or "破了" in b or "驗證" in b):
        return "對"
    if ("止跌" in a or "第二隻腳" in a or "第二支腳" in a) and (
        "主跌" in b or "c3-3" in b.replace(" ", "")
    ):
        return "偏"  # 樂觀止跌後接主跌＝打臉／偏
    return "還沒走完"


def verify_pending_with_event(
    db_path: str, next_post_id: str, next_snippet: str
) -> int:
    """新位階文進來：對先前 pending 粗評一輪。"""
    n = 0
    for row in _pending_rows(db_path):
        pid = str(row.get("post_id") or "")
        if not pid or pid == next_post_id:
            continue
        verdict = _score_against_next(str(row.get("snippet") or ""), next_snippet)
        if verdict == "還沒走完":
            continue
        _mark_verdict(db_path, pid, verdict, next_post_id=next_post_id)
        n += 1
    return n


def record_level_learn_from_events(
    db_path: str, events: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """ingest 鉤子：現況位階 → 畫圖＋對前一筆。失敗回空統計。"""
    stats = {"seen": 0, "snaps": 0, "verified": 0}
    if not db_path or not events:
        return stats
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_LEVEL_LEARN_LIVE") != "1":
        return {**stats, "skipped": "pytest"}
    ensure_tables(db_path)
    for ev in events:
        text = str(ev.get("text") or "")
        if not looks_like_level_now(text):
            continue
        stats["seen"] += 1
        post_id = str(ev.get("id") or "").strip()
        if not post_id:
            continue
        post_date = str(ev.get("date") or "").strip()
        post_time = str(ev.get("time") or "").strip()
        as_of = _ymd(post_date) or datetime.now(TAIPEI).strftime("%Y%m%d")
        snippet = re.sub(r"\s+", " ", text).strip()[:400]
        # 先用新文對舊 pending
        try:
            stats["verified"] += int(
                verify_pending_with_event(db_path, post_id, snippet) or 0
            )
        except Exception:
            logger.exception("位階學習對前筆失敗")
        # 再畫本則
        chart = ""
        try:
            chart = _render_snap(db_path, post_id, as_of)
        except Exception:
            logger.exception("位階學習渲圖略過")
        try:
            _upsert_snap(
                db_path,
                post_id=post_id,
                as_of=as_of,
                post_date=post_date,
                post_time=post_time,
                snippet=snippet,
                chart_path=chart,
            )
            if chart:
                stats["snaps"] += 1
        except Exception:
            logger.exception("位階學習落檔失敗")
    return stats
