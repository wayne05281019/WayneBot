#!/usr/bin/env python3
"""一次算出：黃金買點進場 + 如何賣直接減碼 的來回勝率／獲利％。

三層樣本都跑，不准只留引擎閘那一層：
- engine：對齊現在海選（月K往上、量熱或昨20低、擋5高／空頭）
- wide：跳過月K（先前約 1512）
- profit_only：獲利剛離零＋擋5高＋流動 STOCK/KY（更寬）

出場＝作者如何賣「直接減碼」；最多抱 60 交易日。對照＝死抱 20 交易日。
不是下單、不畫紅箭頭、不改海選桶。
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

from decision_card_signals import (  # noqa: E402
    _MONTHLY_PULLBACK,
    alert_tag,
    cal60_profit_bundle,
    compute_card_temperature,
    leave_zero_screen_ok,
)
from sell_discipline import sell_action_series  # noqa: E402
from wayne_navigator import compute_temp_trend_labels  # noqa: E402

LIQ_VOL = 1000
LIQ_TO_K = 30000.0
HOLD20 = 20
HOLD_MAX = 60


def _load(db: str) -> pd.DataFrame:
    conn = sqlite3.connect(db)
    u = pd.read_sql_query(
        """
        SELECT stock_id, stock_name, industry, asset_type
        FROM stock_universe
        WHERE is_active=1 AND length(stock_id)=4
          AND stock_id GLOB '[0-9][0-9][0-9][0-9]'
          AND UPPER(COALESCE(asset_type,'')) IN ('STOCK','KY','')
        """,
        conn,
    )
    q = pd.read_sql_query(
        """
        SELECT replace(date,'-','') AS date, stock_id, open, high, low, close,
               volume, turnover_k
        FROM daily_quotes
        WHERE length(stock_id)=4 AND close > 0
        ORDER BY stock_id, date
        """,
        conn,
    )
    conn.close()
    u["industry"] = u["industry"].fillna("").astype(str).str.strip()
    q["date"] = q["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    q = q.merge(u[["stock_id", "industry"]], on="stock_id", how="inner")
    q = q[~q["industry"].isin(["", "ETF", "指數投資證券", "存託憑證"])]
    return q.sort_values(["stock_id", "date"]).reset_index(drop=True)


def _kind_from_monthly(series: list[float]) -> str:
    if len(series) < 3:
        return ""
    cur = float(series[-1])
    prev = float(series[-2])
    kind = "side"
    if len(series) >= 13:
        sma_now = float(sum(series[-12:]) / 12.0)
        sma_prev = float(sum(series[-13:-1]) / 12.0)
        if sma_now > 0:
            above = cur > sma_now
            rising = sma_now + 1e-12 >= sma_prev
            drop = (cur - prev) / prev if prev > 0 else 0.0
            if above and rising and drop >= -_MONTHLY_PULLBACK:
                kind = "up"
            elif (not above) and (not rising) and drop <= _MONTHLY_PULLBACK:
                kind = "down"
            else:
                kind = "side"
    else:
        older = float(series[-3])
        if cur > prev > older:
            kind = "up"
        elif cur < prev < older:
            kind = "down"
    return kind


def _monthly_kind_series(dates: list, closes: np.ndarray) -> list[str]:
    """逐日增量月K，不要每個交易日重掃整段日期。"""
    last: dict[str, float] = {}
    completed: list[float] = []
    prev_ym = None
    out = [""] * len(closes)
    for i, (d, c) in enumerate(zip(dates, closes)):
        ds = str(d or "").replace("-", "").replace("/", "")[:8]
        if len(ds) < 6:
            continue
        ym = ds[:6]
        cv = float(c)
        if cv != cv or cv <= 0:
            continue
        if prev_ym is None:
            prev_ym = ym
        elif ym != prev_ym:
            completed.append(last[prev_ym])
            prev_ym = ym
        last[ym] = cv
        out[i] = _kind_from_monthly(completed + [last[ym]])
    return out


def _alert_series(close: pd.Series) -> list[str]:
    c = close.astype(float)
    low60 = c.rolling(60, min_periods=20).min()
    high20 = c.rolling(20, min_periods=5).max()
    low20 = c.rolling(20, min_periods=5).min()
    ma20 = c.rolling(20, min_periods=1).mean()
    span = (high20 - low20).clip(lower=c * 0.002)
    rsv = ((c - low20) / span * 100.0).clip(0, 100)
    bias = ((c - ma20) / ma20.replace(0, np.nan) * 100.0).fillna(0.0)
    out = []
    for i in range(len(c)):
        out.append(
            alert_tag(
                float(c.iloc[i]),
                low60=float(low60.iloc[i] or 0),
                high20=float(high20.iloc[i] or 0),
                low20=float(low20.iloc[i] or 0),
                bias_monthly=float(bias.iloc[i] or 0),
                rsv=float(rsv.iloc[i]) if pd.notna(rsv.iloc[i]) else None,
            )
        )
    return out


def _vol_rank_series(vals: np.ndarray, window: int = 120) -> np.ndarray:
    n = len(vals)
    out = np.full(n, 99, dtype=int)
    if n < 20:
        return out
    w = min(window, n)
    if w >= 20:
        from numpy.lib.stride_tricks import sliding_window_view

        view = sliding_window_view(vals, w)
        last = view[:, -1]
        out[w - 1 :] = (view[:, :-1] > last[:, None]).sum(axis=1) + 1
    return out


def _profit_ok(py: float, pt: float, ya: str, ta: str) -> bool:
    ok, _reason = leave_zero_screen_ok(py, pt, yest_alert=ya, today_alert=ta)
    return bool(ok)


def _summarize(rets: np.ndarray) -> dict:
    x = np.asarray(rets, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return {"n": 0}
    win = x[x > 0]
    lose = x[x <= 0]
    return {
        "n": int(x.size),
        "hit": float((x > 0).mean()),
        "mean": float(x.mean()),
        "med": float(np.median(x)),
        "p25": float(np.percentile(x, 25)),
        "p75": float(np.percentile(x, 75)),
        "avg_win": float(win.mean()) if win.size else 0.0,
        "avg_loss": float(lose.mean()) if lose.size else 0.0,
        "n_win": int(win.size),
        "n_lose": int(lose.size),
    }


def _fmt(row: dict, label: str) -> str:
    if not row or row.get("n", 0) == 0:
        return f"{label:28s} n=0"
    return (
        f"{label:28s} n={row['n']:5d}  "
        f"勝={row['hit']*100:5.1f}%  "
        f"中位{row['med']*100:+6.2f}%  均{row['mean']*100:+6.2f}%  "
        f"p25{row['p25']*100:+6.2f}%  p75{row['p75']*100:+6.2f}%  "
        f"賺均{row['avg_win']*100:+5.2f}%／{row['n_win']}  "
        f"虧均{row['avg_loss']*100:+5.2f}%／{row['n_lose']}"
    )


def _stock_flags(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].astype(float)
    high = g["high"].astype(float)
    low = g["low"].astype(float)
    vol = g["volume"].astype(float)
    to_k = g["turnover_k"].astype(float)
    n = len(g)
    if n < 80:
        return pd.DataFrame()

    ma20 = close.rolling(20, min_periods=1).mean()
    ma60 = close.rolling(60, min_periods=20).mean()
    high20_c = close.rolling(20, min_periods=1).max()
    low20_c = close.rolling(20, min_periods=5).min()
    high20 = high.rolling(20, min_periods=1).max()
    low20 = low.rolling(20, min_periods=1).min()
    high60 = high.rolling(60, min_periods=1).max()
    low60 = low.rolling(60, min_periods=1).min()
    hi5 = high.shift(1).rolling(5, min_periods=1).max()
    low20_ex = low.shift(1).rolling(20, min_periods=5).min()
    vol_ma60 = vol.rolling(60, min_periods=20).mean()
    q60r = vol / vol_ma60.replace(0, np.nan)
    d20 = (close - low20_ex) / low20_ex.replace(0, np.nan) * 100.0
    prev_close = close.shift(1)
    prev_d20 = (prev_close - low20_ex) / low20_ex.replace(0, np.nan) * 100.0
    leave_l20 = (prev_d20 <= 2.0) & (d20 >= 2.0)
    yest_l20 = low20_c.shift(1)
    yest_hl_low = (yest_l20 > 0) & (prev_close <= yest_l20 * 1.002)
    ranks = _vol_rank_series(to_k.to_numpy(dtype=float))
    vol_hot = leave_l20.fillna(False) | (ranks <= 20) | (q60r.fillna(0) >= 2.0) | yest_hl_low.fillna(False)
    at_5hi = (hi5 > 0) & (close >= hi5)
    bear = (ma20 > 0) & (ma60 > 0) & (close <= ma20) & (ma20 <= ma60)
    break_low = (low20_ex > 0) & (close <= low20_ex * 1.008)
    ma20_lt_ma60 = (ma60 > 0) & (ma20 < ma60)
    liq = (vol >= LIQ_VOL) & (to_k >= LIQ_TO_K)

    _floors, profits = cal60_profit_bundle(g)
    alerts = _alert_series(close)
    dates = g["date"].tolist()
    mk = _monthly_kind_series(dates, close.to_numpy(dtype=float))
    bias = ((close - ma20) / ma20.replace(0, np.nan) * 100.0).fillna(0.0)
    temps = [
        compute_card_temperature(
            float(c),
            float(h20),
            float(l20),
            float(b),
            high60=float(h60),
            low60=float(l60),
            ma60=float(m60) if pd.notna(m60) else 0.0,
        )
        for c, h20, l20, b, h60, l60, m60 in zip(
            close, high20, low20, bias, high60, low60, ma60
        )
    ]
    labels, _notes = compute_temp_trend_labels(temps, closes=list(close))
    hl = np.where(close >= high20_c * 0.998, "20高", "No").tolist()
    acts = sell_action_series(hl, labels)

    profit_ok = np.zeros(n, dtype=bool)
    p = profits.to_numpy(dtype=float)
    for i in range(1, n):
        profit_ok[i] = _profit_ok(float(p[i - 1]), float(p[i]), alerts[i - 1], alerts[i])

    trend_core = (~bear.fillna(False)) & (~break_low.fillna(False)) & (~ma20_lt_ma60.fillna(False)) & (ma20 > 0)
    mk_s = pd.Series(mk)
    engine = (
        profit_ok
        & vol_hot.fillna(False)
        & trend_core
        & (~at_5hi.fillna(False))
        & (mk_s == "up")
        & liq
    )
    wide = (
        profit_ok
        & vol_hot.fillna(False)
        & trend_core
        & (~at_5hi.fillna(False))
        & liq
    )
    profit_only = profit_ok & (~at_5hi.fillna(False)) & trend_core & liq

    out = g.copy()
    out["profit_ok"] = profit_ok
    out["engine"] = engine.to_numpy()
    out["wide"] = wide.to_numpy()
    out["profit_only"] = profit_only.to_numpy()
    out["sell_action"] = acts
    out["liq"] = liq.to_numpy()
    return out


def _roundtrip(df: pd.DataFrame, mask_col: str, start: str, end: str) -> dict:
    cut_rets = []
    hold20_rets = []
    holds = []
    n_cut = 0
    n_timeout = 0
    n_skip = 0
    for sid, g in df.groupby("stock_id", sort=False):
        g = g.reset_index(drop=True)
        dates = g["date"].astype(str)
        close = g["close"].astype(float).to_numpy()
        acts = g["sell_action"].tolist()
        flags = g[mask_col].to_numpy()
        n = len(g)
        for i in range(n):
            d = dates.iloc[i]
            if d < start or d > end:
                continue
            if not flags[i]:
                continue
            j20 = i + HOLD20
            if j20 >= n:
                n_skip += 1
                continue
            hold20_rets.append(close[j20] / close[i] - 1.0)
            j_end = min(n - 1, i + HOLD_MAX)
            j_cut = None
            for j in range(i + 1, j_end + 1):
                if acts[j] == "直接減碼":
                    j_cut = j
                    break
            if j_cut is None:
                if (j_end - i) < HOLD_MAX:
                    n_skip += 1
                    hold20_rets.pop()
                    continue
                j_cut = j_end
                n_timeout += 1
            else:
                n_cut += 1
            cut_rets.append(close[j_cut] / close[i] - 1.0)
            holds.append(j_cut - i)
    cut = _summarize(np.array(cut_rets, dtype=float))
    h20 = _summarize(np.array(hold20_rets, dtype=float))
    hold_med = float(np.median(holds)) if holds else 0.0
    return {
        "cut": cut,
        "hold20": h20,
        "n_cut": n_cut,
        "n_timeout": n_timeout,
        "n_skip": n_skip,
        "hold_med": hold_med,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "wayne_market.db"))
    ap.add_argument("--start", default="20260101")
    ap.add_argument("--end", default="20260820")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    q = _load(args.db)
    chunks = []
    for _sid, sg in q.groupby("stock_id", sort=False):
        flagged = _stock_flags(sg)
        if flagged.empty:
            continue
        chunks.append(
            flagged[
                [
                    "stock_id",
                    "date",
                    "close",
                    "engine",
                    "wide",
                    "profit_only",
                    "sell_action",
                ]
            ]
        )
    if not chunks:
        print("no rows")
        return 1
    s = pd.concat(chunks, ignore_index=True)
    layers = (
        ("engine", "引擎閘（月K+量熱）"),
        ("wide", "寬樣本（跳過月K）"),
        ("profit_only", "更寬（獲利離零+擋5高）"),
    )
    lines = [
        f"黃金買點進場 + 如何賣直接減碼（{args.start}–{args.end}，流動 STOCK/KY）",
        "出場＝不同步／不同步再脫離的直接減碼；最多 60 交易日。對照＝死抱 20 日。",
        "不是下單、不畫紅箭頭。三層都算，不准只留一層 n。",
        "",
    ]
    for col, lab in layers:
        pack = _roundtrip(s, col, args.start, args.end)
        lines.append(f"【{lab}】 減碼{pack['n_cut']}／超時{pack['n_timeout']}／資料不足略過{pack['n_skip']}  抱中位 {pack['hold_med']:.0f} 日")
        lines.append("  " + _fmt(pack["cut"], "進場＋直接減碼"))
        lines.append("  " + _fmt(pack["hold20"], "對照死抱20日"))
        if pack["cut"].get("n") and pack["hold20"].get("n"):
            dh = (pack["cut"]["hit"] - pack["hold20"]["hit"]) * 100.0
            lines.append(f"  勝率差 {dh:+.1f} 個百分點（減碼 − 死抱20日）")
        lines.append("")
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
