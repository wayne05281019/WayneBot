"""晚間／早上海選快照：同一根台股收盤，早上再對美股。

晚上 20:00＝只用台股收盤（不推播，美股還沒開）。
早上 06:30＝同一基準日＋美股收盤／盤後過濾，主動寄出；大跌會先單獨通知。
兩邊都有的標【雙時段】，轉 LINE 一眼能認。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, List, Set

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

BUCKETS = (
    "revenue_cross",
    "leave_zero",
    "select_01",
    "select_02",
    "select_03",
    "select_04",
    "day_trade",
    "overnight",
)


def ensure_screen_session_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_sessions (
            as_of TEXT NOT NULL,
            session TEXT NOT NULL,
            bucket TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            pick_close REAL,
            hi20_close REAL,
            entry_price REAL,
            defense_price REAL,
            chase_warning INTEGER DEFAULT 0,
            PRIMARY KEY (as_of, session, bucket, stock_id)
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_screen_sessions_asof ON screen_sessions(as_of, session);"
    )
    conn.commit()
    conn.close()


def ids_in_results(results: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for key in BUCKETS:
        for it in results.get(key) or []:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("stock_id") or it.get("code") or "").strip()
            if sid:
                out.add(sid)
    return out


def save_screen_session(db_path: str, as_of: str, session: str, results: Dict[str, Any]) -> int:
    as_of = str(as_of or "").replace("-", "")
    session = str(session or "").strip()
    if not as_of or session not in ("evening", "morning"):
        return 0
    ensure_screen_session_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM screen_sessions WHERE as_of=? AND session=?", (as_of, session))
    n = 0
    for key in BUCKETS:
        for it in results.get(key) or []:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("stock_id") or it.get("code") or "").strip()
            if not sid:
                continue
            def f(name):
                try:
                    v = it.get(name)
                    return float(v) if v is not None and v != "" else None
                except (TypeError, ValueError):
                    return None

            conn.execute(
                """
                INSERT OR REPLACE INTO screen_sessions(
                    as_of, session, bucket, stock_id, stock_name,
                    pick_close, hi20_close, entry_price, defense_price, chase_warning
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    as_of,
                    session,
                    key,
                    sid,
                    str(it.get("stock_name") or it.get("name") or ""),
                    f("close"),
                    f("hi20_close"),
                    f("entry_price"),
                    f("defense_price"),
                    1 if it.get("chase_warning") else 0,
                ),
            )
            n += 1
    conn.commit()
    conn.close()
    return n


def session_ids(db_path: str, as_of: str, session: str) -> Set[str]:
    ensure_screen_session_table(db_path)
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT stock_id FROM screen_sessions WHERE as_of=? AND session=?",
        (str(as_of or "").replace("-", ""), session),
    ).fetchall()
    conn.close()
    return {str(r[0]) for r in rows if r and r[0]}


def overlap_ids(db_path: str, as_of: str) -> Set[str]:
    return session_ids(db_path, as_of, "evening") & session_ids(db_path, as_of, "morning")


def mark_both_sessions(results: Dict[str, Any], both: Iterable[str]) -> int:
    both_set = {str(x) for x in both}
    n = 0
    for key in BUCKETS:
        lst = results.get(key) or []
        if not isinstance(lst, list):
            continue
        for it in lst:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("stock_id") or it.get("code") or "")
            if sid in both_set:
                it["both_sessions"] = True
                n += 1
        lst.sort(key=lambda x: (0 if x.get("both_sessions") else 1, 1 if x.get("chase_warning") else 0))
    return n


def ensure_line_share_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_line_share (
            as_of TEXT PRIMARY KEY,
            body TEXT NOT NULL,
            updated_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def save_line_share(db_path: str, as_of: str, body: str) -> None:
    """06:30 與手動海選都寫一份，轉寄鈕跨行程也能讀到。"""
    as_of = str(as_of or "").replace("-", "")
    text = str(body or "").strip()
    if not as_of or not text:
        return
    ensure_line_share_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO screen_line_share(as_of, body, updated_at)
        VALUES (?,?,datetime('now'))
        ON CONFLICT(as_of) DO UPDATE SET
            body=excluded.body,
            updated_at=excluded.updated_at
        """,
        (as_of, text),
    )
    conn.commit()
    conn.close()


def load_line_share(db_path: str, as_of: str = "") -> str:
    ensure_line_share_table(db_path)
    conn = sqlite3.connect(db_path)
    as_of = str(as_of or "").replace("-", "")
    if as_of:
        row = conn.execute(
            "SELECT body FROM screen_line_share WHERE as_of=?", (as_of,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT body FROM screen_line_share ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    conn.close()
    return str(row[0] or "") if row else ""


def load_morning_rows(db_path: str, as_of: str) -> List[Dict[str, Any]]:
    ensure_screen_session_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT bucket, stock_id, stock_name, pick_close, hi20_close, entry_price, defense_price, chase_warning
        FROM screen_sessions WHERE as_of=? AND session='morning'
        ORDER BY bucket, stock_id
        """,
        (str(as_of or "").replace("-", ""),),
    ).fetchall()
    conn.close()
    seen = set()
    out = []
    for r in rows:
        sid = str(r["stock_id"])
        if sid in seen:
            continue
        seen.add(sid)
        out.append(dict(r))
    return out
