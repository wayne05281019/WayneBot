# -*- coding: utf-8 -*-
"""飆大未讀：定時抓到的新文／樓下自回，未讀前重疊的只留最新，按進去看一口重點。

Telegram 鍵盤不能閃；未讀改寫在按鈕旁「飆大 3」。兩人分開計。
不進海選、不改黃金買點。社團不進。
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
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


def unread_events(
    user_id: str, db_path: str, *, now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
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
        clock = now or taipei_now()
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=TAIPEI)
        floor = (clock.astimezone(TAIPEI) - timedelta(days=14)).strftime("%Y-%m-%d")
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


_NOISE = re.compile(
    r"(打錯|很有心|出書|90%\s*老師|碩哥和我|蕭明道|楊少凱)"
)
_BOARD = re.compile(r"(夜盤|47578|C\s*波|頭部型態|大盤要漲|前波高點|加權|逃命|45398)")
_FIELD = re.compile(r"(ASIC|散熱|光通訊|記憶體|多頭格局的族群)")
_PCB = re.compile(r"(PCB|台光電|金像電|台燿|富喬|金居|ABF)")
_PREVIEW = re.compile(r"(星期[日天]晚上|技術分析看法)")
_NOISE_ONLY = re.compile(r"(出書|90%\s*老師|我自己都沒|說實話|看盤當下寫|很有心)")


def _speak(text: str, limit: int = 220) -> str:
    """口語重述：像當面講一遍，重點留著，不倒時間牆、不砍條件句。"""
    s = _CHART.sub("（有圖）", text or "")
    s = _SPACE.sub(" ", s).strip()
    s = s.replace("2024/10~2025/02", "2024年10月到2025年2月")
    s = s.replace("2024/10～2025/02", "2024年10月到2025年2月")
    s = re.sub(r"我這周末比較忙", "這周末比較忙", s)
    s = re.sub(r"星期[日天]晚上我發一篇", "星期天晚上會發一篇", s)
    s = re.sub(r"^從夜盤反彈", "夜盤已經彈", s)
    s = re.sub(r"不過這次大盤要漲到目標點位一定要過", "不過要漲到他講的目標，一定要過", s)
    s = re.sub(r"目前唯一在多頭格局的族群就是", "現在唯一還在多頭的是", s)
    s = re.sub(
        r"因為現在追蹤我的人數過多，我已經無法像以前那樣公開點名",
        "追的人太多就不再公開點名",
        s,
    )
    s = re.sub(r"未來不是再一次出現這一次大修正，或者走", "後面不是再來一次大修正，就是走出", s)
    s = re.sub(r"做一個大的頭部型態出來", "那種大頭部", s)
    s = _SPACE.sub(" ", s).strip()
    s = re.sub(r"^我+", "", s)
    parts = [p.strip(" ，、") for p in re.split(r"[。！？；]", s) if p.strip()]
    keep: List[str] = []
    for p in parts:
        if _NOISE_ONLY.search(p) and not re.search(r"(47578|ASIC|PCB|台光電|夜盤|頭部)", p):
            continue
        if len(p) < 6:
            continue
        keep.append(p)
        if len(keep) >= 4:
            break
    out = "。".join(keep)
    if out and not out.endswith("。"):
        out += "。"
    return _oral_body(out or s, limit)


def _when_short(date: str, time_s: str) -> str:
    d = str(date or "").strip()
    t = str(time_s or "").strip()
    day = d
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", d)
    if m:
        day = f"{int(m.group(2))}/{int(m.group(3))}"
    if not t:
        return day
    try:
        h = int(t[:2])
    except ValueError:
        h = -1
    if h >= 18:
        tod = "晚上"
    elif h >= 12:
        tod = "下午"
    elif h >= 5:
        tod = "早上"
    elif h >= 0:
        tod = "凌晨"
    else:
        tod = ""
    clock = t[:5] if len(t) >= 5 else t
    bits = [x for x in (day, tod, clock) if x]
    return " ".join(bits)


def _row_key(p: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(p.get("date") or ""),
        str(p.get("time") or ""),
        str(p.get("post_id") or p.get("id") or ""),
    )


def _noise_reply(text: str) -> bool:
    s = _SPACE.sub(" ", text or "").strip()
    if len(s) < 6:
        return True
    if _NOISE.search(s) and not re.search(r"(PCB|台光電|夜盤|47578|ASIC|整理|錯殺)", s):
        return True
    return False


def _numbered_bits(text: str) -> List[str]:
    raw = _SPACE.sub(" ", text or "").strip()
    raw = re.sub(r"^重要留言看法分享\s*", "", raw)
    parts = re.split(r"(?:^|\s)\d+\.\s+", raw)
    bits = [p.strip().rstrip("。") for p in parts if p and len(p.strip()) >= 12]
    if len(bits) >= 2:
        return bits
    return [raw] if raw else []


def format_focus_oral(
    mains: Sequence[Dict[str, Any]],
    replies: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> str:
    """空白按飆大：口語重述最新重點。不准倒原文、不准時間跳來跳去。"""
    mains = [dict(p) for p in mains if str(p.get("text") or "").strip()]
    if not mains:
        return ""
    mains = sorted(mains, key=_row_key, reverse=True)
    replies = [
        dict(p)
        for p in replies
        if str(p.get("text") or "").strip() and not _noise_reply(str(p.get("text") or ""))
    ]
    replies = sorted(replies, key=_row_key, reverse=True)
    latest = mains[0]
    when_p = latest
    if replies and _row_key(replies[0]) > _row_key(latest):
        when_p = replies[0]
    when = _when_short(str(when_p.get("date") or ""), str(when_p.get("time") or ""))
    board = ""
    field = ""
    pcb = ""
    preview = ""
    spare: List[str] = []
    extra: List[str] = []
    older_long = False
    newer_short = False
    for bit in _numbered_bits(str(latest.get("text") or "")):
        if not board and _BOARD.search(bit):
            board = _speak(bit, 260)
        elif not field and _FIELD.search(bit):
            field = _speak(bit, 140)
        elif not pcb and _PCB.search(bit):
            pcb = _speak(bit, 140)
        else:
            spare.append(_speak(bit, 140))
    for p in mains[1:]:
        t = str(p.get("text") or "")
        if re.search(r"整理三個月|全面減碼", t):
            older_long = True
        if not board and _BOARD.search(t):
            board = _speak(t, 200)
        if not field and _FIELD.search(t):
            field = _speak(t, 120)
    latest_day = str(latest.get("date") or "")
    for p in replies:
        t = str(p.get("text") or "")
        if _PREVIEW.search(t) and not preview:
            preview = _speak(t, 140)
            continue
        if re.search(r"比ABF短|錯殺", t):
            newer_short = True
            pcb = _speak(t, 140)
            continue
        if not pcb and _PCB.search(t):
            pcb = _speak(t, 140)
            continue
        day = str(p.get("date") or "")
        if day and latest_day and day < latest_day:
            continue
        extra.append(_speak(t, 100))
    if older_long and newer_short:
        pcb = (
            "前一天還說台光電至少整理三個月、PCB 全面減碼；"
            "晚上改口，整理時間會比 ABF 短很多，昨天錯殺居多，下波可能還是漲的主流。"
        )
    if not board:
        board = _speak(str(latest.get("text") or ""), 260)
    latest_t = str(latest.get("text") or "")
    if board and re.search(r"(否則|如果|一定要過)", board + latest_t) and "如果句" not in board:
        board = board.rstrip("。") + "。這句還是如果句，不是已確認主升。"
    said = " ".join(
        x.rstrip("。") + "。"
        for x in ([preview] + spare[:1] + extra[:2])
        if x
    ).strip()
    blocks: List[str] = [
        "<b>飆大現在在講</b>",
        html_escape(f"最新　{when}" if when else "最新"),
    ]

    def _add(title: str, body: str) -> None:
        if not body:
            return
        blocks.append("")
        blocks.append(f"<b>{html_escape(title)}</b>")
        blocks.append(html_escape(body))

    _add("大盤", board)
    _add("族群", field)
    _add("PCB", pcb)
    _add("他還說", said)
    asks = _likely_asks(list(mains[:2]) + replies[:8])
    if asks:
        blocks.append("")
        blocks.append("<b>還能問</b>")
        blocks.extend(html_escape(a) for a in asks[:3])
    clock = ""
    if now is not None:
        dt = now if now.tzinfo else now.replace(tzinfo=TAIPEI)
        clock = dt.astimezone(TAIPEI).strftime("%H:%M")
    tail = "直接打字或語音。"
    if clock:
        tail = f"看到這裡是 {clock}。{tail}"
    blocks.append("")
    blocks.append(html_escape(tail))
    return "\n".join(blocks)


def format_unread_digest(
    events: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> str:
    """未讀期間同一篇抓很多次，只留最新再口語重述。按飆大才看。"""
    uniq: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        pid = str(ev.get("post_id") or "")
        if pid:
            uniq[pid] = dict(ev)
    rows = list(uniq.values())
    mains = [
        r
        for r in rows
        if str(r.get("kind") or "post") not in ("reply", "bystander")
    ]
    replies = [r for r in rows if str(r.get("kind") or "") == "reply"]
    if not mains and replies:
        mains = [replies[0]]
        replies = replies[1:]
    if not mains:
        return ""
    return format_focus_oral(mains, replies, now=now)


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
    if "逃命波" in blob or "C-2" in blob:
        asks.insert(0, "現在是逃命波嗎")
    if "夜盤" in blob or "46506" in blob:
        asks.append("夜盤過了沒")
    if "波浪" in blob or "位階" in blob or "細微波" in blob or "右肩" in blob:
        asks.insert(0, "現在波浪位階")
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


def format_latest_focus(db_path: str = "", *, n_main: int = 2, n_reply: int = 16) -> str:
    """按飆大空白進去：口語重述最新重點。不准倒原文、不念課綱、不疊舊位階。"""
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
        if (p.get("kind") or "post") not in ("reply", "bystander")
        and is_biaoke_voice(str(p.get("text") or ""))
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
    return format_focus_oral(latest, latest_replies, now=taipei_now())


def take_unread_digest(user_id: str, db_path: str, *, now: Optional[datetime] = None) -> str:
    """讀出未讀彙整。不在這裡標記已讀，等訊息真的送出。"""
    events = unread_events(user_id, db_path, now=now)
    if not events:
        return ""
    return format_unread_digest(events, now=now)
