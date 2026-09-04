#!/usr/bin/env python3
"""採樣作者「如何賣」：不同步／同步脫離後 5／10 日報酬，相對當日流動母體。

只印數字，不寫入口號。勝過「貼 20 高還抱」才值得當紀律標。
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

from decision_card_signals import compute_card_temperature
from sell_discipline import classify_how_to_sell
from wayne_navigator import compute_temp_trend_labels

LIQ_VOL = 1000
LIQ_TO_K = 30000.0


def _load(db: str) -> pd.DataFrame:
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
        SELECT replace(date,'-','') AS date, stock_id, close, volume, turnover_k, ma20
        FROM daily_quotes
        WHERE length(stock_id)=4 AND close > 0
        ORDER BY stock_id, date
        """,
        conn,
    )
    conn.close()
    q["date"] = q["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    u["industry"] = u["industry"].fillna("").astype(str).str.strip()
    q = q.merge(u[["stock_id", "industry"]], on="stock_id", how="inner")
    q = q[~q["industry"].isin(["", "ETF", "指數投資證券", "存託憑證"])]
    return q.sort_values(["stock_id", "date"]).reset_index(drop=True)


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


def _fmt(row: dict) -> str:
    if row["n"] == 0:
        return f"{row['label']:24s} n=0"
    return (
        f"{row['label']:24s} n={row['n']:5d}  "
        f"hit={row['hit']*100:5.1f}%  med={row['med']*100:+6.2f}%  "
        f"mean={row['mean']*100:+6.2f}%"
    )


def _stock_flags(g: pd.DataFrame) -> pd.DataFrame:
    close = g["close"].astype(float)
    high20 = close.rolling(20, min_periods=1).max()
    low20 = close.rolling(20, min_periods=1).min()
    high60 = close.rolling(60, min_periods=1).max()
    low60 = close.rolling(60, min_periods=1).min()
    ma20 = pd.to_numeric(g["ma20"], errors="coerce")
    if ma20.isna().all():
        ma20 = close.rolling(20, min_periods=1).mean()
    bias = ((close - ma20) / ma20.replace(0, np.nan) * 100.0).fillna(0.0)
    hl = np.where(close >= high20 * 0.998, "20高", "No")
    temps = [
        compute_card_temperature(
            float(c), float(h20), float(l20), float(b), high60=float(h60), low60=float(l60)
        )
        for c, h20, l20, b, h60, l60 in zip(close, high20, low20, bias, high60, low60)
    ]
    labels, _notes = compute_temp_trend_labels(temps, closes=list(close))
    acts = []
    for i in range(len(g)):
        flags = classify_how_to_sell(hl[: i + 1], labels[: i + 1])
        acts.append(flags["sell_action"] or "")
    out = g.copy()
    out["hl"] = hl
    out["sell_action"] = acts
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "wayne_market.db"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    q = _load(args.db)
    g = q.groupby("stock_id", sort=False)
    q["fwd5"] = g["close"].shift(-5) / q["close"] - 1.0
    q["fwd10"] = g["close"].shift(-10) / q["close"] - 1.0
    dates = sorted(q["date"].unique())
    sample_days = dates[40:-12:5]
    chunks = []
    for sid, sg in q.groupby("stock_id", sort=False):
        if len(sg) < 80:
            continue
        flagged = _stock_flags(sg)
        flagged = flagged[flagged["date"].isin(sample_days)]
        if flagged.empty:
            continue
        chunks.append(flagged[["stock_id", "date", "volume", "turnover_k", "hl", "sell_action", "fwd5", "fwd10"]])
    if not chunks:
        print("no rows")
        return 1
    s = pd.concat(chunks, ignore_index=True)
    liq = (s["volume"] >= LIQ_VOL) & (s["turnover_k"] >= LIQ_TO_K)
    s = s[liq].copy()
    uni = s.groupby("date")["fwd10"].transform("median")
    s["ex10"] = s["fwd10"] - uni
    s["ex5"] = s["fwd5"] - s.groupby("date")["fwd5"].transform("median")

    lines = ["如何賣 採樣（流動母體、每 5 日截面、後 5／10 日超額相對當日中位數）", ""]
    for col, lab in (("fwd10", "後10日"), ("ex10", "後10日超額"), ("fwd5", "後5日"), ("ex5", "後5日超額")):
        lines.append(lab)
        lines.append(_fmt(_summarize("母體", s[col])))
        lines.append(_fmt(_summarize("貼20高還抱", s.loc[s["hl"] == "20高", col])))
        lines.append(_fmt(_summarize("直接減碼", s.loc[s["sell_action"] == "直接減碼", col])))
        lines.append(_fmt(_summarize("準備減碼", s.loc[s["sell_action"] == "準備減碼", col])))
        lines.append("")
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
