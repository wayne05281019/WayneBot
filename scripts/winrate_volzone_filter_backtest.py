#!/usr/bin/env python3
"""勝率買點母體 × 大量區／裸 K＋量再篩・歷史回測（建議哪檔靜默量化）。

母體＝歷史 leave_zero 且過 buy_exclude_v5（現況整包 proxy；可選 AI ONLY）。
變體＝TRACK_VARIANTS（含 no_upper_dump／vol_own_mid／bull_close／combo_*）。
不准改黃金買點公式；不寫話筒；結果進 evolve tape＋JSON 報告。

用法：
  python scripts/winrate_volzone_filter_backtest.py \\
    --db data/wayne_market.db --start 20250101 --end 20261001 \\
    --out /tmp/winrate-volzone-filter-stats.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from buy_exclude import should_exclude_buy  # noqa: E402
from decision_card_signals import leave_zero_bar_indices  # noqa: E402
from winrate_volzone_filter_verify import (  # noqa: E402
    KIND,
    MIN_WR_LIFT,
    PRIMARY_H,
    SCORE_HORIZONS,
    TRACK_VARIANTS,
    VARIANT_CURRENT,
    compute_filter_features,
    ensure_tables,
    persist_tape,
    recompute_rates,
    score_pending,
    variant_pass,
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _active_sids(db: str, *, ai_only: bool) -> List[str]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT stock_id FROM stock_universe
            WHERE is_active=1 AND length(stock_id)=4
              AND stock_id GLOB '[0-9][0-9][0-9][0-9]'
              AND UPPER(COALESCE(asset_type,'')) IN ('STOCK','KY','')
            ORDER BY stock_id
            """
        ).fetchall()
    finally:
        conn.close()
    sids = [str(r[0]) for r in rows]
    if not ai_only:
        return sids
    try:
        from winrate_ai_priority import load_priority_flags

        flags = load_priority_flags(db, sids)
        keep = [s for s in sids if flags.get(s)]
        return keep or sids
    except Exception:
        # 分區失敗＝退回全母體（不准假刪）
        return sids


def _load_sid(db: str, sid: str, end: str) -> pd.DataFrame:
    conn = sqlite3.connect(db)
    try:
        q = pd.read_sql_query(
            """
            SELECT replace(CAST(date AS TEXT),'-','') AS date,
                   stock_name, open, high, low, close, volume, turnover_k
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY date
            """,
            conn,
            params=(sid, end),
        )
    finally:
        conn.close()
    if q is None or q.empty:
        return pd.DataFrame()
    q["stock_id"] = sid
    return q


def _forward_close(closes: Sequence[float], i: int, h: int) -> Optional[float]:
    j = i + int(h)
    if j >= len(closes):
        return None
    try:
        c = float(closes[j])
    except (TypeError, ValueError):
        return None
    return c if c > 0 else None


