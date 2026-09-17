# -*- coding: utf-8 -*-
"""捕獲主文／自回後立刻想：條件更新、改口、還在等哪個他自己的位。

五件脊骨＝波浪／形態／量價／關鍵K／碎形。要疊在同一個他點過的位才寫。
想＝只更新他點過的條件；說＝可講還在等、未收不下判。不准新價、不准演浪。
路人樓不收。IET＝IET-KY 4971。不是買訊。
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_watch (
    post_id TEXT PRIMARY KEY,
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    layer INTEGER NOT NULL DEFAULT 0,
    seen TEXT NOT NULL DEFAULT '',
    because TEXT NOT NULL DEFAULT '',
    nxt TEXT NOT NULL DEFAULT '',
    five TEXT NOT NULL DEFAULT '',
    prior TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_biaoke_watch_dt
    ON biaoke_watch(post_date, post_time);
"""
_SPACE = re.compile(r"\s+")
_WAVE = re.compile(
    r"(C\s*波|C-[1235]|逃命波|細微波|主升段|複式\s*abc|短線回升就是\s*1|"
    r"C-2\s*轉\s*C-3|位階)"
)
_SHAPE = re.compile(r"(洗盤|吸籌|反彈|假突破|頭肩|整理|築底)")
_TAPE = re.compile(r"(量|吸籌|漲\s*1000|支撐區|先看量)")
_KEYK = re.compile(r"(穿刺|有效|轉折K|破線|站回|關鍵K)")
_FRAC = re.compile(r"(碎形|細微波|只能上不能下)")
_LATE = "2025-01-01"  # 後期思考權重大於 2023–2024
_NUM = re.compile(r"(?<![\d.])(\d{4,5})(?![\d])")
_HINT = re.compile(r"(C\s*波|C-[1235]|逃命波|細微波|洗盤|穿刺|45398|46626|46747|46767|47548|43500)")
_POINTED = (
    "47548",
    "46747",
    "46767",
    "46626",
    "45398",
    "43500",
    "45839",
    "46506",
    "48218",
)
_NEXT = (
    (re.compile(r"46626"), "如果台指期先過他自己點的46626＝防C-2轉C-3第一步"),
    (re.compile(r"46747|46767"), "如果穿刺有效、漲開細微波；成功才當短線1"),
    (re.compile(r"47548"), "如果過不了前高47548才可能再走C波／複式abc"),
    (re.compile(r"45398"), "如果收盤不破45398才是C-5低點確認"),
    (re.compile(r"不要去追高|絕對不要去追高"), "個股不追高、防逃命波"),
    (re.compile(r"拉回2|支撐區再"), "沒進場的等他自己說的拉回2或支撐區"),
)


def ensure_watch_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(biaoke_watch)").fetchall()}
        if "prior" not in cols:
            conn.execute("ALTER TABLE biaoke_watch ADD COLUMN prior TEXT NOT NULL DEFAULT ''")
        conn.commit()
    finally:
        conn.close()


def _clip(text: str, n: int = 160) -> str:
    t = _SPACE.sub(" ", str(text or "")).strip()
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _pointed_in(spoken: str) -> List[str]:
    out: List[str] = []
    blob = spoken or ""
    for p in _POINTED:
        if p in blob and p not in out:
            out.append(p)
    return out


def _unclosed(spoken: str, tape_note: str = "") -> bool:
    blob = (spoken or "") + " " + (tape_note or "")
    return any(x in blob for x in ("未收", "夜盤", "盤中", "還沒收"))


def _stance(text: str) -> str:
    t = (text or "").replace(" ", "")
    if "暫時化解C波" in t or "暫化解C波" in t or "暫時化解" in t:
        return "c_ease"
    if "C波" in t or "C-2" in t or "C-3" in t or "逃命波" in t:
        return "c_risk"
    return ""


