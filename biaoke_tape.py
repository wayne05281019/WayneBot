# -*- coding: utf-8 -*-
"""捕獲飆大主文／自回後立刻對官方日 K 建檔。

點到的檔才寫；IET 這種沒點代號的不准編。引號裡路人話不收。
盤中未收盤柱不當官方收，對最後一根完整官方柱。不是買訊。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_tape (
    post_id TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    bar_date TEXT NOT NULL DEFAULT '',
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    pct_change REAL,
    note TEXT NOT NULL DEFAULT '',
    charts TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (post_id, stock_id)
);
CREATE INDEX IF NOT EXISTS idx_biaoke_tape_sid ON biaoke_tape(stock_id, post_date);
"""
_IDX = re.compile(r"(大盤|加權|台指)")
_SPACE = re.compile(r"\s+")
_TICKER = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def ensure_biaoke_tape_table(db_path: str) -> None:
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


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return str(raw or "").strip()


def _snip(text: str, needle: str, n: int = 80) -> str:
    blob = _SPACE.sub(" ", text or "").strip()
    if not blob:
        return ""
    i = blob.find(needle) if needle else -1
    if i < 0:
        return blob[:n]
    a = max(0, i - 10)
    return blob[a : a + n]


def named_pairs(text: str, tags: Optional[Sequence[Any]] = None) -> List[Tuple[str, str]]:
    """只收他點過、表裡有代號的檔。IET 不在表裡就不編。"""
    from biaoke_why import _NAME_SID, named_stocks

    spoken = _spoken(text)
    out: List[Tuple[str, str]] = []
    seen = set()
    for name in named_stocks(spoken, tags):
        sid = str(_NAME_SID.get(name) or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append((sid, name))
    inv: Dict[str, str] = {}
    for name, sid in _NAME_SID.items():
        inv.setdefault(str(sid), name)
    for m in _TICKER.finditer(spoken):
        sid = m.group(1)
        if sid in inv and sid not in seen:
            seen.add(sid)
            out.append((sid, inv[sid]))
    return out


def last_official_bar(db_path: str, sid: str) -> Optional[Dict[str, Any]]:
    """庫裡最後一根完整官方柱。沒這列就空，不編。"""
    from biaoke_link import bar_on

    if not db_path or not os.path.isfile(db_path) or not sid:
        return None
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        if sid == "TWII":
            try:
                row = conn.execute(
                    "SELECT date FROM index_daily "
                    "WHERE symbol='TWII' OR symbol='^TWII' "
                    "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1"
                ).fetchone()
            except sqlite3.Error:
                row = None
        else:
            try:
                row = conn.execute(
                    "SELECT date FROM daily_quotes WHERE stock_id=? "
                    "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1",
                    (sid,),
                ).fetchone()
            except sqlite3.Error:
                row = None
    finally:
        conn.close()
    if not row:
        return None
    return bar_on(db_path, sid, str(row[0]))


def official_for_post(db_path: str, sid: str, post_date: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """發文當天有完整官方柱就用當天；沒有就對最後一根，並標未收盤。"""
    from biaoke_link import bar_on

    day = _ymd(post_date)
    bar = bar_on(db_path, sid, day) if day else None
    if bar:
        return bar, False
    last = last_official_bar(db_path, sid)
    if last:
        return last, True
    return None, bool(day)


def _note(name: str, spoken: str, bar: Optional[Dict[str, Any]], pinned: bool) -> str:
    bits: List[str] = []
    if pinned:
        bits.append(
            f"盤中未收盤，對最後官方收 {bar.get('date')}" if bar else "盤中未收盤，官方還沒這列"
        )
    if not bar:
        if not pinned:
            bits.append("官方還沒這列，不准編")
        return "；".join(bits)
    vol = bar.get("volume")
    vol_s = str(int(vol)) if vol is not None else "—"
    bits.append(
        f"官方{name} {bar.get('date')} "
        f"開{_px(bar.get('open')) or '—'} 高{_px(bar.get('high')) or '—'} "
        f"低{_px(bar.get('low')) or '—'} 收{_px(bar.get('close')) or '—'} 量{vol_s}"
    )
    blob = spoken or ""
    if "站回" in blob or "跌破" in blob:
        bits.append("原文跌破／站回，對這根官方高低收")
    if "跌停" in blob and pinned:
        bits.append("原文跌停是盤中說法，未收盤不當官方收")
    return "；".join(bits)


def record_events(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """新抓到的主文／樓下立刻對官方圖建檔。"""
    if not db_path or not events:
        return 0
    ensure_biaoke_tape_table(db_path)
    try:
        from biaoke_walk import post_chart_urls
    except Exception:
        post_chart_urls = lambda _t: []  # noqa: E731

    rows: List[Tuple[Any, ...]] = []
    for ev in events:
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        raw = str(ev.get("text") or "").strip()
        if not pid or not raw:
            continue
        spoken = _spoken(raw)
        charts = " ".join((post_chart_urls(raw) or [])[:4])
        pairs = named_pairs(raw, ev.get("tags"))
        if _IDX.search(spoken) and not any(s == "TWII" for s, _n in pairs):
            pairs.append(("TWII", "加權"))
        day = str(ev.get("date") or "")
        hm = str(ev.get("time") or "")
        for sid, name in pairs:
            bar, pinned = official_for_post(db_path, sid, day)
            note = _note(name, spoken, bar, pinned)
            rows.append(
                (
                    pid,
                    sid,
                    name,
                    day,
                    hm,
                    _snip(spoken, name),
                    str((bar or {}).get("date") or ""),
                    (bar or {}).get("open"),
                    (bar or {}).get("high"),
                    (bar or {}).get("low"),
                    (bar or {}).get("close"),
                    (bar or {}).get("volume"),
                    (bar or {}).get("pct_change"),
                    note,
                    charts,
                    "daily_quotes" if bar and sid != "TWII" else ("index_daily" if bar else ""),
                )
            )
    if not rows:
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO biaoke_tape
            (post_id, stock_id, stock_name, post_date, post_time, snippet,
             bar_date, open, high, low, close, volume, pct_change, note, charts, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def glance_for(db_path: str, sid: str, *, n: int = 2) -> str:
    """第④顆讀最近建檔：他剛點這檔時官方高低量。"""
    if not db_path or not os.path.isfile(db_path) or not sid:
        return ""
    ensure_biaoke_tape_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT post_date, post_time, stock_name, note
            FROM biaoke_tape WHERE stock_id=?
            ORDER BY post_date DESC, post_time DESC LIMIT ?
            """,
            (sid, max(1, int(n))),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    bits: List[str] = []
    for day, hm, name, note in rows:
        stamp = " ".join(x for x in (str(day or ""), str(hm or "")) if x)
        bits.append(f"{stamp} {name} {note}".strip())
    if not bits:
        return ""
    return "即時建檔：" + "；".join(bits)
