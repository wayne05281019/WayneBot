# -*- coding: utf-8 -*-
"""止穩觀察標靜默對質：沒按查股也每日落檔。

現況 tag＝hold_l60（與畫圖同源）；下一版候選 hold_l60_tight（HOLD_N=5）只收不畫。
前瞻 1／5／10 日官方收報酬；空名單不算。不准當買訊、不准改黃金買點。
接 judge_tape → night_tick；失敗不擋海選／查股。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path
from stabilize_watch import (
    HOLD_N,
    HOLD_N_NEXT,
    RULE_ID,
    RULE_NEXT_ID,
    stabilize_fires_today,
)

KIND = "stabilize"
TAG_CURRENT = RULE_ID
TAG_NEXT = RULE_NEXT_ID
TAGS: Tuple[str, ...] = (TAG_CURRENT, TAG_NEXT)
SCORE_HORIZONS: Tuple[int, ...] = (1, 5, 10)
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
PRIMARY_H = 5


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
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stabilize_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                name TEXT DEFAULT '',
                close REAL,
                tagged_low REAL,
                bars_held INTEGER,
                PRIMARY KEY (kind, as_of, sid, tag)
            );
            CREATE TABLE IF NOT EXISTS stabilize_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                check_as_of TEXT NOT NULL DEFAULT '',
                entry REAL,
                exit REAL,
                ret_pct REAL,
                verdict TEXT NOT NULL,
                PRIMARY KEY (kind, as_of, sid, tag, horizon)
            );
            CREATE TABLE IF NOT EXISTS stabilize_rates (
                kind TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                n INTEGER NOT NULL DEFAULT 0,
                hit INTEGER NOT NULL DEFAULT 0,
                miss INTEGER NOT NULL DEFAULT 0,
                pending INTEGER NOT NULL DEFAULT 0,
                n_days INTEGER NOT NULL DEFAULT 0,
                avg_ret REAL,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, tag, horizon)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def persist_tape(db_path: str, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    n = 0
    try:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO stabilize_tape(
                    kind, as_of, sid, tag, name, close, tagged_low, bars_held
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    _ymd(r.get("as_of")),
                    str(r.get("sid") or "").strip(),
                    str(r.get("tag") or ""),
                    str(r.get("name") or "")[:40],
                    r.get("close"),
                    r.get("tagged_low"),
                    int(r.get("bars_held") or 0),
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def tags_for_frame(df) -> List[str]:
    """當日最新柱命中哪些止穩規則（觀察，非買訊）。"""
    out: List[str] = []
    if df is None or len(df) < 62:
        return out
    if stabilize_fires_today(df, hold_n=HOLD_N):
        out.append(TAG_CURRENT)
    if stabilize_fires_today(df, hold_n=HOLD_N_NEXT):
        out.append(TAG_NEXT)
    return out


def snapshot_day(db_path: str, as_of: str = "") -> Dict[str, int]:
    """盤後：流動母體掃止穩命中，沒按查股也留。"""
    counts = {t: 0 for t in TAGS}
    if not db_path or not os.path.isfile(db_path):
        return counts
    day = _ymd(as_of)
    try:
        from screening_engine import ScreeningEngine

        eng = ScreeningEngine(db_path)
        if not day:
            day = _ymd(eng.get_latest_trading_date())
        frames, _em_ids = eng._load_profit_scan_frames(day)
    except Exception:
        return counts
    if not day or not frames:
        return counts
    rows: List[Dict[str, Any]] = []
    for sid, df in (frames or {}).items():
        sid_s = str(sid or "").strip()
        if not sid_s or df is None or len(df) < 62:
            continue
        try:
            from wayne_navigator import frame_for_cal60_profit

            profit_df = frame_for_cal60_profit(df, db_path)
        except Exception:
            profit_df = df
        tags = tags_for_frame(profit_df)
        if not tags:
            continue
        try:
            close = _f(profit_df["close"].iloc[-1])
            name = ""
            if "stock_name" in profit_df.columns:
                name = str(profit_df["stock_name"].iloc[-1] or "")
        except Exception:
            close = None
            name = ""
        detail = None
        try:
            from stabilize_watch import stabilize_detail

            detail = stabilize_detail(profit_df, hold_n=HOLD_N)
        except Exception:
            detail = None
        tagged_low = (detail or {}).get("tagged_low")
        bars_held = int((detail or {}).get("bars_held") or 0)
        for tag in tags:
            rows.append(
                {
                    "as_of": day,
                    "sid": sid_s,
                    "tag": tag,
                    "name": name,
                    "close": close,
                    "tagged_low": tagged_low,
                    "bars_held": bars_held,
                }
            )
            counts[tag] = int(counts.get(tag) or 0) + 1
    persist_tape(db_path, rows)
    return counts


def _next_trading_close(
    conn: sqlite3.Connection,
    sid: str,
    as_of: str,
    horizon: int,
) -> Tuple[str, Optional[float]]:
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-','') AS d, close
            FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','') > ?
              AND close > 0
            ORDER BY d
            LIMIT ?
            """,
            (sid, as_of, int(horizon)),
        ).fetchall()
    except sqlite3.Error:
        return "", None
    if len(rows) < int(horizon):
        # 興櫃備援
        try:
            rows = conn.execute(
                """
                SELECT REPLACE(CAST(date AS TEXT),'-','') AS d, close
                FROM emerging_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','') > ?
                  AND close > 0
                ORDER BY d
                LIMIT ?
                """,
                (sid, as_of, int(horizon)),
            ).fetchall()
        except sqlite3.Error:
            return "", None
    if len(rows) < int(horizon):
        return "", None
    d, c = rows[int(horizon) - 1]
    return _ymd(d), _f(c)


