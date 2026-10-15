# -*- coding: utf-8 -*-
"""開盤前恐懼複合｜靜默落檔與對質骨架（不是買訊）。

kind＝fear_preopen_warn
標籤分軌（勝率不准混）：
  F_Dump／F_ForeignSell／F_StockHit_top500／F_StockHit_qianjin
  另：lead／sync 分列；dump_day 混淆分表

沒按也記；空日（未亮或不可評估）不算 n。
接 judge_tape → night_tick；失敗不擋海選／查股。不准改 leave_zero。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path
from fear_composite import (
    DEFAULT_DUMP_DAY_PCT,
    FOREIGN_NET_UNIT,
    SELL_SHARE_UNIT,
    VOLUME_UNIT,
    FearParams,
    evaluate_fear_composite,
    is_dump_day,
    night_vs_prior_settle_pct,
    sell_share,
)

KIND = "fear_preopen_warn"
TAG_DUMP = "F_Dump"
TAG_FOREIGN = "F_ForeignSell"
TAG_STOCK_TOP500 = "F_StockHit_top500"
TAG_STOCK_QIANJIN = "F_StockHit_qianjin"
TAGS: Tuple[str, ...] = (TAG_DUMP, TAG_FOREIGN, TAG_STOCK_TOP500, TAG_STOCK_QIANJIN)
SCORE_HORIZONS: Tuple[int, ...] = (1, 3, 5)
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
PRIMARY_H = 1
# 大盤假碼（事件日落檔用）
SID_TWII = "_TWII"
SID_FEAR = "_FEAR"
# Top500＝近 6m 日均額排序；千金＝收盤≥1000
TOP_N = 500
QIANJIN_PX = 1000.0
LOOKBACK_CAL_DAYS = 180
# Σ外資賣超極端：當日分位相對密窗（靜默用近窗累積）
FOREIGN_EXTREME_PCTL = 90.0


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
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
            CREATE TABLE IF NOT EXISTS fear_preopen_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                lit INTEGER NOT NULL DEFAULT 0,
                evaluable INTEGER NOT NULL DEFAULT 0,
                votes INTEGER NOT NULL DEFAULT 0,
                lead_sync TEXT NOT NULL DEFAULT '',
                gap_open_pct REAL,
                dump_day INTEGER NOT NULL DEFAULT 0,
                twii_ret_d REAL,
                vote_json TEXT NOT NULL DEFAULT '{}',
                skip_reason TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, as_of, params_key)
            );
            CREATE TABLE IF NOT EXISTS fear_preopen_events (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                sid TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                universe TEXT NOT NULL DEFAULT '',
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                foreign_net REAL,
                sell_share REAL,
                ex_rights INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, as_of, params_key, sid, universe)
            );
            CREATE TABLE IF NOT EXISTS fear_preopen_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL,
                lead_sync TEXT NOT NULL DEFAULT '',
                dump_day INTEGER NOT NULL DEFAULT 0,
                horizon INTEGER NOT NULL,
                check_as_of TEXT NOT NULL DEFAULT '',
                metric REAL,
                baseline_metric REAL,
                hit INTEGER,
                verdict TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (kind, as_of, params_key, tag, lead_sync, dump_day, horizon)
            );
            CREATE TABLE IF NOT EXISTS fear_preopen_rates (
                kind TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL,
                lead_sync TEXT NOT NULL DEFAULT 'all',
                dump_day_filter TEXT NOT NULL DEFAULT 'all',
                horizon INTEGER NOT NULL,
                n INTEGER NOT NULL DEFAULT 0,
                hit INTEGER NOT NULL DEFAULT 0,
                miss INTEGER NOT NULL DEFAULT 0,
                pending INTEGER NOT NULL DEFAULT 0,
                n_days INTEGER NOT NULL DEFAULT 0,
                avg_metric REAL,
                baseline_avg REAL,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, params_key, tag, lead_sync, dump_day_filter, horizon)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def _load_us_snap(db_path: str, day: str) -> Dict[str, Any]:
    day = _ymd(day)
    if not day or not db_path or not os.path.isfile(db_path):
        return {}
    try:
        from us_overnight import load_us_overnight

        return dict(load_us_overnight(db_path, day) or {})
    except Exception:
        return {}


def _tw_closed(db_path: str, day: str) -> bool:
    day = _ymd(day)
    if not day:
        return True
    try:
        from tw_holidays import closed_tw_session
        from datetime import datetime
        from zoneinfo import ZoneInfo

        dt = datetime.strptime(day, "%Y%m%d").replace(
            hour=12, tzinfo=ZoneInfo("Asia/Taipei")
        )
        hit = closed_tw_session(now=dt, db_path=db_path)
        return bool(hit)
    except Exception:
        # 無年曆時：有加權柱＝開市
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                """
                SELECT 1 FROM index_daily
                WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')=?
                """,
                (day,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
        return row is None


def _index_bar(db_path: str, day: str) -> Dict[str, Optional[float]]:
    day = _ymd(day)
    out: Dict[str, Optional[float]] = {
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "pct_change": None,
        "volume": None,
    }
    if not day or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT open, high, low, close, pct_change, volume
            FROM index_daily
            WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')=?
            """,
            (day,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row:
        return out
    out["open"] = _f(row[0])
    out["high"] = _f(row[1])
    out["low"] = _f(row[2])
    out["close"] = _f(row[3])
    out["pct_change"] = _f(row[4])
    out["volume"] = _f(row[5])
    return out


def _prior_index_close(db_path: str, day: str) -> Optional[float]:
    day = _ymd(day)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT close FROM index_daily
            WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')<?
              AND close>0
            ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1
            """,
            (day,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    return _f(row[0]) if row else None


def _gap_open_pct(db_path: str, day: str) -> Optional[float]:
    bar = _index_bar(db_path, day)
    op = bar.get("open")
    prev = _prior_index_close(db_path, day)
    if op is None or prev is None or prev <= 0:
        return None
    return (op / prev - 1.0) * 100.0


def _futures_night_pct(db_path: str, day: str, symbol: str) -> Optional[float]:
    """夜盤 date=day 相對前一 regular 結算。"""
    day = _ymd(day)
    sym = str(symbol or "TX").upper()
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        night = conn.execute(
            """
            SELECT close, settlement FROM futures_daily
            WHERE symbol=? AND session='night'
              AND REPLACE(CAST(date AS TEXT),'-','')=?
            """,
            (sym, day),
        ).fetchone()
        if not night:
            return None
        prior = conn.execute(
            """
            SELECT settlement, close FROM futures_daily
            WHERE symbol=? AND session='regular'
              AND REPLACE(CAST(date AS TEXT),'-','')<?
            ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1
            """,
            (sym, day),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not prior:
        return None
    settle = _f(prior[0]) or _f(prior[1])
    return night_vs_prior_settle_pct(night[0], settle)


def _ex_rights_set(db_path: str, day: str) -> set:
    day = _ymd(day)
    out: set = set()
    if not day:
        return out
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT stock_id FROM ex_rights
            WHERE REPLACE(CAST(ex_date AS TEXT),'-','')=?
            """,
            (day,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for r in rows:
        sid = str(r[0] or "").strip()
        if sid:
            out.add(sid)
    return out


def _top_universe(
    db_path: str, day: str, *, top_n: int = TOP_N, qianjin_only: bool = False
) -> List[str]:
    """近 LOOKBACK 曆日有額的股票，依日均 turnover_k 全排序取 TopN。

    不准抽樣：當日母體內可算的全進排序。
    """
    day = _ymd(day)
    if not day:
        return []
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT stock_id,
                   AVG(CASE WHEN turnover_k>0 THEN turnover_k END) AS avg_to,
                   AVG(CASE WHEN close>0 THEN close END) AS avg_px
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','')<=?
              AND REPLACE(CAST(date AS TEXT),'-','')>=?
              AND length(stock_id)=4
              AND stock_id GLOB '[0-9][0-9][0-9][0-9]'
            GROUP BY stock_id
            HAVING avg_to IS NOT NULL AND avg_to>0
            ORDER BY avg_to DESC
            """,
            (day, _shift_ymd(day, -LOOKBACK_CAL_DAYS)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    sids: List[str] = []
    for sid, _avg_to, avg_px in rows:
        sid_s = str(sid or "").strip()
        if not sid_s:
            continue
        if qianjin_only and (_f(avg_px) or 0) < QIANJIN_PX:
            # 千金子報：再用當日收盤過濾（下面 snapshot 再卡 close）
            pass
        sids.append(sid_s)
        if len(sids) >= int(top_n) and not qianjin_only:
            break
    if not qianjin_only:
        return sids[: int(top_n)]
    # 千金：Top 流動池內再濾當日 close≥1000（全數，不抽）
    return sids[: max(int(top_n) * 3, int(top_n))]


def _shift_ymd(day: str, delta_days: int) -> str:
    from datetime import datetime, timedelta

    d = datetime.strptime(_ymd(day), "%Y%m%d") + timedelta(days=int(delta_days))
    return d.strftime("%Y%m%d")


def _day_quotes(
    db_path: str, day: str, sids: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    day = _ymd(day)
    want = [str(s).strip() for s in sids if str(s).strip()]
    if not day or not want:
        return {}
    conn = sqlite3.connect(db_path, timeout=30.0)
    out: Dict[str, Dict[str, Any]] = {}
    try:
        # 分批 IN，避免過長
        for i in range(0, len(want), 400):
            chunk = want[i : i + 400]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"""
                SELECT stock_id, stock_name, open, high, low, close, volume, foreign_net
                FROM daily_quotes
                WHERE REPLACE(CAST(date AS TEXT),'-','')=?
                  AND stock_id IN ({marks})
                """,
                [day, *chunk],
            ).fetchall()
            for r in rows:
                sid = str(r[0] or "").strip()
                if not sid:
                    continue
                out[sid] = {
                    "stock_id": sid,
                    "stock_name": str(r[1] or ""),
                    "open": _f(r[2]),
                    "high": _f(r[3]),
                    "low": _f(r[4]),
                    "close": _f(r[5]),
                    "volume": _f(r[6]),
                    "foreign_net": _f(r[7]),
                }
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return out


def _market_foreign_sell_share(db_path: str, day: str) -> Optional[float]:
    """全市場 Σmax(0,-foreign)/Σvolume；無法人日回 None。"""
    day = _ymd(day)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN foreign_net IS NOT NULL AND foreign_net<0
                       THEN -foreign_net ELSE 0 END),
              SUM(CASE WHEN volume>0 THEN volume ELSE 0 END),
              SUM(CASE WHEN foreign_net IS NOT NULL THEN 1 ELSE 0 END)
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','')=?
            """,
            (day,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row or not row[2] or int(row[2]) < 200:
        return None
    sold = _f(row[0]) or 0.0
    vol = _f(row[1]) or 0.0
    if vol <= 0:
        return None
    return sold / vol


def evaluate_day(
    db_path: str, as_of: str, *, params: Optional[FearParams] = None
) -> Dict[str, Any]:
    """單日恐懼複合（只讀庫內已凍美股／夜盤／加權）。"""
    day = _ymd(as_of)
    p = params or FearParams()
    closed = _tw_closed(db_path, day)
    us = _load_us_snap(db_path, day)
    tx_n = _futures_night_pct(db_path, day, "TX")
    te_n = _futures_night_pct(db_path, day, "TE")
    gap = _gap_open_pct(db_path, day)
    res = evaluate_fear_composite(
        as_of=day,
        us_snap=us,
        tx_night_pct=tx_n,
        te_night_pct=te_n,
        gap_open_pct=gap,
        params=p,
        tw_closed=closed,
    )
    bar = _index_bar(db_path, day)
    twii_ret = bar.get("pct_change")
    if twii_ret is None and bar.get("close") and _prior_index_close(db_path, day):
        prev = _prior_index_close(db_path, day)
        if prev and prev > 0 and bar["close"]:
            twii_ret = (float(bar["close"]) / prev - 1.0) * 100.0
    dump = is_dump_day(twii_ret, p.dump_day_pct)
    return {
        "result": res,
        "twii": bar,
        "twii_ret_d": twii_ret,
        "dump_day": dump,
        "tx_night_pct": tx_n,
        "te_night_pct": te_n,
        "params": p,
    }


def persist_day(
    db_path: str,
    as_of: str,
    *,
    params: Optional[FearParams] = None,
    persist_stocks: bool = True,
) -> Dict[str, Any]:
    """落檔一日：複合列＋（若亮）Top500／千金事件列。空不算。"""
    day = _ymd(as_of)
    info = evaluate_day(db_path, day, params=params)
    res = info["result"]
    p: FearParams = info["params"]
    store = ensure_tables(db_path)
    vote_json = json.dumps(
        [
            {
                "name": v.name,
                "lit": v.lit,
                "available": v.available,
                "reason": v.reason,
                "value": v.value,
            }
            for v in res.vote_details
        ],
        ensure_ascii=False,
    )
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO fear_preopen_tape(
                kind, as_of, params_key, lit, evaluable, votes, lead_sync,
                gap_open_pct, dump_day, twii_ret_d, vote_json, skip_reason
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                KIND,
                day,
                p.key(),
                1 if res.lit else 0,
                1 if res.evaluable else 0,
                int(res.votes),
                res.lead_sync or "",
                res.gap_open_pct,
                1 if info["dump_day"] else 0,
                info.get("twii_ret_d"),
                vote_json,
                res.skip_reason or "",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    events_n = 0
    if persist_stocks and res.lit and res.evaluable:
        events_n = _persist_stock_events(db_path, day, p.key())
    # 大盤假碼列（亮或可評估日都留一根官方柱，方便對質）
    if res.evaluable:
        bar = info["twii"]
        if bar.get("close"):
            _persist_index_event(db_path, day, p.key(), bar)
            events_n += 1
    return {
        "as_of": day,
        "lit": res.lit,
        "evaluable": res.evaluable,
        "votes": res.votes,
        "lead_sync": res.lead_sync,
        "events": events_n,
        "params_key": p.key(),
        "skip_reason": res.skip_reason,
    }


def _persist_index_event(
    db_path: str, day: str, params_key: str, bar: Dict[str, Any]
) -> None:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO fear_preopen_events(
                kind, as_of, params_key, sid, name, universe,
                open, high, low, close, volume, foreign_net, sell_share, ex_rights
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                KIND,
                day,
                params_key,
                SID_TWII,
                "加權",
                "index",
                bar.get("open"),
                bar.get("high"),
                bar.get("low"),
                bar.get("close"),
                bar.get("volume"),
                None,
                None,
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _persist_stock_events(db_path: str, day: str, params_key: str) -> int:
    """亮日起：Top500 全檔＋千金子集合（除權息標記；全寫，不抽）。"""
    top = _top_universe(db_path, day, top_n=TOP_N, qianjin_only=False)
    quotes = _day_quotes(db_path, day, top)
    ex_set = _ex_rights_set(db_path, day)
    store = ensure_tables(db_path)
    n = 0
    conn = sqlite3.connect(store, timeout=30.0)
    try:
        for sid in top:
            q = quotes.get(sid)
            if not q or not q.get("close") or not q.get("volume"):
                continue
            ss = sell_share(q.get("foreign_net"), q.get("volume"))
            is_ex = 1 if sid in ex_set else 0
            conn.execute(
                """
                INSERT OR REPLACE INTO fear_preopen_events(
                    kind, as_of, params_key, sid, name, universe,
                    open, high, low, close, volume, foreign_net, sell_share, ex_rights
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    day,
                    params_key,
                    sid,
                    q.get("stock_name") or "",
                    "top500",
                    q.get("open"),
                    q.get("high"),
                    q.get("low"),
                    q.get("close"),
                    q.get("volume"),
                    q.get("foreign_net"),
                    ss,
                    is_ex,
                ),
            )
            n += 1
            # 千金子報：同一日 close≥1000 另宇宙列（完整，非抽樣）
            if (_f(q.get("close")) or 0) >= QIANJIN_PX:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fear_preopen_events(
                        kind, as_of, params_key, sid, name, universe,
                        open, high, low, close, volume, foreign_net, sell_share, ex_rights
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        day,
                        params_key,
                        sid,
                        q.get("stock_name") or "",
                        "qianjin",
                        q.get("open"),
                        q.get("high"),
                        q.get("low"),
                        q.get("close"),
                        q.get("volume"),
                        q.get("foreign_net"),
                        ss,
                        is_ex,
                    ),
                )
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def snapshot_day(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """盤後靜默：預設參數落一列。"""
    day = _ymd(as_of)
    if not day:
        try:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(db_path))
        except Exception:
            day = ""
    if not day:
        return {"as_of": "", "lit": False, "events": 0}
    return persist_day(db_path, day, params=FearParams(), persist_stocks=True)


def _forward_index_ret(
    db_path: str, as_of: str, horizon: int
) -> Tuple[str, Optional[float]]:
    day = _ymd(as_of)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-','') AS d, close
            FROM index_daily
            WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')>?
              AND close>0
            ORDER BY d LIMIT ?
            """,
            (day, int(horizon)),
        ).fetchall()
        base = conn.execute(
            """
            SELECT close FROM index_daily
            WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')=?
              AND close>0
            """,
            (day,),
        ).fetchone()
    except sqlite3.Error:
        return "", None
    finally:
        conn.close()
    if not base or not _f(base[0]) or len(rows) < int(horizon):
        return "", None
    d, c = rows[int(horizon) - 1]
    ent = float(base[0])
    ex = _f(c)
    if ex is None or ent <= 0:
        return _ymd(d), None
    return _ymd(d), (ex / ent - 1.0) * 100.0


def score_pending(db_path: str, *, params_key: str = "") -> int:
    """對已落檔亮起日打 F→Dump 前瞻（1／3／5）。ForeignSell／StockHit 由離線掃完整算。"""
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        q = """
            SELECT as_of, params_key, lead_sync, dump_day, lit, evaluable
            FROM fear_preopen_tape WHERE kind=? AND lit=1 AND evaluable=1
        """
        args: List[Any] = [KIND]
        if params_key:
            q += " AND params_key=?"
            args.append(params_key)
        tape = conn.execute(q, args).fetchall()
    finally:
        conn.close()
    if not tape:
        return 0
    n = 0
    store_conn = sqlite3.connect(store, timeout=8.0)
    try:
        for as_of, pkey, lead_sync, dump_day, _lit, _ev in tape:
            as_of = _ymd(as_of)
            for h in SCORE_HORIZONS:
                check_as, ret = _forward_index_ret(db_path, as_of, h)
                if ret is None:
                    verdict = "pending"
                    hit = None
                else:
                    # Dump 命中＝後窗報酬為負（出事）
                    hit = 1 if ret < 0 else 0
                    verdict = "hit" if hit else "miss"
                store_conn.execute(
                    """
                    INSERT OR REPLACE INTO fear_preopen_score(
                        kind, as_of, params_key, tag, lead_sync, dump_day,
                        horizon, check_as_of, metric, baseline_metric, hit, verdict
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        as_of,
                        pkey,
                        TAG_DUMP,
                        lead_sync or "",
                        int(dump_day or 0),
                        int(h),
                        check_as or "",
                        ret,
                        None,
                        hit,
                        verdict,
                    ),
                )
                n += 1
        store_conn.commit()
    finally:
        store_conn.close()
    return n


def recompute_rates(db_path: str) -> Dict[str, Any]:
    """分 lead_sync × dump_day_filter × horizon 完整重算，不准混成一個％。"""
    store = ensure_tables(db_path)
    now = _now_iso()
    conn = sqlite3.connect(store, timeout=8.0)
    out: Dict[str, Any] = {}
    try:
        conn.execute("DELETE FROM fear_preopen_rates WHERE kind=?", (KIND,))
        keys = conn.execute(
            "SELECT DISTINCT params_key FROM fear_preopen_score WHERE kind=?",
            (KIND,),
        ).fetchall()
        for (pkey,) in keys:
            for tag in (TAG_DUMP,):
                for ls in ("all", "lead", "sync"):
                    for df in ("all", "exclude_dump", "dump_only"):
                        for h in SCORE_HORIZONS:
                            clauses = ["kind=?", "params_key=?", "tag=?", "horizon=?"]
                            args: List[Any] = [KIND, pkey, tag, int(h)]
                            if ls != "all":
                                clauses.append("lead_sync=?")
                                args.append(ls)
                            if df == "exclude_dump":
                                clauses.append("dump_day=0")
                            elif df == "dump_only":
                                clauses.append("dump_day=1")
                            where = " AND ".join(clauses)
                            row = conn.execute(
                                f"""
                                SELECT
                                  SUM(CASE WHEN verdict='hit' THEN 1 ELSE 0 END),
                                  SUM(CASE WHEN verdict='miss' THEN 1 ELSE 0 END),
                                  SUM(CASE WHEN verdict='pending' THEN 1 ELSE 0 END),
                                  AVG(CASE WHEN verdict IN ('hit','miss') THEN metric END),
                                  COUNT(DISTINCT CASE WHEN verdict IN ('hit','miss')
                                        THEN as_of END)
                                FROM fear_preopen_score
                                WHERE {where}
                                """,
                                args,
                            ).fetchone()
                            hit = int(row[0] or 0)
                            miss = int(row[1] or 0)
                            pending = int(row[2] or 0)
                            avg_m = row[3]
                            n_days = int(row[4] or 0)
                            n = hit + miss
                            conn.execute(
                                """
                                INSERT INTO fear_preopen_rates(
                                    kind, params_key, tag, lead_sync, dump_day_filter,
                                    horizon, n, hit, miss, pending, n_days,
                                    avg_metric, baseline_avg, updated_at
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                """,
                                (
                                    KIND,
                                    pkey,
                                    tag,
                                    ls,
                                    df,
                                    int(h),
                                    n,
                                    hit,
                                    miss,
                                    pending,
                                    n_days,
                                    avg_m,
                                    None,
                                    now,
                                ),
                            )
                            out[f"{pkey}|{tag}|{ls}|{df}|h{h}"] = {
                                "n": n,
                                "hit": hit,
                                "miss": miss,
                                "pending": pending,
                                "n_days": n_days,
                                "avg_metric": avg_m,
                            }
        conn.commit()
    finally:
        conn.close()
    return out


def night_tick(market_db: str, as_of: str = "") -> Dict[str, Any]:
    """盤後掛勾：落檔＋打分＋重算。失敗由呼叫端吞。"""
    snap = snapshot_day(market_db, as_of)
    scored = 0
    rates: Dict[str, Any] = {}
    try:
        scored = score_pending(market_db)
        rates = recompute_rates(market_db)
    except Exception:
        pass
    snap["scored"] = scored
    snap["rates_keys"] = len(rates)
    return snap


def gate_status(db_path: str) -> Dict[str, Any]:
    """觀察閘：永不 promote 買訊。"""
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT n_days, n, hit FROM fear_preopen_rates
            WHERE kind=? AND tag=? AND lead_sync='lead'
              AND dump_day_filter='exclude_dump' AND horizon=?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (KIND, TAG_DUMP, PRIMARY_H),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    n_days = int(row[0] or 0) if row else 0
    n = int(row[1] or 0) if row else 0
    hit = int(row[2] or 0) if row else 0
    ready = n_days >= MIN_UNIQUE_DAYS and n >= MIN_UNIQUE_DAYS
    return {
        "kind": KIND,
        "n_days": n_days,
        "n": n,
        "hit": hit,
        "min_n": MIN_UNIQUE_DAYS,
        "ready_to_observe": ready,
        "buy_signal": False,
        "promote_golden_buy": False,
        "promote_leave_zero": False,
        "promote_paint": False,
    }


def optimize_status_one_liner(db_path: str) -> str:
    g = gate_status(db_path)
    if g["n_days"] < MIN_UNIQUE_DAYS:
        return (
            f"恐懼開盤前：獨立日 n={g['n_days']}/{MIN_UNIQUE_DAYS}，"
            f"未過閘；只觀察、非買訊"
        )
    return (
        f"恐懼開盤前：獨立日 n={g['n_days']}，"
        f"{'可談觀察形' if g['ready_to_observe'] else '未過閘'}；非買訊、不改黃金買點"
    )
