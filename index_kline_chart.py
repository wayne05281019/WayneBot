# -*- coding: utf-8 -*-
"""加權指數橫式日 K（淺底、紅漲綠跌、月線／季線 + 量），質感對齊個股導航圖。"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import requests

from wayne_navigator import NAV_CHART_DPI, _fp, _mpl_serial
from decision_card_signals import candle_up_taiwan

logger = logging.getLogger(__name__)

_INDEX_YAHOO = "%5ETWII"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot/1.0"})

# 對齊個股導航圖：白底、右軸、台股紅漲綠跌
_BG = "#ffffff"
_PANEL = "#ffffff"
_GRID = "#bdbdbd"
_TEXT = "#1f2933"
_UP = "#e53935"
_DN = "#00897b"
_VOL_UP = "#ef5350"
_VOL_DN = "#26a69a"
_MA5 = "#ef6c00"
_MA20 = "#f9a825"
_MA60 = "#7b1fa2"
_BARS = 180  # 與個股導航圖同一視窗，橫向才讀得清


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


def load_index_daily_ohlc(db_path: str | None = None, days: int = 120) -> pd.DataFrame:
    """庫內官方加權日 K（MI_INDEX／FMTQIK 融合）。有開高低收才畫，不拿 Yahoo 當答案。"""
    import sqlite3

    try:
        from config import get_db_path
    except Exception:
        get_db_path = lambda: os.getenv("WAYNE_DB_PATH") or "data/wayne_market.db"

    path = db_path or get_db_path()
    if not path or not os.path.isfile(path):
        return pd.DataFrame()
    need = max(30, int(days or 120))
    try:
        con = sqlite3.connect(path)
        try:
            rows = con.execute(
                """
                SELECT date, open, high, low, close, volume
                FROM index_daily
                WHERE symbol = 'TWII'
                  AND close > 0 AND open > 0 AND high > 0 AND low > 0
                ORDER BY date DESC
                LIMIT ?
                """,
                (need,),
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:
        logger.warning("index_daily OHLC 讀取失敗: %s", exc)
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows[::-1], columns=["date", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["dt"]).reset_index(drop=True)
    return df


def _tw_color(up: bool) -> str:
    return _UP if up else _DN


def _vol_color(up: bool) -> str:
    return _VOL_UP if up else _VOL_DN


def _fmt_vol(v: float, _pos=None) -> str:
    """index_daily.volume 是張。軸標要寫張，避免 927萬被看成元、1.0億被看成金額。"""
    av = abs(float(v or 0))
    if av >= 1e8:
        return f"{v / 1e8:.1f}億張"
    if av >= 1e4:
        return f"{v / 1e4:.1f}萬張"
    return f"{v:,.0f}張"


def _fmt_last_vol(v: float) -> str:
    """加權指數當日量 Yahoo 常是 0，不要寫「量 0張」讓人以為沒量。"""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        n = 0.0
    if n <= 0:
        return "—"
    return _fmt_vol(n)


@_mpl_serial
def render_index_kline_png(
    df: pd.DataFrame,
    save_path: str,
    *,
    title: str = "加權指數",
    live: Optional[Dict[str, Any]] = None,
) -> str:
    """橫式日K：對齊個股導航圖（白底、右軸、20日高低帶、月線、量能）。"""
    if df is None or df.empty:
        return ""
    from live_quote import sanitize_ohlc_frame
    from matplotlib import patches

    full = sanitize_ohlc_frame(df.copy())
    full["ma5"] = full["close"].rolling(5, min_periods=1).mean()
    full["ma20"] = full["close"].rolling(20, min_periods=1).mean()
    full["ma60"] = full["close"].rolling(60, min_periods=1).mean()
    work = full.tail(_BARS).reset_index(drop=True)
    work["vol_ma"] = work["volume"].rolling(20, min_periods=1).mean()
    n = len(work)
    if n < 2:
        return ""

    last = work.iloc[-1]
    prev = work.iloc[-2]
    live_px = float((live or {}).get("close") or 0)
    close = live_px if live_px > 0 else float(last["close"])
    ref_close = float(prev["close"])
    chg = close - ref_close
    chg_pct = (chg / ref_close * 100.0) if ref_close else 0.0
    up = chg >= 0
    xs = np.arange(n, dtype=float)
    hi_s = work["high"].astype(float)
    lo_s = work["low"].astype(float)
    h20 = float(hi_s.tail(20).max())
    l20 = float(lo_s.tail(20).min())
    h60 = float(hi_s.tail(60).max())
    l60 = float(lo_s.tail(60).min())
    span = max(float(hi_s.max()) - float(lo_s.min()), 1.0)
    ymin = float(lo_s.min()) - span * 0.04
    ymax = float(hi_s.max()) + span * 0.10

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(12.8, 7.55),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.15, 1.45), hspace=0.04),
        facecolor=_BG,
    )
    ax1.set_facecolor(_PANEL)
    ax2.set_facecolor(_PANEL)
    ax1.axhspan(h20, ymax, color="#f8bbd0", alpha=0.16, zorder=0)
    ax1.axhspan(l20, h20, color="#fffde7", alpha=0.28, zorder=0)
    ax1.axhspan(ymin, l20, color="#c8e6c9", alpha=0.16, zorder=0)
    ax1.set_ylim(ymin, ymax)
    ax1.set_xlim(-0.8, n - 0.2)

    candle_up = []
    for i in range(n):
        prev_c = float(work["close"].iloc[i - 1]) if i else None
        candle_up.append(
            candle_up_taiwan(float(work["close"].iloc[i]), prev_c, float(work["open"].iloc[i]))
        )
    for i in range(n):
        op, cl = float(work["open"].iloc[i]), float(work["close"].iloc[i])
        hi, lo = float(work["high"].iloc[i]), float(work["low"].iloc[i])
        x = xs[i]
        c = _tw_color(candle_up[i])
        ax1.plot([x, x], [lo, hi], color=c, linewidth=1.05, zorder=3, solid_capstyle="round")
        body = max(abs(cl - op), span * 0.0018)
        ax1.add_patch(
            patches.Rectangle(
                (x - 0.32, min(op, cl)),
                0.64,
                body,
                facecolor=c,
                edgecolor=c,
                zorder=3,
            )
        )

    ax1.plot(xs, work["ma5"], color=_MA5, linewidth=1.15, zorder=4, label=f"5日均 {float(last['ma5']):,.0f}")
    ax1.plot(xs, work["ma20"], color=_MA20, linewidth=1.85, zorder=4, label=f"月線 {float(last['ma20']):,.0f}")
    ax1.plot(xs, work["ma60"], color=_MA60, linewidth=1.35, zorder=4, label=f"季線 {float(last['ma60']):,.0f}")
    ax1.axhline(h60, color="#f48fb1", linewidth=1.35, zorder=2)
    ax1.axhline(l60, color="#81c784", linewidth=1.35, zorder=2)
    ax1.axhline(h20, color="#f8bbd0", linewidth=1.05, linestyle="--", zorder=2)
    ax1.axhline(l20, color="#80deea", linewidth=1.05, linestyle="--", zorder=2)
    live_note = ""
    if live_px > 0:
        t = str((live or {}).get("update_time") or "")
        live_note = f"  ·盤中 {t[:5]}" if t else "  ·盤中即時"
    ax1.set_title(
        f"{title} (日K線) {n}日區間  高低帶＝近20日高／低{live_note}   WayneBot ® 2026",
        fontproperties=_fp(14, "bold"),
        pad=38,
        color=_TEXT,
    )
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID, zorder=1)
    ax1.legend(
        loc="upper left",
        ncol=3,
        frameon=True,
        facecolor="#ffffff",
        edgecolor="#e0e0e0",
        prop=_fp(8),
        handlelength=1.6,
        columnspacing=0.9,
        borderpad=0.4,
        framealpha=0.95,
    )
    ax1.yaxis.tick_right()
    ax1.yaxis.set_label_position("right")
    ax1.tick_params(labelsize=9, left=False, right=True, bottom=False, labelbottom=False)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{v:,.0f}"))
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(9))
    sign = "▲" if up else "▼"
    ohlc_line = (
        f"Op:{float(last['open']):,.2f}  Hi:{float(last['high']):,.2f}  "
        f"Lo:{float(last['low']):,.2f}  Cl:{close:,.2f}  {sign}{chg:+,.2f}（{chg_pct:+.2f}%）"
        f"    月線: {float(last['ma20']):,.2f}"
    )

    vol_colors = [_vol_color(candle_up[i]) for i in range(n)]
    ax2.bar(xs, work["volume"], color=vol_colors, width=0.72, zorder=3)
    ax2.plot(xs, work["vol_ma"], color="#90a4ae", linewidth=1.05, zorder=4)
    ax2.yaxis.tick_right()
    ax2.yaxis.set_label_position("right")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_vol))
    ax2.tick_params(labelsize=9, left=False, right=True)
    ax2.set_xlim(-0.8, n - 0.2)
    ax2.text(
        0.006,
        0.92,
        f"量 {_fmt_last_vol(float(last['volume']))}　20日均 {_fmt_vol(float(last['vol_ma']))}",
        transform=ax2.transAxes,
        fontproperties=_fp(10, "bold"),
        va="top",
        zorder=4,
        bbox=dict(boxstyle="round,pad=0.2", facecolor="#eceff1", edgecolor="none"),
    )
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID)
    months, mpos = [], []
    prev_m = None
    for i, dt in enumerate(work["dt"]):
        key = (int(dt.year), int(dt.month))
        if key != prev_m:
            months.append(f"{dt.month}月'{dt.year % 100:02d}")
            mpos.append(i)
            prev_m = key
    ax2.set_xticks(mpos)
    ax2.set_xticklabels(months, fontproperties=_fp(9))
    for lab in ax2.get_yticklabels():
        lab.set_fontproperties(_fp(9))
    for side in ("top", "left"):
        ax1.spines[side].set_visible(False)
        ax2.spines[side].set_visible(False)

    fig.subplots_adjust(left=0.03, right=0.96, top=0.78, bottom=0.11)
    fig.text(
        0.03,
        0.955,
        ohlc_line,
        ha="left",
        va="top",
        fontproperties=_fp(10, "bold"),
        color="#1b5e20",
        zorder=9,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="#e8f5e9", edgecolor="#a5d6a7", linewidth=0.6),
    )
    as_of = work["dt"].iloc[-1].strftime("%Y/%m/%d")
    fig.text(
        0.50,
        0.015,
        f"{as_of}　K 線紅漲綠跌＝相對昨收（台股慣例）；粉帶＝近20日高區、綠帶＝近20日低區；黃線＝月線、紫線＝季線；灰線＝20日均量",
        ha="center",
        va="bottom",
        fontproperties=_fp(9, "bold"),
        color="#263238",
    )
    fig.savefig(save_path, dpi=NAV_CHART_DPI, facecolor=_BG)
    plt.close(fig)
    return save_path if os.path.isfile(save_path) else ""


def build_market_kline_chart(
    save_path: str,
    *,
    days: int = 180,
    live: Optional[Dict[str, Any]] = None,
    db_path: str | None = None,
) -> str:
    df = load_index_daily_ohlc(db_path, days=days)
    if df.empty:
        logger.warning("大盤日K：庫內無官方開高低收，略過 Yahoo 圖（漲跌會跟官方差）")
        return ""
    return render_index_kline_png(df, save_path, live=live)
