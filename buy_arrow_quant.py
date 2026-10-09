# -*- coding: utf-8 -*-
"""買點藍▲紅框（leave_zero）精準度量：同帶首根 vs 後續。

對齊導航 ``_nav_buy_arrow_alphas``：連續交易日柱（index 差 1）為同一段；
每段第一根＝清楚箭、後面＝淡箭。本模組用官方 OHLC 前向報酬量化兩者，
並對照「全畫（現況）」基線。

規則（AGENTS 第 3／4／13 條）：
- 獨立交易日 n≥20 **且** 候選贏現況（all_painted）才 ``promote_ready``。
- 過關前不准改 leave_zero 公式、不准改海選桶、不准當進場買訊。
- 可改的只有呈現／過濾／淡化（與 #540 同軌）；結果落 ``wayne_evolve.db``。
- 對話只報閘狀態一句；過程／％不准講。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "buy_arrow_band"
TAG_FIRST = "band_first"
TAG_FOLLOW = "band_follow"
TAG_ALL = "all_painted"  # 現況＝畫出的全部 leave_zero（含淡後續）
# 下一版靜默候選（§13 再生）：若首根持續贏全畫 → 考慮只畫同帶首根（仍不准改公式）
NEXT_PRESENTATION = "first_only_paint"
SCORE_HORIZONS: Tuple[int, ...] = (1, 5, 10)
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
MIN_DISTINCT_SIDS = 80


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def ensure_buy_arrow_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS buy_arrow_quant_tape (
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
            CREATE TABLE IF NOT EXISTS buy_arrow_quant_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                check_as_of TEXT NOT NULL,
                entry REAL,
                exit REAL,
                ret_pct REAL,
                false_break INTEGER,
                verdict TEXT NOT NULL,
                PRIMARY KEY (kind, as_of, sid, tag, horizon)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS buy_arrow_quant_rates (
                kind TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                n INTEGER NOT NULL,
                hit INTEGER NOT NULL,
                miss INTEGER NOT NULL,
                pending INTEGER NOT NULL,
                false_break INTEGER NOT NULL,
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


def band_role_map(buy_is: Sequence[int]) -> Dict[int, str]:
    """可見窗買點 index → band_first／band_follow（與導航淡化同段定義）。"""
    out: Dict[int, str] = {}
    idxs: List[int] = []
    for i in buy_is:
        try:
            idxs.append(int(i))
        except (TypeError, ValueError):
            continue
    if not idxs:
        return out
    idxs = sorted(set(idxs))
    prev = None
    for ii in idxs:
        if prev is None or ii - prev > 1:
            out[ii] = TAG_FIRST
        else:
            out[ii] = TAG_FOLLOW
        prev = ii
    return out


def painted_buy_indices(df: pd.DataFrame) -> List[int]:
    """與導航畫標同源：paint_leave_zero_indices（公式＋排除層）。"""
    if df is None or len(df) < 2:
        return []
    try:
        from buy_exclude import paint_leave_zero_indices

        return [int(i) for i in paint_leave_zero_indices(df)]
    except Exception:
        try:
            from decision_card_signals import leave_zero_bar_indices

            return [int(i) for i in leave_zero_bar_indices(df)]
        except Exception:
            return []


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


def _false_break(
    closes: Sequence[float], i: int, horizon: int, *, entry: float
) -> Optional[int]:
    """後 N 日內任一根收盤跌破進場收＝假突破（1）；否則 0；柱不夠＝None。"""
    j = i + int(horizon)
    if j >= len(closes) or entry <= 0:
        return None
    for k in range(i + 1, j + 1):
        try:
            c = float(closes[k])
        except (TypeError, ValueError, IndexError):
            return None
        if c > 0 and c < entry:
            return 1
    return 0


def score_stock_day(df: pd.DataFrame, *, as_of: str) -> List[Dict[str, Any]]:
    """單檔截至 as_of：若當日有畫買點箭，依同帶角色產出各 horizon 分數。"""
    as_of = _ymd(as_of)
    if df is None or not as_of or "date" not in df.columns:
        return []
    g = df.copy()
    g["date"] = g["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    g = g.sort_values("date").reset_index(drop=True)
    hist = g[g["date"] <= as_of].reset_index(drop=True)
    if len(hist) < 60:
        return []
    if str(hist["date"].iloc[-1]) != as_of:
        return []
    painted = painted_buy_indices(hist)
    if not painted:
        return []
    roles = band_role_map(painted)
    i = len(hist) - 1
    if i not in roles:
        return []
    full_dates = g["date"].tolist()
    try:
        fi = full_dates.index(as_of)
    except ValueError:
        return []
    closes = pd.to_numeric(g["close"], errors="coerce").tolist()
    sid = str(hist["stock_id"].iloc[-1] or "") if "stock_id" in hist.columns else ""
    name = str(hist["stock_name"].iloc[-1] or "") if "stock_name" in hist.columns else ""
    entry = float(closes[fi] or 0)
    role = roles[i]
    tags = (TAG_ALL, role)
    rows: List[Dict[str, Any]] = []
    for tag in tags:
        for h in SCORE_HORIZONS:
            ret = _fwd_ret(closes, fi, h)
            fb = _false_break(closes, fi, h, entry=entry)
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
                    "false_break": fb,
                    "verdict": verdict,
                    "check_as_of": check_as,
                }
            )
    return rows


def persist_scores(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    store = ensure_buy_arrow_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    n = 0
    try:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO buy_arrow_quant_tape(
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
                INSERT OR REPLACE INTO buy_arrow_quant_score(
                    kind, as_of, sid, tag, horizon, check_as_of,
                    entry, exit, ret_pct, false_break, verdict
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
                    r.get("false_break"),
                    r["verdict"],
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def recompute_rates(db_path: str) -> Dict[str, Any]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store = ensure_buy_arrow_tables(db_path)
    now = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(store, timeout=8.0)
    out: Dict[str, Any] = {}
    try:
        conn.execute("DELETE FROM buy_arrow_quant_rates WHERE kind=?", (KIND,))
        for tag in (TAG_FIRST, TAG_FOLLOW, TAG_ALL):
            for h in SCORE_HORIZONS:
                row = conn.execute(
                    """
                    SELECT
                      SUM(CASE WHEN verdict='hit' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='miss' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='pending' THEN 1 ELSE 0 END),
                      AVG(CASE WHEN verdict IN ('hit','miss') THEN ret_pct END),
                      SUM(CASE WHEN false_break=1 AND verdict IN ('hit','miss')
                               THEN 1 ELSE 0 END)
                    FROM buy_arrow_quant_score
                    WHERE kind=? AND tag=? AND horizon=?
                    """,
                    (KIND, tag, h),
                ).fetchone()
                hit = int(row[0] or 0)
                miss = int(row[1] or 0)
                pending = int(row[2] or 0)
                avg_ret = float(row[3]) if row[3] is not None else None
                fb = int(row[4] or 0)
                n = hit + miss
                conn.execute(
                    """
                    INSERT OR REPLACE INTO buy_arrow_quant_rates(
                        kind, tag, horizon, n, hit, miss, pending,
                        false_break, avg_ret, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (KIND, tag, h, n, hit, miss, pending, fb, avg_ret, now),
                )
                out[f"{tag}:h{h}"] = {
                    "n": n,
                    "hit": hit,
                    "miss": miss,
                    "pending": pending,
                    "false_break": fb,
                    "avg_ret": avg_ret,
                    "hit_rate": (hit / n) if n else None,
                    "false_break_rate": (fb / n) if n else None,
                }
        conn.commit()
    finally:
        conn.close()
    return out


