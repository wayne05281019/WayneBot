# -*- coding: utf-8 -*-
"""洞燭先機每日落檔與隔日官方收對質。

不必等人按鈕。盤後齊了就暫存當日推薦＋判斷依據，下一根官方收再對／偏／還沒走完。
不准發明收盤、不准改黃金買點。進化＝留下可量化的對質，不是另開買訊。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(val: Any) -> Optional[float]:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def ensure_dongzhu_tape_tables(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_run (
                as_of TEXT PRIMARY KEY,
                field TEXT DEFAULT '',
                pre_sign TEXT DEFAULT '',
                share_last REAL DEFAULT 0,
                buy_n INTEGER DEFAULT 0,
                watch_n INTEGER DEFAULT 0,
                capture_n INTEGER DEFAULT 0,
                ran_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_tape (
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                name TEXT DEFAULT '',
                field TEXT DEFAULT '',
                role TEXT DEFAULT '',
                close REAL,
                vs20 REAL,
                vs60 REAL,
                volr REAL,
                why TEXT DEFAULT '',
                PRIMARY KEY (as_of, sid, tag)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_score (
                as_of TEXT NOT NULL,
                check_as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                pick_close REAL,
                now_close REAL,
                fwd_pct REAL,
                vs20_then REAL,
                vs20_now REAL,
                verdict TEXT NOT NULL,
                note TEXT DEFAULT '',
                PRIMARY KEY (as_of, check_as_of, sid, tag)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_rates (
                tag TEXT PRIMARY KEY,
                n INTEGER DEFAULT 0,
                hit INTEGER DEFAULT 0,
                miss INTEGER DEFAULT 0,
                pending INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _why(tag: str, item: Dict[str, Any], field: str, pre_sign: str) -> str:
    vs = _f(item.get("vs20"))
    vs_s = f"距20高 {vs:+.1f}%" if vs is not None else ""
    bits = []
    if tag == "leave_zero":
        bits.append("黃金買點獲利剛離零")
    elif tag == "golden_buy":
        bits.append("60低超跌觀察不是買")
    else:
        bits.append("同鏈比價落後不是買訊")
    if field:
        bits.append(str(field))
    if pre_sign == "pre":
        bits.append("佔比升還沒第一")
    elif pre_sign == "chase":
        bits.append("已是當天第一偏晚")
    elif pre_sign == "leaving":
        bits.append("佔比在退")
    if vs_s:
        bits.append(vs_s)
    return "；".join(bits)


def _iter_pick_rows(data: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    seen = set()
    for tag, key in (
        ("leave_zero", "buys"),
        ("golden_buy", "watches"),
        ("capture", "laggards"),
    ):
        for item in list(data.get(key) or []):
            sid = str(item.get("sid") or "").strip()
            if not sid or (sid, tag) in seen:
                continue
            close = _f(item.get("close") or item.get("pick_close"))
            if close is None or close <= 0:
                continue
            seen.add((sid, tag))
            out.append((tag, item))
    return out


def write_snapshot(db_path: str, data: Dict[str, Any]) -> int:
    """把當日洞燭名單寫進庫。沒官方收盤的不上。"""
    if not db_path or not isinstance(data, dict):
        return 0
    cap = _ymd(data.get("cap") or data.get("chip_cap"))
    if not cap:
        return 0
    ensure_dongzhu_tape_tables(db_path)
    field = str(data.get("field") or "")
    pre_sign = str(data.get("pre_sign") or "")
    share_last = _f((data.get("flow") or {}).get("share_last")) or 0.0
    rows = _iter_pick_rows(data)
    buy_n = sum(1 for t, _ in rows if t == "leave_zero")
    watch_n = sum(1 for t, _ in rows if t == "golden_buy")
    cap_n = sum(1 for t, _ in rows if t == "capture")
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO dongzhu_pick_run(
                as_of, field, pre_sign, share_last, buy_n, watch_n, capture_n, ran_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (cap, field, pre_sign, share_last, buy_n, watch_n, cap_n, _now_iso()),
        )
        conn.execute("DELETE FROM dongzhu_pick_tape WHERE as_of=?", (cap,))
        for tag, item in rows:
            sid = str(item.get("sid") or "").strip()
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_tape(
                    as_of, sid, tag, name, field, role, close, vs20, vs60, volr, why
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cap,
                    sid,
                    tag,
                    str(item.get("name") or sid),
                    field,
                    str(item.get("role") or ""),
                    _f(item.get("close") or item.get("pick_close")),
                    _f(item.get("vs20")),
                    _f(item.get("vs60")),
                    _f(item.get("volr")),
                    _why(tag, item, field, pre_sign),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def snapshot_dongzhu_picks(db_path: str, cap: str = "", *, spoken: str = "") -> int:
    """盤後自動跑，不等人按洞燭鈕。spoken 空＝機制名單，不被當下問句帶跑。"""
    if not db_path:
        return 0
    from biaoke_field_scan import _cap, dongzhu_picks

    data = dongzhu_picks(db_path, spoken=spoken)
    if cap:
        data["cap"] = _ymd(cap) or data.get("cap")
    elif not _ymd(data.get("cap")):
        data["cap"] = _cap(db_path)
    return write_snapshot(db_path, data)


def _verdict(tag: str, fwd: Optional[float], vs_delta: Optional[float]) -> Tuple[str, str]:
    """對／偏／還沒走完。只用官方收與當時 vs20，不 invent。"""
    if tag == "capture":
        if vs_delta is not None and vs_delta > 1.0:
            return "對", "距20高拉近＝補漲方向"
        if vs_delta is not None and vs_delta < -1.0:
            return "偏", "距20高更深"
        return "還沒走完", "補漲還沒走完"
    if fwd is None:
        return "還沒走完", "還沒官方收"
    if fwd > 0.5:
        return "對", f"收 {fwd:+.1f}%"
    if fwd < -0.5:
        return "偏", f"收 {fwd:+.1f}%"
    return "還沒走完", f"收 {fwd:+.1f}%"


def _official_close(db_path: str, sid: str, day: str) -> Optional[float]:
    """只認這檔這日官方收。沒有、0、負的都不當已知。"""
    day = _ymd(day)
    if not db_path or not sid or not day:
        return None
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT close FROM daily_quotes WHERE stock_id=? "
            "AND REPLACE(CAST(date AS TEXT),'-','')=?",
            (sid, day),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    close = _f(row[0] if row else None)
    if close is None or close <= 0:
        return None
    return close


def _vs20_on(db_path: str, sid: str, day: str) -> Optional[float]:
    """vs20 必須是 check 當日那根官方柱算出來的，不准拿前一日冒充。"""
    day = _ymd(day)
    if not db_path or not sid or not day:
        return None
    from biaoke_field_scan import _bars, _stats

    st = _stats(_bars(db_path, sid, day)) or {}
    if _ymd(st.get("date")) != day:
        return None
    return _f(st.get("vs20"))


def score_dongzhu_picks(db_path: str, check_as_of: str) -> int:
    """用 check_as_of 這根官方收，對質更早一天的洞燭暫存。"""
    cap = _ymd(check_as_of)
    if not db_path or not cap:
        return 0
    ensure_dongzhu_tape_tables(db_path)

    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        prev = conn.execute(
            "SELECT MAX(as_of) FROM dongzhu_pick_run WHERE as_of < ?",
            (cap,),
        ).fetchone()
        as_of = _ymd(prev[0] if prev else "")
        if not as_of:
            return 0
        picks = conn.execute(
            """
            SELECT sid, tag, close, vs20
            FROM dongzhu_pick_tape WHERE as_of=?
            """,
            (as_of,),
        ).fetchall()
    finally:
        conn.close()
    scored = 0
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        for sid, tag, pick_close, vs20_then in picks:
            sid = str(sid or "").strip()
            tag = str(tag or "")
            px = _f(pick_close)
            if not sid or px is None or px <= 0:
                continue
            now_c = _official_close(db_path, sid, cap)
            if now_c is None:
                continue
            fwd = (now_c / px - 1.0) * 100.0
            vs_now = _vs20_on(db_path, sid, cap)
            vs_then = _f(vs20_then)
            vs_delta = (
                (vs_now - vs_then) if vs_now is not None and vs_then is not None else None
            )
            verdict, note = _verdict(tag, fwd, vs_delta)
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_score(
                    as_of, check_as_of, sid, tag, pick_close, now_close,
                    fwd_pct, vs20_then, vs20_now, verdict, note
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    as_of,
                    cap,
                    sid,
                    tag,
                    px,
                    now_c,
                    round(fwd, 2),
                    vs_then,
                    vs_now,
                    verdict,
                    note,
                ),
            )
            scored += 1
        conn.commit()
    finally:
        conn.close()
    _refresh_rates(db_path)
    return scored


def _refresh_rates(db_path: str) -> None:
    """累計全部已對質樣本。這是紀錄，不是改黃金買點。"""
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT tag,
                   SUM(CASE WHEN verdict='對' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='偏' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='還沒走完' THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM dongzhu_pick_score
            GROUP BY tag
            """
        ).fetchall()
        now = _now_iso()
        conn.execute("DELETE FROM dongzhu_pick_rates")
        for tag, hit, miss, pending, n in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_rates(
                    tag, n, hit, miss, pending, updated_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (str(tag), int(n or 0), int(hit or 0), int(miss or 0), int(pending or 0), now),
            )
        conn.commit()
    finally:
        conn.close()


