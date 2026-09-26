# -*- coding: utf-8 -*-
"""紅箭頭型低點：正式量化／回測關（過關前仍不是買訊）。

CaryBot 紅箭頭是人工標「可買低點」，沒有公開可複製公式。
這裡量化的是高低卡編碼已對齊的 OHLC 代理：導航圖向上低點箭頭首觸
（``l60``／``l20``），與話筒圖上低點箭頭同一套條件。

規則（AGENTS 第 4／3 條）：
- 獨立交易日 n≥20 **且** 贏黃金買點（leave_zero）基線，才 ``promote_ready``。
- 過關前不准改海選桶、不准當進場、不准改話筒買訊文案。
- 結果落 ``wayne_evolve.db``，不准進對話講過程／％。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "red_arrow_proxy"
TAG_LOW = "nav_low_first"  # l60／l20 首觸
TAG_BASE = "leave_zero"  # 對照基線
SCORE_HORIZONS: Tuple[int, ...] = (1, 5, 10)
# 獨立交易日＋夠廣母體才過關；事件筆數 alone 不准 promote
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
MIN_DISTINCT_SIDS = 100


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def ensure_red_arrow_tables(db_path: str) -> str:
    """落在 evolve 碟；公開 zip 帶不走。"""
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS red_arrow_quant_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                name TEXT DEFAULT '',
                close REAL,
                PRIMARY KEY (kind, as_of, sid, tag)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS red_arrow_quant_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                check_as_of TEXT NOT NULL,
                entry REAL,
                exit REAL,
                ret_pct REAL,
                verdict TEXT NOT NULL,
                PRIMARY KEY (kind, as_of, sid, tag, horizon)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS red_arrow_quant_rates (
                kind TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                n INTEGER NOT NULL,
                hit INTEGER NOT NULL,
                miss INTEGER NOT NULL,
                pending INTEGER NOT NULL,
                avg_ret REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (kind, tag, horizon)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def nav_low_arrow_first_mask(df: pd.DataFrame) -> pd.Series:
    """與 wayne_navigator 向上低點箭頭首觸同一條件：當日新觸 60 低或 20 低。

    不含 near／leave（那些是脫離／貼近，不是紅箭頭型「標低點」主訊號）。
    """
    if df is None or len(df) < 60:
        return pd.Series(dtype=bool)
    hi = pd.to_numeric(df["high"], errors="coerce")
    lo = pd.to_numeric(df["low"], errors="coerce")
    cl = pd.to_numeric(df["close"], errors="coerce")
    n = len(df)
    is_20l = np.zeros(n, dtype=bool)
    is_60l = np.zeros(n, dtype=bool)
    for i in range(n):
        if not np.isfinite(lo.iloc[i]) or not np.isfinite(cl.iloc[i]):
            continue
        wick_l20 = float(lo.iloc[max(0, i - 19) : i + 1].min())
        close_l20 = float(cl.iloc[max(0, i - 19) : i + 1].min())
        wick_l60 = float(lo.iloc[max(0, i - 59) : i + 1].min())
        lv, cv = float(lo.iloc[i]), float(cl.iloc[i])
        is_20l[i] = lv <= wick_l20 * 1.001 or cv <= close_l20 * 1.002
        is_60l[i] = lv <= wick_l60 * 1.001
    was_20l = np.concatenate([[False], is_20l[:-1]])
    was_60l = np.concatenate([[False], is_60l[:-1]])
    first = (is_60l & ~was_60l) | (is_20l & ~was_20l)
    return pd.Series(first, index=df.index)


def _fwd_ret(closes: Sequence[float], i: int, horizon: int) -> Optional[float]:
    j = i + int(horizon)
    if j >= len(closes):
        return None
    try:
        a = float(closes[i])
        b = float(closes[j])
    except (TypeError, ValueError, IndexError):
        return None
    if a <= 0 or b <= 0:
        return None
    return round((b / a - 1.0) * 100.0, 3)


def score_stock_day(
    df: pd.DataFrame, *, as_of: str
) -> List[Dict[str, Any]]:
    """單檔截至 as_of：若當日觸發低點代理或 leave_zero，產出各 horizon 分數列。"""
    from decision_card_signals import leave_zero_from_quote_df

    as_of = _ymd(as_of)
    if df is None or not as_of or "date" not in df.columns:
        return []
    g = df.copy()
    g["date"] = g["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    g = g.sort_values("date").reset_index(drop=True)
    # 訊號只用 as_of 當日以前（含當日）；前向報酬保留 as_of 之後的柱
    hist = g[g["date"] <= as_of].reset_index(drop=True)
    if len(hist) < 60:
        return []
    if str(hist["date"].iloc[-1]) != as_of:
        return []
    lows = nav_low_arrow_first_mask(hist)
    lz_hit = bool(leave_zero_from_quote_df(hist))
    i = len(hist) - 1
    # 對齊全序列 index，才能取 as_of 之後的收盤
    full_dates = g["date"].tolist()
    try:
        fi = full_dates.index(as_of)
    except ValueError:
        return []
    closes = pd.to_numeric(g["close"], errors="coerce").tolist()
    sid = str(hist["stock_id"].iloc[-1] or "") if "stock_id" in hist.columns else ""
    name = str(hist["stock_name"].iloc[-1] or "") if "stock_name" in hist.columns else ""
    rows: List[Dict[str, Any]] = []
    for tag, hit in ((TAG_LOW, bool(lows.iloc[i])), (TAG_BASE, lz_hit)):
        if not hit:
            continue
        entry = float(closes[fi] or 0)
        for h in SCORE_HORIZONS:
            ret = _fwd_ret(closes, fi, h)
            if ret is None:
                verdict = "pending"
            elif ret > 0:
                verdict = "hit"
            else:
                verdict = "miss"
            check_as = ""
            exit_px = None
            if ret is not None and fi + h < len(g):
                check_as = _ymd(g["date"].iloc[fi + h])
                exit_px = float(closes[fi + h])
            rows.append(
                {
                    "kind": KIND,
                    "as_of": as_of,
                    "sid": sid,
                    "name": name,
                    "tag": tag,
                    "horizon": h,
                    "entry": entry,
                    "exit": exit_px,
                    "ret_pct": ret,
                    "verdict": verdict,
                    "check_as_of": check_as,
                }
            )
    return rows


def persist_scores(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    store = ensure_red_arrow_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    n = 0
    try:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO red_arrow_quant_tape(
                    kind, as_of, sid, tag, name, close
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    KIND,
                    r["as_of"],
                    r["sid"],
                    r["tag"],
                    r.get("name") or "",
                    r.get("entry"),
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO red_arrow_quant_score(
                    kind, as_of, sid, tag, horizon, check_as_of,
                    entry, exit, ret_pct, verdict
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    r["as_of"],
                    r["sid"],
                    r["tag"],
                    int(r["horizon"]),
                    r.get("check_as_of") or "",
                    r.get("entry"),
                    r.get("exit"),
                    r.get("ret_pct"),
                    r["verdict"],
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def recompute_rates(db_path: str) -> Dict[str, Any]:
    """彙總 hit／miss；寫 rates。不算 pending 進 n。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store = ensure_red_arrow_tables(db_path)
    now = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(store, timeout=8.0)
    out: Dict[str, Any] = {}
    try:
        conn.execute("DELETE FROM red_arrow_quant_rates WHERE kind=?", (KIND,))
        for tag in (TAG_LOW, TAG_BASE):
            for h in SCORE_HORIZONS:
                row = conn.execute(
                    """
                    SELECT
                      SUM(CASE WHEN verdict='hit' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='miss' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='pending' THEN 1 ELSE 0 END),
                      AVG(CASE WHEN verdict IN ('hit','miss') THEN ret_pct END)
                    FROM red_arrow_quant_score
                    WHERE kind=? AND tag=? AND horizon=?
                    """,
                    (KIND, tag, h),
                ).fetchone()
                hit = int(row[0] or 0)
                miss = int(row[1] or 0)
                pending = int(row[2] or 0)
                avg_ret = float(row[3]) if row[3] is not None else None
                n = hit + miss
                conn.execute(
                    """
                    INSERT OR REPLACE INTO red_arrow_quant_rates(
                        kind, tag, horizon, n, hit, miss, pending, avg_ret, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (KIND, tag, h, n, hit, miss, pending, avg_ret, now),
                )
                out[f"{tag}:h{h}"] = {
                    "n": n,
                    "hit": hit,
                    "miss": miss,
                    "pending": pending,
                    "avg_ret": avg_ret,
                    "hit_rate": (hit / n) if n else None,
                }
        conn.commit()
    finally:
        conn.close()
    return out


def gate_status(db_path: str, *, horizon: int = 5) -> Dict[str, Any]:
    """明確優化狀態：獨立交易日夠不夠、母體夠不夠、有沒有贏 leave_zero。

    對話只准報這層；過關＝才「考慮」改編碼，仍不准自動改買訊。
    """
    store = ensure_red_arrow_tables(db_path)
    h = int(horizon)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        low = conn.execute(
            """
            SELECT n, hit, miss, avg_ret FROM red_arrow_quant_rates
            WHERE kind=? AND tag=? AND horizon=?
            """,
            (KIND, TAG_LOW, h),
        ).fetchone()
        base = conn.execute(
            """
            SELECT n, hit, miss, avg_ret FROM red_arrow_quant_rates
            WHERE kind=? AND tag=? AND horizon=?
            """,
            (KIND, TAG_BASE, h),
        ).fetchone()

        def _days(tag: str) -> int:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT as_of) FROM red_arrow_quant_score
                WHERE kind=? AND tag=? AND horizon=?
                  AND verdict IN ('hit','miss')
                """,
                (KIND, tag, h),
            ).fetchone()
            return int(row[0] or 0)

        def _sids(tag: str) -> int:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT sid) FROM red_arrow_quant_score
                WHERE kind=? AND tag=? AND horizon=?
                  AND verdict IN ('hit','miss')
                """,
                (KIND, tag, h),
            ).fetchone()
            return int(row[0] or 0)

        low_days, base_days = _days(TAG_LOW), _days(TAG_BASE)
        low_sids, base_sids = _sids(TAG_LOW), _sids(TAG_BASE)
    finally:
        conn.close()

    def _pack(row):
        if not row:
            return {"n": 0, "hit": 0, "miss": 0, "avg_ret": None, "hit_rate": None}
        n, hit, miss, avg = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0), row[3]
        return {
            "n": n,
            "hit": hit,
            "miss": miss,
            "avg_ret": float(avg) if avg is not None else None,
            "hit_rate": (hit / n) if n else None,
        }

    low_s = _pack(low)
    base_s = _pack(base)
    low_s["unique_days"] = low_days
    base_s["unique_days"] = base_days
    low_s["distinct_sids"] = low_sids
    base_s["distinct_sids"] = base_sids
    n_ok = (
        low_days >= MIN_UNIQUE_DAYS
        and base_days >= MIN_UNIQUE_DAYS
        and low_sids >= MIN_DISTINCT_SIDS
        and base_sids >= MIN_DISTINCT_SIDS
    )
    beat = False
    if (
        low_s["hit_rate"] is not None
        and base_s["hit_rate"] is not None
        and low_s["n"] >= OPTIMIZE_MIN_N
        and base_s["n"] >= OPTIMIZE_MIN_N
    ):
        if low_s["hit_rate"] > base_s["hit_rate"]:
            beat = True
        elif (
            low_s["hit_rate"] == base_s["hit_rate"]
            and low_s["avg_ret"] is not None
            and base_s["avg_ret"] is not None
            and low_s["avg_ret"] > base_s["avg_ret"]
        ):
            beat = True
    ready = bool(n_ok and beat)
    return {
        "kind": KIND,
        "horizon": h,
        "low": low_s,
        "leave_zero": base_s,
        "n_ok": n_ok,
        "beats_leave_zero": beat,
        "promote_ready": ready,
        "min_n": OPTIMIZE_MIN_N,
        "min_unique_days": MIN_UNIQUE_DAYS,
        "min_distinct_sids": MIN_DISTINCT_SIDS,
        "note": (
            "可考慮當買訊（仍須人工確認才改編碼）"
            if ready
            else "還沒過關：紅箭頭代理仍不是買訊"
        ),
    }


def promote_ready(db_path: str, *, horizon: int = 5) -> bool:
    """唯一放行閘：True 才准討論改買訊；False＝維持紅箭頭不是買訊。"""
    return bool(gate_status(db_path, horizon=horizon).get("promote_ready"))


def night_sample_tick(
    db_path: str,
    *,
    as_of: str = "",
    limit: int = 40,
) -> Dict[str, Any]:
    """盤後默默取樣：掃有限檔、寫分數、重算 rates。失敗不擋 night_review。"""
    stats = {"wrote": 0, "promote": False, "n_low": 0, "n_lz": 0}
    if not db_path or not os.path.isfile(db_path):
        return stats
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            if not as_of:
                row = conn.execute(
                    "SELECT MAX(replace(CAST(date AS TEXT),'-','')) FROM daily_quotes"
                ).fetchone()
                as_of = _ymd(row[0] if row else "")
            sids = conn.execute(
                """
                SELECT stock_id, COALESCE(stock_name,'')
                FROM stock_universe
                WHERE is_active=1 AND length(stock_id)=4
                  AND stock_id GLOB '[0-9][0-9][0-9][0-9]'
                  AND UPPER(COALESCE(asset_type,'')) IN ('STOCK','KY','')
                ORDER BY stock_id
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        if not as_of or not sids:
            return stats
        wrote = 0
        for sid, name in sids:
            conn = sqlite3.connect(db_path, timeout=8.0)
            try:
                q = pd.read_sql_query(
                    """
                    SELECT replace(CAST(date AS TEXT),'-','') AS date,
                           open, high, low, close, volume
                    FROM daily_quotes
                    WHERE stock_id=? AND close>0
                    ORDER BY date
                    """,
                    conn,
                    params=(str(sid),),
                )
            finally:
                conn.close()
            if q.empty or len(q) < 80:
                continue
            q["stock_id"] = str(sid)
            q["stock_name"] = str(name or "")
            rows = score_stock_day(q, as_of=as_of)
            if rows:
                wrote += persist_scores(db_path, rows)
        recompute_rates(db_path)
        st = gate_status(db_path, horizon=5)
        stats["wrote"] = wrote
        stats["promote"] = bool(st.get("promote_ready"))
        stats["n_low"] = int((st.get("low") or {}).get("n") or 0)
        stats["n_lz"] = int((st.get("leave_zero") or {}).get("n") or 0)
    except Exception:
        return stats
    return stats
