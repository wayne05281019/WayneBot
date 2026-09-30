# -*- coding: utf-8 -*-
"""盤中剛離零（藍▲紅框）→ 收盤是否仍 leave_zero・靜默對質。

查股／MIS 路徑：盤中亮買點標時默默記一列（代號＋日）；官方收齊後對質：
  1) 主勝＝當日官方收仍 leave_zero_ok（close_hold）
  2) 選填＝隔日官方收相對當日收的報酬（next_1；只記，不進改碼）

不是買訊。不准改黃金買點／leave_zero 公式／話筒畫面／海選桶。
分軌記、勝率不准混進海選／壓撐／洞燭／AI／飆大。
獨立交易日 n≥20 且明確贏基線前不准改碼；本軌 promote_* 恒 False。
失敗吞掉，不准擋查股／出卡／海選。過程／％不准進對話。Asia/Taipei。
盤中未收不當官方收。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

TAIPEI = ZoneInfo("Asia/Taipei")

KIND = "intraday_leave_zero"
HORIZON_CLOSE = "close_hold"
HORIZON_NEXT = "next_1"
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
SRC_LOOKUP = "lookup"


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


def _now_iso() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def mark_lights_leave_zero_buy(card: Optional[Dict[str, Any]]) -> bool:
    """對齊導航藍▲紅框：買點亮了才記。不是改畫圖。"""
    if not card or card.get("error"):
        return False
    verdict = str(card.get("buy_verdict") or "")
    if verdict == "buy":
        lit = True
    elif verdict in ("watch", "no"):
        lit = False
    elif str(card.get("relative_buy_kind") or "") == "just_left":
        lit = True
    else:
        lit = False
    if str(card.get("entry_stage") or "") == "watch":
        lit = False
    return bool(lit)


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS intraday_lz_hit (
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                name TEXT DEFAULT '',
                seen_at TEXT NOT NULL DEFAULT '',
                live_px REAL,
                live_profit_pct REAL,
                src TEXT DEFAULT 'lookup',
                PRIMARY KEY (as_of, sid)
            );
            CREATE TABLE IF NOT EXISTS intraday_lz_score (
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                close_px REAL,
                close_leave_zero_ok INTEGER NOT NULL DEFAULT 0,
                next_px REAL,
                next_ret_pct REAL,
                reconciled_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (as_of, sid)
            );
            CREATE TABLE IF NOT EXISTS intraday_lz_rates (
                horizon TEXT NOT NULL PRIMARY KEY,
                n_days INTEGER NOT NULL DEFAULT 0,
                n_rows INTEGER NOT NULL DEFAULT 0,
                win_rate REAL,
                avg_next_ret REAL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def note_intraday_hit(
    market_db: str,
    *,
    stock_id: str,
    as_of: str,
    name: str = "",
    live_px: Any = None,
    live_profit_pct: Any = None,
    src: str = SRC_LOOKUP,
) -> bool:
    """盤中亮標時 append-only 記一列。同日同代號只留第一次。失敗→False。"""
    day = _ymd(as_of)
    sid = str(stock_id or "").strip()
    if not market_db or not day or not sid:
        return False
    try:
        store = ensure_tables(market_db)
        conn = sqlite3.connect(store, timeout=8.0)
        try:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO intraday_lz_hit(
                    as_of, sid, name, seen_at, live_px, live_profit_pct, src
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    day,
                    sid,
                    str(name or "")[:40],
                    _now_iso(),
                    _f(live_px),
                    _f(live_profit_pct),
                    str(src or SRC_LOOKUP)[:24],
                ),
            )
            conn.commit()
            return int(cur.rowcount or 0) > 0
        finally:
            conn.close()
    except Exception:
        return False


def maybe_note_from_card(market_db: str, card: Optional[Dict[str, Any]]) -> bool:
    """查股回卡後：僅盤中＋亮買點標才記。永不擋出卡。"""
    try:
        if not market_db or not card or card.get("error"):
            return False
        if not card.get("is_live"):
            return False
        if not mark_lights_leave_zero_buy(card):
            return False
        sid = str(card.get("stock_id") or card.get("code") or "").strip()
        day = _ymd(
            card.get("latest_date")
            or card.get("date")
            or card.get("as_of")
            or card.get("db_as_of")
            or ""
        )
        if not sid or not day:
            return False
        return note_intraday_hit(
            market_db,
            stock_id=sid,
            as_of=day,
            name=str(card.get("stock_name") or card.get("name") or ""),
            live_px=card.get("close") or card.get("price"),
            live_profit_pct=card.get("gain_pct") or card.get("profit_pct"),
            src=SRC_LOOKUP,
        )
    except Exception:
        return False


def _official_ohlc_through(
    market_db: str, sid: str, as_of: str, *, need: int = 90
):
    """官方已收柱至 as_of（含）。不足回 None。不准塞盤中列。"""
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not market_db or not os.path.isfile(market_db) or not sid or not day:
        return None
    conn = sqlite3.connect(market_db, timeout=12.0)
    try:
        rows = conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY replace(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (sid, day, max(30, int(need))),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    if len(rows) < 2:
        return None
    import pandas as pd

    df = pd.DataFrame(
        list(reversed(rows)),
        columns=["date", "open", "high", "low", "close", "volume"],
    )
    dnorm = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    df = df.loc[dnorm <= day].reset_index(drop=True)
    if len(df) < 2:
        return None
    return df


def _next_official_bar(market_db: str, sid: str, as_of: str) -> Optional[Tuple[str, float]]:
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not market_db or not os.path.isfile(market_db) or not sid or not day:
        return None
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT replace(CAST(date AS TEXT),'-',''), close
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')>?
            ORDER BY replace(CAST(date AS TEXT),'-','') ASC
            LIMIT 1
            """,
            (sid, day),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row:
        return None
    nd = _ymd(row[0])
    px = _f(row[1])
    if not nd or px is None or px <= 0:
        return None
    return nd, float(px)


