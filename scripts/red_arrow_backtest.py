#!/usr/bin/env python3
"""紅箭頭代理 vs 過濾候選／leave_zero／無箭頭：正式回測取樣（過關前不當買訊）。

用法（本機／Render 碟）：
  python scripts/red_arrow_backtest.py --db data/wayne_market.db --days 40 --limit 80

只寫 wayne_evolve.db；印 gate_status 一句
（n／假突破前後／是否贏 leave_zero／能不能 promote）。
不准改海選、不准改話筒買訊。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from red_arrow_quant import (  # noqa: E402
    gate_status,
    persist_scores,
    recompute_rates,
    score_stock_day,
)


def _as_of_list(db: str, days: int) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT replace(CAST(date AS TEXT),'-','') AS d
            FROM daily_quotes
            WHERE length(replace(CAST(date AS TEXT),'-',''))=8
            ORDER BY d DESC
            LIMIT ?
            """,
            (max(1, int(days)),),
        ).fetchall()
    finally:
        conn.close()
    return [str(r[0]) for r in reversed(rows)]


def _active_sids(db: str, limit: int) -> list[tuple[str, str]]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
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
    return [(str(a), str(b or "")) for a, b in rows]


def _load_sid(db: str, sid: str, name: str) -> pd.DataFrame:
    conn = sqlite3.connect(db)
    try:
        q = pd.read_sql_query(
            """
            SELECT replace(CAST(date AS TEXT),'-','') AS date,
                   open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=? AND close > 0
            ORDER BY date
            """,
            conn,
            params=(sid,),
        )
    finally:
        conn.close()
    if q.empty:
        return q
    q["stock_id"] = sid
    q["stock_name"] = name
    return q


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--days", type=int, default=30, help="最近幾個官方完整日當 as_of")
    ap.add_argument("--limit", type=int, default=60, help="掃幾檔股票（省時）")
    args = ap.parse_args()
    db = str(Path(args.db))
    if not Path(db).is_file():
        print(f"no db: {db}", file=sys.stderr)
        return 2
    dates = _as_of_list(db, args.days)
    sids = _active_sids(db, args.limit)
    written = 0
    for sid, name in sids:
        df = _load_sid(db, sid, name)
        if df.empty or len(df) < 80:
            continue
        for as_of in dates:
            rows = score_stock_day(df, as_of=as_of)
            if rows:
                written += persist_scores(db, rows)
    rates = recompute_rates(db)
    st = gate_status(db, horizon=5)
    st1 = gate_status(db, horizon=1)
    low, prev = st["low"], st.get("prev_filter") or {}
    filt = st.get("filtered") or {}
    lz, none = st["leave_zero"], st["no_arrow"]

    def _r(p: dict) -> str:
        hr = p.get("hit_rate")
        fb = p.get("false_break_rate")
        ar = p.get("avg_ret")
        return (
            f"n={p.get('n')} days={p.get('unique_days')} "
            f"hit={hr if hr is None else round(hr, 3)} "
            f"fb={fb if fb is None else round(fb, 3)} "
            f"avg={ar if ar is None else round(ar, 3)}"
        )

    drop = st.get("false_break_drop")
    drop_p = st.get("false_break_drop_vs_prev")
    print(
        f"wrote={written} rates_keys={len(rates)} "
        f"low[{_r(low)}] prev[{_r(prev)}] filt[{_r(filt)}] "
        f"lz[{_r(lz)}] none[{_r(none)}] "
        f"fb_drop={drop if drop is None else round(drop, 3)} "
        f"fb_drop_vs_prev={drop_p if drop_p is None else round(drop_p, 3)} "
        f"fb_ok={st.get('false_break_ok')} beats_prev={st.get('beats_prev')} "
        f"n_ok={st['n_ok']} beat_lz={st['beats_leave_zero']} "
        f"beat_none={st['beats_no_arrow']} "
        f"promote={st['promote_ready']} — {st['note']}"
    )
    f1 = st1.get("filtered") or {}
    l1 = st1.get("low") or {}
    p1 = st1.get("prev_filter") or {}
    print(
        f"h1_low_fb={None if l1.get('false_break_rate') is None else round(l1['false_break_rate'], 3)} "
        f"h1_prev_fb={None if p1.get('false_break_rate') is None else round(p1['false_break_rate'], 3)} "
        f"h1_filt_fb={None if f1.get('false_break_rate') is None else round(f1['false_break_rate'], 3)} "
        f"h1_fb_drop={st1.get('false_break_drop') if st1.get('false_break_drop') is None else round(st1['false_break_drop'], 3)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
