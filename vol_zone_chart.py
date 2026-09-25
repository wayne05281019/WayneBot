# -*- coding: utf-8 -*-
"""查股大量區專圖：近窗仍有效的爆大量日高低＝壓／撐。

獨立一張，不改導航圖。不是買訊、不發明 5／9。
畫法對齊教學圖：白底雙欄、桃色帶、洋紅壓／綠撐、量柱黃標爆大量日。

K 棒只認官方日表原柱（daily_quotes／emerging_quotes）：
不准除權還原、不准 MIS 盤中假柱、不准 sanitize 改高低、不准飆大疊加柱。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import patches

from wayne_navigator import _fp, _fmt_price, _mpl_serial

logger = logging.getLogger("WayneBot.VolZone")

VOL_ZONE_DPI = 200
VOL_ZONE_LOOKBACK = 40
VOL_ZONE_BARS = 78  # 只畫近窗，跟教學圖一樣清楚，不塞 180 日雜訊

_BG = "#ffffff"
_UP = "#e53935"
_DN = "#00897b"
_FILL = "#ffe0b2"
_PRESS = "#ad1457"
_HOLD = "#1b5e20"
_SPIKE = "#f9a825"
_GRID = "#cfd8dc"
_TEXT = "#1f2933"
_MUTED = "#607d8b"
_CALL = "#e65100"


def _md(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{int(t[4:6]):02d}/{int(t[6:8]):02d}"
    return str(raw or "").strip()


def load_official_ohlc(stock_id: str, db_path: str, days: int = 120) -> pd.DataFrame:
    """只讀官方日表原柱。上市櫃 daily_quotes；不足再讀興櫃 emerging_quotes。

    不除權還原、不合併 MIS、不改開高低收。
    """
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    if not sid or not path:
        return pd.DataFrame()
    lim = max(int(days or 0), 30)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=10000;")
        df = pd.read_sql_query(
            """
            SELECT date, stock_name, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            conn,
            params=(sid, lim),
        )
    finally:
        conn.close()
    source = "daily_quotes"
    if df is None or df.empty or len(df) < 5:
        try:
            from emerging_quotes import load_stock_bars

            em = load_stock_bars(path, sid, lim)
        except Exception:
            em = None
        if em is not None and not em.empty:
            keep = [
                c
                for c in ("date", "stock_name", "open", "high", "low", "close", "volume")
                if c in em.columns
            ]
            df = em[keep].copy()
            source = "emerging_quotes"
    if df is None or df.empty:
        return pd.DataFrame()
    # DB／興櫃常 DESC → 左舊右新
    dnorm = df["date"].astype(str).str.replace("-", "", regex=False)
    df = (
        df.assign(_d=dnorm)
        .sort_values("_d", kind="mergesort")
        .drop(columns="_d")
        .reset_index(drop=True)
    )
    if len(df) > lim:
        df = df.iloc[-lim:].reset_index(drop=True)
    df["stock_id"] = sid
    df["quote_source"] = source
    return df


