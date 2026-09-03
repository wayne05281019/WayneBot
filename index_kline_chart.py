# -*- coding: utf-8 -*-
"""加權指數日 K 線圖（TradingView 風格：暗色 K 棒 + MA + 量 + KD），供大盤專頁推送。"""
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

# TradingView-like palette
_TV_BG = "#131722"
_TV_GRID = "#2a2e39"
_TV_TEXT = "#b2b5be"
_TV_TEXT_DIM = "#787b86"
_TV_MA5 = "#f0b90b"
_TV_MA20 = "#2962ff"
_TV_MA60 = "#ab47bc"
_TV_K = "#2962ff"
_TV_D = "#ff9800"


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
    return "#ef5350" if up else "#26a69a"


def _style_tv_axis(ax, *, show_xlabels: bool = False) -> None:
    ax.set_facecolor(_TV_BG)
    ax.grid(True, color=_TV_GRID, linestyle="-", linewidth=0.6, alpha=1.0)
    ax.tick_params(
        colors=_TV_TEXT_DIM,
        labelsize=7,
        bottom=show_xlabels,
        labelbottom=show_xlabels,
        left=False,
        right=True,
    )
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    for side in ("top", "left"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "right"):
        ax.spines[side].set_color(_TV_GRID)
        ax.spines[side].set_linewidth(0.6)


@_mpl_serial
def render_index_kline_png(
    df: pd.DataFrame,
    save_path: str,
    *,
    title: str = "加權指數",
    live: Optional[Dict[str, Any]] = None,
) -> str:
    """TradingView 風格：暗色主題、右側價軸、K+MA / 量 / KD；直式適合 Telegram 手機。"""
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
    price_color = _tw_color(up)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    # ~1300px wide @ 175 dpi for crisp mobile Telegram
    fig = plt.figure(figsize=(7.43, 10.8), dpi=175, facecolor=_TV_BG)
    gs = fig.add_gridspec(
        3,
        1,
        height_ratios=[4.5, 1.0, 0.85],
        hspace=0.04,
        top=0.90,
        bottom=0.06,
        left=0.06,
        right=0.94,
    )
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    xs = mdates.date2num(work["dt"].tolist())
    n = len(work)
    bar_w = 0.55 if n < 2 else min(0.65, max(0.35, (xs[-1] - xs[0]) / max(n - 1, 1) * 0.72))
    body_min = max((work["high"] - work["low"]).median() * 0.04, close * 0.00015)

    for i in range(n):
        op, cl = float(work["open"].iloc[i]), float(work["close"].iloc[i])
        hi, lo = float(work["high"].iloc[i]), float(work["low"].iloc[i])
        c = _tw_color(cl >= op)
        x = xs[i]
        ax1.plot([x, x], [lo, hi], color=c, linewidth=1.1, solid_capstyle="round", zorder=2)
        body = max(abs(cl - op), body_min)
        ax1.add_patch(
            plt.Rectangle(
                (x - bar_w / 2, min(op, cl)),
                bar_w,
                body,
                facecolor=c,
                edgecolor=c,
                linewidth=0,
                zorder=3,
            )
        )

    ma5_v, ma20_v, ma60_v = float(last["ma5"]), float(last["ma20"]), float(last["ma60"])
    ax1.plot(xs, work["ma5"], color=_TV_MA5, linewidth=1.1, label=f"MA5 {ma5_v:,.0f}", zorder=4)
    ax1.plot(xs, work["ma20"], color=_TV_MA20, linewidth=1.1, label=f"MA20 {ma20_v:,.0f}", zorder=4)
    ax1.plot(xs, work["ma60"], color=_TV_MA60, linewidth=1.1, label=f"MA60 {ma60_v:,.0f}", zorder=4)
    ax1.legend(
        loc="upper left",
        ncol=3,
        frameon=True,
        facecolor=_TV_BG,
        edgecolor=_TV_GRID,
        labelcolor=_TV_TEXT,
        fontsize=7,
        handlelength=1.4,
        columnspacing=0.8,
        borderpad=0.4,
    )
    _style_tv_axis(ax1)

    vol_colors = [
        _tw_color(float(work["close"].iloc[i]) >= float(work["open"].iloc[i])) for i in range(n)
    ]
    ax2.bar(xs, work["volume"], width=bar_w, color=vol_colors, alpha=0.75, linewidth=0)
    ax2.set_ylabel("量", fontproperties=_fp(7), color=_TV_TEXT_DIM)
    _style_tv_axis(ax2)

    k9_v, d9_v = float(last["k9"]), float(last["d9"])
    ax3.plot(xs, work["k9"], color=_TV_K, linewidth=1.1, label=f"K {k9_v:.1f}", zorder=3)
    ax3.plot(xs, work["d9"], color=_TV_D, linewidth=1.1, label=f"D {d9_v:.1f}", zorder=3)
    ax3.axhline(80, color=_TV_GRID, linewidth=0.5, linestyle="--", alpha=0.7)
    ax3.axhline(20, color=_TV_GRID, linewidth=0.5, linestyle="--", alpha=0.7)
    ax3.set_ylim(0, 100)
    ax3.legend(
        loc="upper left",
        ncol=2,
        frameon=True,
        facecolor=_TV_BG,
        edgecolor=_TV_GRID,
        labelcolor=_TV_TEXT,
        fontsize=7,
        handlelength=1.4,
        borderpad=0.4,
    )
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    _style_tv_axis(ax3, show_xlabels=True)

    # TradingView-style header: title + price + change
    fig.text(
        0.06,
        0.955,
        title,
        fontproperties=_fp(11, "bold"),
        color=_TV_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.06,
        0.925,
        f"{close:,.2f}",
        fontproperties=_fp(16, "bold"),
        color=price_color,
        ha="left",
        va="top",
    )
    fig.text(
        0.34,
        0.928,
        f"{chg:+.2f}  ({chg_pct:+.2f}%)",
        fontproperties=_fp(10, "bold"),
        color=price_color,
        ha="left",
        va="top",
    )
    fig.text(
        0.06,
        0.905,
        f"開 {float(last['open']):,.2f}   高 {float(last['high']):,.2f}   "
        f"低 {float(last['low']):,.2f}   收 {float(last['close']):,.2f}",
        fontproperties=_fp(7),
        color=_TV_TEXT_DIM,
        ha="left",
        va="top",
    )

    fig.savefig(save_path, bbox_inches="tight", pad_inches=0.08, facecolor=_TV_BG)
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