def snapshot_and_score_dongzhu(db_path: str, cap: str) -> Dict[str, Any]:
    """盤後齊了：先對質前一天，再落當日檔。盤中未收不當官方收。"""
    cap = _ymd(cap)
    if not db_path or not cap:
        return {"snap": 0, "scored": 0, "cap": cap}
    scored = score_dongzhu_picks(db_path, cap)
    snap = snapshot_dongzhu_picks(db_path, cap, spoken="")
    return {"snap": int(snap), "scored": int(scored), "cap": cap}


def scoreboard_lines(db_path: str, cap: str = "") -> List[str]:
    """洞燭頁一句：昨日官方收對質。沒有就不寫。"""
    if not db_path:
        return []
    ensure_dongzhu_tape_tables(db_path)
    cap = _ymd(cap)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        if not cap:
            row = conn.execute(
                "SELECT MAX(check_as_of) FROM dongzhu_pick_score"
            ).fetchone()
            cap = _ymd(row[0] if row else "")
        if not cap:
            return []
        scores = conn.execute(
            """
            SELECT sid, name, tag, verdict
            FROM dongzhu_pick_score s
            JOIN dongzhu_pick_tape t USING (as_of, sid, tag)
            WHERE s.check_as_of=?
            ORDER BY CASE s.tag WHEN 'leave_zero' THEN 0 WHEN 'capture' THEN 1 ELSE 2 END, s.sid
            """,
            (cap,),
        ).fetchall()
        rates = conn.execute(
            "SELECT tag, n, hit, miss, pending FROM dongzhu_pick_rates ORDER BY tag"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    if not scores:
        return []
    lines = [f"官方收 {cap[4:6]}/{cap[6:]}"]
    for sid, name, _tag, verdict in scores[:6]:
        nm = str(name or sid)
        lines.append(f"{sid} {nm} {verdict}")
    titles = {"leave_zero": "買點", "capture": "捕捉", "golden_buy": "觀察"}
    for tag, n, hit, miss, pending in rates:
        if int(n or 0) <= 0:
            continue
        title = titles.get(str(tag), str(tag))
        lines.append(f"{title}對{int(hit)}偏{int(miss)}還沒{int(pending)}")
    lines.append("不是改黃金買點")
    return lines
