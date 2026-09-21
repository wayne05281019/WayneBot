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


_SCREEN_BUCKETS = (
    "leave_zero",
    "golden_buy",
    "revenue_cross",
    "select_01",
    "select_02",
    "select_03",
    "day_trade",
    "overnight",
)
_BAR_KEYS = ("o", "h", "l", "c", "v")
_EXTRA_KEEP = ("live", "chase_warning", "entry_stars", "stance", "rel_kind", "src")


def _bars_on(market_db: str, sids: Sequence[str], day: str) -> Dict[str, Dict[str, float]]:
    """只讀已進庫的官方柱數字。沒有就不寫。不准產圖。"""
    day = _ymd(day)
    want = [str(s).strip() for s in sids if str(s or "").strip()]
    if not market_db or not os.path.isfile(market_db) or not day or not want:
        return {}
    conn = sqlite3.connect(market_db, timeout=8.0)
    out: Dict[str, Dict[str, float]] = {}
    try:
        chunk = 400
        for i in range(0, len(want), chunk):
            part = want[i : i + chunk]
            marks = ",".join("?" * len(part))
            rows = conn.execute(
                f"""
                SELECT stock_id, open, high, low, close, volume
                FROM daily_quotes
                WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND stock_id IN ({marks})
                """,
                [day, *part],
            ).fetchall()
            for sid, o, h, lo, c, v in rows:
                bar = {}
                for key, raw in (("o", o), ("h", h), ("l", lo), ("c", c), ("v", v)):
                    n = _num(raw)
                    if n is None:
                        continue
                    bar[key] = n
                if bar.get("c"):
                    out[str(sid)] = bar
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


def _row_bar(raw: Dict[str, Any]) -> Dict[str, float]:
    bar: Dict[str, float] = {}
    mapping = (
        ("o", ("open", "o")),
        ("h", ("high", "h")),
        ("l", ("low", "l")),
        ("c", ("close", "c", "price", "px", "pick_close")),
        ("v", ("volume", "v")),
    )
    for key, aliases in mapping:
        for a in aliases:
            n = _num(raw.get(a))
            if n is not None:
                bar[key] = n
                break
    return bar


def remember_rows(
    market_db: str,
    kind: str,
    rows: Iterable[Dict[str, Any]] | None,
    *,
    as_of: str = "",
    pick: str = "",
    src: str = "",
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
    sids = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("stock_id") or raw.get("code") or raw.get("sid") or "").strip()
        if sid:
            sids.append(sid)
    bars = _bars_on(market_db, sids, day)
    conn = sqlite3.connect(store, timeout=30.0)
    n = 0
    try:
        if not items:
            empty_extra = {"n": 0}
            if src:
                empty_extra["src"] = str(src)
            conn.execute(
                """
                INSERT OR REPLACE INTO live_judge(
                    as_of, kind, pick, sid, name, px, profit, extra, ran_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (day, kind, tag, "", "", None, None, json.dumps(empty_extra, ensure_ascii=False), ran),
            )
            n = 1
        for raw in items:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("stock_id") or raw.get("code") or raw.get("sid") or "").strip()
            if not sid:
                continue
            extra: Dict[str, Any] = {}
            for key in _EXTRA_KEEP:
                if key == "src":
                    continue
                if raw.get(key) not in (None, "", {}, []):
                    extra[key] = raw.get(key) if key != "live" else True
            if src:
                extra["src"] = str(src)
            bar = dict(bars.get(sid) or {})
            bar.update(_row_bar(raw))
            for key in _BAR_KEYS:
                if key in bar:
                    extra[key] = bar[key]
            px = _num(raw.get("close") or raw.get("price") or raw.get("px") or extra.get("c"))
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
                    px,
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


def snapshot_button_lists(market_db: str, as_of: str = "") -> Dict[str, int]:
    """當天規則名單沒按也落檔。只留代號＋官方柱數字，不准渲圖、不推話筒。"""
    stats: Dict[str, int] = {}
    if not market_db:
        return stats
    day = _as_of(market_db, as_of)
    if not day:
        return stats
    results: Dict[str, Any] = {}
    src = "none"
    try:
        from screen_sessions import load_session_results, screen_session_has_data

        results = load_session_results(market_db, day, "morning") or {}
        if not any(results.values()):
            results = load_session_results(market_db, day, "evening") or {}
        if any(results.values()) or screen_session_has_data(market_db, day):
            src = "session"
    except Exception:
        results = {}
    for bucket in _SCREEN_BUCKETS:
        rows = results.get(bucket) if isinstance(results.get(bucket), list) else []
        stats[bucket] = remember_rows(
            market_db, bucket, rows, as_of=day, pick="rule", src=src
        )
    try:
        from buy_streak import KIND_BOTH, KIND_FOREIGN, KIND_TRUST, MARKET_ALL, MIN_STREAK, load_snapshot

        for kind in (KIND_FOREIGN, KIND_TRUST, KIND_BOTH):
            snap = load_snapshot(market_db, kind, MARKET_ALL, as_of=day, use_cache=True)
            key = f"streak_{kind}"
            days_map = getattr(snap, "by_days", None) or {}
            if not days_map:
                stats[key] = remember_rows(
                    market_db, key, [], as_of=day, pick="rule", src="streak"
                )
                continue
            n = 0
            for days, rows in days_map.items():
                if int(days) < int(MIN_STREAK) or not rows:
                    continue
                payload = [
                    {"stock_id": r.stock_id, "stock_name": getattr(r, "name", "")}
                    for r in rows
                ]
                n += remember_rows(
                    market_db,
                    key,
                    payload,
                    as_of=day,
                    pick=str(int(days)),
                    src="streak",
                )
            stats[key] = n
    except Exception:
        pass
    if not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            from screening_engine import ScreeningEngine

            em = ScreeningEngine(market_db).run_emerging_screening(day, sync=False) or {}
            em_day = str(em.get("as_of") or day)
            for bucket, kind in (("leave_zero", "em_leave_zero"), ("golden_buy", "em_golden_buy")):
                rows = em.get(bucket) if isinstance(em.get(bucket), list) else []
                stats[kind] = remember_rows(
                    market_db, kind, rows, as_of=em_day, pick="rule", src="emerging"
                )
        except Exception:
            pass
    return stats


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
