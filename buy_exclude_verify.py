# -*- coding: utf-8 -*-
"""買點排除層靜默對質：lz_raw／v2／v3 候選用官方柱前瞻報酬比較。

接 judge_tape.snapshot_button_lists → night_tick；可重複跑、可落檔。
母體：收盤 < 20000（含興櫃）；分價層記 tape。
不准假資料；盤中未收不當收。不准改 leave_zero／黃金買點公式。
對話只准報明確優化狀態（n 夠／贏現況／要不要改那一條）。
v2＝現況排除（結構破底＋鎖跌停＋量縮等，已接 paint）。
v3＝再生候選（收紅／收在振幅中上半），過閘才准接到 paint。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "buy_exclude"
TAG_RAW = "lz_raw"
TAG_V2 = "lz_v2"
TAG_V3_CLOSE_UP = "lz_v3_close_up"
TAG_V3_RANGE = "lz_v3_range_upper"
# 靜默對照：live 已不排除 near_h20；仍記 cohort 便宜對質
TAG_CTRL_NEAR_H20 = "lz_ctrl_near_h20"
TAGS: Tuple[str, ...] = (
    TAG_RAW,
    TAG_V2,
    TAG_V3_CLOSE_UP,
    TAG_V3_RANGE,
    TAG_CTRL_NEAR_H20,
)
SCORE_HORIZONS: Tuple[int, ...] = (1, 5, 10)
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
CLOSE_CAP = 20000.0
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


def price_tier(close: Any) -> str:
    c = _f(close)
    if c is None or c <= 0:
        return "na"
    if c < 10:
        return "penny"
    if c < 50:
        return "low"
    if c < 200:
        return "mid"
    if c < 1000:
        return "high"
    if c < 5000:
        return "xhigh"
    return "ultra"


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS buy_exclude_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                name TEXT DEFAULT '',
                close REAL,
                tier TEXT DEFAULT '',
                emerging INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, as_of, sid, tag)
            );
            CREATE TABLE IF NOT EXISTS buy_exclude_score (
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
            CREATE TABLE IF NOT EXISTS buy_exclude_rates (
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


def _v3_close_up(df, i: int = -1) -> bool:
    """再生候選：收紅（收 > 開）。缺柱＝不通過。"""
    if df is None or len(df) < 1:
        return False
    try:
        row = df.iloc[i]
        o = _f(row["open"] if "open" in df.columns else None)
        c = _f(row["close"] if "close" in df.columns else None)
    except Exception:
        return False
    if o is None or c is None or o <= 0 or c <= 0:
        return False
    return bool(c > o)


def _v3_range_upper(df, i: int = -1) -> bool:
    """再生候選：收在當日振幅中上半（含中點）。缺柱／零振幅＝不通過。"""
    if df is None or len(df) < 1:
        return False
    try:
        row = df.iloc[i]
        h = _f(row["high"] if "high" in df.columns else None)
        l = _f(row["low"] if "low" in df.columns else None)
        c = _f(row["close"] if "close" in df.columns else None)
    except Exception:
        return False
    if None in (h, l, c) or c <= 0 or h is None or l is None:
        return False
    if h <= l:
        return False
    mid = (h + l) / 2.0
    return bool(c >= mid)


def tags_for_frame(
    df,
    *,
    emerging: bool = False,
    quote_source: str = "",
) -> List[str]:
    """當日最後一根若 leave_zero 且收 < CLOSE_CAP，回傳應記的 tag 列表。"""
    from decision_card_signals import leave_zero_from_quote_df
    from buy_exclude import is_near_h20, should_exclude_buy

    if df is None or len(df) < 2:
        return []
    try:
        c = _f(df["close"].iloc[-1])
    except Exception:
        return []
    if c is None or c <= 0 or c >= CLOSE_CAP:
        return []
    try:
        if not bool(leave_zero_from_quote_df(df)):
            return []
    except Exception:
        return []
    out = [TAG_RAW]
    # 靜默對照臂：near_h20 命中仍記，不擋 live paint／v2
    if is_near_h20(df):
        out.append(TAG_CTRL_NEAR_H20)
    if should_exclude_buy(df, emerging=emerging, quote_source=quote_source):
        return out
    out.append(TAG_V2)
    if _v3_close_up(df):
        out.append(TAG_V3_CLOSE_UP)
    if _v3_range_upper(df):
        out.append(TAG_V3_RANGE)
    return out


def persist_tape(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    n = 0
    try:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO buy_exclude_tape(
                    kind, as_of, sid, tag, name, close, tier, emerging
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    r["as_of"],
                    r["sid"],
                    r["tag"],
                    str(r.get("name") or "")[:40],
                    r.get("close"),
                    str(r.get("tier") or ""),
                    1 if r.get("emerging") else 0,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def snapshot_day(db_path: str, as_of: str = "") -> Dict[str, int]:
    """盤後：掃 leave_zero 母體（<20000＋興櫃），凍 raw／v2／v3 標。"""
    counts = {t: 0 for t in TAGS}
    if not db_path or not os.path.isfile(db_path):
        return counts
    day = _ymd(as_of)
    try:
        from screening_engine import ScreeningEngine

        eng = ScreeningEngine(db_path)
        if not day:
            day = _ymd(eng.get_latest_trading_date())
        frames, em_ids = eng._load_profit_scan_frames(day)
    except Exception:
        return counts
    if not day or not frames:
        return counts
    rows: List[Dict[str, Any]] = []
    for sid, df in (frames or {}).items():
        sid_s = str(sid or "").strip()
        if not sid_s or df is None or len(df) < 2:
            continue
        em = sid_s in (em_ids or set())
        src = "emerging_quotes" if em else ""
        try:
            from wayne_navigator import frame_for_cal60_profit

            profit_df = frame_for_cal60_profit(df, db_path)
        except Exception:
            profit_df = df
        tags = tags_for_frame(profit_df, emerging=em, quote_source=src)
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
        tier = price_tier(close)
        for tag in tags:
            rows.append(
                {
                    "as_of": day,
                    "sid": sid_s,
                    "tag": tag,
                    "name": name,
                    "close": close,
                    "tier": tier,
                    "emerging": em,
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
    *,
    emerging: bool = False,
) -> Tuple[str, Optional[float]]:
    table = "emerging_quotes" if emerging else "daily_quotes"
    try:
        rows = conn.execute(
            f"""
            SELECT REPLACE(CAST(date AS TEXT),'-','') AS d, close
            FROM {table}
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
    """對已凍 tape 補前瞻 1／5／10 日官方收。未齊＝pending。"""
    store = ensure_tables(db_path)
    day_cap = _ymd(cap)
    conn_e = sqlite3.connect(store, timeout=8.0)
    try:
        tape = conn_e.execute(
            """
            SELECT as_of, sid, tag, close, emerging
            FROM buy_exclude_tape WHERE kind=?
            """,
            (KIND,),
        ).fetchall()
    finally:
        conn_e.close()
    if not tape:
        return 0
    if not os.path.isfile(db_path):
        return 0
    mconn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        store_conn = sqlite3.connect(store, timeout=8.0)
        try:
            for as_of, sid, tag, entry, emerging in tape:
                as_of = _ymd(as_of)
                sid = str(sid or "").strip()
                tag = str(tag or "")
                if not as_of or not sid or tag not in TAGS:
                    continue
                if day_cap and as_of > day_cap:
                    continue
                ent = _f(entry)
                for h in SCORE_HORIZONS:
                    check_as, exit_px = _next_trading_close(
                        mconn, sid, as_of, h, emerging=bool(emerging)
                    )
                    if exit_px is None or ent is None or ent <= 0:
                        verdict = "pending"
                        ret = None
                        check_as = check_as or ""
                    else:
                        ret = round((exit_px / ent - 1.0) * 100.0, 3)
                        verdict = "hit" if ret > 0 else "miss"
                    store_conn.execute(
                        """
                        INSERT OR REPLACE INTO buy_exclude_score(
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
        conn.execute("DELETE FROM buy_exclude_rates WHERE kind=?", (KIND,))
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
                    FROM buy_exclude_score
                    WHERE kind=? AND tag=? AND horizon=?
                    """,
                    (KIND, tag, h),
                ).fetchone()
                hit = int(row[0] or 0)
                miss = int(row[1] or 0)
                pending = int(row[2] or 0)
                avg_ret = float(row[3]) if row[3] is not None else None
                n_days = int(row[4] or 0)
                n = hit + miss
                conn.execute(
                    """
                    INSERT OR REPLACE INTO buy_exclude_rates(
                        kind, tag, horizon, n, hit, miss, pending,
                        n_days, avg_ret, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        tag,
                        h,
                        n,
                        hit,
                        miss,
                        pending,
                        n_days,
                        avg_ret,
                        now,
                    ),
                )
                out[f"{tag}:h{h}"] = {
                    "n": n,
                    "hit": hit,
                    "miss": miss,
                    "pending": pending,
                    "n_days": n_days,
                    "avg_ret": avg_ret,
                    "hit_rate": (hit / n) if n else None,
                }
        conn.commit()
    finally:
        conn.close()
    return out


def _pack_rate(row) -> Dict[str, Any]:
    if not row:
        return {
            "n": 0,
            "hit": 0,
            "miss": 0,
            "n_days": 0,
            "avg_ret": None,
            "hit_rate": None,
        }
    n, hit, miss, n_days, avg = (
        int(row[0] or 0),
        int(row[1] or 0),
        int(row[2] or 0),
        int(row[3] or 0),
        row[4],
    )
    return {
        "n": n,
        "hit": hit,
        "miss": miss,
        "n_days": n_days,
        "avg_ret": float(avg) if avg is not None else None,
        "hit_rate": (hit / n) if n else None,
    }


def _beats(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """a 贏 b：hit_rate 較高；並列比 avg_ret。"""
    if a.get("hit_rate") is None or b.get("hit_rate") is None:
        return False
    if int(a.get("n") or 0) < OPTIMIZE_MIN_N or int(b.get("n") or 0) < OPTIMIZE_MIN_N:
        return False
    if a["hit_rate"] > b["hit_rate"]:
        return True
    if a["hit_rate"] == b["hit_rate"]:
        ar, br = a.get("avg_ret"), b.get("avg_ret")
        if ar is not None and br is not None and ar > br:
            return True
    return False


def gate_status(db_path: str, *, horizon: int = PRIMARY_H) -> Dict[str, Any]:
    """明確優化狀態。v2 已是話筒現況；只問 v3 是否贏 v2 且 n 夠。

    promote_paint＝v3 過閘才准接到 paint／名單（仍須合 main）。
    不准自動改黃金買點公式。
    """
    store = ensure_tables(db_path)
    h = int(horizon)
    conn = sqlite3.connect(store, timeout=8.0)
    by: Dict[str, Dict[str, Any]] = {}
    try:
        for tag in TAGS:
            row = conn.execute(
                """
                SELECT n, hit, miss, n_days, avg_ret
                FROM buy_exclude_rates
                WHERE kind=? AND tag=? AND horizon=?
                """,
                (KIND, tag, h),
            ).fetchone()
            by[tag] = _pack_rate(row)
    finally:
        conn.close()
    raw, v2 = by[TAG_RAW], by[TAG_V2]
    v3_up, v3_rg = by[TAG_V3_CLOSE_UP], by[TAG_V3_RANGE]
    n_v2 = int(v2.get("n_days") or 0)
    n_ok_v2 = n_v2 >= MIN_UNIQUE_DAYS
    v2_beats_raw = bool(n_ok_v2 and _beats(v2, raw))
    # 再生：兩個候選各自對 v2
    best_tag = ""
    best = None
    for tag, pack in ((TAG_V3_CLOSE_UP, v3_up), (TAG_V3_RANGE, v3_rg)):
        if int(pack.get("n_days") or 0) < MIN_UNIQUE_DAYS:
            continue
        if not _beats(pack, v2):
            continue
        if best is None or (pack.get("hit_rate") or 0) > (best.get("hit_rate") or 0):
            best = pack
            best_tag = tag
        elif (
            pack.get("hit_rate") == best.get("hit_rate")
            and (pack.get("avg_ret") or -1e18) > (best.get("avg_ret") or -1e18)
        ):
            best = pack
            best_tag = tag
    promote = bool(best_tag and best is not None)
    return {
        "kind": KIND,
        "horizon": h,
        "close_cap": CLOSE_CAP,
        "raw": raw,
        "v2": v2,
        "v3_close_up": v3_up,
        "v3_range_upper": v3_rg,
        "n_ok": n_ok_v2,
        "v2_beats_raw": v2_beats_raw,
        "v3_best_tag": best_tag,
        "v3_beats_v2": promote,
        "promote_paint": promote,
        "promote_golden_buy": False,
        "min_n": MIN_UNIQUE_DAYS,
        "note": (
            f"v3 {best_tag} n≥{MIN_UNIQUE_DAYS} 且贏 v2 → 可接到 paint／名單；不改黃金買點公式"
            if promote
            else (
                f"買點排除靜默對質：v2 n={n_v2}/{MIN_UNIQUE_DAYS}；"
                "v3 續收／尚未改碼"
            )
        ),
    }


def optimize_status_one_liner(db_path: str) -> str:
    """對話唯一准講的一句（明確優化狀態）。"""
    g = gate_status(db_path)
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    n = int((g.get("v2") or {}).get("n_days") or 0)
    if g.get("promote_paint"):
        return (
            f"買點排除 v3：{g.get('v3_best_tag')} n≥{need} 且贏 v2 → "
            "可接到藍▲ paint／名單；黃金買點公式不動。"
        )
    return (
        f"買點排除靜默對質：v2 n={n}/{need}；v3 續收／尚未改碼。"
    )


def night_tick(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """接默默落檔節奏。失敗吞掉，不准擋海選／勝率。"""
    out: Dict[str, Any] = {
        "wrote": {},
        "scored": 0,
        "gate": {},
        "tags": list(TAGS),
    }
    try:
        out["wrote"] = snapshot_day(db_path, as_of=as_of)
        out["scored"] = score_pending(db_path, cap=as_of)
        out["rates"] = recompute_rates(db_path)
        out["gate"] = gate_status(db_path)
    except Exception:
        return out
    return out


def backfill_recent_days(db_path: str, *, trading_days: int = 45) -> Dict[str, Any]:
    """可重複：回填近窗交易日 tape＋分數（開機／手動一次）。"""
    out: Dict[str, Any] = {"days": [], "scored": 0, "gate": {}}
    if not db_path or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
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
            continue
    try:
        out["scored"] = score_pending(db_path)
        out["rates"] = recompute_rates(db_path)
        out["gate"] = gate_status(db_path)
    except Exception:
        pass
    return out
