# -*- coding: utf-8 -*-
"""紅箭頭型低點：正式量化／回測關（過關前仍不是買訊）。

CaryBot 紅箭頭是人工標「可買低點」，沒有公開可複製公式。
這裡量化的是高低卡編碼已對齊的 OHLC 代理：導航圖向上低點箭頭首觸
（``l60``／``l20``），與話筒圖上低點箭頭同一套條件。

度量（可重複）：
- 官方柱後續報酬（h1／h5／h10）
- 假突破（後 N 日內任一根收盤跌破進場收；#547 口徑）
- 對照 leave_zero（黃金買點現況）、無箭頭、#548 ma60_vol、以及本輪過濾候選

規則（AGENTS 第 4／3／13 條）：
- 獨立交易日 n≥20 **且** 贏黃金買點（leave_zero）基線，**且** 假突破相對
  #547 未過濾基線明顯下降，**且** 能量化優於 #548，才 ``promote_ready``
  （仍須人工確認才改買訊）。
- 過關前不准改海選桶、不准當進場、不准改話筒買訊文案／leave_zero 公式。
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
TAG_LOW = "nav_low_first"  # l60／l20 首觸（#547 未過濾基線）
TAG_BASE = "leave_zero"  # 對照：現況買訊基線
TAG_NONE = "no_arrow"  # 對照：當日無低點首觸且無 leave_zero
# #548 已收軌（對照用；本輪候選須能量化優於它才收）
TAG_PREV = "nav_low_first_ma60_vol"
# 本輪假突破下降候選（#548 再生 hold_low_confirm）
TAG_FILTER = "nav_low_first_hold_low_confirm"
SCORE_HORIZONS: Tuple[int, ...] = (1, 5, 10)
# 獨立交易日＋夠廣母體才過關；事件筆數 alone 不准 promote
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
MIN_DISTINCT_SIDS = 100
# 假突破「明顯下降」：絕對降幅（h5 主閘；h1 佐證）；相對 #547 未過濾
MIN_FB_DROP = 0.03
# 相對 #548：假突破至少再降一點，且 hit／avg 不輸超過容差
MIN_FB_DROP_VS_PREV = 0.01
# §13 再生：hold／ma60×hold 本機假突破均升 → 下一版改試 ma60＋上半收（仍不當買訊）
NEXT_CANDIDATE = "nav_low_first_ma60_upper"


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _ensure_col(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


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
                false_break INTEGER,
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
                false_break INTEGER NOT NULL DEFAULT 0,
                avg_ret REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (kind, tag, horizon)
            )
            """
        )
        _ensure_col(conn, "red_arrow_quant_score", "false_break", "INTEGER")
        _ensure_col(conn, "red_arrow_quant_rates", "false_break", "INTEGER NOT NULL DEFAULT 0")
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


def nav_low_ma60_vol_mask(df: pd.DataFrame) -> pd.Series:
    """#548 假突破候選：低點首觸＋收盤落在 MA60 帶＋量不過熱。

    條件（只用當日及以前官方 OHLC／量）：
    - ``nav_low_arrow_first_mask`` 為真
    - 收盤 ≥ 近 60 收盤均 × 0.95（遠離長期均＝急殺，假突破偏高）
    - 近 5 交易日收盤跌幅 > −8%（排除瀑布）
    - 當日量 ≤ 近 20 日均量 × 1.25（排除恐慌放量續跌）

    過關前仍不是買訊；本輪保留作對照軌。
    """
    first = nav_low_arrow_first_mask(df)
    if first.empty or not bool(first.any()):
        return first
    cl = pd.to_numeric(df["close"], errors="coerce")
    vo = pd.to_numeric(df["volume"], errors="coerce")
    n = len(df)
    ok = np.zeros(n, dtype=bool)
    for i in range(n):
        if not bool(first.iloc[i]):
            continue
        c = float(cl.iloc[i]) if np.isfinite(cl.iloc[i]) else 0.0
        if c <= 0:
            continue
        ma60 = float(cl.iloc[max(0, i - 59) : i + 1].mean())
        if ma60 <= 0 or c < ma60 * 0.95:
            continue
        if i >= 5:
            c5 = float(cl.iloc[i - 5])
            if c5 > 0 and (c / c5 - 1.0) * 100.0 <= -8.0:
                continue
        v = float(vo.iloc[i] or 0) if np.isfinite(vo.iloc[i]) else 0.0
        v20 = float(vo.iloc[max(0, i - 19) : i + 1].mean())
        if v20 <= 0 or v > 1.25 * v20:
            continue
        ok[i] = True
    return pd.Series(ok, index=df.index)


