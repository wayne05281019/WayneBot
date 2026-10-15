#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FearComposite₀ 離線全樣本回測（不是買訊）。

資料優先序（使用者鎖）：
  1. 本庫 ``wayne_market.db``（us_overnight／futures_daily／index_daily／daily_quotes／ex_rights）
  2. 缺美股／外圍欄 → 外聯 Yahoo 官方日 K 補齊並 **落回 us_overnight**
  3. 仍缺 → 標缺、``evaluable=False``，不准假數交差

硬鎖：窗內全部開市日；Top500 全檔＋千金子報分開；Lead／Sync／dump／除權息分表；網格全跑；不准抽測。

用法：
  .venv/bin/python scripts/fear_composite_backtest.py \\
    --db data/wayne_market.db \\
    --out /opt/cursor/artifacts/fear-composite-backtest-20261015
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fear_composite import (  # noqa: E402
    FOREIGN_NET_UNIT,
    LOTS_PER_SHARE,
    SELL_SHARE_UNIT,
    VOLUME_UNIT,
    FearParams,
    evaluate_fear_composite,
    iter_fear_param_grid,
    night_vs_prior_settle_pct,
    sell_share,
    unit_consistency_report,
    us_keys_present,
)
from fear_preopen_verify import (  # noqa: E402
    LOOKBACK_CAL_DAYS,
    QIANJIN_PX,
    TOP_N,
    _ex_rights_set,
    _top_universe,
)
from fear_us_history import (  # noqa: E402
    backfill_us_overnight_for_tw_days,
    load_us_prefer_db,
    outer_present,
)

TP = ZoneInfo("Asia/Taipei")


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
    return datetime.now(TP).isoformat(timespec="seconds")


def list_tw_open_days(db: str, start: str, end: str) -> List[str]:
    start, end = _ymd(start), _ymd(end)
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-','') AS d
            FROM index_daily
            WHERE symbol='TWII' AND close>0
              AND REPLACE(CAST(date AS TEXT),'-','')>=?
              AND REPLACE(CAST(date AS TEXT),'-','')<=?
            ORDER BY d
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()
    return [_ymd(r[0]) for r in rows if _ymd(r[0])]


def us_overnight_coverage(db: str) -> Dict[str, Any]:
    """``us_overnight`` 覆蓋盤點（補齊前後都可呼叫）。"""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT as_of, regime FROM us_overnight ORDER BY as_of"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    days = []
    with_outer = 0
    with_us_keys = 0
    for as_of, regime in rows:
        d = _ymd(as_of)
        if not d:
            continue
        snap = load_us_prefer_db(db, d)
        ok_us = us_keys_present(snap)
        ok_outer = outer_present(snap)
        if ok_us:
            with_us_keys += 1
        if ok_outer:
            with_outer += 1
        days.append(
            {
                "as_of": d,
                "regime": regime or snap.get("regime"),
                "us_keys": ok_us,
                "outer_keys": ok_outer,
            }
        )
    return {
        "n_rows": len(days),
        "n_with_us_keys": with_us_keys,
        "n_with_outer": with_outer,
        "min_as_of": days[0]["as_of"] if days else "",
        "max_as_of": days[-1]["as_of"] if days else "",
        "days": days,
        "source": "us_overnight（本庫＋已落庫之外聯補）",
    }


def load_futures_night_map(db: str, symbol: str) -> Dict[str, float]:
    sym = str(symbol).upper()
    conn = sqlite3.connect(db)
    out: Dict[str, float] = {}
    try:
        nights = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), close
            FROM futures_daily
            WHERE symbol=? AND session='night' AND close>0
            ORDER BY 1
            """,
            (sym,),
        ).fetchall()
        regs = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), settlement, close
            FROM futures_daily
            WHERE symbol=? AND session='regular'
            ORDER BY 1
            """,
            (sym,),
        ).fetchall()
    finally:
        conn.close()
    reg_list = [(_ymd(d), _f(s) or _f(c)) for d, s, c in regs]
    reg_list = [(d, v) for d, v in reg_list if d and v and v > 0]
    for nd, nc in nights:
        nd = _ymd(nd)
        nc = _f(nc)
        if not nd or nc is None:
            continue
        prior = None
        for rd, rv in reg_list:
            if rd < nd:
                prior = rv
            else:
                break
        pct = night_vs_prior_settle_pct(nc, prior)
        if pct is not None:
            out[nd] = pct
    return out


