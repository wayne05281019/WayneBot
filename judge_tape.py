# -*- coding: utf-8 -*-
"""當下判斷默默落檔；官方收齊再對隔日／五日。

不推話筒、不改畫面、不改黃金買點。盤中未收不當官方收。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
HORIZONS = (1, 5)

_DDL = """
CREATE TABLE IF NOT EXISTS live_judge (
    as_of TEXT NOT NULL,
    kind TEXT NOT NULL,
    pick TEXT NOT NULL DEFAULT '',
    sid TEXT NOT NULL,
    name TEXT DEFAULT '',
    px REAL,
    profit REAL,
    extra TEXT DEFAULT '',
    ran_at TEXT DEFAULT '',
    PRIMARY KEY (as_of, kind, pick, sid)
);
CREATE TABLE IF NOT EXISTS live_judge_score (
    as_of TEXT NOT NULL,
    kind TEXT NOT NULL,
    pick TEXT NOT NULL DEFAULT '',
    sid TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    check_as_of TEXT NOT NULL,
    now_px REAL,
    fwd_pct REAL,
    verdict TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (as_of, kind, pick, sid, horizon)
);
"""


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def store_path(market_db: str) -> str:
    path = os.path.abspath(str(market_db or "data/wayne_market.db"))
    root = os.path.dirname(path) or "."
    name = os.path.basename(path)
    if name == "wayne_evolve.db":
        return path
    return os.path.join(root, "wayne_evolve.db")


def _ensure(store: str) -> None:
    parent = os.path.dirname(os.path.abspath(store))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(store, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _num(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _as_of(market_db: str, hint: str = "") -> str:
    day = _ymd(hint)
    if day:
        return day
    try:
        from import_health import latest_complete_quote_date

        return _ymd(latest_complete_quote_date(market_db))
    except Exception:
        return ""


def remember_rows(
    market_db: str,
    kind: str,
    rows: Iterable[Dict[str, Any]] | None,
    *,
    as_of: str = "",
    pick: str = "",
) -> int:
    """記下此刻秀出的判斷。失敗當沒發生，不准影響原功能。"""
    kind = str(kind or "").strip()
    if not market_db or not kind:
        return 0
    day = _as_of(market_db, as_of)
    if not day:
        return 0
    store = store_path(market_db)
    try:
        _ensure(store)
    except Exception:
        return 0
    items = list(rows or [])
    ran = _now()
    tag = str(pick or "")
    conn = sqlite3.connect(store, timeout=30.0)
    n = 0
    try:
        if not items:
            conn.execute(
                """
                INSERT OR REPLACE INTO live_judge(
                    as_of, kind, pick, sid, name, px, profit, extra, ran_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (day, kind, tag, "", "", None, None, json.dumps({"n": 0}, ensure_ascii=False), ran),
            )
            n = 1
        for raw in items:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("stock_id") or raw.get("code") or raw.get("sid") or "").strip()
            if not sid:
                continue
            extra = {}
            for key in ("live", "chase_warning", "entry_stars", "stance", "rel_kind"):
                if raw.get(key) not in (None, "", {}, []):
                    extra[key] = raw.get(key) if key != "live" else True
            conn.execute(
                """
                INSERT OR REPLACE INTO live_judge(
                    as_of, kind, pick, sid, name, px, profit, extra, ran_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    day,
                    kind,
                    tag,
                    sid,
                    str(raw.get("stock_name") or raw.get("name") or "")[:40],
                    _num(raw.get("close") or raw.get("price") or raw.get("px")),
                    _num(raw.get("profit_pct") if raw.get("profit_pct") is not None else raw.get("profit")),
                    json.dumps(extra, ensure_ascii=False) if extra else "",
                    ran,
                ),
            )
            n += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return n


def _quote_dates(market_db: str, cap: str) -> List[str]:
    cap = _ymd(cap)
    if not market_db or not cap or not os.path.isfile(market_db):
        return []
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') AS d
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','') <= ?
            ORDER BY d
            """,
            (cap,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [_ymd(r[0]) for r in rows if _ymd(r[0])]


def _close_on(market_db: str, sid: str, day: str) -> Optional[float]:
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT close FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
            """,
            (sid, day),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return _num(row[0] if row else None)


def _verdict(fwd: Optional[float]) -> str:
    if fwd is None:
        return ""
    if fwd > 0.15:
        return "up"
    if fwd < -0.15:
        return "down"
    return "flat"


def score_live_judges(market_db: str, cap: str = "") -> int:
    """官方柱走完才填隔日／五日。未收盤不寫。"""
    day = _as_of(market_db, cap)
    if not market_db or not day:
        return 0
    store = store_path(market_db)
    if not os.path.isfile(store):
        return 0
    dates = _quote_dates(market_db, day)
    if not dates:
        return 0
    by_i = {d: i for i, d in enumerate(dates)}
    conn = sqlite3.connect(store, timeout=30.0)
    conn.row_factory = sqlite3.Row
    filled = 0
    try:
        conn.executescript(_DDL)
        rows = conn.execute(
            "SELECT as_of, kind, pick, sid, px FROM live_judge WHERE sid!=''"
        ).fetchall()
        scored = {
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]), int(r[4]))
            for r in conn.execute(
                "SELECT as_of, kind, pick, sid, horizon FROM live_judge_score"
            )
        }
        for row in rows:
            as_of = str(row["as_of"] or "")
            sid = str(row["sid"] or "")
            if as_of not in by_i or not sid:
                continue
            start = by_i[as_of]
            pick_px = _num(row["px"])
            if pick_px is None or pick_px <= 0:
                pick_px = _close_on(market_db, sid, as_of)
            if pick_px is None or pick_px <= 0:
                continue
            for hz in HORIZONS:
                key = (as_of, str(row["kind"]), str(row["pick"] or ""), sid, int(hz))
                if key in scored:
                    continue
                want_i = start + int(hz)
                if want_i >= len(dates):
                    continue
                check = dates[want_i]
                if check > day:
                    continue
                now_px = _close_on(market_db, sid, check)
                if now_px is None or now_px <= 0:
                    continue
                fwd = round((now_px / pick_px - 1.0) * 100.0, 2)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO live_judge_score(
                        as_of, kind, pick, sid, horizon, check_as_of, now_px, fwd_pct, verdict
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        as_of,
                        str(row["kind"]),
                        str(row["pick"] or ""),
                        sid,
                        int(hz),
                        check,
                        now_px,
                        fwd,
                        _verdict(fwd),
                    ),
                )
                filled += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return filled
