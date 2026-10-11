#!/usr/bin/env python3
"""準再緊 dig：一次掃完 ma60_lower vs ma60_lower_tight（不改買訊）。

比 red_arrow_backtest 快：每檔只算一次 mask，再對 as_of 取末根分數。
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

from decision_card_signals import leave_zero_from_quote_df  # noqa: E402
from red_arrow_quant import (  # noqa: E402
    KIND,
    SCORE_HORIZONS,
    TAG_BASE,
    TAG_FILTER,
    TAG_HOLD,
    TAG_LOW,
    TAG_NEXT,
    TAG_NONE,
    TAG_PREV,
    _false_break,
    _fwd_ret,
    _ymd,
    gate_status,
    nav_low_arrow_first_mask,
    nav_low_hold_low_confirm_mask,
    nav_low_ma60_lower_mask,
    nav_low_ma60_lower_tight_mask,
    nav_low_ma60_vol_mask,
    persist_scores,
    recompute_rates,
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


def _score_all_asofs(df: pd.DataFrame, as_ofs: set[str]) -> list[dict]:
    """每檔一次 mask；對每個 as_of 只取當日末根（無前視）。"""
    g = df.copy()
    g["date"] = g["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    g = g.sort_values("date").reset_index(drop=True)
    if len(g) < 80:
        return []
    lows = nav_low_arrow_first_mask(g)
    prev_f = nav_low_ma60_vol_mask(g)
    hold_f = nav_low_hold_low_confirm_mask(g)
    filt = nav_low_ma60_lower_mask(g)
    tight = nav_low_ma60_lower_tight_mask(g)
    closes = pd.to_numeric(g["close"], errors="coerce").tolist()
    dates = g["date"].tolist()
    sid = str(g["stock_id"].iloc[-1] or "") if "stock_id" in g.columns else ""
    name = str(g["stock_name"].iloc[-1] or "") if "stock_name" in g.columns else ""
    rows: list[dict] = []
    for i, d in enumerate(dates):
        if d not in as_ofs or i < 59:
            continue
        # leave_zero 只用截至當日（含）
        hist = g.iloc[: i + 1]
        lz_hit = bool(leave_zero_from_quote_df(hist))
        tags = [
            (TAG_LOW, bool(lows.iloc[i])),
            (TAG_PREV, bool(prev_f.iloc[i])),
            (TAG_HOLD, bool(hold_f.iloc[i])),
            (TAG_FILTER, bool(filt.iloc[i])),
            (TAG_NEXT, bool(tight.iloc[i])),
            (TAG_BASE, lz_hit),
            (TAG_NONE, (not bool(lows.iloc[i])) and (not lz_hit)),
        ]
        entry = float(closes[i] or 0)
        for tag, hit in tags:
            if not hit:
                continue
            for h in SCORE_HORIZONS:
                ret = _fwd_ret(closes, i, h)
                fb = _false_break(closes, i, h, entry=entry)
                if ret is None:
                    verdict = "pending"
                elif ret > 0:
                    verdict = "hit"
                else:
                    verdict = "miss"
                check_as = ""
                exit_px = None
                if ret is not None and i + h < len(g):
                    check_as = _ymd(g["date"].iloc[i + h])
                    exit_px = float(closes[i + h])
                rows.append(
                    {
                        "kind": KIND,
                        "as_of": d,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    db = str(Path(args.db))
    if not Path(db).is_file():
        print(f"no db: {db}", file=sys.stderr)
        return 2
    dates = _as_of_list(db, args.days)
    as_ofs = set(dates)
    sids = _active_sids(db, args.limit)
    written = 0
    for sid, name in sids:
        df = _load_sid(db, sid, name)
        if df.empty or len(df) < 80:
            continue
        rows = _score_all_asofs(df, as_ofs)
        if rows:
            written += persist_scores(db, rows)
    rates = recompute_rates(db)
    st = gate_status(db, horizon=5)
    st1 = gate_status(db, horizon=1)

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

    filt = st.get("filtered") or {}
    nxt = st.get("next_filter") or {}
    print(
        f"wrote={written} rates_keys={len(rates)} "
        f"low[{_r(st['low'])}] prev[{_r(st.get('prev_filter') or {})}] "
        f"filt[{_r(filt)}] next[{_r(nxt)}] "
        f"lz[{_r(st['leave_zero'])}] "
        f"beats_current={st.get('beats_current_entry')} "
        f"next_promote={st.get('next_promote_ready')} "
        f"n_ok={st['n_ok']} beat_lz={st['beats_leave_zero']}"
    )
    print(
        f"h1_filt[{_r(st1.get('filtered') or {})}] "
        f"h1_next[{_r(st1.get('next_filter') or {})}]"
    )
    # 嚴格 dig 閘：hit／avg／fb 都要贏現況（不只 _beats 的 hit 優先）
    if filt.get("n") and nxt.get("n"):
        hit_ok = (nxt.get("hit_rate") or 0) > (filt.get("hit_rate") or 0)
        avg_ok = (nxt.get("avg_ret") is not None and filt.get("avg_ret") is not None
                  and nxt["avg_ret"] > filt["avg_ret"])
        fb_ok = (nxt.get("false_break_rate") is not None
                 and filt.get("false_break_rate") is not None
                 and nxt["false_break_rate"] < filt["false_break_rate"])
        days_ok = (nxt.get("unique_days") or 0) >= 20 and (filt.get("unique_days") or 0) >= 20
        print(
            f"strict_vs_ma60_lower days_ok={days_ok} hit_ok={hit_ok} "
            f"avg_ok={avg_ok} fb_ok={fb_ok} "
            f"win_all={days_ok and hit_ok and avg_ok and fb_ok}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