def load_index_series(db: str) -> Dict[str, Dict[str, Any]]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, pct_change, volume
            FROM index_daily WHERE symbol='TWII' AND close>0 ORDER BY 1
            """
        ).fetchall()
    finally:
        conn.close()
    out: Dict[str, Dict[str, Any]] = {}
    prev_c = None
    for d, o, h, l, c, pct, vol in rows:
        d = _ymd(d)
        c = _f(c)
        if not d or c is None:
            continue
        ret = _f(pct)
        if ret is None and prev_c and prev_c > 0:
            ret = (c / prev_c - 1.0) * 100.0
        gap = None
        op = _f(o)
        if op is not None and prev_c and prev_c > 0:
            gap = (op / prev_c - 1.0) * 100.0
        out[d] = {
            "open": op,
            "high": _f(h),
            "low": _f(l),
            "close": c,
            "pct_change": ret,
            "volume": _f(vol),
            "gap_open_pct": gap,
            "prior_close": prev_c,
        }
        prev_c = c
    return out


def forward_rets(
    days: Sequence[str], idx: Dict[str, Dict[str, Any]], i: int, horizons: Sequence[int]
) -> Dict[int, Optional[float]]:
    out: Dict[int, Optional[float]] = {}
    base = idx.get(days[i], {}).get("close")
    if not base or base <= 0:
        return {h: None for h in horizons}
    for h in horizons:
        j = i + int(h)
        if j >= len(days):
            out[h] = None
            continue
        c = idx.get(days[j], {}).get("close")
        out[h] = (c / base - 1.0) * 100.0 if c and c > 0 else None
    return out


def load_daily_foreign_market(db: str, days: Sequence[str]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    conn = sqlite3.connect(db)
    try:
        for d in days:
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
                (d,),
            ).fetchone()
            if not row or not row[2] or int(row[2]) < 200:
                out[d] = None
                continue
            sold = _f(row[0]) or 0.0
            vol = _f(row[1]) or 0.0
            out[d] = (sold / vol) if vol > 0 else None
    finally:
        conn.close()
    return out


def percentile_rank(values: List[float], x: float) -> float:
    if not values:
        return 0.0
    less = sum(1 for v in values if v < x)
    eq = sum(1 for v in values if v == x)
    return (less + 0.5 * eq) / len(values) * 100.0


def stock_hit_stats_for_day(
    day: str,
    twii_ret: Optional[float],
    *,
    universe: str,
    sids: Sequence[str],
    quotes: Dict[str, Dict[str, Any]],
    ex_set: set,
    sell_pctl_thr: float = 70.0,
) -> Dict[str, Any]:
    rows_out: List[Dict[str, Any]] = []
    n_missing = 0
    n_ex = 0
    n_ok = 0
    weak = 0
    for sid in sids:
        q = quotes.get(sid)
        if not q or not q.get("close") or not q.get("volume"):
            n_missing += 1
            continue
        if universe == "qianjin" and (_f(q.get("close")) or 0) < QIANJIN_PX:
            continue
        is_ex = sid in ex_set
        if is_ex:
            n_ex += 1
        ss = sell_share(q.get("foreign_net"), q.get("volume"))
        op = _f(q.get("open"))
        cl = _f(q.get("close"))
        stock_ret = (cl / op - 1.0) * 100.0 if op and op > 0 and cl and cl > 0 else None
        n_ok += 1
        is_weak = stock_ret is not None and twii_ret is not None and stock_ret < twii_ret
        if is_weak:
            weak += 1
        rows_out.append(
            {
                "sid": sid,
                "name": q.get("stock_name") or "",
                "open": q.get("open"),
                "high": q.get("high"),
                "low": q.get("low"),
                "close": q.get("close"),
                "volume": q.get("volume"),
                "foreign_net": q.get("foreign_net"),
                "sell_share": ss,
                "stock_ret_oc": stock_ret,
                "ex_rights": int(is_ex),
                "weak_vs_twii": int(bool(is_weak)),
            }
        )
    ss_vals = [
        float(r["sell_share"])
        for r in rows_out
        if r.get("sell_share") is not None and not r.get("ex_rights")
    ]
    hit = 0
    hit_ex_included = 0
    for r in rows_out:
        ss = r.get("sell_share")
        pctl = percentile_rank(ss_vals, float(ss)) if ss is not None and ss_vals else 0.0
        r["sell_share_pctl"] = pctl
        flag = bool(r.get("weak_vs_twii")) and pctl >= float(sell_pctl_thr)
        r["stock_hit"] = int(flag)
        if flag:
            hit_ex_included += 1
            if not r.get("ex_rights"):
                hit += 1
    n_non_ex = sum(1 for r in rows_out if not r.get("ex_rights"))
    return {
        "universe": universe,
        "n_listed": len(sids),
        "n_ok": n_ok,
        "n_missing_bar": n_missing,
        "n_ex_rights": n_ex,
        "n_non_ex": n_non_ex,
        "n_weak": weak,
        "n_hit_ex_excl": hit,
        "n_hit_ex_incl": hit_ex_included,
        "hit_rate_ex_excl": (hit / n_non_ex) if n_non_ex else None,
        "hit_rate_ex_incl": (hit_ex_included / n_ok) if n_ok else None,
        "rows": rows_out,
    }


def _load_quotes(db: str, day: str, sids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    quotes: Dict[str, Dict[str, Any]] = {}
    if not sids:
        return quotes
    conn = sqlite3.connect(db, timeout=60.0)
    try:
        for j in range(0, len(sids), 400):
            chunk = list(sids[j : j + 400])
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
                quotes[str(r[0])] = {
                    "stock_id": str(r[0]),
                    "stock_name": str(r[1] or ""),
                    "open": _f(r[2]),
                    "high": _f(r[3]),
                    "low": _f(r[4]),
                    "close": _f(r[5]),
                    "volume": _f(r[6]),
                    "foreign_net": _f(r[7]),
                }
    finally:
        conn.close()
    return quotes


def run_backtest(
    db: str,
    *,
    start: str,
    end: str,
    out_dir: str,
    persist_event_rows: bool = True,
    yahoo_range: str = "2y",
    skip_yahoo_fill: bool = False,
) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    print("== 資料優先序：本庫 → 缺欄 Yahoo 官方補齊落庫 → 仍缺標缺 ==", flush=True)
    cov0 = us_overnight_coverage(db)
    print(
        f"  補齊前 us_overnight 列={cov0['n_rows']} 有美股鍵={cov0['n_with_us_keys']} "
        f"有外圍={cov0['n_with_outer']}  {cov0['min_as_of']}→{cov0['max_as_of']}",
        flush=True,
    )
    with open(
        os.path.join(out_dir, "db_coverage_us_overnight_before.json"),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(cov0, f, ensure_ascii=False, indent=2)

    print("== 載入台股開市日（全窗）==", flush=True)
    days = list_tw_open_days(db, start, end)
    print(
        f"  開市日 n={len(days)}  {days[0] if days else '—'}→{days[-1] if days else '—'}",
        flush=True,
    )

    fill_stats: Dict[str, Any] = {
        "skipped": True,
        "reason": "skip_yahoo_fill" if skip_yahoo_fill else "",
    }
    if not skip_yahoo_fill:
        print("== 缺美股／外圍：外聯 Yahoo 日 K 補齊並落庫 ==", flush=True)
        fill_stats = backfill_us_overnight_for_tw_days(
            db, days, range_=yahoo_range, fill_outer_only_gaps=True
        )
        print(
            f"  本庫已有={fill_stats['already_in_db']} "
            f"Yahoo補美股={fill_stats['filled_from_yahoo']} "
            f"補外圍={fill_stats['outer_filled']} "
            f"仍缺={fill_stats['n_still_missing']}",
            flush=True,
        )
        with open(
            os.path.join(out_dir, "us_overnight_backfill_stats.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(fill_stats, f, ensure_ascii=False, indent=2)
        if fill_stats.get("still_missing"):
            with open(
                os.path.join(out_dir, "us_overnight_still_missing.jsonl"),
                "w",
                encoding="utf-8",
            ) as f:
                for d in fill_stats["still_missing"]:
                    f.write(json.dumps({"as_of": d, "missing": "美股關鍵欄"}, ensure_ascii=False) + "\n")

    cov = us_overnight_coverage(db)
    print(
        f"  補齊後 us_overnight 列={cov['n_rows']} 有美股鍵={cov['n_with_us_keys']} "
        f"有外圍={cov['n_with_outer']}",
        flush=True,
    )
    with open(
        os.path.join(out_dir, "db_coverage_us_overnight_after.json"),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(cov, f, ensure_ascii=False, indent=2)

    print("== 載入加權／夜盤（庫內）==", flush=True)
    idx = load_index_series(db)
    tx_n = load_futures_night_map(db, "TX")
    te_n = load_futures_night_map(db, "TE")
    print(f"  TX night 可算日={len(tx_n)}  TE night 可算日={len(te_n)}", flush=True)
    print("== 全市場外資賣超佔量（全日庫內）==", flush=True)
    mkt_ss = load_daily_foreign_market(db, days)
    dense_ss = [v for v in mkt_ss.values() if v is not None]
    print(f"  法人密日={len(dense_ss)}／{len(days)}", flush=True)

    horizons = (1, 3, 5)
    grid = iter_fear_param_grid()
    print(f"== 門檻網格 {len(grid)} 組（全跑）==", flush=True)

    day_ctx: Dict[str, Dict[str, Any]] = {}
    missing_us_days = 0
    for d in days:
        us = load_us_prefer_db(db, d)
        bar = idx.get(d) or {}
        has_us = us_keys_present(us)
        if not has_us:
            missing_us_days += 1
        day_ctx[d] = {
            "us": us,
            "tx": tx_n.get(d),
            "te": te_n.get(d),
            "gap": bar.get("gap_open_pct"),
            "twii_ret": bar.get("pct_change"),
            "bar": bar,
            "mkt_ss": mkt_ss.get(d),
            "missing_us": not has_us,
            "missing_outer": not outer_present(us),
        }
    print(
        f"  窗內仍缺美股鍵日={missing_us_days}／{len(days)}（標缺，已盡力補）",
        flush=True,
    )

    summary_grid: List[Dict[str, Any]] = []
    default_key = FearParams().key()
    event_days_default: List[Dict[str, Any]] = []

    for gi, params in enumerate(grid):
        print(f"  [{gi+1}/{len(grid)}] {params.key()}", flush=True)
        lit_days: List[str] = []
        dark_days: List[str] = []
        skip_days: List[str] = []
        per_day: List[Dict[str, Any]] = []
        for d in days:
            ctx = day_ctx[d]
            res = evaluate_fear_composite(
                as_of=d,
                us_snap=ctx["us"],
                tx_night_pct=ctx["tx"],
                te_night_pct=ctx["te"],
                gap_open_pct=ctx["gap"],
                params=params,
                tw_closed=False,
            )
            dump = bool(
                ctx["twii_ret"] is not None and ctx["twii_ret"] <= params.dump_day_pct
            )
            # 缺欄明細（不准假補）
            miss = []
            if ctx["missing_us"]:
                miss.append("美股關鍵欄")
            if ctx["missing_outer"]:
                miss.append("外圍油匯")
            if ctx["tx"] is None and ctx["te"] is None:
                miss.append("TX/TE夜盤")
            rec = {
                "as_of": d,
                "lit": res.lit,
                "evaluable": res.evaluable,
                "votes": res.votes,
                "lead_sync": res.lead_sync,
                "gap_open_pct": res.gap_open_pct,
                "twii_ret_d": ctx["twii_ret"],
                "dump_day": dump,
                "skip_reason": res.skip_reason,
                "db_missing": miss,
                "votes_detail": [
                    {
                        "name": v.name,
                        "lit": v.lit,
                        "available": v.available,
                        "reason": v.reason,
                        "value": v.value,
                    }
                    for v in res.vote_details
                ],
                "tx_night_pct": ctx["tx"],
                "te_night_pct": ctx["te"],
                "mkt_sell_share": ctx["mkt_ss"],
                "data_source": "wayne_market.db",
            }
            per_day.append(rec)
            if not res.evaluable:
                skip_days.append(d)
            elif res.lit:
                lit_days.append(d)
            else:
                dark_days.append(d)

        day_index = {d: i for i, d in enumerate(days)}

        def bucket_dump(filter_ls: str, filter_dump: str, lit_only: bool) -> Dict[str, Any]:
            rets = {h: [] for h in horizons}
            n_days = 0
            for rec in per_day:
                if not rec["evaluable"]:
                    continue
                if lit_only and not rec["lit"]:
                    continue
                if (not lit_only) and rec["lit"]:
                    continue
                if filter_ls == "lead" and rec["lead_sync"] != "lead":
                    continue
                if filter_ls == "sync" and rec["lead_sync"] != "sync":
                    continue
                if filter_dump == "exclude_dump" and rec["dump_day"]:
                    continue
                if filter_dump == "dump_only" and not rec["dump_day"]:
                    continue
                i = day_index[rec["as_of"]]
                fr = forward_rets(days, idx, i, horizons)
                ok_any = False
                for h in horizons:
                    if fr[h] is None:
                        continue
                    rets[h].append(fr[h])
                    ok_any = True
                if ok_any:
                    n_days += 1
            out_h: Dict[str, Any] = {}
            for h in horizons:
                xs = rets[h]
                if not xs:
                    out_h[f"h{h}"] = {
                        "n": 0,
                        "avg_ret": None,
                        "hit_neg": None,
                        "hit_rate": None,
                    }
                    continue
                neg = sum(1 for x in xs if x < 0)
                out_h[f"h{h}"] = {
                    "n": len(xs),
                    "avg_ret": sum(xs) / len(xs),
                    "hit_neg": neg,
                    "hit_rate": neg / len(xs),
                }
            out_h["n_days"] = n_days
            return out_h

        dump_tables = {}
        for ls in ("all", "lead", "sync"):
            for df in ("all", "exclude_dump", "dump_only"):
                dump_tables[f"lit|{ls}|{df}"] = bucket_dump(ls, df, True)
                dump_tables[f"base|{ls}|{df}"] = bucket_dump("all", df, False)

        p90 = None
        if dense_ss:
            ss_sorted = sorted(dense_ss)
            p90 = ss_sorted[int(0.9 * (len(ss_sorted) - 1))]

        def foreign_bucket(filter_ls: str, lit_only: bool) -> Dict[str, Any]:
            hits = 0
            n = 0
            vals = []
            for rec in per_day:
                if not rec["evaluable"]:
                    continue
                if lit_only and not rec["lit"]:
                    continue
                if (not lit_only) and rec["lit"]:
                    continue
                if lit_only and filter_ls == "lead" and rec["lead_sync"] != "lead":
                    continue
                if lit_only and filter_ls == "sync" and rec["lead_sync"] != "sync":
                    continue
                ss = rec.get("mkt_sell_share")
                if ss is None or p90 is None:
                    continue
                n += 1
                vals.append(ss)
                if ss >= p90:
                    hits += 1
            return {
                "n": n,
                "hit": hits,
                "hit_rate": (hits / n) if n else None,
                "avg_sell_share": (sum(vals) / len(vals)) if vals else None,
                "p90_thr": p90,
            }

        foreign_tables = {}
        for ls in ("all", "lead", "sync"):
            foreign_tables[f"lit|{ls}"] = foreign_bucket(ls, True)
            foreign_tables[f"base|{ls}"] = foreign_bucket("all", False)

        cell = {
            "params": params.as_dict(),
            "params_key": params.key(),
            "n_open_days": len(days),
            "n_evaluable": len(days) - len(skip_days),
            "n_skip": len(skip_days),
            "n_lit": len(lit_days),
            "n_dark": len(dark_days),
            "F_Dump": dump_tables,
            "F_ForeignSell": foreign_tables,
        }
        summary_grid.append(cell)

        if params.key() == default_key:
            path_days = os.path.join(out_dir, "fear_days_default.jsonl")
            with open(path_days, "w", encoding="utf-8") as f:
                for rec in per_day:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # 缺日清單（完整，非抽樣）
            miss_path = os.path.join(out_dir, "fear_days_missing_us.jsonl")
            with open(miss_path, "w", encoding="utf-8") as f:
                for rec in per_day:
                    if not rec["evaluable"]:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            event_days_default = [r for r in per_day if r["lit"] and r["evaluable"]]
            print(
                f"    預設：可評估={cell['n_evaluable']} 亮={cell['n_lit']} "
                f"略過(缺美股等)={cell['n_skip']}",
                flush=True,
            )

    # StockHit：僅對可評估日全量 Top500／千金（庫內）
    print("== F→StockHit：可評估日 × Top500／千金全檔（庫內）==", flush=True)
    stock_hit_summary: Dict[str, Any] = {
        "top500": {"days": []},
        "qianjin": {"days": []},
    }
    stock_rows_path = os.path.join(out_dir, "fear_stockhit_events.jsonl")
    stock_day_path = os.path.join(out_dir, "fear_stockhit_by_day.jsonl")
    default_params = FearParams()
    evaluable_default: List[Tuple[str, Any]] = []
    for d in days:
        ctx = day_ctx[d]
        res = evaluate_fear_composite(
            as_of=d,
            us_snap=ctx["us"],
            tx_night_pct=ctx["tx"],
            te_night_pct=ctx["te"],
            gap_open_pct=ctx["gap"],
            params=default_params,
            tw_closed=False,
        )
        if res.evaluable:
            evaluable_default.append((d, res))

    print(f"  可評估日（將全掃 Top500）n={len(evaluable_default)}", flush=True)
    # 單位一致性累計（張/張；非整檔抽測，是全日全母體列累加）
    unit_acc_rows: List[Dict[str, Any]] = []
    with open(stock_rows_path, "w", encoding="utf-8") as fe, open(
        stock_day_path, "w", encoding="utf-8"
    ) as fd:
        for i, (d, res) in enumerate(evaluable_default):
            print(
                f"  StockHit {i+1}/{len(evaluable_default)} {d} lit={int(res.lit)}",
                flush=True,
            )
            top = _top_universe(db, d, top_n=TOP_N, qianjin_only=False)
            quotes = _load_quotes(db, d, top)
            ex_set = _ex_rights_set(db, d)
            twii_ret = day_ctx[d]["twii_ret"]
            for q in quotes.values():
                unit_acc_rows.append(
                    {
                        "foreign_net": q.get("foreign_net"),
                        "volume": q.get("volume"),
                    }
                )
            for uni in ("top500", "qianjin"):
                st = stock_hit_stats_for_day(
                    d,
                    twii_ret,
                    universe=uni,
                    sids=top,
                    quotes=quotes,
                    ex_set=ex_set,
                )
                day_rec = {
                    "as_of": d,
                    "lit": res.lit,
                    "lead_sync": res.lead_sync,
                    "dump_day": bool(
                        twii_ret is not None and twii_ret <= default_params.dump_day_pct
                    ),
                    "twii_ret_d": twii_ret,
                    "universe": uni,
                    "n_ok": st["n_ok"],
                    "n_ex_rights": st["n_ex_rights"],
                    "n_hit_ex_excl": st["n_hit_ex_excl"],
                    "hit_rate_ex_excl": st["hit_rate_ex_excl"],
                    "hit_rate_ex_incl": st["hit_rate_ex_incl"],
                    "data_source": "wayne_market.db",
                }
                fd.write(json.dumps(day_rec, ensure_ascii=False) + "\n")
                stock_hit_summary[uni]["days"].append(dict(day_rec))
                if persist_event_rows and res.lit:
                    for r in st["rows"]:
                        fe.write(
                            json.dumps(
                                {
                                    "as_of": d,
                                    "universe": uni,
                                    "lead_sync": res.lead_sync,
                                    "volume_unit": VOLUME_UNIT,
                                    "foreign_net_unit": FOREIGN_NET_UNIT,
                                    "sell_share_unit": SELL_SHARE_UNIT,
                                    **r,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )

    for uni in ("top500", "qianjin"):
        lit_rates, dark_rates, lit_lead, lit_sync = [], [], [], []
        for rec in stock_hit_summary[uni]["days"]:
            hr = rec.get("hit_rate_ex_excl")
            if hr is None:
                continue
            if rec.get("lit"):
                lit_rates.append(hr)
                if rec.get("lead_sync") == "lead":
                    lit_lead.append(hr)
                elif rec.get("lead_sync") == "sync":
                    lit_sync.append(hr)
            else:
                dark_rates.append(hr)

        def _avg(xs):
            return sum(xs) / len(xs) if xs else None

        stock_hit_summary[uni]["lit"] = {
            "n_days": len(lit_rates),
            "avg_hit_rate_ex_excl": _avg(lit_rates),
        }
        stock_hit_summary[uni]["base_dark"] = {
            "n_days": len(dark_rates),
            "avg_hit_rate_ex_excl": _avg(dark_rates),
        }
        stock_hit_summary[uni]["lit_lead"] = {
            "n_days": len(lit_lead),
            "avg_hit_rate_ex_excl": _avg(lit_lead),
        }
        stock_hit_summary[uni]["lit_sync"] = {
            "n_days": len(lit_sync),
            "avg_hit_rate_ex_excl": _avg(lit_sync),
        }

    units_rep = unit_consistency_report(unit_acc_rows)
    print(
        f"== 單位檢查 volume={VOLUME_UNIT} foreign_net={FOREIGN_NET_UNIT} "
        f"sell_share={SELL_SHARE_UNIT} ok={units_rep.get('units_ok')} "
        f"n_sell={units_rep.get('n_sell_rows')} gt10={units_rep.get('n_sell_share_gt10')}",
        flush=True,
    )
    report = {
        "generated_at": _now_iso(),
        "tz": "Asia/Taipei",
        "units": {
            "lots_per_share": LOTS_PER_SHARE,
            "volume": VOLUME_UNIT,
            "foreign_net": FOREIGN_NET_UNIT,
            "sell_share": SELL_SHARE_UNIT,
            "twii_ret": "％",
            "night_pct": "％",
            "consistency": units_rep,
        },
        "data_policy": {
            "db_first": True,
            "official_yahoo_fill_on_gap": not skip_yahoo_fill,
            "persist_fill_to_us_overnight": not skip_yahoo_fill,
            "missing_marked": True,
            "no_fake_numbers": True,
            "source_tables": [
                "us_overnight",
                "futures_daily",
                "index_daily",
                "daily_quotes",
                "ex_rights",
            ],
        },
        "backfill_stats": {
            k: fill_stats.get(k)
            for k in (
                "already_in_db",
                "filled_from_yahoo",
                "outer_filled",
                "n_still_missing",
                "yahoo_sessions",
                "policy",
                "skipped",
                "reason",
            )
            if k in fill_stats or fill_stats.get("skipped")
        },
        "window": {"start": _ymd(start), "end": _ymd(end), "n_open_days": len(days)},
        "us_overnight_coverage_before": {
            k: cov0[k]
            for k in (
                "n_rows",
                "n_with_us_keys",
                "n_with_outer",
                "min_as_of",
                "max_as_of",
                "source",
            )
        },
        "us_overnight_coverage": {
            k: cov[k]
            for k in (
                "n_rows",
                "n_with_us_keys",
                "n_with_outer",
                "min_as_of",
                "max_as_of",
                "source",
            )
        },
        "rules": {
            "not_buy_signal": True,
            "no_leave_zero_change": True,
            "empty_days_excluded_from_n": True,
            "full_grid": True,
            "full_open_days": True,
            "top500": TOP_N,
            "qianjin_px": QIANJIN_PX,
            "lookback_cal_days": LOOKBACK_CAL_DAYS,
        },
        "data_coverage": {
            "tx_night_days": len(tx_n),
            "te_night_days": len(te_n),
            "foreign_dense_days": len(dense_ss),
            "missing_us_days_in_window": missing_us_days,
        },
        "grid": summary_grid,
        "stock_hit_default": {
            k: {kk: vv for kk, vv in v.items() if kk != "days"}
            for k, v in stock_hit_summary.items()
        },
        "stock_hit_default_full_days_path": stock_day_path,
        "default_params_key": default_key,
        "n_lit_default": len(event_days_default),
    }
    report_path = os.path.join(out_dir, "fear_composite_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    md = _render_zh_summary(report, summary_grid, stock_hit_summary, default_key)
    md_path = os.path.join(out_dir, "fear_composite_summary_zh.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"== 完成 report={report_path}", flush=True)
    print(f"== 中文摘要 {md_path}", flush=True)
    return report


def _render_zh_summary(
    report: Dict[str, Any],
    grid: List[Dict[str, Any]],
    stock_hit: Dict[str, Any],
    default_key: str,
) -> str:
    cov = report.get("us_overnight_coverage") or {}
    bf = report.get("backfill_stats") or {}
    cov0 = report.get("us_overnight_coverage_before") or {}
    lines = [
        "# FearComposite₀ 離線全樣本對質摘要（本庫→缺補→仍缺標缺）",
        "",
        f"- 產生時間（台北）：`{report.get('generated_at')}`",
        f"- 資料政策：**本庫優先**；缺欄 → Yahoo 官方日 K 補齊並落庫；仍缺才標缺；不准假數",
        f"- 窗：`{report['window']['start']}`→`{report['window']['end']}`，"
        f"開市日 n={report['window']['n_open_days']}（全日，非抽樣）",
        f"- 補齊前 `us_overnight`：列={cov0.get('n_rows')} 美股鍵={cov0.get('n_with_us_keys')} "
        f"外圍={cov0.get('n_with_outer')}",
        f"- 補齊後 `us_overnight`：列={cov.get('n_rows')} 美股鍵={cov.get('n_with_us_keys')} "
        f"外圍={cov.get('n_with_outer')}（{cov.get('min_as_of')}→{cov.get('max_as_of')}）",
        f"- 外聯補：本庫已有={bf.get('already_in_db')} Yahoo補美股={bf.get('filled_from_yahoo')} "
        f"補外圍={bf.get('outer_filled')} 仍缺={bf.get('n_still_missing')}",
        f"- 窗內仍缺美股鍵日={report['data_coverage']['missing_us_days_in_window']}（不算 n）",
        f"- 法人密日：{report['data_coverage']['foreign_dense_days']}",
        f"- TX／TE 夜盤可算日：{report['data_coverage']['tx_night_days']}／"
        f"{report['data_coverage']['te_night_days']}",
        "- **不是買訊**；不准改 leave_zero。",
        "",
        "## 單位（張≠股）",
        f"- 1 張＝{LOTS_PER_SHARE} 股",
        f"- `volume`＝{VOLUME_UNIT}；`foreign_net`＝{FOREIGN_NET_UNIT}；"
        f"`sell_share`＝{SELL_SHARE_UNIT}；報酬／夜盤＝％",
        f"- 一致性：ok={((report.get('units') or {}).get('consistency') or {}).get('units_ok')} "
        f"賣超列 n={((report.get('units') or {}).get('consistency') or {}).get('n_sell_rows')} "
        f"佔量>10 筆數={((report.get('units') or {}).get('consistency') or {}).get('n_sell_share_gt10')}",
        "",
        "## 預設參數（計畫稿）",
        f"- params_key=`{default_key}`",
    ]
    cell = next((g for g in grid if g["params_key"] == default_key), None)
    if cell:
        lines += [
            f"- 可評估日={cell['n_evaluable']}；略過={cell['n_skip']}；"
            f"亮={cell['n_lit']}；未亮={cell['n_dark']}",
            "",
            "### F→Dump（亮 vs 未亮基線；分 Lead／Sync／dump）",
        ]
        for ls in ("all", "lead", "sync"):
            for df in ("all", "exclude_dump"):
                lit = cell["F_Dump"].get(f"lit|{ls}|{df}") or {}
                base = cell["F_Dump"].get(f"base|{ls}|{df}") or {}
                lines.append(f"- **{ls}／{df}**")
                for h in (1, 3, 5):
                    lh = lit.get(f"h{h}") or {}
                    bh = base.get(f"h{h}") or {}
                    lines.append(
                        f"  - h{h}：亮 n={lh.get('n')} avg={_fmt(lh.get('avg_ret'))}% "
                        f"負報率={_fmt_rate(lh.get('hit_rate'))}；"
                        f"基線 n={bh.get('n')} avg={_fmt(bh.get('avg_ret'))}% "
                        f"負報率={_fmt_rate(bh.get('hit_rate'))}"
                    )
        lines += ["", "### F→ForeignSell（當日 Σ賣超佔量 ≥ 密窗 P90）"]
        for ls in ("all", "lead", "sync"):
            lit = cell["F_ForeignSell"].get(f"lit|{ls}") or {}
            base = cell["F_ForeignSell"].get(f"base|{ls}") or {}
            lines.append(
                f"- **{ls}**：亮 n={lit.get('n')} hit={lit.get('hit')} "
                f"率={_fmt_rate(lit.get('hit_rate'))}；"
                f"基線 n={base.get('n')} hit={base.get('hit')} "
                f"率={_fmt_rate(base.get('hit_rate'))}；"
                f"P90={_fmt(lit.get('p90_thr'))}"
            )
    lines += ["", "## F→StockHit（預設參數；Top500／千金分開）"]
    for uni in ("top500", "qianjin"):
        block = stock_hit.get(uni) or {}
        lines.append(f"### {uni}")
        for k in ("lit", "lit_lead", "lit_sync", "base_dark"):
            b = block.get(k) or {}
            lines.append(
                f"- {k}：n_days={b.get('n_days')} "
                f"avg_hit_rate(除權息排除)={_fmt_rate(b.get('avg_hit_rate_ex_excl'))}"
            )
    lines += ["", "## 全網格一覽（每組 n_lit／可評估）"]
    for g in grid:
        lines.append(
            f"- `{g['params_key']}`：可評估={g['n_evaluable']} 亮={g['n_lit']} "
            f"略過={g['n_skip']}"
        )
    lines += [
        "",
        "## 硬邊界複核",
        "- 全日日全跑、網格全跑、Top500 全檔、千金分開、Lead／Sync／dump／除權息分表。",
        "- 本庫優先；缺欄一次 bulk Yahoo 日 K（每符號整段 range）落庫；仍缺分開標，不准假數。",
        "- 過程禁止抽測；空日／仍缺美股鍵不計 n。",
        "",
    ]
    return "\n".join(lines) + "\n"


def _fmt(x: Any) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x):.3f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_rate(x: Any) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def main() -> int:
    ap = argparse.ArgumentParser(description="FearComposite₀ 庫內全樣本離線回測")
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--start", default="", help="YYYYMMDD；空＝自動約 1y 開市日")
    ap.add_argument("--end", default="", help="YYYYMMDD；空＝庫內加權末日")
    ap.add_argument(
        "--out",
        default="/opt/cursor/artifacts/fear-composite-backtest",
    )
    ap.add_argument(
        "--no-event-rows",
        action="store_true",
        help="不寫逐檔 jsonl（仍算全日全母體彙總）",
    )
    ap.add_argument("--yahoo-range", default="2y", help="缺欄外聯 Yahoo 日 K 窗")
    ap.add_argument(
        "--skip-yahoo-fill",
        action="store_true",
        help="略過外聯（僅本庫；資訊不完整時可評估 n 會偏小）",
    )
    args = ap.parse_args()
    db = args.db
    if not os.path.isfile(db):
        print(f"缺庫：{db}", file=sys.stderr)
        return 2
    days_probe = list_tw_open_days(db, "20200101", "20991231")
    end = _ymd(args.end) or (days_probe[-1] if days_probe else "")
    if args.start:
        start = _ymd(args.start)
    else:
        start = days_probe[max(0, len(days_probe) - 260)] if days_probe else ""
    if not start or not end:
        print("無法決定窗", file=sys.stderr)
        return 2
    print(f"窗 {start}→{end}（本庫→缺補官方→仍缺標缺）", flush=True)
    run_backtest(
        db,
        start=start,
        end=end,
        out_dir=args.out,
        persist_event_rows=not args.no_event_rows,
        yahoo_range=args.yahoo_range,
        skip_yahoo_fill=bool(args.skip_yahoo_fill),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
