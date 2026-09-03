# -*- coding: utf-8 -*-
"""加權指數日 K 線圖（UDN 風格：K 棒 + MA + 量 + KD），供大盤專頁推送。"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

from wayne_navigator import _fp, _mpl_serial

logger = logging.getLogger(__name__)

_INDEX_YAHOO = "%5ETWII"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot/1.0"})


def fetch_twii_ohlc(days: int = 120) -> pd.DataFrame:
    """Yahoo ^TWII 日 OHLCV（舊→新）。"""
    span = "6mo" if days <= 130 else "1y"
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{_INDEX_YAHOO}"
        f"?interval=1d&range={span}"
    )
    try:
        resp = _SESSION.get(url, timeout=20)
        resp.raise_for_status()
        block = ((resp.json().get("chart") or {}).get("result") or [None])[0] or {}
    except Exception as exc:
        logger.warning("TWII OHLC 抓取失敗: %s", exc)
        return pd.DataFrame()
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for ts, op, hi, lo, cl, vol in zip(
        stamps,
        q.get("open") or [],
        q.get("high") or [],
        q.get("low") or [],
        q.get("close") or [],
        q.get("volume") or [],
    ):
        if cl is None or op is None:
            continue
        rows.append(
            {
                "date": pd.Timestamp(ts, unit="s", tz="UTC")
                .tz_convert("Asia/Taipei")
                .strftime("%Y%m%d"),
                "open": float(op),
                "high": float(hi or cl),
                "low": float(lo or cl),
                "close": float(cl),
                "volume": float(vol or 0),
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).tail(max(30, days))
    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df.reset_index(drop=True)


def _kd_series(df: pd.DataFrame, n: int = 9) -> tuple[pd.Series, pd.Series]:
    lo = df["low"].rolling(n, min_periods=1).min()
    hi = df["high"].rolling(n, min_periods=1).max()
    span = (hi - lo).replace(0, np.nan)
    rsv = ((df["close"] - lo) / span * 100.0).fillna(50.0)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    return k, d


def _tw_color(up: bool) -> str:
    return "#e53935" if up else "#00897b"


@_mpl_serial
def render_index_kline_png(
    df: pd.DataFrame,
    save_path: str,
    *,
    title: str = "加權指數 日K",
    live: Optional[Dict[str, Any]] = None,
) -> str:
    """UDN 風格：上 K+MA、中量能、下 KD；直式適合 Telegram 手機。"""
    if df is None or df.empty:
        return ""
    work = df.copy().tail(120)
    work["ma5"] = work["close"].rolling(5, min_periods=1).mean()
    work["ma20"] = work["close"].rolling(20, min_periods=1).mean()
    work["ma60"] = work["close"].rolling(60, min_periods=1).mean()
    work["k9"], work["d9"] = _kd_series(work)

    last = work.iloc[-1]
    prev = work.iloc[-2] if len(work) > 1 else last
    live_px = float((live or {}).get("close") or 0)
    close = live_px if live_px > 0 else float(last["close"])
    ref_close = float(prev["close"])
    chg = close - ref_close
    chg_pct = (chg / ref_close * 100.0) if ref_close else 0.0
    up = chg >= 0
    color = _tw_color(up)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    fig = plt.figure(figsize=(4.6, 7.8), dpi=160, facecolor="#ffffff")
    gs = fig.add_gridspec(3, 1, height_ratios=[4.2, 1.1, 0.9], hspace=0.05)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    xs = mdates.date2num(work["dt"].tolist())
    n = len(work)
    for i in range(n):
        op, cl = float(work["open"].iloc[i]), float(work["close"].iloc[i])
        hi, lo = float(work["high"].iloc[i]), float(work["low"].iloc[i])
        c = _tw_color(cl >= op)
        x = xs[i]
        ax1.plot([x, x], [lo, hi], color=c, linewidth=0.9, solid_capstyle="round")
        body = max(abs(cl - op), (hi - lo) * 0.02)
        ax1.add_patch(
            plt.Rectangle(
                (x - 0.25, min(op, cl)),
                0.5,
                body,
                facecolor=c,
                edgecolor=c,
            )
        )
    ax1.plot(xs, work["ma5"], color="#1e88e5", linewidth=1.0, label="MA5")
    ax1.plot(xs, work["ma20"], color="#e53935", linewidth=1.0, label="MA20")
    ax1.plot(xs, work["ma60"], color="#f9a825", linewidth=1.0, label="MA60")
    ax1.set_ylabel("")
    ax1.grid(True, linestyle=":", alpha=0.35)
    ax1.tick_params(labelbottom=False)

    vol_colors = [
        _tw_color(float(work["close"].iloc[i]) >= float(work["open"].iloc[i])) for i in range(n)
    ]
    ax2.bar(xs, work["volume"], width=0.55, color=vol_colors, alpha=0.85)
    ax2.set_ylabel("量", fontproperties=_fp(8))
    ax2.grid(True, linestyle=":", alpha=0.25)
    ax2.tick_params(labelbottom=False)

    ax3.plot(xs, work["k9"], color="#1e88e5", linewidth=1.0, label="K9")
    ax3.plot(xs, work["d9"], color="#e53935", linewidth=1.0, label="D9")
    ax3.set_ylim(0, 100)
    ax3.grid(True, linestyle=":", alpha=0.25)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

    header = (
        f"{title}\n"
        f"{close:,.1f}  {chg:+.1f} ({chg_pct:+.2f}%)  量 {int(last['volume']):,}\n"
        f"開 {float(last['open']):.1f}  高 {float(last['high']):.1f}  "
        f"低 {float(last['low']):.1f}  收 {float(last['close']):.1f}\n"
        f"MA5 {float(last['ma5']):,.1f}  MA20 {float(last['ma20']):,.1f}  "
        f"MA60 {float(last['ma60']):,.1f}  "
        f"K9 {float(last['k9']):.2f}  D9 {float(last['d9']):.2f}"
    )
    fig.suptitle(header, fontproperties=_fp(9, "bold"), ha="left", x=0.04, y=0.98)
    for ax in (ax1, ax2, ax3):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.savefig(save_path, bbox_inches="tight", pad_inches=0.12, facecolor="#ffffff")
    plt.close(fig)
    return save_path if os.path.isfile(save_path) else ""


def build_market_kline_chart(
    save_path: str,
    *,
    days: int = 120,
    live: Optional[Dict[str, Any]] = None,
) -> str:
    df = fetch_twii_ohlc(days=days)
    if df.empty:
        return ""
    return render_index_kline_png(df, save_path, live=live)
