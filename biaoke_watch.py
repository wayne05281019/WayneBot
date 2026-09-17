# -*- coding: utf-8 -*-
"""捕獲主文／自回後立刻想：他看到什麼才回、下一步盯什麼。

五件脊骨＝波浪／形態／量價／關鍵K／碎形。交叉才寫，不准六顆各貼一句。
擴延只收他自己點過的位（如果句），不發明 5／9，盤中未收不當官方。
路人樓不收。IET＝IET-KY 4971。不是買訊。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_watch (
    post_id TEXT PRIMARY KEY,
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    layer INTEGER NOT NULL DEFAULT 0,
    seen TEXT NOT NULL DEFAULT '',
    because TEXT NOT NULL DEFAULT '',
    nxt TEXT NOT NULL DEFAULT '',
    five TEXT NOT NULL DEFAULT ''
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
_NEXT = (
    (re.compile(r"46626"), "台指期先過46626＝防C-2轉C-3第一步"),
    (re.compile(r"46747|46767"), "穿刺後看是否有效、能否漲開細微波；成功才當短線1"),
    (re.compile(r"47548"), "過不了前高47548才可能再走C波／複式abc"),
    (re.compile(r"45398"), "收盤不破45398才是C-5低點確認"),
    (re.compile(r"不要去追高|絕對不要去追高"), "個股不追高、防逃命波"),
    (re.compile(r"拉回2|支撐區再"), "沒進場的等拉回2或支撐區"),
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
        conn.commit()
    finally:
        conn.close()


def _clip(text: str, n: int = 160) -> str:
    t = _SPACE.sub(" ", str(text or "")).strip()
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def think_spoken(text: str, *, tape_note: str = "") -> Dict[str, str]:
    """一則主文／自回：看到什麼、為何這樣回、下一步盯什麼。沒交叉就不寫死。"""
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
    nxt: List[str] = []
    for pat, line in _NEXT:
        if pat.search(spoken) and line not in nxt:
            nxt.append(line)
    if "有效穿刺" in spoken or ("穿刺" in spoken and "有效" in spoken):
        if not any("有效" in x for x in nxt):
            nxt.append("穿刺後看是否有效、能否漲開細微波；成功才當短線1")
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
    because = ""
    if five:
        because = "×".join(five) + "交叉；"
    because += "他回這句是因為" + _clip(spoken, 72)
    if len(five) < 2 and not nxt:
        # 單件不夠交叉就不裝篤定，仍留下原文觀察
        because = "五件還沒疊滿，不講死；" + _clip(spoken, 72)
    return {
        "seen": _clip("；".join(seen_bits), 180),
        "because": _clip(because, 180),
        "nxt": _clip("；".join(nxt), 180),
        "five": "×".join(five),
    }


def record_watch_events(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """捕獲當下寫觀察／為何／下一步。路人略過。同一則覆蓋。"""
    if not db_path:
        return 0
    ensure_watch_table(db_path)
    rows: List[Tuple[Any, ...]] = []
    tape_by: Dict[str, str] = {}
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            for (pid, note) in conn.execute(
                "SELECT post_id, note FROM biaoke_tape"
            ).fetchall():
                tape_by[str(pid)] = str(note or "")
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    except Exception:
        tape_by = {}
    for ev in events:
        if str(ev.get("kind") or "") == "bystander":
            continue
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        raw = str(ev.get("text") or "").strip()
        if not pid or not raw:
            continue
        thought = think_spoken(raw, tape_note=tape_by.get(pid, ""))
        if not thought:
            continue
        layer = int(ev.get("layer") or 0)
        rows.append(
            (
                pid,
                str(ev.get("date") or ""),
                str(ev.get("time") or ""),
                layer,
                thought["seen"],
                thought["because"],
                thought["nxt"],
                thought["five"],
            )
        )
    if not rows:
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            """
            INSERT INTO biaoke_watch(
                post_id, post_date, post_time, layer, seen, because, nxt, five
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(post_id) DO UPDATE SET
                post_date=excluded.post_date,
                post_time=excluded.post_time,
                layer=excluded.layer,
                seen=excluded.seen,
                because=excluded.because,
                nxt=excluded.nxt,
                five=excluded.five
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def latest_watch_line(db_path: str) -> str:
    """開火巢穴用：最近一則他自己的觀察＋下一步。沒有就空。"""
    if not db_path or not os.path.isfile(db_path):
        return ""
    ensure_watch_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT post_date, post_time, seen, because, nxt, five
            FROM biaoke_watch
            ORDER BY post_date DESC, post_time DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row:
        return ""
    day, hm, seen, because, nxt, five = row
    bits = [f"他自己最新 {day} {hm}".strip()]
    if five:
        bits.append(str(five))
    if seen:
        bits.append("看到：" + str(seen))
    if because:
        bits.append(str(because))
    if nxt:
        bits.append("下一步：" + str(nxt) + "（如果句，未收不當官方）")
    bits.append("不是買訊")
    return _clip("。".join(bits), 280)