def think_spoken(text: str, *, tape_note: str = "", prior: str = "") -> Dict[str, str]:
    """一則主文／自回：條件更新、改口、還在等哪個他自己的位。不准新價。"""
    spoken = _SPACE.sub(" ", str(text or "")).strip()
    if not spoken:
        return {}
    five: List[str] = []
    if _WAVE.search(spoken):
        five.append("波浪")
    if _SHAPE.search(spoken):
        five.append("形態")
    if _TAPE.search(spoken):
        five.append("量價")
    if _KEYK.search(spoken):
        five.append("關鍵K")
    if _FRAC.search(spoken):
        five.append("碎形")
    pointed = _pointed_in(spoken)
    nxt: List[str] = []
    if _unclosed(spoken, tape_note):
        if pointed:
            nxt.append(
                "他還在等自己點過的"
                + "／".join(pointed[:3])
                + "；官方還沒收，所以不下判"
            )
        else:
            nxt.append("官方還沒收，所以不下判")
    for pat, line in _NEXT:
        if pat.search(spoken) and line not in nxt:
            nxt.append(line)
    if "有效穿刺" in spoken or ("穿刺" in spoken and "有效" in spoken):
        if not any("有效" in x for x in nxt):
            nxt.append("如果穿刺有效、漲開細微波；成功才當短線1")
    seen_bits: List[str] = []
    note = _clip(tape_note, 80)
    if note:
        seen_bits.append(note)
    if "夜盤已經反彈超過" in spoken or "夜盤已經反彈" in spoken:
        seen_bits.append("他看到夜盤反彈幅度（盤中／夜盤未收不當日K官方）")
    if "穿刺" in spoken:
        seen_bits.append("他看到台指期穿刺他自己點的位（未收不當官方）")
    if "震幅非常大" in spoken or "激烈震幅" in spoken:
        seen_bits.append("他看到夜盤／美股震幅大，先當反彈不是主升")
    if not seen_bits:
        seen_bits.append("以他自己這句為觀察，尚未對上新官方收")
    st_now, st_old = _stance(spoken), _stance(prior)
    if st_now and st_old and st_now != st_old:
        because = "改口：條件仍是他自己點過的位，只更新機率；" + _clip(spoken, 64)
    elif len(five) >= 2 and pointed:
        because = (
            "×".join(five)
            + "疊在他點過的"
            + pointed[0]
            + "；他回這句是因為"
            + _clip(spoken, 56)
        )
    else:
        because = "五件還沒疊在同一個他點過的位，不講死；" + _clip(spoken, 72)
    return {
        "seen": _clip("；".join(seen_bits), 180),
        "because": _clip(because, 180),
        "nxt": _clip("；".join(nxt), 180),
        "five": "×".join(five),
    }


def lookback_prior(
    conn: sqlite3.Connection, spoken: str, day: str, hm: str
) -> str:
    """同一條判斷的先前句。2025–2026 優先；早年只當方法、不蓋後期。"""
    tokens: List[str] = []
    for n in _NUM.findall(spoken or ""):
        if n not in tokens:
            tokens.append(n)
    for m in _HINT.findall(spoken or ""):
        t = str(m).replace(" ", "")
        if t and t not in tokens:
            tokens.append(t)
    if not tokens:
        return ""
    keys = tokens[:4]
    where = " OR ".join(["ifnull(text,'') LIKE ?" for _ in keys])
    day = str(day or "")
    hm = str(hm or "")
    try:
        row = conn.execute(
            f"""
            SELECT date, time, substr(replace(ifnull(text,''), char(10), ' '), 1, 72)
            FROM biaoke_posts
            WHERE ifnull(kind,'post') != 'bystander'
              AND (date < ? OR (date = ? AND ifnull(time,'') < ?))
              AND ({where})
            ORDER BY CASE WHEN date >= ? THEN 0 ELSE 1 END, date DESC, time DESC
            LIMIT 1
            """,
            [day, day, hm] + [f"%{k}%" for k in keys] + [_LATE],
        ).fetchone()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    d, t, snip = row
    era = "後期" if str(d or "") >= _LATE else "早年方法、後期五件為準"
    return _clip(f"{era} {d} {t} 先想到：{snip}", 160)