def _pack_rate_row(row) -> Dict[str, Any]:
    if not row:
        return {
            "n": 0,
            "hit": 0,
            "miss": 0,
            "avg_ret": None,
            "hit_rate": None,
            "false_break": 0,
            "false_break_rate": None,
        }
    n, hit, miss, avg, fb = (
        int(row[0] or 0),
        int(row[1] or 0),
        int(row[2] or 0),
        row[3],
        int(row[4] or 0),
    )
    return {
        "n": n,
        "hit": hit,
        "miss": miss,
        "avg_ret": float(avg) if avg is not None else None,
        "hit_rate": (hit / n) if n else None,
        "false_break": fb,
        "false_break_rate": (fb / n) if n else None,
    }


def _beats(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """a 贏 b：先比 hit_rate，平手比更高 avg_ret、更低假突破率。"""
    if a.get("hit_rate") is None or b.get("hit_rate") is None:
        return False
    if a["n"] < OPTIMIZE_MIN_N or b["n"] < OPTIMIZE_MIN_N:
        return False
    if a["hit_rate"] > b["hit_rate"]:
        return True
    if a["hit_rate"] < b["hit_rate"]:
        return False
    ar, br = a.get("avg_ret"), b.get("avg_ret")
    if ar is not None and br is not None and ar > br:
        return True
    if ar is not None and br is not None and ar < br:
        return False
    fa, fb = a.get("false_break_rate"), b.get("false_break_rate")
    if fa is not None and fb is not None and fa < fb:
        return True
    return False


def gate_status(db_path: str, *, horizon: int = 5) -> Dict[str, Any]:
    """明確優化狀態：n 夠不夠、首根有沒有贏後續／贏全畫現況。

    promote_ready＝可考慮「只強調首根／再淡後續」呈現；仍不准改 leave_zero 公式。
    """
    store = ensure_buy_arrow_tables(db_path)
    h = int(horizon)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        def _rate(tag: str):
            return conn.execute(
                """
                SELECT n, hit, miss, avg_ret, false_break FROM buy_arrow_quant_rates
                WHERE kind=? AND tag=? AND horizon=?
                """,
                (KIND, tag, h),
            ).fetchone()

        def _days(tag: str) -> int:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT as_of) FROM buy_arrow_quant_score
                WHERE kind=? AND tag=? AND horizon=?
                  AND verdict IN ('hit','miss')
                """,
                (KIND, tag, h),
            ).fetchone()
            return int(row[0] or 0)

        def _sids(tag: str) -> int:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT sid) FROM buy_arrow_quant_score
                WHERE kind=? AND tag=? AND horizon=?
                  AND verdict IN ('hit','miss')
                """,
                (KIND, tag, h),
            ).fetchone()
            return int(row[0] or 0)

        first_s = _pack_rate_row(_rate(TAG_FIRST))
        follow_s = _pack_rate_row(_rate(TAG_FOLLOW))
        all_s = _pack_rate_row(_rate(TAG_ALL))
        for tag, pack in (
            (TAG_FIRST, first_s),
            (TAG_FOLLOW, follow_s),
            (TAG_ALL, all_s),
        ):
            pack["unique_days"] = _days(tag)
            pack["distinct_sids"] = _sids(tag)
    finally:
        conn.close()

    n_ok = (
        first_s["unique_days"] >= MIN_UNIQUE_DAYS
        and all_s["unique_days"] >= MIN_UNIQUE_DAYS
        and first_s["distinct_sids"] >= MIN_DISTINCT_SIDS
        and all_s["distinct_sids"] >= MIN_DISTINCT_SIDS
    )
    first_beats_follow = _beats(first_s, follow_s)
    first_beats_all = _beats(first_s, all_s)
    # 呈現閘：首根同時贏後續（證淡化）且贏全畫（證可再收呈現）
    ready = bool(n_ok and first_beats_follow and first_beats_all)
    return {
        "kind": KIND,
        "horizon": h,
        "band_first": first_s,
        "band_follow": follow_s,
        "all_painted": all_s,
        "n_ok": n_ok,
        "first_beats_follow": first_beats_follow,
        "first_beats_all": first_beats_all,
        "promote_ready": ready,
        "next_presentation": NEXT_PRESENTATION,
        "min_n": OPTIMIZE_MIN_N,
        "min_unique_days": MIN_UNIQUE_DAYS,
        "min_distinct_sids": MIN_DISTINCT_SIDS,
        "note": (
            "可考慮再收呈現（只強調同帶首根／再淡後續；仍不准改 leave_zero 公式）"
            if ready
            else "還沒過關：維持現況淡化，不准改買訊／公式"
        ),
    }


def promote_ready(db_path: str, *, horizon: int = 5) -> bool:
    return bool(gate_status(db_path, horizon=horizon).get("promote_ready"))


def night_sample_tick(
    db_path: str,
    *,
    as_of: str = "",
    limit: int = 40,
) -> Dict[str, Any]:
    """盤後默默取樣：掃有限檔、寫分數、重算 rates。失敗不擋 night_review。"""
    stats = {"wrote": 0, "promote": False, "n_first": 0, "n_all": 0}
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
        stats["n_first"] = int((st.get("band_first") or {}).get("n") or 0)
        stats["n_all"] = int((st.get("all_painted") or {}).get("n") or 0)
    except Exception:
        return stats
    return stats