def score_pending(db_path: str, *, cap: str = "") -> int:
    store = ensure_tables(db_path)
    day_cap = _ymd(cap)
    conn_e = sqlite3.connect(store, timeout=8.0)
    try:
        tape = conn_e.execute(
            """
            SELECT as_of, sid, tag, close
            FROM stabilize_tape WHERE kind=?
            """,
            (KIND,),
        ).fetchall()
    finally:
        conn_e.close()
    if not tape or not os.path.isfile(db_path):
        return 0
    mconn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        store_conn = sqlite3.connect(store, timeout=8.0)
        try:
            for as_of, sid, tag, entry in tape:
                as_of = _ymd(as_of)
                sid = str(sid or "").strip()
                tag = str(tag or "")
                if not as_of or not sid or tag not in TAGS:
                    continue
                if day_cap and as_of > day_cap:
                    continue
                ent = _f(entry)
                for h in SCORE_HORIZONS:
                    check_as, exit_px = _next_trading_close(mconn, sid, as_of, h)
                    if exit_px is None or ent is None or ent <= 0:
                        verdict = "pending"
                        ret = None
                        check_as = check_as or ""
                    else:
                        ret = round((exit_px / ent - 1.0) * 100.0, 3)
                        verdict = "hit" if ret > 0 else "miss"
                    store_conn.execute(
                        """
                        INSERT OR REPLACE INTO stabilize_score(
                            kind, as_of, sid, tag, horizon, check_as_of,
                            entry, exit, ret_pct, verdict
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            KIND,
                            as_of,
                            sid,
                            tag,
                            int(h),
                            check_as,
                            ent,
                            exit_px,
                            ret,
                            verdict,
                        ),
                    )
                    n += 1
            store_conn.commit()
        finally:
            store_conn.close()
    finally:
        mconn.close()
    return n


def recompute_rates(db_path: str) -> Dict[str, Any]:
    store = ensure_tables(db_path)
    now = _now_iso()
    conn = sqlite3.connect(store, timeout=8.0)
    out: Dict[str, Any] = {}
    try:
        conn.execute("DELETE FROM stabilize_rates WHERE kind=?", (KIND,))
        for tag in TAGS:
            for h in SCORE_HORIZONS:
                row = conn.execute(
                    """
                    SELECT
                      SUM(CASE WHEN verdict='hit' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='miss' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='pending' THEN 1 ELSE 0 END),
                      AVG(CASE WHEN verdict IN ('hit','miss') THEN ret_pct END),
                      COUNT(DISTINCT CASE WHEN verdict IN ('hit','miss')
                            THEN as_of END)
                    FROM stabilize_score
                    WHERE kind=? AND tag=? AND horizon=?
                    """,
                    (KIND, tag, h),
                ).fetchone()
                hit = int(row[0] or 0)
                miss = int(row[1] or 0)
                pending = int(row[2] or 0)
                avg_ret = row[3]
                n_days = int(row[4] or 0)
                n = hit + miss
                conn.execute(
                    """
                    INSERT INTO stabilize_rates(
                        kind, tag, horizon, n, hit, miss, pending,
                        n_days, avg_ret, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        tag,
                        int(h),
                        n,
                        hit,
                        miss,
                        pending,
                        n_days,
                        avg_ret,
                        now,
                    ),
                )
                out[f"{tag}_h{h}"] = {
                    "n": n,
                    "hit": hit,
                    "miss": miss,
                    "pending": pending,
                    "n_days": n_days,
                    "avg_ret": avg_ret,
                }
        conn.commit()
    finally:
        conn.close()
    return out