def record_watch_events(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """捕獲當下寫觀察／為何／下一步。路人略過。同一則覆蓋。"""
    if not db_path:
        return 0
    ensure_watch_table(db_path)
    pending: List[Dict[str, Any]] = []
    ids: List[str] = []
    for ev in events:
        if str(ev.get("kind") or "") == "bystander":
            continue
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        raw = str(ev.get("text") or "").strip()
        if not pid or not raw:
            continue
        ids.append(pid)
        pending.append(ev)
    if not pending:
        return 0
    tape_by: Dict[str, str] = {}
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        if ids:
            q = ",".join("?" * len(ids))
            try:
                for pid, note in conn.execute(
                    f"SELECT post_id, note FROM biaoke_tape WHERE post_id IN ({q})",
                    ids,
                ):
                    tape_by[str(pid)] = str(note or "")
            except sqlite3.Error:
                tape_by = {}
        rows: List[Tuple[Any, ...]] = []
        for ev in pending:
            pid = str(ev.get("id") or ev.get("post_id") or "").strip()
            raw = str(ev.get("text") or "").strip()
            prior = lookback_prior(
                conn, raw, str(ev.get("date") or ""), str(ev.get("time") or "")
            )
            thought = think_spoken(
                raw, tape_note=tape_by.get(pid, ""), prior=prior
            )
            if not thought:
                continue
            rows.append(
                (
                    pid,
                    str(ev.get("date") or ""),
                    str(ev.get("time") or ""),
                    int(ev.get("layer") or 0),
                    thought["seen"],
                    thought["because"],
                    thought["nxt"],
                    thought["five"],
                    prior,
                )
            )
        if not rows:
            return 0
        conn.executemany(
            """
            INSERT INTO biaoke_watch(
                post_id, post_date, post_time, layer, seen, because, nxt, five, prior
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(post_id) DO UPDATE SET
                post_date=excluded.post_date,
                post_time=excluded.post_time,
                layer=excluded.layer,
                seen=excluded.seen,
                because=excluded.because,
                nxt=excluded.nxt,
                five=excluded.five,
                prior=excluded.prior
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _bar_is_official_close(ymd: str, *, now: Optional[datetime] = None) -> bool:
    """只有已收的官方日K才對質。當天 13:30 前那根不算官方收。"""
    day = str(ymd or "").replace("-", "")[:8]
    if len(day) != 8 or not day.isdigit():
        return False
    stamp = now or datetime.now(ZoneInfo("Asia/Taipei"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    else:
        stamp = stamp.astimezone(ZoneInfo("Asia/Taipei"))
    today = stamp.strftime("%Y%m%d")
    if day < today:
        return True
    if day > today:
        return False
    return (stamp.hour, stamp.minute) >= (13, 30)


def _he_pointed_escape(conn: sqlite3.Connection) -> bool:
    """逃命／43500 是他點過的位，不看最新一則有沒有再講。"""
    blob = (
        "ifnull(seen,'')||ifnull(because,'')||ifnull(nxt,'')||ifnull(prior,'')"
    )
    queries = (
        f"SELECT 1 FROM biaoke_watch WHERE instr({blob},'43500') OR instr({blob},'逃命') LIMIT 1",
        """
        SELECT 1 FROM biaoke_posts
        WHERE ifnull(kind,'post') != 'bystander'
          AND (instr(ifnull(text,''),'43500') OR instr(ifnull(text,''),'逃命'))
        LIMIT 1
        """,
    )
    for sql in queries:
        try:
            if conn.execute(sql).fetchone():
                return True
        except sqlite3.Error:
            continue
    return False


def _escape_crash_line(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None
) -> str:
    """他點過逃命／43500 才對官方收。後續自回不准蓋掉；未收不下判；不喊崩。"""
    if not _he_pointed_escape(conn):
        return ""
    try:
        bars = conn.execute(
            """
            SELECT date, close FROM index_daily
            WHERE symbol IN ('TWII','^TWII') AND close IS NOT NULL
            ORDER BY date DESC LIMIT 4
            """
        ).fetchall()
    except sqlite3.Error:
        return ""
    ymd = ""
    cl: Any = None
    for raw_d, raw_c in bars:
        day = str(raw_d or "").replace("-", "")[:8]
        if _bar_is_official_close(day, now=now):
            ymd, cl = day, raw_c
            break
    if not ymd:
        return ""
    try:
        c = float(cl)
    except (TypeError, ValueError):
        return ""
    if c > 43500:
        return (
            f"官方收 {ymd} {c:.0f} 還在他自己點的43500之上，"
            "逃命／C波預告還沒走到（看錯抽屜，不是喊崩）"
        )
    return (
        f"官方收 {ymd} {c:.0f} 已低於他自己點的43500，"
        "對質偏（看錯抽屜，不是喊崩）"
    )


def latest_watch_line(
    db_path: str, *, now: Optional[datetime] = None
) -> str:
    """開火用：最近觀察＋他沒再回＝還在等。逃命／43500 只對官方收，不喊崩。"""
    if not db_path or not os.path.isfile(db_path):
        return ""
    ensure_watch_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT post_date, post_time, seen, because, nxt, five, prior
            FROM biaoke_watch
            ORDER BY post_date DESC, post_time DESC
            LIMIT 1
            """
        ).fetchone()
        crash = _escape_crash_line(conn, now=now) if row else ""
    except sqlite3.Error:
        row = None
        crash = ""
    finally:
        conn.close()
    if not row:
        return ""
    day, hm, seen, because, nxt, five, prior = (list(row) + [""])[:7]
    bits = [f"他自己最新 {day} {hm}".strip()]
    bits.append("這段沒再回＝還在等自己點過的位，不是沒想法")
    if crash:
        bits.append(crash)
    if five:
        bits.append(str(five))
    if prior:
        bits.append(str(prior))
    if seen:
        bits.append("看到：" + str(seen))
    if because:
        bits.append(str(because))
    if nxt:
        wait = "不下判" in str(nxt) or "還沒收" in str(nxt) or "未收" in str(seen)
        label = "等待：" if wait else "如果："
        bits.append(label + str(nxt))
    bits.append("不是買訊")
    return _clip("。".join(bits), 360)
