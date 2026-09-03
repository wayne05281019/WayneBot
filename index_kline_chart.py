# -*- coding: utf-8 -*-
"""加權指數日 K 線圖（淺底、紅漲綠跌、MA + 量 + KD），供大盤專頁推送。"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import requests

from wayne_navigator import _fp, _mpl_serial
from decision_card_signals import candle_up_taiwan

logger = logging.getLogger(__name__)

_INDEX_YAHOO = "%5ETWII"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot/1.0"})

# 淺底看盤：白面板、淡灰網格、台股紅漲綠跌
_BG = "#f4f5f7"
_PANEL = "#ffffff"
_GRID = "#d9dde3"
_TEXT = "#1f2933"
_DIM = "#6b7280"
_UP = "#d32f2f"
_DN = "#00897b"
_MA5 = "#ef6c00"
_MA20 = "#1565c0"
_MA60 = "#7b1fa2"
_K = "#1565c0"
_D = "#ef6c00"
_BARS = 72  # 約 3.5 個月，手機上 K 棒才看得清


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
    return _UP if up else _DN


def _fmt_vol(v: float, _pos=None) -> str:
    av = abs(float(v or 0))
    if av >= 1e8:
        return f"{v / 1e8:.1f}億"
    if av >= 1e4:
        return f"{v / 1e4:.0f}萬"
    return f"{v:,.0f}"


def _style_axis(ax, *, show_xlabels: bool = False) -> None:
    ax.set_facecolor(_PANEL)
    ax.grid(True, color=_GRID, linestyle="-", linewidth=0.7, alpha=1.0)
    ax.set_axisbelow(True)
    ax.tick_params(
        colors=_DIM,
        labelsize=8,
        bottom=show_xlabels,
        labelbottom=show_xlabels,
        left=False,
        right=True,
        pad=3,
    )
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    for side in ("top", "left"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "right"):
        ax.spines[side].set_color("#c5cad3")
        ax.spines[side].set_linewidth(0.8)


@_mpl_serial
def render_index_kline_png(
    df: pd.DataFrame,
    save_path: str,
    *,
    title: str = "加權指數",
    live: Optional[Dict[str, Any]] = None,
) -> str:
    """淺底日K：右側價軸、K+MA / 量 / KD；直式適合 Telegram 手機。"""
    if df is None or df.empty:
        return ""
    full = df.copy()
    full["ma5"] = full["close"].rolling(5, min_periods=1).mean()
    full["ma20"] = full["close"].rolling(20, min_periods=1).mean()
    full["ma60"] = full["close"].rolling(60, min_periods=1).mean()
    full["k9"], full["d9"] = _kd_series(full)
    work = full.tail(_BARS).reset_index(drop=True)

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
    fig = plt.figure(figsize=(7.6, 10.4), dpi=200, facecolor=_BG)
    gs = fig.add_gridspec(
        3,
        1,
        height_ratios=[4.6, 1.05, 0.95],
        hspace=0.06,
        top=0.88,
        bottom=0.055,
        left=0.06,
        right=0.92,
    )
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    xs = mdates.date2num(work["dt"].tolist())
    n = len(work)
    gap = (xs[-1] - xs[0]) / max(n - 1, 1) if n > 1 else 1.0
    bar_w = min(0.72, max(0.42, gap * 0.68))
    body_min = max((work["high"] - work["low"]).median() * 0.035, close * 0.00012)

    for i in range(n):
        op, cl = float(work["open"].iloc[i]), float(work["close"].iloc[i])
        hi, lo = float(work["high"].iloc[i]), float(work["low"].iloc[i])
        prev_c = float(work["close"].iloc[i - 1]) if i else None
        c = _tw_color(candle_up_taiwan(cl, prev_c, op))
        x = xs[i]
        ax1.plot([x, x], [lo, hi], color=c, linewidth=1.35, solid_capstyle="butt", zorder=2)
        body = max(abs(cl - op), body_min)
        ax1.add_patch(
            plt.Rectangle(
                (x - bar_w / 2, min(op, cl)),
                bar_w,
                body,
                facecolor=c,
                edgecolor=c,
                linewidth=0.4,
                zorder=3,
                antialiased=True,
            )
        )

    ma5_v, ma20_v, ma60_v = float(last["ma5"]), float(last["ma20"]), float(last["ma60"])
    ax1.plot(xs, work["ma5"], color=_MA5, linewidth=1.35, label=f"MA5 {ma5_v:,.0f}", zorder=4)
    ax1.plot(xs, work["ma20"], color=_MA20, linewidth=1.35, label=f"MA20 {ma20_v:,.0f}", zorder=4)
    ax1.plot(xs, work["ma60"], color=_MA60, linewidth=1.35, label=f"MA60 {ma60_v:,.0f}", zorder=4)
    ax1.legend(
        loc="upper left",
        ncol=3,
        frameon=True,
        facecolor=_PANEL,
        edgecolor=_GRID,
        labelcolor=_TEXT,
        fontsize=8,
        handlelength=1.5,
        columnspacing=0.9,
        borderpad=0.45,
        framealpha=0.95,
    )
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
    _style_axis(ax1)

    vol_colors = [
        _tw_color(
            candle_up_taiwan(
                float(work["close"].iloc[i]),
                float(work["close"].iloc[i - 1]) if i else None,
                float(work["open"].iloc[i]),
            )
        )
        for i in range(n)
    ]
    ax2.bar(xs, work["volume"], width=bar_w, color=vol_colors, alpha=0.82, linewidth=0, zorder=3)
    ax2.set_ylabel("成交量", fontproperties=_fp(8), color=_DIM)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_vol))
    _style_axis(ax2)

    k9_v, d9_v = float(last["k9"]), float(last["d9"])
    ax3.axhspan(80, 100, color=_UP, alpha=0.05, zorder=0)
    ax3.axhspan(0, 20, color=_DN, alpha=0.05, zorder=0)
    ax3.plot(xs, work["k9"], color=_K, linewidth=1.35, label=f"K {k9_v:.1f}", zorder=3)
    ax3.plot(xs, work["d9"], color=_D, linewidth=1.35, label=f"D {d9_v:.1f}", zorder=3)
    ax3.axhline(80, color=_UP, linewidth=0.6, linestyle="--", alpha=0.45)
    ax3.axhline(50, color=_GRID, linewidth=0.6, linestyle="-")
    ax3.axhline(20, color=_DN, linewidth=0.6, linestyle="--", alpha=0.45)
    ax3.set_ylim(0, 100)
    ax3.legend(
        loc="upper left",
        ncol=2,
        frameon=True,
        facecolor=_PANEL,
        edgecolor=_GRID,
        labelcolor=_TEXT,
        fontsize=8,
        handlelength=1.5,
        borderpad=0.4,
        framealpha=0.95,
    )
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax3.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    _style_axis(ax3, show_xlabels=True)

    fig.text(0.06, 0.965, title, fontproperties=_fp(13, "bold"), color=_TEXT, ha="left", va="top")
    fig.text(
        0.06,
        0.932,
        f"{close:,.2f}",
        fontproperties=_fp(20, "bold"),
        color=price_color,
        ha="left",
        va="top",
    )
    sign = "▲" if up else "▼"
    fig.text(
        0.42,
        0.936,
        f"{sign} {chg:+,.2f}  ({chg_pct:+.2f}%)",
        fontproperties=_fp(11, "bold"),
        color=price_color,
        ha="left",
        va="top",
    )
    as_of = work["dt"].iloc[-1].strftime("%Y/%m/%d")
    fig.text(
        0.06,
        0.900,
        f"{as_of}　開 {float(last['open']):,.2f}　高 {float(last['high']):,.2f}　"
        f"低 {float(last['low']):,.2f}　收 {float(last['close']):,.2f}",
        fontproperties=_fp(8),
        color=_DIM,
        ha="left",
        va="top",
    )

    fig.savefig(
        save_path,
        dpi=200,
        facecolor=_BG,
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.12,
    )
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
