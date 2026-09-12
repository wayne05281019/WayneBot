# -*- coding: utf-8 -*-
"""飆大未讀：定時抓到的新文／樓下自回，未讀前重疊的只留最新，按進去看一口重點。

Telegram 鍵盤不能閃；未讀改寫在按鈕旁「飆大 3」。兩人分開計。
不進海選、不改黃金買點。社團不進。
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
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
        floor = (taipei_now() - timedelta(days=14)).strftime("%Y-%m-%d")
        if last:
            rows = conn.execute(
                """
                SELECT post_id, kind, date, time, text, fetched_at
                FROM biaoke_inbox
                WHERE fetched_at > ?
                ORDER BY date DESC, time DESC, post_id DESC
                """,
                (last,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT post_id, kind, date, time, text, fetched_at
                FROM biaoke_inbox
                ORDER BY date DESC, time DESC, post_id DESC
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        day = str(r[2] or "")
        if day and day < floor:
            continue
        out.append(
            {
                "post_id": r[0],
                "kind": r[1],
                "date": r[2],
                "time": r[3],
                "text": r[4],
                "fetched_at": r[5],
            }
        )
    return out


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


def _oral_body(text: str, limit: int = 280) -> str:
    s = _CHART.sub("（有圖）", text or "")
    s = _SPACE.sub(" ", s).strip()
    n = max(40, int(limit))
    return s if len(s) <= n else s[: n - 1] + "…"


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
    rows.sort(
        key=lambda x: (
            str(x.get("date") or ""),
            str(x.get("time") or ""),
            str(x.get("post_id") or ""),
        ),
        reverse=True,
    )
    bits: List[str] = []
    for ev in rows[:8]:
        body = _oral_body(str(ev.get("text") or ""))
        if not body:
            continue
        day = str(ev.get("date") or "").strip()
        when = str(ev.get("time") or "").strip()
        stamp = " ".join(x for x in (day, when) if x)
        if ev.get("kind") == "reply":
            head = f"他自己樓下補{'（' + stamp + '）' if stamp else ''}："
        else:
            head = f"新發／改寫{'（' + stamp + '）' if stamp else ''}："
        bits.append(head + body)
    if not bits:
        return ""
    blob = "\n\n".join(bits)
    return (
        "今天飆大重點就是：\n\n"
        + html_escape(blob)
        + f"\n\n（以上資料更新至 {clock}）"
    )


_ASK_SKIP = {
    "飆客",
    "飆大",
    "AI飆客",
    "夜盤",
    "大盤",
    "加權",
    "台指期",
    "細微波",
}


def _likely_asks(posts: Sequence[Dict[str, Any]]) -> List[str]:
    asks: List[str] = []
    blob = " ".join(str(p.get("text") or "") for p in posts)
    tags: List[str] = []
    for p in posts:
        tags.extend(str(t) for t in (p.get("tags") or []) if t)
    if "夜盤" in blob or "46506" in blob:
        asks.append("夜盤過了沒")
    if "45839" in blob:
        asks.append("45839有沒有守")
    if "47578" in blob:
        asks.append("47578過了沒")
    if "長線" in blob or "龍頭" in blob:
        asks.append("長線龍頭現在怎麼抱")
    for tag in tags:
        if tag in _ASK_SKIP or tag in asks:
            continue
        if tag.isdigit() and len(tag) == 4:
            continue
        asks.append(tag)
        if len(asks) >= 4:
            break
    if not any("大盤" in a for a in asks):
        asks.insert(0, "大盤現在怎樣")
    out: List[str] = []
    for a in asks:
        if a not in out:
            out.append(a)
        if len(out) >= 4:
            break
    return out


def format_latest_focus(db_path: str = "", *, n_main: int = 2, n_reply: int = 4) -> str:
    """按飆大空白進去：現況推論＋你可能會問的。不倒原文、不念課綱。"""
    try:
        from biaoke_desk import load_corpus
    except Exception:
        return ""
    blob = load_corpus(db_path if db_path else None)
    posts = list((blob or {}).get("posts") or [])
    try:
        from biaoke_ingest import is_biaoke_voice
    except Exception:
        is_biaoke_voice = lambda _t: True  # noqa: E731
    mains = [
        p
        for p in posts
        if (p.get("kind") or "post") != "reply" and is_biaoke_voice(str(p.get("text") or ""))
    ]
    replies = [
        p
        for p in posts
        if p.get("kind") == "reply" and is_biaoke_voice(str(p.get("text") or ""))
    ]
    if not mains:
        return ""
    latest = list(reversed(mains[-max(1, int(n_main)) :]))
    latest_replies = list(reversed(replies[-max(0, int(n_reply)) :])) if n_reply else []
    lines: List[str] = []
    for p in latest:
        body = _oral_body(str(p.get("text") or ""), 96)
        if not body:
            continue
        day = str(p.get("date") or "").strip()
        when = str(p.get("time") or "").strip()
        stamp = " ".join(x for x in (day, when) if x)
        lines.append((stamp + " " + body).strip())
    for p in latest_replies[:2]:
        body = _oral_body(str(p.get("text") or ""), 80)
        if not body:
            continue
        day = str(p.get("date") or "").strip()
        when = str(p.get("time") or "").strip()
        stamp = " ".join(x for x in (day, when) if x)
        lines.append(("樓下 " + stamp + " " + body).strip())
    if not lines:
        return ""
    stamp = " ".join(
        x
        for x in (
            str(latest[0].get("date") or "").strip(),
            str(latest[0].get("time") or "").strip(),
        )
        if x
    )
    blob_l = " ".join(str(p.get("text") or "") for p in latest + latest_replies)
    infer = ""
    if re.search(r"(夜盤|細微波|15\s*分|60\s*分|波浪)", blob_l):
        infer = (
            "這幾則是在看大盤。方向可以準，位階他不講死，要點數再驗。"
            "個股先看產業趨勢，很少用波浪硬套；大盤不穩先想資金，不是等崩了才跑。"
        )
    asks = _likely_asks(latest + latest_replies)
    out = [f"庫 {stamp}。", *lines]
    try:
        from biaoke_chain import fire_chain

        nest = next(
            (
                s
                for s in (fire_chain(db_path, "大盤現在怎麼看").get("steps") or [])
                if s.get("id") == "nest"
            ),
            None,
        )
        if nest and nest.get("ok") and nest.get("text"):
            out.insert(1, "現在大盤巢穴：" + str(nest.get("text") or "")[:240])
    except Exception:
        pass
    if infer:
        out.append(infer)
    if asks:
        out.append("你可能會問：" + "　".join(asks))
    out.append("直接打字或語音。不是買訊。")
    return html_escape("\n\n".join(out))


def take_unread_digest(user_id: str, db_path: str, *, now: Optional[datetime] = None) -> str:
    """讀出未讀彙整。不在這裡標記已讀，等訊息真的送出。"""
    events = unread_events(user_id, db_path)
    if not events:
        return ""
    return format_unread_digest(events, now=now)