def nav_low_hold_low_confirm_mask(df: pd.DataFrame) -> pd.Series:
    """本輪假突破下降候選：低點首觸＋同日站穩／收復前低。

    條件（只用當日及以前官方 OHLC，無前視）：
    - ``nav_low_arrow_first_mask`` 為真
    - 有前一日：收盤 ≥ 前一日低（收復前低＝站穩；續殺跌破前低剔除）
    - 同日影線確認：收盤不貼當日低——(close−low)/(high−low) ≥ 0.45
      （或 high≈low 時要求 close ≥ open）

    過關前仍不是買訊；只作靜默對質候選。須能量化優於 #548 才收。
    """
    first = nav_low_arrow_first_mask(df)
    if first.empty or not bool(first.any()):
        return first
    cl = pd.to_numeric(df["close"], errors="coerce")
    lo = pd.to_numeric(df["low"], errors="coerce")
    hi = pd.to_numeric(df["high"], errors="coerce")
    op = pd.to_numeric(df["open"], errors="coerce")
    n = len(df)
    ok = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not bool(first.iloc[i]):
            continue
        c = float(cl.iloc[i]) if np.isfinite(cl.iloc[i]) else 0.0
        lv = float(lo.iloc[i]) if np.isfinite(lo.iloc[i]) else 0.0
        hv = float(hi.iloc[i]) if np.isfinite(hi.iloc[i]) else 0.0
        ov = float(op.iloc[i]) if np.isfinite(op.iloc[i]) else 0.0
        prev_lo = float(lo.iloc[i - 1]) if np.isfinite(lo.iloc[i - 1]) else 0.0
        if c <= 0 or lv <= 0 or prev_lo <= 0:
            continue
        if c < prev_lo * 0.999:
            continue
        rng = hv - lv
        if rng > 1e-9:
            if (c - lv) / rng < 0.45:
                continue
        elif ov > 0 and c < ov:
            continue
        ok[i] = True
    return pd.Series(ok, index=df.index)


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