def run_backtest(
    db: str,
    *,
    start: str,
    end: str,
    ai_only: bool = True,
    limit: int = 0,
    persist: bool = True,
) -> Dict[str, Any]:
    start = _ymd(start)
    end = _ymd(end)
    sids = _active_sids(db, ai_only=ai_only)
    if limit > 0:
        sids = sids[:limit]
    # variant -> horizon -> list of (as_of, win, fwd_pct)
    buckets: Dict[str, Dict[int, List[Tuple[str, int, float]]]] = {
        v: {h: [] for h in SCORE_HORIZONS} for v in TRACK_VARIANTS
    }
    tape_rows: List[Dict[str, Any]] = []
    n_events = 0
    n_stocks = 0
    t0 = time.time()
    for sid in sids:
        df = _load_sid(db, sid, end)
        if df is None or len(df) < 70:
            continue
        n_stocks += 1
        try:
            idxs = leave_zero_bar_indices(df) or []
        except Exception:
            continue
        dates = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
        closes = df["close"].astype(float).tolist()
        name = ""
        if "stock_name" in df.columns and len(df):
            name = str(df["stock_name"].iloc[-1] or "")
        for i in idxs:
            try:
                ii = int(i)
            except (TypeError, ValueError):
                continue
            if ii < 64 or ii >= len(df):
                continue
            day = _ymd(dates.iloc[ii])
            if not day or day < start or day > end:
                continue
            # 盤中未收：只認 end 以前完整收
            sub = df.iloc[: ii + 1].copy()
            try:
                if should_exclude_buy(sub):
                    continue
            except Exception:
                continue
            feat = compute_filter_features(sub)
            if not feat:
                continue
            n_events += 1
            entry = float(feat.get("close") or closes[ii] or 0)
            if entry <= 0:
                continue
            for variant in TRACK_VARIANTS:
                if not variant_pass(feat, variant):
                    continue
                if persist:
                    tape_rows.append(
                        {
                            "as_of": day,
                            "sid": sid,
                            "variant": variant,
                            "name": name,
                            "close": entry,
                            "zone_pos": feat.get("zone_pos"),
                            "vol_ratio": feat.get("vol_ratio"),
                            "ma60_rising": feat.get("ma60_rising"),
                            "ma_spread_pct": feat.get("ma_spread_pct"),
                            "dist_h20_pct": feat.get("dist_h20_pct"),
                            "in_band": feat.get("in_band"),
                            "near_press": feat.get("near_press"),
                            "ma20_rising": feat.get("ma20_rising"),
                            "tangled": feat.get("tangled"),
                            "close_ge_ma5": feat.get("close_ge_ma5"),
                            "pressure": feat.get("pressure"),
                            "support": feat.get("support"),
                            "zone_date": feat.get("zone_date"),
                            "bull_close": feat.get("bull_close"),
                            "upper_shadow_ratio": feat.get("upper_shadow_ratio"),
                            "vol_own_pctile": feat.get("vol_own_pctile"),
                            "dump_r1e1": feat.get("dump_r1e1"),
                        }
                    )
                for h in SCORE_HORIZONS:
                    exit_c = _forward_close(closes, ii, h)
                    if exit_c is None:
                        continue
                    fwd = (exit_c - entry) / entry * 100.0
                    win = 1 if exit_c > entry else 0
                    buckets[variant][h].append((day, win, fwd))
    # 聚合：獨立交易日平均勝率
    summary: Dict[str, Any] = {
        "kind": KIND,
        "start": start,
        "end": end,
        "ai_only": ai_only,
        "n_stocks_scanned": n_stocks,
        "n_baseline_events": n_events,
        "elapsed_sec": round(time.time() - t0, 1),
        "primary_h": PRIMARY_H,
        "variants": {},
    }
    for variant in TRACK_VARIANTS:
        summary["variants"][variant] = {}
        for h in SCORE_HORIZONS:
            rows = buckets[variant][h]
            by_day: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
            for day, win, fwd in rows:
                by_day[day].append((win, fwd))
            n_days = len(by_day)
            n_rows = len(rows)
            if n_days <= 0:
                wr = avg = med = None
            else:
                day_wrs = [sum(w for w, _ in xs) / len(xs) for xs in by_day.values()]
                all_fwd = [f for xs in by_day.values() for _, f in xs]
                wr = sum(day_wrs) / len(day_wrs)
                avg = sum(all_fwd) / len(all_fwd)
                med = sorted(all_fwd)[len(all_fwd) // 2]
            summary["variants"][variant][str(h)] = {
                "n_days": n_days,
                "n_rows": n_rows,
                "win_rate": None if wr is None else round(wr, 4),
                "avg_fwd_pct": None if avg is None else round(avg, 4),
                "med_fwd_pct": None if med is None else round(med, 4),
            }
    base = summary["variants"].get(VARIANT_CURRENT, {}).get(str(PRIMARY_H), {})
    base_wr = base.get("win_rate")
    base_avg = base.get("avg_fwd_pct")
    base_n = int(base.get("n_days") or 0)
    best_v = VARIANT_CURRENT
    best_wr = base_wr
    best_avg = base_avg
    for v in TRACK_VARIANTS:
        if v == VARIANT_CURRENT:
            continue
        info = summary["variants"][v].get(str(PRIMARY_H), {})
        wr = info.get("win_rate")
        avg = info.get("avg_fwd_pct")
        n_v = int(info.get("n_days") or 0)
        if wr is None or base_wr is None or n_v < 20:
            continue
        if wr < (base_wr + MIN_WR_LIFT):
            continue
        if base_avg is not None and avg is not None and avg < base_avg:
            continue
        if wr > (best_wr if best_wr is not None else -1):
            best_wr = wr
            best_avg = avg
            best_v = v
    # 報告仍標「相對現況誰最高」；過閘另看 MIN_WR_LIFT
    lead_v, lead_wr, lead_avg = VARIANT_CURRENT, base_wr, base_avg
    for v in TRACK_VARIANTS:
        if v == VARIANT_CURRENT:
            continue
        info = summary["variants"][v].get(str(PRIMARY_H), {})
        wr = info.get("win_rate")
        avg = info.get("avg_fwd_pct")
        n_v = int(info.get("n_days") or 0)
        if wr is None or n_v < 20:
            continue
        if wr > (lead_wr if lead_wr is not None else -1):
            lead_v, lead_wr, lead_avg = v, wr, avg
    passed = bool(
        base_n >= 20
        and best_v != VARIANT_CURRENT
        and best_wr is not None
        and base_wr is not None
        and best_wr >= (base_wr + MIN_WR_LIFT)
    )
    summary["gate"] = {
        "n_days_baseline": base_n,
        "baseline_wr_h5": base_wr,
        "baseline_avg_fwd_h5": base_avg,
        "best_variant": best_v,
        "best_wr_h5": best_wr,
        "best_avg_fwd_h5": best_avg,
        "lead_variant_raw": lead_v,
        "lead_wr_h5_raw": lead_wr,
        "lead_avg_fwd_h5_raw": lead_avg,
        "delta_pt": (
            None
            if lead_wr is None or base_wr is None
            else round((lead_wr - base_wr) * 100.0, 2)
        ),
        "min_wr_lift_pt": round(MIN_WR_LIFT * 100.0, 2),
        "passed": passed,
        "phone_change": False,  # 本腳本／本 PR 不改話筒
        "gate_note": (
            "過閘＝獨立日 n≥20 且＋5日勝率≥現況+"
            f"{MIN_WR_LIFT*100:.1f}pt 且平均報酬不差於現況"
        ),
    }
    if persist and tape_rows:
        ensure_tables(db)
        # 分批寫，避免一次太大
        batch = 2000
        for i in range(0, len(tape_rows), batch):
            persist_tape(db, tape_rows[i : i + batch])
        score_pending(db, cap=end)
        recompute_rates(db)
        summary["persisted_tape_rows"] = len(tape_rows)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--start", default="20250101")
    ap.add_argument("--end", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=0, help="除錯用：只掃前 N 檔")
    ap.add_argument(
        "--all-industries",
        action="store_true",
        help="母體不砍 AI ONLY（對照用；預設與話筒對齊 AI ONLY）",
    )
    ap.add_argument("--no-persist", action="store_true")
    args = ap.parse_args()
    db = args.db
    end = _ymd(args.end)
    if not end:
        conn = sqlite3.connect(db)
        try:
            end = _ymd(
                conn.execute(
                    "SELECT MAX(replace(CAST(date AS TEXT),'-','')) FROM daily_quotes"
                ).fetchone()[0]
            )
        finally:
            conn.close()
    # 前瞻 10 日：end 往前留緩衝
    summary = run_backtest(
        db,
        start=args.start,
        end=end,
        ai_only=not args.all_industries,
        limit=int(args.limit or 0),
        persist=not args.no_persist,
    )
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    out = args.out
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
