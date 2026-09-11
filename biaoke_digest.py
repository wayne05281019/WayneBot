# -*- coding: utf-8 -*-
"""飆大未讀：定時抓到的新文／樓下自回，未讀前重疊的只留最新，按進去看一口重點。

Telegram 鍵盤不能閃；未讀改寫在按鈕旁「飆大 3」。兩人分開計。
不進海選、不改黃金買點。社團不進。
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from tg_layout import html_escape

TAIPEI = ZoneInfo("Asia/Taipei")
_BTN = "飆大"
_CHART = re.compile(r"https://image\.cmoney\.tw/attachment/\S+", re.I)
_SPACE = re.compile(r"\s+")

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_inbox (
    post_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'post',
    date TEXT NOT NULL DEFAULT '',
    time TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS biaoke_reader (
    user_id TEXT PRIMARY KEY,
    last_read_at TEXT NOT NULL DEFAULT ''
);
"""


def taipei_now() -> datetime:
    return datetime.now(TAIPEI)


def _iso(now: Optional[datetime] = None) -> str:
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def ensure_biaoke_digest_tables(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def record_ingest_events(
    db_path: str,
    events: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> int:
    """同一篇只留最新正文。沒改到的不寫，才不會把舊文當成未讀。"""
    if not db_path or not events:
        return 0
    ensure_biaoke_digest_tables(db_path)
    stamp = _iso(now)
    n = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for ev in events:
            pid = str(ev.get("post_id") or ev.get("id") or "").strip()
            text = str(ev.get("text") or "").strip()
            if not pid or not text:
                continue
            kind = str(ev.get("kind") or "post")
            date = str(ev.get("date") or "")
            time_s = str(ev.get("time") or "")
            body = text[:4000]
            prev = conn.execute(
                "SELECT text, kind, date, time FROM biaoke_inbox WHERE post_id=?",
                (pid,),
            ).fetchone()
            if prev and (
                str(prev[0] or "") == body
                and str(prev[1] or "") == kind
                and str(prev[2] or "") == date
                and str(prev[3] or "") == time_s
            ):
                continue
            conn.execute(
                """
                INSERT INTO biaoke_inbox(post_id, kind, date, time, text, fetched_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(post_id) DO UPDATE SET
                    kind=excluded.kind,
                    date=excluded.date,
                    time=excluded.time,
                    text=excluded.text,
                    fetched_at=excluded.fetched_at
                """,
                (pid, kind, date, time_s, body, stamp),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def unread_events(user_id: str, db_path: str) -> List[Dict[str, Any]]:
    uid = str(user_id or "").strip()
    if not uid or not db_path:
        return []
    ensure_biaoke_digest_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT last_read_at FROM biaoke_reader WHERE user_id=?",
            (uid,),
        ).fetchone()
        last = str(row[0] or "") if row else ""
        if last:
            rows = conn.execute(
                """
                SELECT post_id, kind, date, time, text, fetched_at
                FROM biaoke_inbox
                WHERE fetched_at > ?
                ORDER BY fetched_at ASC, date, time, post_id
                """,
                (last,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT post_id, kind, date, time, text, fetched_at
                FROM biaoke_inbox
                ORDER BY fetched_at ASC, date, time, post_id
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [
        {
            "post_id": r[0],
            "kind": r[1],
            "date": r[2],
            "time": r[3],
            "text": r[4],
            "fetched_at": r[5],
        }
        for r in rows
    ]


def unread_count(user_id: str, db_path: str) -> int:
    return len(unread_events(user_id, db_path))


def mark_biaoke_read(user_id: str, db_path: str, *, now: Optional[datetime] = None) -> None:
    uid = str(user_id or "").strip()
    if not uid or not db_path:
        return
    ensure_biaoke_digest_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_reader(user_id, last_read_at) VALUES (?,?)
            ON CONFLICT(user_id) DO UPDATE SET last_read_at=excluded.last_read_at
            """,
            (uid, _iso(now)),
        )
        conn.commit()
    finally:
        conn.close()


def biaoke_button_label(user_id: str, db_path: str) -> str:
    """Telegram 鍵盤不能閃；未讀寫在兩個字後面。"""
    n = unread_count(user_id, db_path) if user_id else 0
    if n <= 0:
        return _BTN
    return f"{_BTN} {n}"


def normalize_biaoke_button(text: str) -> str:
    t = str(text or "").strip()
    if t == _BTN or t.startswith(_BTN + " ") or t.startswith(_BTN + "·"):
        rest = t[len(_BTN) :].strip(" ·")
        if not rest or rest.isdigit():
            return _BTN
    return t


def _oral_body(text: str) -> str:
    s = _CHART.sub("（有圖）", text or "")
    s = _SPACE.sub(" ", s).strip()
    return s if len(s) <= 280 else s[:279] + "…"


def format_unread_digest(
    events: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> str:
    """未讀期間同一篇抓很多次，這裡只留最新再口語化。"""
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    clock = dt.astimezone(TAIPEI).strftime("%H:%M")
    uniq: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        pid = str(ev.get("post_id") or "")
        if pid:
            uniq[pid] = dict(ev)
    rows = list(uniq.values())
    rows.sort(key=lambda x: (str(x.get("date") or ""), str(x.get("time") or ""), str(x.get("post_id") or "")))
    bits: List[str] = []
    for ev in rows[:8]:
        body = _oral_body(str(ev.get("text") or ""))
        if not body:
            continue
        when = str(ev.get("time") or "").strip()
        if ev.get("kind") == "reply":
            head = f"他自己樓下補{'（' + when + '）' if when else ''}："
        else:
            head = f"新發／改寫{'（' + when + '）' if when else ''}："
        bits.append(head + body)
    if not bits:
        return ""
    blob = "\n\n".join(bits)
    return (
        "今天飆大重點就是：\n\n"
        + html_escape(blob)
        + f"\n\n（以上資料更新至 {clock}）"
    )


def take_unread_digest(user_id: str, db_path: str, *, now: Optional[datetime] = None) -> str:
    """讀出未讀彙整。不在這裡標記已讀，等訊息真的送出。"""
    events = unread_events(user_id, db_path)
    if not events:
        return ""
    return format_unread_digest(events, now=now)