def gate_status(db_path: str) -> Dict[str, Any]:
    """n≥20 且下一版贏現況才可換畫圖規則；永遠不准 promote 成買訊。"""
    rates = recompute_rates(db_path)
    cur = rates.get(f"{TAG_CURRENT}_h{PRIMARY_H}") or {}
    nxt = rates.get(f"{TAG_NEXT}_h{PRIMARY_H}") or {}
    n_cur = int(cur.get("n_days") or 0)
    n_nxt = int(nxt.get("n_days") or 0)
    hit_cur = int(cur.get("hit") or 0)
    miss_cur = int(cur.get("miss") or 0)
    hit_nxt = int(nxt.get("hit") or 0)
    miss_nxt = int(nxt.get("miss") or 0)
    rate_cur = (hit_cur / (hit_cur + miss_cur)) if (hit_cur + miss_cur) else None
    rate_nxt = (hit_nxt / (hit_nxt + miss_nxt)) if (hit_nxt + miss_nxt) else None
    promote_rule = bool(
        n_nxt >= MIN_UNIQUE_DAYS
        and n_cur >= MIN_UNIQUE_DAYS
        and rate_nxt is not None
        and rate_cur is not None
        and rate_nxt > rate_cur
    )
    return {
        "kind": KIND,
        "buy_signal": False,
        "promote_golden_buy": False,
        "promote_paint": False,
        "promote_rule": promote_rule,
        "current": cur,
        "next": nxt,
        "min_n": MIN_UNIQUE_DAYS,
        "note": (
            f"止穩觀察：{TAG_NEXT} n≥{MIN_UNIQUE_DAYS} 且贏 {TAG_CURRENT} → 可換畫圖規則；"
            "永遠不是買訊"
            if promote_rule
            else (
                f"止穩觀察靜默：{TAG_CURRENT} n={n_cur}/{MIN_UNIQUE_DAYS}；"
                f"{TAG_NEXT} 續收／不改買訊"
            )
        ),
    }


def optimize_status_one_liner(db_path: str) -> str:
    return str(confront_summary(db_path).get("line") or "")


def night_tick(db_path: str, as_of: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "wrote": {},
        "scored": 0,
        "gate": {},
        "tags": list(TAGS),
        "buy_signal": False,
    }
    try:
        out["wrote"] = snapshot_day(db_path, as_of=as_of)
        out["scored"] = score_pending(db_path, cap=as_of)
        out["rates"] = recompute_rates(db_path)
        out["gate"] = gate_status(db_path)
    except Exception:
        return out
    return out


