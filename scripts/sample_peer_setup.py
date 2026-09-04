#!/usr/bin/env python3
"""採樣飆客兩則個股文拆出的可量化規則（不寫入口號）。

文 A：同板塊相對強度（金像電 vs 金居）— 流動性同業 20 日報酬排名。
文 B：漲數倍後回撤 35–50%、窒息量近支撐、爆量貼月高觀望（聯亞／奇鋐）。

對 wayne_market.db 週五截面 + 5/10/20 日前瞻報酬，相對當日流動母體中位數。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(db: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = sqlite3.connect(db)
    u = pd.read_sql_query(
        """
        SELECT stock_id, stock_name, industry, asset_type
        FROM stock_universe
        WHERE is_active=1 AND length(stock_id)=4
          AND UPPER(COALESCE(asset_type,'')) IN ('STOCK','KY','')
        """,
        conn,
    )
    q = pd.read_sql_query(
        """
        SELECT replace(date,'-','') AS date, stock_id, close, high, low, volume, turnover_k
        FROM daily_quotes
        WHERE length(stock_id)=4 AND close > 0
        ORDER BY stock_id, date
        """,
        conn,
    )
    conn.close()
    q["date"] = q["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    u["industry"] = u["industry"].fillna("").astype(str).str.strip()
    return u, q


def _summarize(label: str, rets: pd.Series) -> dict:
    x = pd.to_numeric(rets, errors="coerce").dropna()
    if x.empty:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": int(len(x)),
        "mean": float(x.mean()),
        "med": float(x.median()),
        "hit": float((x > 0).mean()),
        "p25": float(x.quantile(0.25)),
        "p75": float(x.quantile(0.75)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "wayne_market.db"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    u, q = _load(args.db)
    q = q.merge(u[["stock_id", "industry", "stock_name"]], on="stock_id", how="inner")
    q = q[~q["industry"].isin(["", "ETF", "指數投資證券", "存託憑證"])]
    q = q.sort_values(["stock_id", "date"]).reset_index(drop=True)

    g = q.groupby("stock_id", sort=False)
    q["ret20"] = g["close"].pct_change(20)
    q["ret60"] = g["close"].pct_change(60)
    q["fwd5"] = g["close"].shift(-5) / q["close"] - 1.0
    q["fwd10"] = g["close"].shift(-10) / q["close"] - 1.0
    q["fwd20"] = g["close"].shift(-20) / q["close"] - 1.0

    def _roll_max(s: pd.Series, n: int, minp: int) -> pd.Series:
        return s.rolling(n, min_periods=minp).max()

    def _roll_min(s: pd.Series, n: int, minp: int) -> pd.Series:
        return s.rolling(n, min_periods=minp).min()

    def _roll_mean(s: pd.Series, n: int, minp: int) -> pd.Series:
        return s.rolling(n, min_periods=minp).mean()

    q["hi20"] = g["close"].transform(lambda s: _roll_max(s, 20, 20))
    q["lo20"] = g["close"].transform(lambda s: _roll_min(s, 20, 20))
    q["hi120"] = g["high"].transform(lambda s: _roll_max(s, 120, 80))
    q["lo120"] = g["low"].transform(lambda s: _roll_min(s, 120, 80))
    q["vol60"] = g["volume"].transform(lambda s: _roll_mean(s, 60, 20))
    q["to20"] = g["turnover_k"].transform(lambda s: _roll_mean(s, 20, 10))
    q["q60r"] = q["volume"] / q["vol60"].replace(0, np.nan)
    q["dd120"] = (q["hi120"] - q["close"]) / q["hi120"].replace(0, np.nan)
    q["run120"] = (q["hi120"] / q["lo120"].replace(0, np.nan)) - 1.0
    q["near_hi20"] = q["close"] / q["hi20"].replace(0, np.nan)
    q["near_lo20"] = q["close"] / q["lo20"].replace(0, np.nan)

    def _bars_since_high(s: pd.Series) -> pd.Series:
        arr = s.to_numpy(dtype=float)
        out = np.full(len(arr), np.nan)
        for i in range(19, len(arr)):
            w = arr[i - 19 : i + 1]
            if np.isnan(w).any():
                continue
            out[i] = 19 - int(np.argmax(w))
        return pd.Series(out, index=s.index)

    q["since_hi20"] = g["close"].transform(_bars_since_high)

    dates = sorted(q["date"].unique())
    # 需要 120 根回看 + 20 根前瞻：從第 140 個交易日起、到倒數第 21 日
    if len(dates) < 180:
        print("not enough dates", len(dates))
        return 1
    sample_dates = dates[140:-21:5]
    print(f"dates {dates[0]}..{dates[-1]} n={len(dates)} sample={len(sample_dates)}")

    rows = []
    for d in sample_dates:
        day = q[q["date"] == d].copy()
        liq = day[(day["volume"] >= 1000) & (day["turnover_k"] >= 30000) & day["ret20"].notna()]
        if len(liq) < 80:
            continue
        m5 = float(liq["fwd5"].median())
        m10 = float(liq["fwd10"].median())
        m20 = float(liq["fwd20"].median())
        liq = liq.copy()
        liq["x5"] = liq["fwd5"] - m5
        liq["x10"] = liq["fwd10"] - m10
        liq["x20"] = liq["fwd20"] - m20

        # liquid industry peers: top 24 by 20d turnover within industry
        liq["ind_rank"] = np.nan
        liq["ind_n"] = 0
        for ind, gind in liq.groupby("industry"):
            top = gind.nlargest(min(24, len(gind)), "to20") if "to20" in gind else gind
            if len(top) < 5:
                continue
            ranks = top["ret20"].rank(pct=True)
            liq.loc[top.index, "ind_rank"] = ranks
            liq.loc[top.index, "ind_n"] = len(top)

        rows.append(liq)

    panel = pd.concat(rows, ignore_index=True)
    print("panel rows", len(panel), "names", panel["stock_id"].nunique())

    buckets = {
        "baseline": panel,
        "peer_strong_top30": panel[panel["ind_rank"] >= 0.70],
        "peer_mid": panel[(panel["ind_rank"] >= 0.40) & (panel["ind_rank"] <= 0.60)],
        "peer_weak_bot30": panel[panel["ind_rank"] <= 0.30],
        "near_hi20": panel[panel["near_hi20"] >= 0.98],
        "since_hi20_0_3": panel[panel["since_hi20"] <= 3],
        "since_hi20_10_25": panel[(panel["since_hi20"] >= 10) & (panel["since_hi20"] <= 25)],
        "since_hi20_40p": panel[panel["since_hi20"] >= 40],
        "mult_dd_35_50": panel[(panel["run120"] >= 1.0) & (panel["dd120"] >= 0.35) & (panel["dd120"] <= 0.50)],
        "mult_dd_lt15": panel[(panel["run120"] >= 1.0) & (panel["dd120"] < 0.15)],
        "mult_dd_gt55": panel[(panel["run120"] >= 1.0) & (panel["dd120"] > 0.55)],
        "dry_q045": panel[panel["q60r"] <= 0.45],
        "dry_near_lo20": panel[(panel["q60r"] <= 0.45) & (panel["near_lo20"] <= 1.08)],
        "dry_and_dd35": panel[
            (panel["run120"] >= 1.0)
            & (panel["dd120"] >= 0.35)
            & (panel["dd120"] <= 0.50)
            & (panel["q60r"] <= 0.55)
        ],
        "spike_hi20_run": panel[
            (panel["q60r"] >= 2.0) & (panel["near_hi20"] >= 0.98) & (panel["ret60"] >= 0.30)
        ],
        "spike_hi20": panel[(panel["q60r"] >= 2.0) & (panel["near_hi20"] >= 0.98)],
        "strong_and_not_spike": panel[
            (panel["ind_rank"] >= 0.70)
            & ~((panel["q60r"] >= 2.0) & (panel["near_hi20"] >= 0.98) & (panel["ret60"] >= 0.30))
        ],
        "peer_strong_near_hi": panel[(panel["ind_rank"] >= 0.70) & (panel["near_hi20"] >= 0.98)],
        "peer_weak_near_hi": panel[(panel["ind_rank"] <= 0.30) & (panel["near_hi20"] >= 0.98)],
    }

    lines = []
    header = f"{'bucket':<24} {'n':>6} {'x5m':>8} {'x10m':>8} {'x20m':>8} {'h10':>6} {'x10med':>8}"
    print(header)
    lines.append(header)
    summaries = []
    for name, df in buckets.items():
        s5 = _summarize(name, df["x5"])
        s10 = _summarize(name, df["x10"])
        s20 = _summarize(name, df["x20"])
        row = (
            f"{name:<24} {s10.get('n',0):>6} "
            f"{s5.get('mean', float('nan')):>8.3%} {s10.get('mean', float('nan')):>8.3%} "
            f"{s20.get('mean', float('nan')):>8.3%} {s10.get('hit', float('nan')):>6.1%} "
            f"{s10.get('med', float('nan')):>8.3%}"
        )
        print(row)
        lines.append(row)
        summaries.append((name, s5, s10, s20, df))

    # named pairs on last sample date with quotes
    last_d = sample_dates[-1] if sample_dates else dates[-22]
    print("\n=== named pair last-sample-ish ===", last_d)
    for sid in ("2368", "8358", "3081", "3017", "2383", "2330"):
        sub = panel[panel["stock_id"] == sid].tail(3)
        if sub.empty:
            print(sid, "no sample")
            continue
        r = sub.iloc[-1]
        print(
            f"{sid} {r.get('stock_name')} d={r['date']} ret20={r['ret20']:.1%} "
            f"ind_rank={r['ind_rank']} dd120={r['dd120']:.1%} q60r={r['q60r']:.2f} "
            f"since={r['since_hi20']} x10={r['x10']:.2%}"
        )

    # as-of 20260904 live snapshot (no forward)
    live = q[q["date"] == dates[-1]].copy()
    live = live[(live["volume"] >= 1000) & (live["turnover_k"] >= 30000)]
    print("\n=== live", dates[-1], "named ===")
    for sid in ("2368", "8358", "3081", "3017", "2383", "2330", "3653"):
        hit = live[live["stock_id"] == sid]
        if hit.empty:
            print(sid, "illiquid or missing")
            continue
        r = hit.iloc[-1]
        peers = live[live["industry"] == r["industry"]].nlargest(24, "to20")
        rank = float(peers["ret20"].rank(pct=True).get(r.name, np.nan)) if len(peers) >= 5 else float("nan")
        print(
            f"{sid} {r['stock_name']} {r['industry']} close={r['close']} "
            f"ret20={r['ret20']:.1%} rank={rank:.2f} n={len(peers)} "
            f"dd={r['dd120']:.1%} run={r['run120']:.0%} q={r['q60r']:.2f} "
            f"hi20={r['near_hi20']:.3f} since={r['since_hi20']}"
        )

    out = args.out or "/opt/cursor/artifacts/peer_setup_sample.txt"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