def official_work(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """整理官方柱給選區／畫圖：升冪、標停牌、丟掉缺價。不准 normalize／sanitize／live。"""
    if df is None or getattr(df, "empty", True):
        return None
    work = df.copy()
    # 丟掉盤中未收／疊加假來源
    if "is_live" in work.columns:
        work = work.loc[~work["is_live"].fillna(False).astype(bool)].copy()
    if "source" in work.columns:
        work = work.loc[work["source"].astype(str) != "biaoke_stock_day"].copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in work.columns:
            return None
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work["date"] = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    work["dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work = work.dropna(subset=["dt", "open", "high", "low", "close"]).reset_index(drop=True)
    if work.empty:
        return None
    work = work.sort_values("dt", kind="mergesort").reset_index(drop=True)
    # 缺價／非正數收＝不成柱
    ok = (
        (work["close"] > 0)
        & (work["high"] > 0)
        & (work["low"] > 0)
        & (work["high"] >= work["low"])
    )
    work = work.loc[ok].reset_index(drop=True)
    if work.empty:
        return None
    vol = work["volume"].fillna(0.0)
    flat = (vol <= 0) & ((work["high"] - work["low"]).abs() <= 1e-8)
    work["is_halt"] = flat.fillna(False)
    return work


def find_volume_zone(work: pd.DataFrame, *, lookback: int = VOL_ZONE_LOOKBACK) -> Optional[Dict[str, Any]]:
    """近窗仍對現價有效的爆大量日。壓還在頭上才認；已全部站上才退回絕對最大量。

    準則（鎖死）：
    1. 只用官方日 K 原柱；略過停牌、略過 biaoke_stock_day／is_live。
    2. 近窗＝最近 lookback 根（預設 40），不含「最後一根」（大量區＝過去參考日）。
    3. 候選＝當日高 ≥ 最近收（壓還在頭上／還在區內）；其中取成交量最大。
    4. 若近窗已全部站上那些高 → 退回近窗（不含最後一根）絕對最大量。
    5. 壓＝該日官方高、撐＝該日官方低。不是買訊、不發明 5／9。
    """
    if work is None or getattr(work, "empty", True):
        return None
    n = len(work)
    if n < 2:
        return None
    halt = (
        work["is_halt"].fillna(False).astype(bool)
        if "is_halt" in work.columns
        else pd.Series(False, index=work.index)
    )
    # 不含最後一根：大量區是過去爆大量參考日
    end = n - 1
    start = max(0, end - max(int(lookback or 0), 1))
    last_close = float(work["close"].iloc[-1] or 0)
    best_i = None
    best_v = -1.0
    active_i = None
    active_v = -1.0
    for i in range(start, end):
        if bool(halt.iloc[i]):
            continue
        if "source" in work.columns and str(work["source"].iloc[i] or "") == "biaoke_stock_day":
            continue
        if "is_live" in work.columns and bool(work["is_live"].iloc[i]):
            continue
        v = float(work["volume"].iloc[i] or 0)
        if v <= 0:
            continue
        hi = float(work["high"].iloc[i] or 0)
        lo = float(work["low"].iloc[i] or 0)
        if hi <= 0 or lo <= 0 or hi < lo:
            continue
        if v > best_v:
            best_v = v
            best_i = i
        if hi >= last_close and v > active_v:
            active_v = v
            active_i = i
    pick = active_i if active_i is not None else best_i
    if pick is None:
        return None
    hi = float(work["high"].iloc[pick] or 0)
    lo = float(work["low"].iloc[pick] or 0)
    if hi <= 0 or lo <= 0 or hi < lo:
        return None
    return {
        "i": int(pick),
        "date": str(work["date"].iloc[pick] or ""),
        "high": hi,
        "low": lo,
        "volume": float(work["volume"].iloc[pick] or 0),
        "active": bool(active_i is not None and pick == active_i),
    }


def _candle_up(close: float, prev_close: Optional[float], open_: float) -> bool:
    try:
        from decision_card_signals import candle_up_taiwan

        return bool(candle_up_taiwan(close, prev_close, open_))
    except Exception:
        if prev_close is None:
            return float(close) >= float(open_)
        return float(close) >= float(prev_close)


@_mpl_serial
def render_volume_zone_png(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    save_path: str = None,
    df=None,
    *,
    already_normalized: bool = False,  # 保留參數相容；大量區一律當官方原柱處理
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
) -> str:
    """畫大量區專圖。有 db 就只吃官方原柱；失敗回空字串。"""
    del already_normalized  # 相容舊呼叫；不准用還原柱
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    work = None
    # 有庫＝強制官方原柱，忽略決策卡還原／盤中合併的 df
    if db_path:
        raw = load_official_ohlc(sid, db_path, max(int(bars) + int(lookback) + 5, 120))
        work = official_work(raw)
    if work is None or work.empty:
        if df is None or getattr(df, "empty", True):
            return ""
        # 測試／無庫：仍不准走除權還原，只做官方整理
        work = official_work(df)
    if work is None or work.empty:
        return ""
    zone = find_volume_zone(work, lookback=lookback)
    if not zone:
        return ""
    n_all = len(work)
    show_n = min(max(int(bars or VOL_ZONE_BARS), 30), n_all)
    # 爆大量日一定要進畫面
    spike_i_all = int(zone["i"])
    start = max(0, n_all - show_n)
    if spike_i_all < start:
        start = max(0, spike_i_all - 8)
    view = work.iloc[start:].reset_index(drop=True)
    spike_i = int(zone["i"]) - start
    if spike_i < 0 or spike_i >= len(view):
        return ""

    name = stock_name or str(view["stock_name"].iloc[-1] if "stock_name" in view.columns else sid)
    out = save_path or os.path.join(".", f"{sid}_vol_zone.png")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    hi = float(zone["high"])
    lo = float(zone["low"])
    spike_date = str(zone["date"] or "")
    spike_md = _md(spike_date)
    n = len(view)
    xs = np.arange(n, dtype=float)
    halt = (
        view["is_halt"].fillna(False).astype(bool)
        if "is_halt" in view.columns
        else pd.Series(False, index=view.index)
    )

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(11.2, 7.2),
        dpi=VOL_ZONE_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(3.35, 1.05), hspace=0.06),
        facecolor=_BG,
    )
    ax1.set_facecolor(_BG)
    ax2.set_facecolor(_BG)

    # 桃色大量區
    ax1.axhspan(lo, hi, color=_FILL, alpha=0.55, zorder=0)
    ax1.axhline(hi, color=_PRESS, linewidth=2.0, zorder=5)
    ax1.axhline(lo, color=_HOLD, linewidth=2.0, zorder=5)
    ax1.axvline(spike_i, color=_SPIKE, linewidth=1.2, alpha=0.7, zorder=1)

    for i in range(n):
        op = float(view["open"].iloc[i])
        cl = float(view["close"].iloc[i])
        h = float(view["high"].iloc[i])
        l = float(view["low"].iloc[i])
        # 興櫃：開＝前日均價，可能落在當日高低外；影線用官方高低，不改價
        prev = float(view["close"].iloc[i - 1]) if i else None
        up = _candle_up(cl, prev, op)
        color = "#bdbdbd" if bool(halt.iloc[i]) else (_UP if up else _DN)
        x = xs[i]
        ax1.plot([x, x], [l, h], color=color, linewidth=1.15, zorder=3, solid_capstyle="round")
        body = max(abs(cl - op), (hi - lo) * 0.002 if hi > lo else 0.01)
        ax1.add_patch(
            patches.Rectangle(
                (x - 0.32, min(op, cl)),
                0.64,
                body,
                facecolor=color,
                edgecolor=color,
                zorder=3,
            )
        )

    last = view.iloc[-1]
    last_hi = float(last["high"] or 0)
    last_cl = float(last["close"] or 0)
    last_md = _md(last.get("date"))
    # 測壓未過標註
    if hi > 0 and last_hi >= hi * 0.997 and last_cl < hi:
        ax1.annotate(
            f"{last_md} 高{_fmt_price(last_hi)}＝測壓　收{_fmt_price(last_cl)}未過",
            xy=(xs[-1], last_hi),
            xytext=(-24, 22),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontproperties=_fp(10, "bold"),
            color=_CALL,
            zorder=8,
            arrowprops=dict(arrowstyle="->", color=_CALL, lw=1.15, shrinkB=2),
            bbox=dict(
                boxstyle="round,pad=0.28",
                facecolor="#fff8e1",
                edgecolor="#ef6c00",
                linewidth=0.9,
                alpha=0.96,
            ),
        )

    ypad = max((hi - lo) * 0.18, float(view["high"].max() - view["low"].min()) * 0.04)
    ymin = min(float(view["low"].min()), lo) - ypad
    ymax = max(float(view["high"].max()), hi) + ypad * 1.35
    ax1.set_ylim(ymin, ymax)
    ax1.set_xlim(-0.8, n - 0.2)
    ax1.yaxis.tick_right()
    ax1.tick_params(labelbottom=False, labelsize=9)
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID, zorder=0)
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(9))

    ax1.text(
        0.01,
        0.98,
        f"大量區壓 {_fmt_price(hi)}",
        transform=ax1.transAxes,
        ha="left",
        va="top",
        fontproperties=_fp(10, "bold"),
        color=_PRESS,
        zorder=8,
        bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor=_PRESS, linewidth=0.7),
    )
    ax1.text(
        0.01,
        0.02,
        f"大量區撐 {_fmt_price(lo)}",
        transform=ax1.transAxes,
        ha="left",
        va="bottom",
        fontproperties=_fp(10, "bold"),
        color=_HOLD,
        zorder=8,
        bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor=_HOLD, linewidth=0.7),
    )

    vol_colors = []
    for i in range(n):
        prev = float(view["close"].iloc[i - 1]) if i else None
        up = _candle_up(float(view["close"].iloc[i]), prev, float(view["open"].iloc[i]))
        vol_colors.append("#ef5350" if up else "#26a69a")
    ax2.bar(xs, view["volume"], color=vol_colors, width=0.72, zorder=2)
    ax2.bar(
        [spike_i],
        [float(view["volume"].iloc[spike_i] or 0)],
        color=_SPIKE,
        width=0.8,
        zorder=4,
    )
    ax2.text(
        spike_i,
        float(view["volume"].iloc[spike_i] or 0),
        f"爆大量 {spike_md}",
        ha="center",
        va="bottom",
        fontproperties=_fp(9, "bold"),
        color="#5d4037",
        zorder=5,
    )
    ax2.yaxis.tick_right()
    ax2.tick_params(labelsize=9)
    ax2.set_xlim(-0.8, n - 0.2)
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_GRID)
    for lab in ax2.get_yticklabels():
        lab.set_fontproperties(_fp(9))

    # 底軸日期：與 K／量同一根 index；月標寫「08月」避免 08/26 被看成 8 月 26 日
    tick_at: dict[int, str] = {}

    def _put_tick(i: int, lab: str, *, prefer: bool = False) -> None:
        i = int(i)
        if i < 0 or i >= n:
            return
        if i in tick_at and not prefer:
            return
        tick_at[i] = lab

    prev_m = None
    for i, dt in enumerate(view["dt"]):
        key = (int(dt.year), int(dt.month))
        if key != prev_m:
            _put_tick(i, f"{int(dt.month):02d}月")
            prev_m = key
    # 爆大量日、最後一根一定標月日，對準那一根 K／量
    _put_tick(spike_i, _md(view["date"].iloc[spike_i]), prefer=True)
    _put_tick(n - 1, _md(view["date"].iloc[-1]), prefer=True)
    tick_pos = sorted(tick_at)
    tick_lab = [tick_at[i] for i in tick_pos]
    ax2.set_xticks(tick_pos)
    ax2.set_xticklabels(tick_lab, fontproperties=_fp(9))
    ax1.tick_params(labelbottom=False)

    src = str(view["quote_source"].iloc[-1] if "quote_source" in view.columns else "")
    src_note = "興櫃日均價／高低" if src == "emerging_quotes" else "官方日K原柱"
    title = (
        f"{sid} {name}　大量區專圖（非買訊・{src_note}）　"
        f"爆大量 {_md(spike_date)}　壓 {_fmt_price(hi)}／撐 {_fmt_price(lo)}　"
        f"最近 {_md(last.get('date'))} "
        f"開{_fmt_price(last['open'])} 高{_fmt_price(last['high'])} "
        f"低{_fmt_price(last['low'])} 收{_fmt_price(last['close'])}"
    )
    ax1.set_title(title, fontproperties=_fp(12, "bold"), pad=10, color=_TEXT)
    fig.text(
        0.5,
        0.012,
        "桃色帶＝大量區（近窗仍有效爆大量日官方高低）。高觸壓、收未過＝測壓，不是站上、不是買訊。導航圖另按。",
        ha="center",
        va="bottom",
        fontproperties=_fp(9, "bold"),
        color=_MUTED,
    )
    fig.subplots_adjust(left=0.04, right=0.96, top=0.90, bottom=0.10)
    fig.savefig(out, dpi=VOL_ZONE_DPI, facecolor=_BG)
    plt.close(fig)
    return out
