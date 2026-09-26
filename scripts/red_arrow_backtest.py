#!/usr/bin/env python3
"""紅箭頭代理 vs 黃金買點：正式回測取樣（過關前不當買訊）。

用法（本機／Render 碟）：
  python scripts/red_arrow_backtest.py --db data/wayne_market.db --days 40 --limit 80

只寫 wayne_evolve.db；印 gate_status 一句（n／是否贏基線／能不能 promote）。
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
    print(
        f"wrote={written} rates_keys={len(rates)} "
        f"n_low={st['low']['n']} n_lz={st['leave_zero']['n']} "
        f"n_ok={st['n_ok']} beat={st['beats_leave_zero']} "
        f"promote={st['promote_ready']} — {st['note']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