def close_still_leave_zero(market_db: str, sid: str, as_of: str) -> Optional[bool]:
    """官方收是否仍 leave_zero。柱不足／算不出＝None（不記假勝敗）。"""
    from decision_card_signals import leave_zero_from_quote_df

    df = _official_ohlc_through(market_db, sid, as_of)
    if df is None:
        return None
    try:
        return bool(leave_zero_from_quote_df(df))
    except Exception:
        return None


def reconcile_one(market_db: str, as_of: str, sid: str) -> bool:
    """對一檔：寫 close_hold；有隔日柱再填 next_1。未齊官方收＝跳過。"""
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not market_db or not day or not sid:
        return False
    held = close_still_leave_zero(market_db, sid, day)
    if held is None:
        return False
    df = _official_ohlc_through(market_db, sid, day, need=5)
    if df is None or df.empty:
        return False
    close_px = _f(df["close"].iloc[-1])
    if close_px is None or close_px <= 0:
        return False
    next_px = None
    next_ret = None
    nxt = _next_official_bar(market_db, sid, day)
    if nxt is not None:
        next_px = float(nxt[1])
        next_ret = round((next_px - float(close_px)) / float(close_px) * 100.0, 4)
    try:
        store = ensure_tables(market_db)
        conn = sqlite3.connect(store, timeout=8.0)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO intraday_lz_score(
                    as_of, sid, close_px, close_leave_zero_ok,
                    next_px, next_ret_pct, reconciled_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    day,
                    sid,
                    float(close_px),
                    1 if held else 0,
                    next_px,
                    next_ret,
                    _now_iso(),
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


def pending_hits(market_db: str, *, only_unscored: bool = True) -> List[Tuple[str, str]]:
    store = ensure_tables(market_db)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        if only_unscored:
            rows = conn.execute(
                """
                SELECT h.as_of, h.sid FROM intraday_lz_hit h
                LEFT JOIN intraday_lz_score s
                  ON s.as_of=h.as_of AND s.sid=h.sid
                WHERE s.as_of IS NULL
                ORDER BY h.as_of, h.sid
                """
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT as_of, sid FROM intraday_lz_hit ORDER BY as_of, sid"
            ).fetchall()
        return [(_ymd(a), str(s)) for a, s in rows if _ymd(a) and s]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def score_pending(market_db: str, *, cap: str = "") -> int:
    """官方收齊後補對質。cap＝只處理 ≤ 該日的 hit。"""
    cap_d = _ymd(cap)
    n = 0
    for day, sid in pending_hits(market_db, only_unscored=True):
        if cap_d and day > cap_d:
            continue
        if reconcile_one(market_db, day, sid):
            n += 1
    # 已有 score 但缺隔日報酬的：隔日柱來了再補
    n += _fill_next_returns(market_db, cap=cap_d)
    if n:
        recompute_rates(market_db)
    return n


def _fill_next_returns(market_db: str, *, cap: str = "") -> int:
    store = ensure_tables(market_db)
    conn = sqlite3.connect(store, timeout=8.0)
    filled = 0
    try:
        rows = conn.execute(
            """
            SELECT as_of, sid, close_px FROM intraday_lz_score
            WHERE next_ret_pct IS NULL AND close_px IS NOT NULL AND close_px>0
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for as_of, sid, close_px in rows:
        day = _ymd(as_of)
        if cap and day > cap:
            continue
        nxt = _next_official_bar(market_db, str(sid), day)
        if nxt is None:
            continue
        next_px = float(nxt[1])
        cpx = _f(close_px)
        if cpx is None or cpx <= 0:
            continue
        next_ret = round((next_px - float(cpx)) / float(cpx) * 100.0, 4)
        try:
            conn = sqlite3.connect(store, timeout=8.0)
            try:
                conn.execute(
                    """
                    UPDATE intraday_lz_score
                    SET next_px=?, next_ret_pct=?, reconciled_at=?
                    WHERE as_of=? AND sid=?
                    """,
                    (next_px, next_ret, _now_iso(), day, str(sid)),
                )
                conn.commit()
                filled += 1
            finally:
                conn.close()
        except Exception:
            continue
    return filled


def recompute_rates(market_db: str) -> None:
    store = ensure_tables(market_db)
    conn = sqlite3.connect(store, timeout=12.0)
    try:
        conn.execute("DELETE FROM intraday_lz_rates")
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT as_of), COUNT(*), AVG(close_leave_zero_ok)
            FROM intraday_lz_score
            """
        ).fetchone()
        n_days = int(row[0] or 0) if row else 0
        n_rows = int(row[1] or 0) if row else 0
        wr = float(row[2] or 0) if row and row[2] is not None else None
        conn.execute(
            """
            INSERT OR REPLACE INTO intraday_lz_rates(
                horizon, n_days, n_rows, win_rate, avg_next_ret
            ) VALUES (?,?,?,?,?)
            """,
            (HORIZON_CLOSE, n_days, n_rows, wr, None),
        )
        row2 = conn.execute(
            """
            SELECT COUNT(DISTINCT as_of), COUNT(*), AVG(next_ret_pct)
            FROM intraday_lz_score
            WHERE next_ret_pct IS NOT NULL
            """
        ).fetchone()
        nd2 = int(row2[0] or 0) if row2 else 0
        nr2 = int(row2[1] or 0) if row2 else 0
        avg_ret = float(row2[2]) if row2 and row2[2] is not None else None
        # next_1 的「勝」＝隔日報酬 > 0（只記；不進改碼）
        row3 = conn.execute(
            """
            SELECT AVG(CASE WHEN next_ret_pct>0 THEN 1.0 ELSE 0.0 END)
            FROM intraday_lz_score
            WHERE next_ret_pct IS NOT NULL
            """
        ).fetchone()
        wr_next = float(row3[0]) if row3 and row3[0] is not None else None
        conn.execute(
            """
            INSERT OR REPLACE INTO intraday_lz_rates(
                horizon, n_days, n_rows, win_rate, avg_next_ret
            ) VALUES (?,?,?,?,?)
            """,
            (HORIZON_NEXT, nd2, nr2, wr_next, avg_ret),
        )
        conn.commit()
    finally:
        conn.close()


def unique_days(market_db: str, horizon: str = HORIZON_CLOSE) -> int:
    store = ensure_tables(market_db)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT n_days FROM intraday_lz_rates WHERE horizon=?",
            (str(horizon),),
        ).fetchone()
        if row:
            return int(row[0] or 0)
        row = conn.execute(
            "SELECT COUNT(DISTINCT as_of) FROM intraday_lz_score"
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def gate_status(market_db: str) -> Dict[str, Any]:
    """明確優化狀態。本軌永不自動改買訊／話筒。"""
    store = ensure_tables(market_db)
    by: Dict[str, Dict[str, Any]] = {}
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT horizon, n_days, n_rows, win_rate, avg_next_ret FROM intraday_lz_rates"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for horizon, n_days, n_rows, wr, avg_ret in rows:
        by[str(horizon)] = {
            "n_days": int(n_days or 0),
            "n_rows": int(n_rows or 0),
            "win_rate": float(wr) if wr is not None else None,
            "avg_next_ret": float(avg_ret) if avg_ret is not None else None,
        }
    close = by.get(HORIZON_CLOSE) or {}
    n = int(close.get("n_days") or 0)
    n_ok = n >= MIN_UNIQUE_DAYS
    return {
        "kind": KIND,
        "n_days": n,
        "n_ok": n_ok,
        "min_n": MIN_UNIQUE_DAYS,
        "close_hold": close,
        "next_1": by.get(HORIZON_NEXT) or {},
        "baseline": "close_leave_zero_ok",
        "promote_buy_signals": False,
        "promote_ready": False,
        "gate_ready_for_review": bool(n_ok),
        "note": (
            "獨立日 n 夠 → 僅可人工複審；不准自動改黃金買點／海選／話筒"
            if n_ok
            else "繼續收集／尚未改碼；盤中剛離零→收盤站得住靜默對質中"
        ),
    }


def night_tick(market_db: str, as_of: str = "") -> Dict[str, Any]:
    """接默默落檔節奏。失敗吞掉。"""
    out: Dict[str, Any] = {"scored": 0, "gate": {}}
    try:
        out["scored"] = score_pending(market_db, cap=as_of)
        out["gate"] = gate_status(market_db)
    except Exception:
        return out
    return out


def optimize_status_one_liner(market_db: str) -> str:
    """報告結論唯一准講的一句（明確優化狀態）。不准報過程％。"""
    g = gate_status(market_db)
    n = int(g.get("n_days") or 0)
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    if n < need:
        return f"盤中剛離零→收盤站得住靜默對質：n={n}/{need}，繼續收集／尚未改碼。"
    return (
        f"盤中剛離零→收盤站得住靜默對質：n≥{need} 可複審；"
        "未自動改黃金買點／海選／買訊。"
    )


# 測試／重放：純函數對質（不碰庫）
def evaluate_close_hold_from_ohlc(df) -> bool:
    """假 OHLC 測：官方柱是否 leave_zero。"""
    from decision_card_signals import leave_zero_from_quote_df

    return bool(leave_zero_from_quote_df(df))


def evaluate_next_ret(close_px: float, next_px: float) -> Optional[float]:
    c = _f(close_px)
    n = _f(next_px)
    if c is None or n is None or c <= 0:
        return None
    return round((n - c) / c * 100.0, 4)