def score_stock_day(
    df: pd.DataFrame, *, as_of: str
) -> List[Dict[str, Any]]:
    """單檔截至 as_of：低點代理／過濾候選／leave_zero／無箭頭，產出各 horizon 分數列。"""
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
    prev_f = nav_low_ma60_vol_mask(hist)
    filtered = nav_low_hold_low_confirm_mask(hist)
    lz_hit = bool(leave_zero_from_quote_df(hist))
    i = len(hist) - 1
    low_hit = bool(lows.iloc[i])
    prev_hit = bool(prev_f.iloc[i]) if len(prev_f) else False
    filt_hit = bool(filtered.iloc[i]) if len(filtered) else False
    # 對齊全序列 index，才能取 as_of 之後的收盤
    full_dates = g["date"].tolist()
    try:
        fi = full_dates.index(as_of)
    except ValueError:
        return []
    closes = pd.to_numeric(g["close"], errors="coerce").tolist()
    sid = str(hist["stock_id"].iloc[-1] or "") if "stock_id" in hist.columns else ""
    name = str(hist["stock_name"].iloc[-1] or "") if "stock_name" in hist.columns else ""
    tags: List[Tuple[str, bool]] = [
        (TAG_LOW, low_hit),
        (TAG_PREV, prev_hit),
        (TAG_FILTER, filt_hit),
        (TAG_BASE, lz_hit),
        (TAG_NONE, (not low_hit) and (not lz_hit)),
    ]
    rows: List[Dict[str, Any]] = []
    for tag, hit in tags:
        if not hit:
            continue
        entry = float(closes[fi] or 0)
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
    """彙總 hit／miss／假突破；寫 rates。不算 pending 進 n。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store = ensure_red_arrow_tables(db_path)
    now = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(store, timeout=8.0)
    out: Dict[str, Any] = {}
    try:
        conn.execute("DELETE FROM red_arrow_quant_rates WHERE kind=?", (KIND,))
        for tag in (TAG_LOW, TAG_PREV, TAG_FILTER, TAG_BASE, TAG_NONE):
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
                    FROM red_arrow_quant_score
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
                    INSERT OR REPLACE INTO red_arrow_quant_rates(
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
    """明確優化狀態：獨立日／母體／贏 leave_zero／假突破是否相對 #547 基線下降。

    對話只准報這層；過關＝才「考慮」改編碼，仍不准自動改買訊。
    無箭頭基線只作對照，不單獨放行。過濾軌假突破未明顯下降＝不當買訊。
    本輪另須能量化優於 #548（``TAG_PREV``）才 ``beats_prev``。
    """
    store = ensure_red_arrow_tables(db_path)
    h = int(horizon)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        def _rate(tag: str):
            return conn.execute(
                """
                SELECT n, hit, miss, avg_ret, COALESCE(false_break, 0)
                FROM red_arrow_quant_rates
                WHERE kind=? AND tag=? AND horizon=?
                """,
                (KIND, tag, h),
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

        low_s = _pack_rate_row(_rate(TAG_LOW))
        prev_s = _pack_rate_row(_rate(TAG_PREV))
        filt_s = _pack_rate_row(_rate(TAG_FILTER))
        base_s = _pack_rate_row(_rate(TAG_BASE))
        none_s = _pack_rate_row(_rate(TAG_NONE))
        for tag, pack in (
            (TAG_LOW, low_s),
            (TAG_PREV, prev_s),
            (TAG_FILTER, filt_s),
            (TAG_BASE, base_s),
            (TAG_NONE, none_s),
        ):
            pack["unique_days"] = _days(tag)
            pack["distinct_sids"] = _sids(tag)
    finally:
        conn.close()

    n_ok = (
        low_s["unique_days"] >= MIN_UNIQUE_DAYS
        and base_s["unique_days"] >= MIN_UNIQUE_DAYS
        and low_s["distinct_sids"] >= MIN_DISTINCT_SIDS
        and base_s["distinct_sids"] >= MIN_DISTINCT_SIDS
    )
    # 買訊閘改看過濾軌（若有足夠 n）；否則仍看未過濾基線但不放行買訊
    cand = filt_s if (filt_s.get("n") or 0) >= OPTIMIZE_MIN_N else low_s
    beat_lz = _beats(cand, base_s)
    beat_none = _beats(cand, none_s)
    fb_base = low_s.get("false_break_rate")
    fb_filt = filt_s.get("false_break_rate")
    fb_prev = prev_s.get("false_break_rate")
    fb_drop = None
    if fb_base is not None and fb_filt is not None:
        fb_drop = float(fb_base) - float(fb_filt)
    fb_drop_vs_prev = None
    if fb_prev is not None and fb_filt is not None:
        fb_drop_vs_prev = float(fb_prev) - float(fb_filt)
    filt_n_ok = (
        (filt_s.get("unique_days") or 0) >= MIN_UNIQUE_DAYS
        and (filt_s.get("n") or 0) >= OPTIMIZE_MIN_N
    )
    # 報酬不輸：hit 相對 #547 基線容差 −2pp；avg_ret 不強制（與 #548 同）
    ret_ok_vs_base = bool(
        filt_s.get("hit_rate") is None
        or low_s.get("hit_rate") is None
        or filt_s["hit_rate"] + 1e-12 >= (low_s["hit_rate"] or 0) - 0.02
    )
    fb_ok = bool(
        filt_n_ok
        and fb_drop is not None
        and fb_drop >= MIN_FB_DROP
        and ret_ok_vs_base
    )
    # 優於 #548：假突破再降 ≥1pp，且 hit／avg 不輸超過容差
    prev_n_ok = (prev_s.get("n") or 0) >= OPTIMIZE_MIN_N
    ret_ok_vs_prev = True
    if prev_n_ok and filt_s.get("hit_rate") is not None and prev_s.get("hit_rate") is not None:
        ret_ok_vs_prev = filt_s["hit_rate"] + 1e-12 >= (prev_s["hit_rate"] or 0) - 0.02
        ar_f, ar_p = filt_s.get("avg_ret"), prev_s.get("avg_ret")
        if ar_f is not None and ar_p is not None and ar_f + 1e-12 < ar_p - 0.15:
            ret_ok_vs_prev = False
    beats_prev = bool(
        filt_n_ok
        and prev_n_ok
        and fb_drop_vs_prev is not None
        and fb_drop_vs_prev >= MIN_FB_DROP_VS_PREV
        and ret_ok_vs_prev
    )
    # 放行買訊討論：贏 leave_zero ＋ 假突破相對 #547 明顯下降 ＋ 優於 #548
    ready = bool(n_ok and beat_lz and fb_ok and beats_prev)
    return {
        "kind": KIND,
        "horizon": h,
        "low": low_s,
        "prev_filter": prev_s,
        "prev_tag": TAG_PREV,
        "filtered": filt_s,
        "filter_tag": TAG_FILTER,
        "leave_zero": base_s,
        "no_arrow": none_s,
        "n_ok": n_ok,
        "beats_leave_zero": beat_lz,
        "beats_no_arrow": beat_none,
        "beats_prev": beats_prev,
        "false_break_drop": fb_drop,
        "false_break_drop_vs_prev": fb_drop_vs_prev,
        "false_break_ok": fb_ok,
        "min_fb_drop": MIN_FB_DROP,
        "min_fb_drop_vs_prev": MIN_FB_DROP_VS_PREV,
        "promote_ready": ready,
        "next_candidate": NEXT_CANDIDATE,
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
    stats = {
        "wrote": 0,
        "promote": False,
        "n_low": 0,
        "n_prev": 0,
        "n_filt": 0,
        "n_lz": 0,
        "n_none": 0,
    }
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
        stats["n_prev"] = int((st.get("prev_filter") or {}).get("n") or 0)
        stats["n_filt"] = int((st.get("filtered") or {}).get("n") or 0)
        stats["n_lz"] = int((st.get("leave_zero") or {}).get("n") or 0)
        stats["n_none"] = int((st.get("no_arrow") or {}).get("n") or 0)
    except Exception:
        return stats
    return stats