def backfill_recent_days(
    db_path: str,
    *,
    trading_days: int = 55,
    end: str = "",
) -> Dict[str, Any]:
    """回填近窗交易日 tape＋前瞻分（官方已收；空名單日不算）。

    逐日走與 night_tick 同一套 snapshot_day（90 曆日母體＋cal60 臉），
    日與日之間釋放 frames，避免 OOM。不准盤中未收當收。
    """
    import gc

    out: Dict[str, Any] = {
        "days": [],
        "scored": 0,
        "gate": {},
        "line": "",
        "buy_signal": False,
    }
    if not db_path or not os.path.isfile(db_path):
        return out
    end_d = _ymd(end)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        if end_d:
            rows = conn.execute(
                """
                SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') AS d
                FROM daily_quotes
                WHERE close > 0
                  AND REPLACE(CAST(date AS TEXT),'-','') <= ?
                ORDER BY d DESC
                LIMIT ?
                """,
                (end_d, max(1, int(trading_days))),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') AS d
                FROM daily_quotes
                WHERE close > 0
                ORDER BY d DESC
                LIMIT ?
                """,
                (max(1, int(trading_days)),),
            ).fetchall()
    finally:
        conn.close()
    days = [_ymd(r[0]) for r in reversed(rows) if _ymd(r[0])]
    for day in days:
        try:
            wrote = snapshot_day(db_path, as_of=day)
            out["days"].append({"as_of": day, "wrote": wrote})
        except Exception:
            out["days"].append({"as_of": day, "wrote": {}, "error": True})
        gc.collect()
    try:
        out["scored"] = score_pending(db_path, cap=end_d or "")
        out["rates"] = recompute_rates(db_path)
        out["gate"] = gate_status(db_path)
        out["line"] = optimize_status_one_liner(db_path)
    except Exception:
        pass
    return out


def confront_summary(db_path: str) -> Dict[str, Any]:
    """現況 vs 緊版一句話用摘要（主窗 h5；空名單日不計入 n_days）。"""
    g = gate_status(db_path)
    cur = g.get("current") or {}
    nxt = g.get("next") or {}
    n_cur = int(cur.get("n_days") or 0)
    n_nxt = int(nxt.get("n_days") or 0)
    hit_cur = int(cur.get("hit") or 0)
    miss_cur = int(cur.get("miss") or 0)
    hit_nxt = int(nxt.get("hit") or 0)
    miss_nxt = int(nxt.get("miss") or 0)
    den_cur = hit_cur + miss_cur
    den_nxt = hit_nxt + miss_nxt
    rate_cur = (hit_cur / den_cur) if den_cur else None
    rate_nxt = (hit_nxt / den_nxt) if den_nxt else None
    beats = bool(
        rate_nxt is not None
        and rate_cur is not None
        and rate_nxt > rate_cur
    )
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    gate_ok = bool(g.get("promote_rule"))
    if gate_ok:
        line = (
            f"止穩◆閘通過：{TAG_NEXT} n_days={n_nxt}≥{need} 且 h{PRIMARY_H} "
            f"勝率贏 {TAG_CURRENT} → 可換畫圖規則；永遠不是買訊。"
        )
    else:
        beat_s = "贏" if beats else ("未贏" if rate_nxt is not None else "尚無可比")
        line = (
            f"止穩◆閘未過：{TAG_CURRENT} n_days={n_cur}/{need}、"
            f"{TAG_NEXT} n_days={n_nxt}/{need}；緊版 h{PRIMARY_H} {beat_s}現況；"
            "非買訊／不改話筒。"
        )
    return {
        "kind": KIND,
        "tag_current": TAG_CURRENT,
        "tag_next": TAG_NEXT,
        "primary_h": PRIMARY_H,
        "min_n": need,
        "n_days_current": n_cur,
        "n_days_next": n_nxt,
        "rate_current": rate_cur,
        "rate_next": rate_nxt,
        "beats_current": beats,
        "gate_ok": gate_ok,
        "buy_signal": False,
        "line": line,
        "gate": g,
    }
