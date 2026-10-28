# -*- coding: utf-8 -*-
"""查股大量區專圖：近窗仍有效的爆大量日高低＝壓／撐。

獨立一張，不改導航圖。不是買訊、不發明 5／9。
畫法對齊教學圖：白底雙欄、桃色帶、洋紅壓／綠撐、量柱黃標爆大量日。

壓撐選區只認官方日表原柱（daily_quotes／emerging_quotes；加權 TWII＝index_daily）：
不准除權還原、不准 sanitize 改高低、不准飆大疊加柱、不准發明假量。
查股縮圖 paint 時可疊決策卡盤中真開高低收＋量（與圖一／二同源；`overlay_live_face_from_card`）。
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["axes.unicode_minus"] = False  # 右軸不准「− 0」孤號

from wayne_navigator import (
    _fp,
    _fmt_price,
    _set_staggered_month_ticks,
    mpl_render,
    configure_lookup_vol_axis,
    lookup_vol_to_display,
    nav_volume_bar_heights,
    paint_lookup_ohlc_candles,
    paint_lookup_volume_bars,
)
from ex_rights import (
    bar_ymd as _bar_ymd,
    ex_gap_note as _ex_gap_note,
    hydrate_official_ex_for_gaps,
    latest_scale_ex as _latest_ex_event,
    load_scale_ex_events,
    official_scale_events,
    phone_ex_verb,
    unexplained_gap_dates,
)

logger = logging.getLogger("WayneBot.VolZone")

# 對齊高低卡 220DPI；字級／figsize 讓話筒縮圖仍清晰，點開高畫質。
VOL_ZONE_DPI = 220
VOL_ZONE_LOOKBACK = 40
VOL_ZONE_BARS = 78  # 只畫近窗，跟教學圖一樣清楚，不塞 180 日雜訊
# 查股結構／大量區 ensure 並行抓月表：上限 3，縮短第二→第三體感；不准跳過真量
_ENSURE_MONTH_FETCH_WORKERS = 3
# 現任主大量區壓／撐＝大檔字級（兩者同大）。略縮自舊 16，但仍須明顯大於下一層
# （biaoke_next_support.LAYER_TAG_PT≈8.5）。大小跟「是否現任主區」走：find_volume_zone
# 重算後新主區走這條大檔；下一層／更下層永遠小檔——不准寫死文案名決定大小。
VOL_ZONE_TAG_PT = 14
VOL_ZONE_TAG_PAD = 0.24  # 主區框；略縮自 0.30，仍大於下一層 LAYER_TAG_PAD
VOL_ZONE_JPEG_QUALITY = 95
VOL_ZONE_FIG_W = 12.4  # 略放大；左側空白回收給 K 區
VOL_ZONE_FIG_H_NAV = 9.35
VOL_ZONE_FIG_H_PLAIN = 7.7
# 大盤大量區專用：畫布對齊加權日K（12.8×7.55、右緣 0.96）。
# 個股仍走 VOL_ZONE_FIG_W×NAV，不准為了對齊改個股 figsize／日標。
MARKET_VOL_ZONE_FIG = (12.8, 7.55)
MARKET_VOL_ZONE_GS_LEFT = 0.03
MARKET_VOL_ZONE_GS_RIGHT = 0.96
# 查股單張：對齊高低卡 4:5（220DPI → 1920×2400），Telegram 縮圖寬才不獨大／變窄
VOL_ZONE_FIG_LOOKUP = (1920 / 220.0, 2400 / 220.0)
# 月線／季線＝官方收盤 MA20／MA60；畫圖前多抓暖機柱，近窗第一根就要有線
# 五日／十日＝大盤大量區另開（與壓撐／平行軌同圖）；個股大量區預設不畫
VOL_ZONE_MA5 = 5
VOL_ZONE_MA10 = 10
VOL_ZONE_MA20 = 20
VOL_ZONE_MA60 = 60
VOL_ZONE_MA60_WARM = 70


def lookup_vol_ensure_days(
    *,
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
) -> int:
    """查股第 3／4 張 prepare 同一窗長；提早 ensure 用這個 days。"""
    return max(int(bars) + int(lookback) + VOL_ZONE_MA60_WARM, 180)
# 同檔同 as_of 壓力區圖短快取（名單→點股三張可複用）
# 對齊查股 memo TTL：同指紋 90s 內複製不進 paint（現價指紋變了會 miss）
_VZ_RENDER_TTL_SEC = 90.0
_VZ_RENDER_LOCK = threading.Lock()
_VZ_RENDER_MEMO: Dict[Tuple[Any, ...], Tuple[float, str, str]] = {}
_VZ_RENDER_MEMO_MAX = 64
# 畫面上線／戳後 bump
_VZ_PAINT_VER = 61  # 成對共用錨；右溝同 crush 不壓過左／中（2026-10-27）
_BG = "#ffffff"
_UP = "#e53935"
_DN = "#00897b"
_FILL = "#ffe0b2"
_PRESS = "#ad1457"
_HOLD = "#1b5e20"
_SPIKE = "#f9a825"
_MA5 = "#ef6c00"  # 五日：橙（對齊大盤日 K）
_MA10 = "#00838f"  # 十日：青，不跟月線黃／季線藍紫搶
_MA20 = "#f9a825"  # 月線：黃（對齊導航 SMA20）
_MA60 = "#5c6bc0"  # 季線：藍紫，不跟壓洋紅／撐綠搶
_GRID = "#cfd8dc"
_TEXT = "#1f2933"
_MUTED = "#607d8b"
_CALL = "#e65100"


def _md(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{int(t[4:6]):02d}/{int(t[6:8]):02d}"
    return str(raw or "").strip()


def attach_official_sma(
    work: pd.DataFrame, *, col: str, window: int
) -> pd.DataFrame:
    """官方收盤 SMA；不滿窗不畫假線。"""
    if work is None or getattr(work, "empty", True):
        return work
    out = work if col in work.columns else work.copy()
    if col not in out.columns:
        out = out.copy()
    closes = pd.to_numeric(out["close"], errors="coerce")
    out[col] = closes.rolling(int(window), min_periods=int(window)).mean()
    return out


def attach_official_ma5(work: pd.DataFrame, *, window: int = VOL_ZONE_MA5) -> pd.DataFrame:
    """官方收盤 SMA5（五日）。"""
    return attach_official_sma(work, col="ma5", window=window)


def attach_official_ma10(work: pd.DataFrame, *, window: int = VOL_ZONE_MA10) -> pd.DataFrame:
    """官方收盤 SMA10（十日）。"""
    return attach_official_sma(work, col="ma10", window=window)


def attach_official_ma20(work: pd.DataFrame, *, window: int = VOL_ZONE_MA20) -> pd.DataFrame:
    """官方收盤 SMA20（月線）。不滿窗不畫假線。"""
    return attach_official_sma(work, col="ma20", window=window)


def attach_official_ma60(work: pd.DataFrame, *, window: int = VOL_ZONE_MA60) -> pd.DataFrame:
    """官方收盤 SMA60（季線）。缺柱／停牌收不當正量時仍用當日官方收。"""
    return attach_official_sma(work, col="ma60", window=window)


def _ma_label_box_half(
    span: float, *, x_half: float = 0.55
) -> Tuple[float, float, float]:
    """標盒半高／半寬／與 K 的最小空隙（價格單位）。短標視覺窄。

    盒略縮：高價股 span 大時舊半高易把 5 卡在 10／月之間誤判互壓；
    有乾淨位才標，仍不准硬壓 K／他線。
    """
    half_h = span * 0.022
    pad = span * 0.008
    return half_h, float(x_half), pad


def _ma_label_rect(
    x_lab: float, y_lab: float, *, half_h: float, x_half: float
) -> Tuple[float, float, float, float]:
    return (x_lab - x_half, x_lab + x_half, y_lab - half_h, y_lab + half_h)


def _ma_rects_overlap(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
    *,
    pad_x: float = 0.35,
    pad_y: float = 0.0,
) -> bool:
    return not (
        a[1] + pad_x < b[0]
        or b[1] + pad_x < a[0]
        or a[3] + pad_y < b[2]
        or b[3] + pad_y < a[2]
    )


def _ma_x_zone_bonus(frac: float) -> float:
    """程式自動選 x：中左 → 正中 → 中右靠中。遠右／右溝扣到不採用。"""
    if 0.14 <= frac <= 0.34:
        return 1.00  # 中左（首選）
    if 0.34 < frac <= 0.52:
        return 0.78  # 正中
    if 0.52 < frac <= 0.68:
        # 中右但靠中：越靠近 0.52 越好，越靠右越差
        return 0.48 * (0.68 - frac) / 0.16 + 0.22
    if 0.08 <= frac < 0.14:
        return 0.40  # 過左（壓撐區）
    return -1.0  # 禁：太左／遠右／右溝


def _label_ma_blank(
    ax,
    xs,
    highs,
    lows,
    *,
    lab: str,
    vals: np.ndarray,
    color: str,
    face: str,
    occupied: Optional[List[Tuple[float, float, float, float]]] = None,
    press_hi: Optional[float] = None,
    hold_lo: Optional[float] = None,
    spike_i: Optional[int] = None,
    avoid_path_box: bool = False,
    other_mas: Optional[List[np.ndarray]] = None,
) -> Optional[Tuple[float, float]]:
    """均線短標：程式自動選位（中左→中→中右靠中）；y 只貼自己均線。

    不准壓 K、不准壓他均線、不准蓋已放標／壓撐數字。找不到淨空就不畫（不准硬蓋）。
    """
    ok = np.flatnonzero(np.isfinite(vals) & (vals > 0))
    if ok.size == 0 or len(xs) == 0:
        return None
    n = len(xs)
    y0, y1 = ax.get_ylim()
    span = max(float(y1 - y0), 1.0)
    half_h, x_half, pad = _ma_label_box_half(span)
    if occupied is None:
        occupied = []
    others = [a for a in (other_mas or []) if a is not None and len(a) == n]
    # 搜尋窗：約 8%～68%（中右靠中上限）；禁遠右／右溝
    lo_i = max(0, int(n * 0.08))
    hi_i = max(lo_i + 1, min(n - 1, int(n * 0.68)))
    x_cap = float(n - 1) * 0.68

    def _cover_range(x_lab: float) -> tuple[int, int]:
        j0 = max(0, int(np.floor(x_lab - x_half)))
        j1 = min(n - 1, int(np.ceil(x_lab + x_half)))
        return j0, j1

    def _signed_gap_k(x_lab: float, y_lab: float) -> float:
        """標盒相對 K 高低的最小空隙；穿進 K 回負。"""
        j0, j1 = _cover_range(x_lab)
        y_bot, y_top = y_lab - half_h, y_lab + half_h
        best = span
        for k in range(j0, j1 + 1):
            hk = float(highs[k]) if np.isfinite(highs[k]) else np.nan
            lk = float(lows[k]) if np.isfinite(lows[k]) else np.nan
            if not (np.isfinite(hk) and np.isfinite(lk)):
                continue
            if y_lab >= hk:
                best = min(best, y_bot - hk)
            elif y_lab <= lk:
                best = min(best, lk - y_top)
            else:
                best = min(best, -(min(y_top, hk) - max(y_bot, lk)))
        return float(best)

    def _clear_of_bars(x_lab: float, y_lab: float) -> bool:
        return _signed_gap_k(x_lab, y_lab) >= pad

    def _clear_of_other_mas(x_lab: float, y_lab: float) -> bool:
        """標盒不准壓到其他均線（自己線除外）。"""
        if not others:
            return True
        j0, j1 = _cover_range(x_lab)
        y_bot, y_top = y_lab - half_h, y_lab + half_h
        line_pad = span * 0.004
        for arr in others:
            for k in range(j0, j1 + 1):
                v = float(arr[k]) if np.isfinite(arr[k]) else np.nan
                if not np.isfinite(v) or v <= 0:
                    continue
                if (y_bot - line_pad) <= v <= (y_top + line_pad):
                    return False
        return True

    def _blocked_by_tags(x_lab: float, y_lab: float) -> bool:
        try:
            xf = (x_lab - float(ax.get_xlim()[0])) / max(
                float(ax.get_xlim()[1] - ax.get_xlim()[0]), 1e-6
            )
            yf = (y_lab - y0) / span
        except Exception:
            return False
        if xf < 0.22 and yf > 0.86:
            return True
        if xf < 0.22 and yf < 0.14:
            return True
        # 右上狀況簡述（若還在軸內）：短標不准鑽進去
        if avoid_path_box and xf > 0.72 and yf > 0.78:
            return True
        if press_hi is not None and np.isfinite(press_hi):
            if abs(y_lab - float(press_hi)) < half_h * 1.5 and xf < 0.30:
                return True
        if hold_lo is not None and np.isfinite(hold_lo):
            if abs(y_lab - float(hold_lo)) < half_h * 1.5 and xf < 0.30:
                return True
        return False

    def _overlap_occupied(rect: Tuple[float, float, float, float]) -> bool:
        for other in occupied:
            if _ma_rects_overlap(rect, other, pad_x=0.32, pad_y=span * 0.008):
                return True
        return False

    spike_x = float(spike_i) if spike_i is not None else None
    # 逐根掃自己線（自動選位，不問使用者）
    step = max(1, max(1, hi_i - lo_i) // 28)
    chart_best = None  # (score, x, y)

    def _score_at(x_lab: float, y_lab: float) -> Optional[float]:
        if float(x_lab) > x_cap + 0.05:
            return None
        frac = float(x_lab) / max(float(n - 1), 1.0)
        zone = _ma_x_zone_bonus(frac)
        if zone < 0:
            return None
        yf = (y_lab - y0) / span
        if yf < 0.07 or yf > 0.95:
            return None
        if _blocked_by_tags(x_lab, y_lab):
            return None
        rect = _ma_label_rect(x_lab, y_lab, half_h=half_h, x_half=x_half)
        if _overlap_occupied(rect):
            return None
        gap = _signed_gap_k(x_lab, y_lab)
        if gap < pad:
            return None
        if not _clear_of_other_mas(x_lab, y_lab):
            return None
        spike_pen = 0.0
        if spike_x is not None and abs(x_lab - spike_x) < 2.8:
            spike_pen = 0.22
        level_pen = 0.0
        if press_hi is not None and np.isfinite(press_hi):
            if abs(y_lab - float(press_hi)) < half_h * 1.15:
                level_pen += 0.28
        if hold_lo is not None and np.isfinite(hold_lo):
            if abs(y_lab - float(hold_lo)) < half_h * 1.15:
                level_pen += 0.28
        return gap / span + zone - spike_pen - level_pen

    for j in ok:
        jj = int(j)
        if jj < lo_i or jj > hi_i:
            continue
        if (jj - lo_i) % step != 0 and jj not in (
            lo_i,
            hi_i,
            (lo_i + hi_i) // 2,
            int(n * 0.25),
            int(n * 0.50),
            int(n * 0.62),
        ):
            continue
        y_lab = float(vals[jj])
        if not np.isfinite(y_lab) or y_lab <= 0:
            continue
        x_lab = float(xs[jj])
        sc = _score_at(x_lab, y_lab)
        if sc is None:
            continue
        cand = (sc, x_lab, y_lab)
        if chart_best is None or cand[0] > chart_best[0]:
            chart_best = cand

    if chart_best is None:
        # 再密掃一輪；仍無淨空 → 不畫（不准硬壓 K／他線）
        for j in ok:
            jj = int(j)
            if jj < lo_i or jj > hi_i:
                continue
            y_lab = float(vals[jj])
            x_lab = float(xs[jj])
            if not np.isfinite(y_lab) or y_lab <= 0:
                continue
            if not _clear_of_bars(x_lab, y_lab):
                continue
            if not _clear_of_other_mas(x_lab, y_lab):
                continue
            if _blocked_by_tags(x_lab, y_lab):
                continue
            rect = _ma_label_rect(x_lab, y_lab, half_h=half_h, x_half=x_half)
            if _overlap_occupied(rect):
                continue
            sc = _score_at(x_lab, y_lab)
            if sc is None:
                continue
            cand = (sc, x_lab, y_lab)
            if chart_best is None or cand[0] > chart_best[0]:
                chart_best = cand

    if chart_best is None:
        return None

    _, x_lab, y_lab = chart_best
    # 鎖死：y 必須落在自己線上（取最近有限柱）
    j_lock = int(np.clip(int(round(x_lab)), 0, n - 1))
    if np.isfinite(vals[j_lock]) and vals[j_lock] > 0:
        y_lab = float(vals[j_lock])
        x_lab = float(xs[j_lock])
    ax.text(
        x_lab,
        y_lab,
        lab,
        ha="center",
        va="center",
        fontproperties=_fp(10.0, "bold"),
        color=color,
        zorder=12,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.18",
            facecolor=face,
            edgecolor=color,
            linewidth=0.95,
            alpha=0.94,
        ),
    )
    placed = _ma_label_rect(x_lab, y_lab, half_h=half_h, x_half=x_half)
    occupied.append(placed)
    return (float(x_lab), float(y_lab))


def _label_ma_left(
    ax,
    xs,
    highs,
    lows,
    *,
    lab: str,
    vals: np.ndarray,
    color: str,
    face: str,
    occupied: Optional[List[Tuple[float, float, float, float]]] = None,
    press_hi: Optional[float] = None,
    hold_lo: Optional[float] = None,
    spike_i: Optional[int] = None,
    avoid_path_box: bool = False,
    other_mas: Optional[List[np.ndarray]] = None,
) -> Optional[Tuple[float, float]]:
    """相容舊名：自動貼線標（見 _label_ma_blank）。"""
    return _label_ma_blank(
        ax,
        xs,
        highs,
        lows,
        lab=lab,
        vals=vals,
        color=color,
        face=face,
        occupied=occupied,
        press_hi=press_hi,
        hold_lo=hold_lo,
        spike_i=spike_i,
        avoid_path_box=avoid_path_box,
        other_mas=other_mas,
    )


def _paint_ma_line_labels(
    ax,
    xs,
    highs,
    lows,
    *,
    series: List[Tuple[str, np.ndarray, str, str]],
    press_hi: Optional[float] = None,
    hold_lo: Optional[float] = None,
    spike_i: Optional[int] = None,
    avoid_path_box: bool = False,
    extra_occupied: Optional[List[Tuple[float, float, float, float]]] = None,
) -> None:
    """短標 5／10／月／季：程式自動選位；只貼自己線、互避、不壓 K。不准改 OHLC／量。"""
    occupied: List[Tuple[float, float, float, float]] = list(extra_occupied or [])
    order = sorted(
        series,
        key=lambda t: {
            "季": 0,
            "月": 1,
            "10": 2,
            "5": 3,
            "季線": 0,
            "月線": 1,
            "十日": 2,
            "五日": 3,
        }.get(t[0], 9),
    )
    for lab, vals, color, face in order:
        if vals is None or not np.isfinite(vals).any():
            continue
        siblings = [v for (lb, v, _c, _f) in order if lb != lab and v is not None]
        _label_ma_blank(
            ax,
            xs,
            highs,
            lows,
            lab=lab,
            vals=vals,
            color=color,
            face=face,
            occupied=occupied,
            press_hi=press_hi,
            hold_lo=hold_lo,
            spike_i=spike_i,
            avoid_path_box=avoid_path_box,
            other_mas=siblings,
        )


def ma60_is_rising(
    ma60: Any,
    *,
    slope_bars: int = 5,
) -> Optional[bool]:
    """近 slope_bars 交易日季線是否上升。柱不足回 None（不算假上升）。"""
    try:
        s = pd.to_numeric(pd.Series(ma60), errors="coerce").dropna()
    except Exception:
        return None
    n = max(int(slope_bars or 0), 1)
    if len(s) < n + 1:
        return None
    now = float(s.iloc[-1])
    prev = float(s.iloc[-(n + 1)])
    if not (now > 0 and prev > 0):
        return None
    return now > prev


def _load_index_daily_ohlc(db_path: str, days: int = 120) -> pd.DataFrame:
    """加權官方日 K（index_daily TWII）。有開高低收才算；不拿 Yahoo。"""
    path = str(db_path or "").strip()
    lim = max(int(days or 0), 30)
    if not path:
        return pd.DataFrame()
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=10000;")
        try:
            df = pd.read_sql_query(
                """
                SELECT date, open, high, low, close, volume
                FROM index_daily
                WHERE symbol = 'TWII'
                  AND close > 0 AND open > 0 AND high > 0 AND low > 0
                ORDER BY date DESC
                LIMIT ?
                """,
                conn,
                params=(lim,),
            )
        except Exception:
            df = pd.DataFrame()
    finally:
        conn.close()
    if df is None or df.empty:
        return pd.DataFrame()
    dnorm = df["date"].astype(str).str.replace("-", "", regex=False)
    df = (
        df.assign(_d=dnorm)
        .sort_values("_d", kind="mergesort")
        .drop(columns="_d")
        .reset_index(drop=True)
    )
    if len(df) > lim:
        df = df.iloc[-lim:].reset_index(drop=True)
    df["stock_name"] = "加權"
    df["stock_id"] = "TWII"
    df["quote_source"] = "index_daily"
    return df


def missing_open_quote_days(
    stock_id: str,
    db_path: str,
    start_ymd: str,
    end_ymd: str,
    *,
    skip_confirmed_absent: bool = True,
) -> List[str]:
    """開市日曆日 ∩ 窗內，daily_quotes 缺列／量 NULL／櫃買張誤÷1000殘列 的日期。

    週末／休市不列。量 0＝可能真停價，不算缺列。
    source=biaoke_stock_day 且正量卻小到像股數被當張再÷1000 → 當洞重抓（不准留假小量挖洞）。
    skip_confirmed_absent：已落庫「官方月表無列」日不再當缺洞（預設 True）。
    """
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    start = str(start_ymd or "").replace("-", "")[:8]
    end = str(end_ymd or "").replace("-", "")[:8]
    if not sid or not path or len(start) != 8 or len(end) != 8 or sid in ("TWII", "^TWII"):
        return []
    from trading_calendar import iter_tw_open_days

    open_days = iter_tw_open_days(start, end)
    if not open_days:
        return []
    have: set = set()
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=10000;")
        try:
            rows = conn.execute(
                """
                SELECT replace(date,'-','') AS d, volume, IFNULL(source,''), close
                FROM daily_quotes
                WHERE stock_id = ?
                  AND replace(date,'-','') BETWEEN ? AND ?
                """,
                (sid, start, end),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                """
                SELECT replace(date,'-','') AS d, volume, '', close
                FROM daily_quotes
                WHERE stock_id = ?
                  AND replace(date,'-','') BETWEEN ? AND ?
                """,
                (sid, start, end),
            ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    for d_raw, vol, src, close in rows:
        d = str(d_raw or "").replace("-", "")[:8]
        if len(d) != 8:
            continue
        # 量 NULL＝缺官方量，當洞；量 0 可能是真停價，不算缺列
        if vol is None:
            continue
        try:
            v = float(vol)
        except (TypeError, ValueError):
            continue
        try:
            px = float(close or 0)
        except (TypeError, ValueError):
            px = 0.0
        # 櫃買補洞曾把「成交張數」再÷1000 → 留下 1～數十張假小量；高價股尤其荒謬
        if (
            str(src or "") == "biaoke_stock_day"
            and v > 0
            and v < 80
            and px >= 50
        ):
            continue
        have.add(d)
    holes = [d for d in open_days if d not in have]
    if not skip_confirmed_absent or not holes:
        return holes
    # 官方月表已確認無列（休市／未交易）落庫後不再當缺洞，避免每次冷查重抓整月
    known = load_confirmed_absent_dates(sid, path, start, end)
    if not known:
        return holes
    return [d for d in holes if d not in known]


# 補洞結果短記：查股暖路徑會二次 prepare，不准每次重打官方月表（CI ~2s）
# 同人連查／同檔暖路徑：5 分鐘內命中即可，仍只認真月表、不准造假量
_ENSURE_VOL_TTL_SEC = 300.0
_ENSURE_VOL_LOCK = threading.Lock()
_ENSURE_VOL_MEMO: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_ENSURE_VOL_MEMO_MAX = 64
# (sid, yyyymm) → 上次成功 STOCK_DAY 的日期集合（空 frozenset＝月表確認無列）
_ENSURE_MONTH_DATES: Dict[Tuple[str, str], frozenset] = {}
_ABSENT_TABLE = "official_quote_absent"


def clear_ensure_official_volume_cache() -> None:
    """清進程 memo／月表快取。已落庫的 confirmed_absent 不准清（冷啟才省得住）。"""
    with _ENSURE_VOL_LOCK:
        _ENSURE_VOL_MEMO.clear()
        _ENSURE_MONTH_DATES.clear()


def _ensure_absent_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_ABSENT_TABLE} (
            stock_id TEXT NOT NULL,
            ymd TEXT NOT NULL,
            noted_at TEXT,
            PRIMARY KEY (stock_id, ymd)
        )
        """
    )


def load_confirmed_absent_dates(
    stock_id: str,
    db_path: str,
    start_ymd: str = "",
    end_ymd: str = "",
) -> set:
    """讀已落庫：官方月表確認無列的開市日（不准發明量）。"""
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    if not sid or not path:
        return set()
    start = str(start_ymd or "").replace("-", "")[:8]
    end = str(end_ymd or "").replace("-", "")[:8]
    try:
        conn = sqlite3.connect(path, timeout=15.0)
        try:
            _ensure_absent_table(conn)
            if len(start) == 8 and len(end) == 8:
                rows = conn.execute(
                    f"SELECT ymd FROM {_ABSENT_TABLE} WHERE stock_id=? "
                    "AND ymd BETWEEN ? AND ?",
                    (sid, start, end),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT ymd FROM {_ABSENT_TABLE} WHERE stock_id=?",
                    (sid,),
                ).fetchall()
        finally:
            conn.close()
    except Exception:
        return set()
    out = set()
    for (ymd,) in rows or []:
        d = str(ymd or "").replace("-", "")[:8]
        if len(d) == 8:
            out.add(d)
    return out


def save_confirmed_absent_dates(
    stock_id: str,
    db_path: str,
    dates: List[str],
) -> int:
    """官方月表確認無列 → 落庫；下次缺洞掃描跳過，縮短查股第二→第三冷路徑。"""
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    clean = []
    for raw in dates or []:
        d = str(raw or "").replace("-", "")[:8]
        if len(d) == 8 and d.isdigit():
            clean.append(d)
    if not sid or not path or not clean:
        return 0
    from datetime import datetime
    from zoneinfo import ZoneInfo

    noted = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            _ensure_absent_table(conn)
            for d in clean:
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO {_ABSENT_TABLE} "
                    "(stock_id, ymd, noted_at) VALUES (?,?,?)",
                    (sid, d, noted),
                )
                n += int(cur.rowcount or 0)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.debug(
            "save_confirmed_absent fail sid=%s", sid, exc_info=True
        )
        return 0
    return n


def _copy_ensure_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(stats or {})
    for k in (
        "filled",
        "confirmed_absent",
        "still_missing",
        "months_ok",
        "months_fail",
        "months_fetched",
        "missing_before",
        "filled_dates",
    ):
        if k in out and isinstance(out[k], list):
            out[k] = list(out[k])
    return out


def ensure_official_volume_window(
    stock_id: str,
    db_path: str,
    *,
    end_ymd: str = "",
    days: int = 180,
    stock_name: str = "",
) -> Dict[str, Any]:
    """畫結構／大量區前：窗內開市日缺官方量 → 證交所／櫃買 STOCK_DAY 月表補洞。

    不准發明 OHLC／量。官方月表抓成功但當日無列＝休市／未交易 → confirmed_absent。
    同進程短記結果／已抓月份，暖命中不准重打網路。
    缺月並行抓（上限 _ENSURE_MONTH_FETCH_WORKERS），縮短查股第二→第三體感。
    """
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    out: Dict[str, Any] = {
        "sid": sid,
        "filled": [],
        "confirmed_absent": [],
        "still_missing": [],
        "months_ok": [],
        "months_fail": [],
        "months_fetched": [],
    }
    if not sid or not path or sid in ("TWII", "^TWII"):
        return out
    from datetime import datetime, timedelta

    from trading_calendar import normalize_ymd

    end = normalize_ymd(end_ymd)
    if len(end) != 8:
        conn = sqlite3.connect(path, timeout=15.0)
        try:
            row = conn.execute(
                "SELECT replace(date,'-','') FROM daily_quotes WHERE stock_id=? "
                "ORDER BY date DESC LIMIT 1",
                (sid,),
            ).fetchone()
        except Exception:
            row = None
        finally:
            conn.close()
        end = str((row or [""])[0] or "").replace("-", "")[:8]
    if len(end) != 8:
        try:
            from config import fuse_end_date

            end = normalize_ymd(fuse_end_date())
        except Exception:
            end = ""
    # 單檔 max(date) 可能殘留盤中未齊柱；補洞／抓月不准超過 fuse_end／完整日。
    try:
        from config import fuse_end_date
        from quote_integrity import db_as_of_trading_date

        cap = normalize_ymd(fuse_end_date())
        as_of = normalize_ymd(db_as_of_trading_date(path) or "")
        if len(as_of) == 8 and (not cap or as_of < cap):
            cap = as_of
        if len(cap) == 8 and len(end) == 8 and end > cap:
            end = cap
    except Exception:
        pass
    if len(end) != 8:
        return out
    # 日曆略放大，涵蓋開市日 need 根
    need = max(int(days or 0), 60)
    memo_key = (sid, path, end, int(need))
    now = time.monotonic()
    with _ENSURE_VOL_LOCK:
        hit = _ENSURE_VOL_MEMO.get(memo_key)
        if hit is not None and now - float(hit[0]) <= _ENSURE_VOL_TTL_SEC:
            return _copy_ensure_stats(hit[1])

    start_dt = datetime.strptime(end, "%Y%m%d") - timedelta(days=int(need * 1.7) + 20)
    start = start_dt.strftime("%Y%m%d")
    missing = missing_open_quote_days(sid, path, start, end)
    out["missing_before"] = list(missing)
    if not missing:
        # 無缺洞：仍帶已落庫 absent 給 prepare skip_invent（不准發明假量）
        known_abs = load_confirmed_absent_dates(sid, path, start, end)
        if known_abs:
            out["confirmed_absent"] = sorted(known_abs)
        with _ENSURE_VOL_LOCK:
            _ENSURE_VOL_MEMO[memo_key] = (time.monotonic(), _copy_ensure_stats(out))
        return out
    months = sorted({d[:6] for d in missing if len(d) >= 6})
    name = str(stock_name or "").strip() or sid
    if not str(stock_name or "").strip():
        conn = sqlite3.connect(path, timeout=15.0)
        try:
            row = conn.execute(
                "SELECT stock_name FROM daily_quotes WHERE stock_id=? "
                "AND stock_name IS NOT NULL AND stock_name!='' "
                "ORDER BY date DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if row and row[0]:
                name = str(row[0])
        except Exception:
            pass
        finally:
            conn.close()
    try:
        from biaoke_walk import (
            _market_of,
            fetch_stock_month,
            upsert_fetched_quotes,
        )
        from wayne_navigator import clear_align_ohlc_cache
    except Exception as e:
        logger.warning("ensure_official_volume_window import fail sid=%s: %s", sid, e)
        out["still_missing"] = list(missing)
        return out

    market = _market_of(path, sid)
    official_by_month: Dict[str, set] = {}
    wrote_any = False
    to_fetch: List[str] = []
    for ym in months:
        mk = (sid, ym)
        month_miss = [d for d in missing if str(d).startswith(ym)]
        # 庫內已有列仍被標 missing＝假小量／張誤÷1000 → 必須重抓，不准吃月表快取
        force_refetch = False
        if month_miss:
            conn_chk = sqlite3.connect(path, timeout=15.0)
            try:
                # 一批 IN 查，冷路徑少打 N 次單日 SELECT
                placeholders = ",".join("?" for _ in month_miss)
                hit = conn_chk.execute(
                    "SELECT 1 FROM daily_quotes WHERE stock_id=? "
                    f"AND replace(date,'-','') IN ({placeholders}) LIMIT 1",
                    (sid, *month_miss),
                ).fetchone()
                if hit:
                    force_refetch = True
            except Exception:
                force_refetch = True
            finally:
                conn_chk.close()
        cached_dates = None
        if not force_refetch:
            with _ENSURE_VOL_LOCK:
                if mk in _ENSURE_MONTH_DATES:
                    cached_dates = set(_ENSURE_MONTH_DATES[mk])
        else:
            with _ENSURE_VOL_LOCK:
                _ENSURE_MONTH_DATES.pop(mk, None)
        if cached_dates is not None:
            # 本進程已打過此月且無修補需求：不再打網路／sleep（暖路徑）
            out["months_fetched"].append(ym)
            out["months_ok"].append(ym)
            official_by_month[ym] = cached_dates
            continue
        to_fetch.append(ym)

    def _fetch_ym(ym: str) -> Tuple[str, List[Dict[str, Any]]]:
        try:
            rows = fetch_stock_month(
                sid, ym, market=market, name=name, tries=2
            )
        except Exception:
            logger.debug(
                "ensure vol fetch fail sid=%s ym=%s", sid, ym, exc_info=True
            )
            rows = []
        return ym, list(rows or [])

    # 並行抓缺月（真官方月表）；upsert 仍按月序寫入，不准跳過／造假量
    fetched_rows: Dict[str, List[Dict[str, Any]]] = {}
    if to_fetch:
        workers = max(1, min(int(_ENSURE_MONTH_FETCH_WORKERS), len(to_fetch)))
        if workers == 1 or len(to_fetch) == 1:
            for ym in to_fetch:
                y2, rows = _fetch_ym(ym)
                fetched_rows[y2] = rows
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_fetch_ym, ym) for ym in to_fetch]
                for fut in as_completed(futs):
                    try:
                        y2, rows = fut.result()
                    except Exception:
                        logger.debug(
                            "ensure vol pool fail sid=%s", sid, exc_info=True
                        )
                        continue
                    fetched_rows[y2] = rows

    for ym in to_fetch:
        out["months_fetched"].append(ym)
        rows = fetched_rows.get(ym) or []
        if not rows:
            out["months_fail"].append(ym)
            continue
        n = int(upsert_fetched_quotes(path, rows) or 0)
        out["months_ok"].append(ym)
        dates = {
            str(r.get("date") or "").replace("-", "")[:8] for r in rows
        }
        official_by_month[ym] = dates
        mk = (sid, ym)
        with _ENSURE_VOL_LOCK:
            _ENSURE_MONTH_DATES[mk] = frozenset(dates)
        if n:
            out["filled"].append({"yyyymm": ym, "rows": n})
            wrote_any = True
    if wrote_any:
        try:
            clear_align_ohlc_cache()
        except Exception:
            pass
    # 補完再掃：仍缺且該月官方已回＝confirmed_absent；月失敗＝still_missing
    # 不跳過已落庫 absent：本輪剛確認的也要寫進 out／DB
    missing_after = missing_open_quote_days(
        sid, path, start, end, skip_confirmed_absent=False
    )
    for d in missing_after:
        ym = d[:6]
        if ym in official_by_month:
            if d not in official_by_month[ym]:
                out["confirmed_absent"].append(d)
            else:
                # 官方有列但 upsert 後仍缺＝異常，當 still_missing
                out["still_missing"].append(d)
        elif ym in out["months_fail"]:
            out["still_missing"].append(d)
        else:
            out["still_missing"].append(d)
    # 補成功的洞
    filled_dates = [d for d in missing if d not in missing_after]
    out["filled_dates"] = filled_dates
    if out["confirmed_absent"]:
        try:
            save_confirmed_absent_dates(sid, path, out["confirmed_absent"])
        except Exception:
            logger.debug("persist confirmed_absent fail sid=%s", sid, exc_info=True)
        # 合併舊落庫（窗內），給 prepare skip_invent 一次帶齊
        known_abs = load_confirmed_absent_dates(sid, path, start, end)
        if known_abs:
            out["confirmed_absent"] = sorted(
                set(out["confirmed_absent"]) | known_abs
            )
    if filled_dates or out["confirmed_absent"]:
        logger.info(
            "official vol window sid=%s filled=%s absent=%s still=%s months_ok=%s",
            sid,
            len(filled_dates),
            len(out["confirmed_absent"]),
            len(out["still_missing"]),
            out["months_ok"],
        )
    with _ENSURE_VOL_LOCK:
        if len(_ENSURE_VOL_MEMO) >= _ENSURE_VOL_MEMO_MAX:
            oldest = sorted(_ENSURE_VOL_MEMO.items(), key=lambda kv: kv[1][0])[
                : _ENSURE_VOL_MEMO_MAX // 2
            ]
            for k, _ in oldest:
                _ENSURE_VOL_MEMO.pop(k, None)
        _ENSURE_VOL_MEMO[memo_key] = (time.monotonic(), _copy_ensure_stats(out))
    return _copy_ensure_stats(out)


def load_official_ohlc(stock_id: str, db_path: str, days: int = 120) -> pd.DataFrame:
    """只讀官方日表原柱。上市櫃 daily_quotes；不足再讀興櫃 emerging_quotes。

    加權 TWII／^TWII＝index_daily（大盤頁同一套官方柱）。
    不除權還原、不合併 MIS、不改開高低收。
    """
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    if not sid or not path:
        return pd.DataFrame()
    lim = max(int(days or 0), 30)
    if sid in ("TWII", "^TWII"):
        return _load_index_daily_ohlc(path, lim)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=10000;")
        try:
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
        except Exception:
            df = pd.DataFrame()
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
    # 與高低卡同源：只到庫內最後完整收盤日。未齊日（例盤中只寫到兩檔）
    # 不准進結構／大量區，否則兩圖最後收盤日會分叉。
    try:
        from quote_integrity import db_as_of_trading_date

        cap = str(db_as_of_trading_date(path) or "").replace("-", "")[:8]
    except Exception:
        cap = ""
    if cap:
        dcap = df["date"].astype(str).str.replace("-", "", regex=False)
        df = df.loc[dcap <= cap].reset_index(drop=True)
        if df.empty:
            return pd.DataFrame()
    if len(df) > lim:
        df = df.iloc[-lim:].reset_index(drop=True)
    df["stock_id"] = sid
    df["quote_source"] = source
    return df


def official_work(
    df: pd.DataFrame,
    *,
    skip_invent_dates: Optional[set] = None,
) -> Optional[pd.DataFrame]:
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
    # 開市日軸連續（與導航同一套）：缺列先官方補洞；已確認無列不准發明停價量
    from wayne_navigator import align_ohlc_cached

    sid_hint = ""
    if "stock_id" in work.columns:
        try:
            sid_hint = str(work["stock_id"].dropna().iloc[-1] or "")
        except Exception:
            sid_hint = ""
    # 呼叫端忘傳 skip 時仍吃庫內 confirmed_absent（2233 10/23 假柱曾讓兩圖分叉）
    skip_use = skip_invent_dates
    if skip_use is None and sid_hint:
        try:
            from wayne_db import DEFAULT_DB_PATH

            db_hint = str(
                os.environ.get("WAYNE_DB_PATH")
                or os.environ.get("DB_PATH")
                or DEFAULT_DB_PATH
                or ""
            ).strip()
            if db_hint and os.path.isfile(db_hint):
                known = load_confirmed_absent_dates(sid_hint, db_hint)
                if known:
                    skip_use = known
        except Exception:
            logger.debug(
                "official_work auto absent skip fail sid=%s", sid_hint, exc_info=True
            )
    work = align_ohlc_cached(
        work, sid_hint, skip_invent_dates=skip_use
    )
    if work is None or work.empty:
        return None
    work["dt"] = pd.to_datetime(work["date"].astype(str), format="%Y%m%d", errors="coerce")
    work = work.dropna(subset=["dt"]).reset_index(drop=True)
    vol = work["volume"].fillna(0.0)
    flat = (vol <= 0) & ((work["high"] - work["low"]).abs() <= 1e-8)
    if "is_halt" in work.columns:
        work["is_halt"] = work["is_halt"].fillna(False).astype(bool) | flat.fillna(False)
    else:
        work["is_halt"] = flat.fillna(False)
    return work


def _scale_cut_date(ex_events: Optional[List[Dict[str, Any]]], last_date: str) -> str:
    last = _bar_ymd(last_date)
    cut = ""
    for ev in official_scale_events(ex_events):
        d = _bar_ymd(ev.get("ex_date") or ev.get("date"))
        if d and last and d <= last and d >= cut:
            cut = d
    return cut


def _vol_zone_flag_true(v) -> bool:
    """只認明確 True；NaN 不准當 True（bool(nan) 會誤殺近窗）。"""
    if v is True:
        return True
    if v is False or v is None:
        return False
    try:
        if v != v:
            return False
    except Exception:
        pass
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    try:
        import numpy as np

        if isinstance(v, np.bool_):
            return bool(v)
    except Exception:
        pass
    return False


def _vol_zone_bar_skippable(work: pd.DataFrame, i: int, halt: pd.Series) -> bool:
    """停牌／假補／盤中疊加不准佔爆大量近窗名額、也不准當候選。"""
    if _vol_zone_flag_true(halt.iloc[i]):
        return True
    if "no_trade_fill" in work.columns and _vol_zone_flag_true(work["no_trade_fill"].iloc[i]):
        return True
    if "source" in work.columns and str(work["source"].iloc[i] or "") == "biaoke_stock_day":
        return True
    if "is_live" in work.columns and _vol_zone_flag_true(work["is_live"].iloc[i]):
        return True
    return False


def find_volume_zone(
    work: pd.DataFrame,
    *,
    lookback: int = VOL_ZONE_LOOKBACK,
    ex_events: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """近窗仍對現價有效的爆大量日。壓還在頭上才認；已全部站上才退回絕對最大量。

    準則（鎖死；與 ``biaoke_brain.volume_first_price`` 同窗）：
    1. 只用官方日 K 原柱；略過停牌、略過 biaoke_stock_day／is_live。
    2. 近窗＝恰 lookback 根**可交易**候選（預設 40），不含「最後一根」（大量區＝過去參考日）。
       停牌／對齊發明的假柱不准佔名額（2233：發明 10/23 曾把 08/25 擠出窗 → 與結構圖分叉）。
    3. 候選＝當日高 ≥ 最近收（壓還在頭上／還在區內）；其中取成交量最大。
    4. 若近窗已全部站上那些高 → 退回近窗（不含最後一根）絕對最大量。
    5. 壓＝該日官方高、撐＝該日官方低。不是買訊、不發明 5／9。
    6. 官方除權／除息把價位尺度切開：壓撐只在最近一次證交所／櫃買完成稿（含當日）之後的原柱裡找，
       不准拿除息前的高去壓除息後的收。啟發式跳空不准當除權息切窗。
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
    end = n - 1
    lb = max(int(lookback or 0), 1)
    # 由末日往前數恰 lookback 根可交易柱；假停牌不進計數
    tradable: List[int] = []
    for i in range(end - 1, -1, -1):
        if _vol_zone_bar_skippable(work, i, halt):
            continue
        tradable.append(i)
        if len(tradable) >= lb:
            break
    start = int(tradable[-1]) if tradable else end
    last_d = _bar_ymd(work["date"].iloc[-1])
    cut = _scale_cut_date(ex_events, last_d)
    if cut:
        for i in range(n):
            if _bar_ymd(work["date"].iloc[i]) >= cut:
                start = max(start, i)
                break
    last_close = float(work["close"].iloc[-1] or 0)
    provisional = False
    if start >= end:
        start = end
        end = n
        provisional = True
    best_i = None
    best_v = -1.0
    active_i = None
    active_v = -1.0
    for i in range(start, end):
        if _vol_zone_bar_skippable(work, i, halt):
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
        "provisional": bool(provisional),
        "ex_cut": cut,
    }


# 圖下不再加括號定義。事實句由 vol_zone_photo_caption 逐句送出。
VOL_ZONE_CAPTION_HEAD = ""
_PRESS_TOUCH = 0.997
_VOL_REAL = 0.70
_VOL_THIN = 0.35
_HEAT_CLAUSE = {
    "peak": "溫度在最高溫",
    "up": "溫度上升",
    "down": "溫度下降",
    "floor": "溫度在最低溫",
    "flat": "溫度沒再走",
    "diverge": "價溫背離",
}
_ZH_N = {
    1: "一",
    2: "兩",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}
_ZH_ORD = {**_ZH_N, 2: "二"}


def _px(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def _zh_days(n: int, *, ordinal: bool = False) -> str:
    table = _ZH_ORD if ordinal else _ZH_N
    return table.get(int(n), str(int(n)))


def _rows_from_last(last: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [last]


def _trade_day(val: Any) -> str:
    s = str(val or "").replace("-", "").replace("/", "")[:8]
    return s if s.isdigit() and len(s) == 8 else ""


def _is_zone_bar(row: Dict[str, Any], zone: Dict[str, Any]) -> bool:
    """爆大量參考日本身的高低＝壓撐定義，不能當成『昨天碰到上緣』。"""
    zd = _trade_day(zone.get("date"))
    rd = _trade_day(row.get("date"))
    if zd and rd:
        return zd == rd
    return False


def _stand_streak(
    rows: List[Dict[str, Any]],
    lo: float,
    hi: float,
    *,
    since: str = "",
) -> List[Dict[str, Any]]:
    """連站＝從最新收往回，連續收盤 ≥ 撐。

    人在壓之上仍算站在這條撐上（收仍 ≥ 撐）；只有收盤跌破撐才斷。
    since＝除權息尺度切開日（含當日）：更早的柱是另一把尺，不准拿來數「除息後撐」天數。
    hi 留給呼叫端簽名對齊；是否已過壓由 vol_zone_position_line 先分流。
    """
    _ = hi
    cut = _trade_day(since)
    streak: List[Dict[str, Any]] = []
    for row in reversed(rows):
        d = _trade_day(row.get("date"))
        if cut and d and d < cut:
            break
        c = _px(row.get("close"))
        if c >= lo:
            streak.append(row)
        else:
            break
    streak.reverse()
    return streak


def _heat_key(card: Optional[Dict[str, Any]]) -> str:
    if not card:
        return ""
    try:
        from sell_discipline import card_discipline_face

        return str(card_discipline_face(card).get("heat") or "")
    except Exception:
        return ""


def _vol_compare_line(last_vol: float, zone_vol: float, *, named_day: bool) -> str:
    """量比前一次爆大量。門檻仍是 _VOL_REAL／_VOL_THIN，只改口吻。"""
    if zone_vol <= 0 or last_vol <= 0:
        return ""
    ratio = last_vol / zone_vol
    that = "那天" if named_day else "前一次爆大量"
    if ratio >= 1.05:
        return f"今天的量比{that}多"
    if ratio >= _VOL_REAL:
        return f"今天的量仍接近{that}"
    if ratio < _VOL_THIN:
        return f"今天的量比{that}少很多"
    return f"今天的量比{that}少"


def _vol_fact_lines(zone: Optional[Dict[str, Any]], last: Optional[Dict[str, Any]]) -> List[str]:
    """前一次爆大量用選區已算出的日期，不寫死某一天。"""
    last_vol = _px((last or {}).get("volume"))
    zone_vol = _px((zone or {}).get("volume"))
    md = _date_zh_md((zone or {}).get("date"))
    cmp_line = _vol_compare_line(last_vol, zone_vol, named_day=bool(md))
    if not cmp_line:
        return []
    if md:
        return [f"前一次爆大量是{md}", cmp_line]
    return [cmp_line]


def _today_yest_temp(card: Optional[Dict[str, Any]]) -> tuple:
    if not card:
        return None, None
    try:
        tbl = card.get("table")
        rows: List[Dict[str, Any]] = []
        if tbl is not None and hasattr(tbl, "columns"):
            from sell_discipline import _chrono_table

            src = _chrono_table(tbl)
            rows = [dict(x) for x in src.to_dict("records")]
        elif isinstance(tbl, (list, tuple)):
            rows = [dict(x) for x in tbl if isinstance(x, dict)]
            rows.sort(key=lambda r: str(r.get("date") or ""))
        if len(rows) < 2:
            return None, None
        today = _px(rows[-1].get("temp_num"))
        yest = _px(rows[-2].get("temp_num"))
        if today <= 0 or yest <= 0:
            return None, None
        return today, yest
    except Exception:
        return None, None


def _heat_clause(card: Optional[Dict[str, Any]], heat: str) -> str:
    today, yest = _today_yest_temp(card)
    if today is not None and yest is not None:
        if today < yest - 0.05:
            return "溫度比昨天低"
        if today > yest + 0.05:
            if heat in ("up", "peak"):
                return "溫度上升"
            return "溫度比昨天高"
    return _HEAT_CLAUSE.get(heat, "")


def _closes_rising(closes: List[float]) -> bool:
    return len(closes) >= 2 and all(closes[i] > closes[i - 1] for i in range(1, len(closes)))


def _date_zh_md(val: Any) -> str:
    """YYYYMMDD → 10月6日（台北交易日戳，不准寫死某檔）。"""
    s = _trade_day(val)
    if len(s) < 8:
        return ""
    m, d = int(s[4:6]), int(s[6:8])
    if m <= 0 or d <= 0:
        return ""
    return f"{m}月{d}日"


def _bar_tests_hold(row: Dict[str, Any], hold: float) -> bool:
    """當日高低穿過／碰到大量撐（近窗測撐）。"""
    if hold <= 0:
        return False
    lo = _px(row.get("low"))
    hi = _px(row.get("high"))
    if lo <= 0 or hi <= 0:
        return False
    return lo <= hold * (2.0 - _PRESS_TOUCH) and hi >= hold * _PRESS_TOUCH


def _bar_tests_press(row: Dict[str, Any], press: float) -> bool:
    """當日高碰到大量壓且收沒過（測壓≠站上）。"""
    if press <= 0:
        return False
    hi = _px(row.get("high"))
    cl = _px(row.get("close"))
    if hi <= 0 or cl <= 0:
        return False
    return hi >= press * _PRESS_TOUCH and cl <= press


def _vol_zone_price_voice(*, session_live: bool, emerging: bool) -> Dict[str, str]:
    """盤中／收盤圖說價口吻。盤中不准寫收／收盤／當天收；興櫃盤中＝興櫃日均價。"""
    if session_live:
        if emerging:
            return {
                "day_stamp": "興櫃日均價",
                "today_stamp": "興櫃日均價",
                "px_prefix": "興櫃日均價",
                "over": "興櫃日均價已過",
                "not_over": "興櫃日均價未過",
                "still": "興櫃日均價仍",
                "not_through": "興櫃日均價沒過",
                "vs_yest": "比昨天收低",
                "short": "現",
            }
        return {
            "day_stamp": "現價",
            "today_stamp": "現價",
            "px_prefix": "現價",
            "over": "現價已過",
            "not_over": "現價未過",
            "still": "現價仍",
            "not_through": "現價沒過",
            "vs_yest": "比昨天收低",
            "short": "現",
        }
    return {
        "day_stamp": "當天收",
        "today_stamp": "今天收盤",
        "px_prefix": "收盤",
        "over": "收盤已過",
        "not_over": "收盤未過",
        "still": "收盤仍",
        "not_through": "收盤沒過",
        "vs_yest": "比昨天低",
        "short": "收",
    }


def _apply_card_face_to_view(view: pd.DataFrame, card: Optional[Dict[str, Any]]) -> pd.DataFrame:
    """縮圖臉柱末日對齊決策卡表頭：今天已收／盤中現價都要跟上，不准停在昨收。

    與圖說／走勢標同一條 `align_vol_zone_caption_face`：單一今天棒餵渲染。
    """
    if view is None or getattr(view, "empty", True) or not isinstance(card, dict):
        return view
    last_row = view.iloc[-1].to_dict()
    bars = view.to_dict("records")
    face, _face_bars, meta = align_vol_zone_caption_face(last_row, bars, card)
    if not meta.get("aligned") or not face or _px(face.get("close")) <= 0:
        return view
    out = view.copy()
    face_d = _trade_day(face.get("date"))
    last_d = _trade_day(out.iloc[-1].get("date"))
    patch = {
        "date": face.get("date"),
        "open": _px(face.get("open")),
        "high": _px(face.get("high")),
        "low": _px(face.get("low")),
        "close": _px(face.get("close")),
        "volume": _px(face.get("volume")),
        "is_live": bool(meta.get("session_live")),
    }
    if face_d and last_d and face_d > last_d:
        row = dict(out.iloc[-1].to_dict())
        row.update(patch)
        out = pd.concat([out, pd.DataFrame([row])], ignore_index=True)
        return out
    idx = len(out) - 1
    for k, val in patch.items():
        if val is None:
            continue
        if k not in out.columns:
            out[k] = None
        out.iat[idx, out.columns.get_loc(k)] = val
    return out


def align_vol_zone_caption_face(
    last: Optional[Dict[str, Any]],
    bars: Optional[List[Dict[str, Any]]],
    card: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """大量區圖說／走勢標末日柱＝表頭同源（display_quote_from_card）。

    不准用前一日收／開冒充今天收／現價。回傳 (face_last, face_bars, meta)。
    meta: session_live／emerging／voice。
    """
    rows = [dict(x) for x in (bars or []) if isinstance(x, dict)]
    face = dict(last) if isinstance(last, dict) else (dict(rows[-1]) if rows else None)
    emerging = False
    session_live = False
    dq = None
    if isinstance(card, dict) and card:
        listing = str(card.get("listing") or "")
        qs = str(card.get("quote_source") or "")
        if qs == "emerging_quotes" or listing.startswith("興櫃"):
            emerging = True
        try:
            from live_quote import display_quote_from_card

            dq = display_quote_from_card(card)
        except Exception:
            dq = None
    if dq and _px(dq.get("close")) > 0:
        emerging = bool(dq.get("emerging")) or emerging
        # 表頭 label 已分盤中／收盤（含興櫃 15:00）；跟四張圖同源
        session_live = str(dq.get("label") or "") == "盤中"
        face_date = _trade_day(dq.get("date") or dq.get("as_of") or "")
        if not face_date and isinstance(card, dict):
            face_date = _trade_day(card.get("latest_date") or card.get("as_of") or "")
        face = dict(face or {})
        if face_date:
            face["date"] = face_date
        for k in ("open", "high", "low", "close"):
            v = _px(dq.get(k))
            if v > 0:
                face[k] = v
        face["close"] = _px(dq.get("close"))
        vol = dq.get("volume")
        if vol is not None and _px(vol) >= 0:
            face["volume"] = _px(vol)
        if not rows:
            rows = [dict(face)]
        else:
            last_d = _trade_day(rows[-1].get("date"))
            face_d = _trade_day(face.get("date"))
            if face_d and last_d and face_d > last_d:
                # 庫末日仍是前一日：附加今天臉柱，不准蓋掉昨天（連站要比昨天）
                rows = list(rows) + [dict(face)]
            else:
                merged = dict(rows[-1])
                for k in ("date", "open", "high", "low", "close", "volume"):
                    if face.get(k) is not None:
                        merged[k] = face[k]
                rows = list(rows[:-1]) + [merged]
                face = dict(merged)
    elif isinstance(card, dict) and card:
        session_live = bool(card.get("is_live"))
        try:
            from decision_card_signals import _in_board_session
            from config import taipei_now

            session_live = bool(card.get("is_live")) and _in_board_session(
                taipei_now(), emerging=emerging
            )
        except Exception:
            pass
    if face is None and rows:
        face = dict(rows[-1])
    voice = _vol_zone_price_voice(session_live=session_live, emerging=emerging)
    meta = {
        "session_live": session_live,
        "emerging": emerging,
        "voice": voice,
        "aligned": bool(dq and _px((dq or {}).get("close")) > 0),
    }
    return face, rows, meta


def vol_zone_day_path_label(
    press: float,
    hold: float,
    last: Optional[Dict[str, Any]],
    bars: Optional[List[Dict[str, Any]]] = None,
    *,
    zone_date: str = "",
    card: Optional[Dict[str, Any]] = None,
    session_live: Optional[bool] = None,
    emerging: Optional[bool] = None,
) -> str:
    """③最後一根走勢標：對應當日官方／MIS 開高低收＋既有壓撐，不是死釘『月/日 壓價』。

    例形：10月6日 撐為2,940  今最高3,055  今最低2,915  收盤未過撐  收2,920
    盤中改現價／興櫃日均價口吻，價跟表頭同源。只留事實句。不是買訊。
    bars／zone_date 保留給呼叫端相容（判斷句已刪，不再用來計次）。
    """
    del bars, zone_date  # 相容舊呼叫；當日標不再做近窗測次判斷
    face = last
    live = bool(session_live) if session_live is not None else False
    em = bool(emerging) if emerging is not None else False
    if card is not None:
        face, _rows, meta = align_vol_zone_caption_face(last, None, card)
        live = bool(meta.get("session_live"))
        em = bool(meta.get("emerging"))
    elif session_live is None and emerging is None:
        live, em = False, False
    if not face:
        return ""
    voice = _vol_zone_price_voice(session_live=live, emerging=em)
    press = _px(press)
    hold = _px(hold)
    cl = _px(face.get("close"))
    hi = _px(face.get("high") or cl)
    lo = _px(face.get("low") or cl)
    if cl <= 0 or hi <= 0 or press <= 0 or hold <= 0 or press < hold:
        return ""
    day_zh = _date_zh_md(face.get("date"))
    if not day_zh:
        return ""
    press_s = _fmt_price(press)
    hold_s = _fmt_price(hold)
    hi_s = _fmt_price(hi)
    cl_s = _fmt_price(cl)
    lo_s = _fmt_price(lo)

    press_touch = _bar_tests_press(face, press)
    hold_touch = _bar_tests_hold(face, hold)
    if press_touch and not (cl < hold):
        side = "press"
    elif hold_touch or cl < hold:
        side = "hold"
    elif cl > press:
        side = "press"
    else:
        side = "press" if abs(cl - press) <= abs(cl - hold) else "hold"

    short = voice["short"]
    if side == "hold":
        verb = f"{voice['over']}撐" if cl > hold else f"{voice['not_over']}撐"
        low_bit = f"  今最低{lo_s}" if lo > 0 and lo <= hold * 1.01 else ""
        line = (
            f"{day_zh} 撐為{hold_s}  今最高{hi_s}{low_bit}  "
            f"{verb}  {short}{cl_s}"
        )
    else:
        verb = f"{voice['over']}壓" if cl > press else f"{voice['not_over']}壓"
        line = (
            f"{day_zh} 壓為{press_s}  今最高{hi_s}  "
            f"{verb}  {short}{cl_s}"
        )
    return "  ".join(line.split())


def vol_zone_position_line(
    zone: Optional[Dict[str, Any]],
    last: Optional[Dict[str, Any]],
    card: Optional[Dict[str, Any]] = None,
    bars: Optional[List[Dict[str, Any]]] = None,
    *,
    on_ex: bool = False,
    stock_id: str = "",
) -> str:
    """依這檔在帶裡的現況換句，不是同一套填空。不寫抱、不寫賣、不改如何賣。

    今天這根價／口吻跟大量區表頭同源（決策卡 display_quote）；盤中不准用昨收／開當收。
    """
    face, rows, meta = align_vol_zone_caption_face(last, bars, card)
    if not zone or not face:
        return ""
    voice = meta.get("voice") or _vol_zone_price_voice(session_live=False, emerging=False)
    hi = _px(zone.get("high"))
    lo = _px(zone.get("low"))
    cl = _px(face.get("close"))
    if hi <= 0 or lo <= 0 or hi < lo or cl <= 0:
        return ""
    from wayne_navigator import _fmt_price

    hi_s = _fmt_price(hi)
    lo_s = _fmt_price(lo)
    if not rows:
        rows = _rows_from_last(face)
    heat = _heat_key(card)
    heat_line = _heat_clause(card, heat)
    vol_lines = _vol_fact_lines(zone, face)
    last_hi = _px(face.get("high") or cl)
    # 收＝壓＝碰到上緣還沒過；只有收＞壓才算過壓
    test_press = last_hi >= hi * _PRESS_TOUCH and cl <= hi
    near_press = hi > 0 and cl <= hi and (hi - cl) / hi <= 0.015

    def _emit(*clauses: str, nice: bool = False, test: bool = False) -> str:
        bits: List[str] = []
        for raw in clauses:
            s = str(raw or "").strip()
            if not s:
                continue
            if on_ex:
                s = s.replace("剛站在支撐線上", "剛站在除息後支撐線上")
                s = s.replace("站在支撐線上", "站在除息後支撐線上")
                s = s.replace("跌破撐", "跌破除息後撐")
            bits.append(s)
        bits.extend(vol_lines)
        if heat_line:
            bits.append(heat_line)
        if nice:
            bits.append("看起來不錯！")
        elif test:
            bits.append("今天高碰到上緣")
            bits.append(voice["not_through"])
        lines: List[str] = []
        for bit in bits:
            s = str(bit or "").strip()
            if not s:
                continue
            if not s.endswith(("。", "！")):
                s += "。"
            lines.append(s)
        return "\n".join(lines)

    if cl < lo:
        hold = f"撐{lo_s}已跌破"
        gone = "這條撐不算還在"
        if on_ex:
            hold = f"除息後撐{lo_s}已跌破"
            gone = "這條除息後撐不算還在"
        # 破撐原因句：點名下一層壓+撐（非買訊）；無候選明示暫無；破撐≠換主區
        next_bit = ""
        try:
            from biaoke_next_support import resolve_next_support

            sid0 = str(
                stock_id
                or (card or {}).get("stock_id")
                or (card or {}).get("sid")
                or (card or {}).get("code")
                or ""
            )
            pack = resolve_next_support(
                rows,
                sid=sid0,
                close=cl,
                support=lo,
                pressure=hi,
                spike_date=str((zone or {}).get("date") or ""),
                under_support=True,
            )
            layer = pack.get("layer") or {}
            lo_n = _px(layer.get("low"))
            hi_n = _px(layer.get("high"))
            if lo_n > 0 and hi_n > 0:
                next_bit = (
                    f"下一層壓{_fmt_price(hi_n)}／撐{_fmt_price(lo_n)}"
                    "（非買訊；主區未換）"
                )
            else:
                # 無下一層＝靜默，不准寫「暫無下一層大量區」
                next_bit = ""
        except Exception:
            next_bit = ""
        bits_extra = (next_bit,) if next_bit else ()
        return _emit(hold, f"{voice['day_stamp']}{_fmt_price(cl)}", gone, *bits_extra)
    if cl > hi:
        # 過壓對稱：標下一層（次大量區壓+撐）；主區仍依重算規則，不在此硬換
        next_bit = ""
        try:
            from biaoke_next_support import resolve_next_support

            sid0 = str(
                stock_id
                or (card or {}).get("stock_id")
                or (card or {}).get("sid")
                or (card or {}).get("code")
                or ""
            )
            pack = resolve_next_support(
                rows,
                sid=sid0,
                close=cl,
                support=lo,
                pressure=hi,
                spike_date=str((zone or {}).get("date") or ""),
                over_pressure=True,
            )
            layer = pack.get("layer") or {}
            lo_n = _px(layer.get("low"))
            hi_n = _px(layer.get("high"))
            if lo_n > 0 and hi_n > 0:
                next_bit = (
                    f"下一層壓{_fmt_price(hi_n)}／撐{_fmt_price(lo_n)}"
                    "（非買訊）"
                )
            else:
                next_bit = ""
        except Exception:
            next_bit = ""
        bits = (f"{voice['over']}壓{hi_s}上緣",)
        if next_bit:
            bits = bits + (next_bit,)
        return _emit(*bits)

    # 有官方除權息切開才卡 since；沒有則仍用全序列（同尺價可含爆大量日前）。
    since = _trade_day(zone.get("ex_cut") or "")
    streak = _stand_streak(rows, lo, hi, since=since)
    n = len(streak) or 1
    n_zh = _zh_days(n)
    n_ord = _zh_days(n, ordinal=True)
    closes = [_px(r.get("close")) for r in streak]
    rising = _closes_rising(closes)
    last_down = n >= 2 and closes[-1] < closes[-2]
    nice = rising and heat in ("up", "peak", "") and not test_press

    if n == 1:
        if test_press:
            body = (
                f"今天剛站在支撐線上，{voice['px_prefix']}{_fmt_price(cl)}"
                f"還在撐{lo_s}之上，還沒過{hi_s}上緣"
            )
            return _emit(body, test=True)
        body = (
            f"今天剛站在支撐線上，{voice['px_prefix']}{_fmt_price(cl)}還在撐{lo_s}之上，"
            f"仍沒有突破{hi_s}上緣壓力"
        )
        return _emit(body)

    if rising:
        body = (
            f"今天是第{n_ord}天站在支撐線上，且{n_zh}天收盤價持續攀高，"
            f"{voice['still']}沒有突破{hi_s}上緣壓力"
        )
        return _emit(body, nice=nice, test=test_press and not nice)

    if last_down:
        body = (
            f"今天是第{n_ord}天站在支撐線上，但{voice['today_stamp']} "
            f"{_fmt_price(cl)} {voice['vs_yest']}"
        )
        prev = streak[-2] if n >= 2 else {}
        prev_hi = _px(prev.get("high")) if n >= 2 else 0
        if prev_hi >= hi * _PRESS_TOUCH and not _is_zone_bar(prev, zone):
            body += f"；昨天盤中高點有碰到上緣 {hi_s}，這{n_zh}天收盤價沒有持續攀高"
            return _emit(body, test=False)
        body += (
            f"，這{n_zh}天收盤價沒有持續攀高，"
            f"{voice['still']}沒有突破{hi_s}上緣壓力"
        )
        return _emit(body, test=test_press)

    if near_press:
        body = (
            f"今天是第{n_ord}天站在支撐線上，{voice['px_prefix']}{_fmt_price(cl)}"
            f"靠近{hi_s}上緣但沒過，"
            f"仍在撐{lo_s}之上，這{n_zh}天收盤價沒有持續攀高"
        )
        return _emit(body, test=test_press)

    body = (
        f"今天是第{n_ord}天站在支撐線上，{voice['px_prefix']}{_fmt_price(cl)}仍在撐{lo_s}之上，"
        f"但這{n_zh}天收盤價沒有持續攀高，{voice['still']}沒有突破{hi_s}上緣壓力"
    )
    return _emit(body, test=test_press)


def vol_zone_photo_caption(
    stock_id: str = "",
    db_path: str = "",
    card: Optional[Dict[str, Any]] = None,
    *,
    zone: Optional[Dict[str, Any]] = None,
    last: Optional[Dict[str, Any]] = None,
    bars: Optional[List[Dict[str, Any]]] = None,
    ex_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """大量區圖說：原句＋除權息／跳空＋今天臉柱口吻。查股／勝率／壓撐同一條。

    今天價跟表頭同源；盤中現價／興櫃日均價，收盤＝官方收（興櫃＝日均價）。如何賣仍只在介紹圖／高低卡。
    """
    events = list(ex_events or [])
    gaps: List[str] = []
    if zone is None or last is None or bars is None:
        sid = str(stock_id or "").strip()
        path = str(db_path or "").strip()
        if sid and path:
            raw = load_official_ohlc(sid, path, max(VOL_ZONE_BARS + VOL_ZONE_LOOKBACK + 5, 120))
            work = official_work(raw)
            if work is not None and not work.empty:
                start = _bar_ymd(work["date"].iloc[0])
                end = _bar_ymd(work["date"].iloc[-1])
                events = load_scale_ex_events(sid, path, start, end)
                recent = work.tail(8) if hasattr(work, "tail") else work
                events = hydrate_official_ex_for_gaps(sid, path, recent, events)
                gaps = unexplained_gap_dates(recent, way="down")
                zone = find_volume_zone(work, ex_events=events)
                bars = [
                    {
                        "date": r.get("date"),
                        "high": r.get("high"),
                        "low": r.get("low"),
                        "close": r.get("close"),
                        "volume": r.get("volume"),
                    }
                    for r in work.to_dict("records")
                ]
                last = bars[-1] if bars else last
    elif bars:
        recent = bars[-8:] if len(bars) > 8 else bars
        gaps = unexplained_gap_dates(recent, way="down")
    # 圖說末日先對齊決策卡表頭，再算除息日／位置句（上市＋興櫃同一條）
    last, bars, _meta = align_vol_zone_caption_face(last, bars, card)
    on_ex = False
    last_d = _bar_ymd((last or {}).get("date"))
    zd = _bar_ymd((zone or {}).get("date"))
    ev = _latest_ex_event(official_scale_events(events), last_d or zd)
    if ev and phone_ex_verb((ev or {}).get("kind")) and _bar_ymd(ev.get("ex_date")) in {zd, last_d}:
        on_ex = True
    note = _ex_gap_note(events, gaps, last_d or zd, zd, voice="zone")
    pos = vol_zone_position_line(
        zone,
        last,
        card,
        bars=bars,
        on_ex=on_ex,
        stock_id=str(stock_id or ""),
    )
    parts = [x.strip() for x in (note, pos) if str(x or "").strip()]
    if parts:
        return "\n".join(parts)
    return VOL_ZONE_CAPTION_HEAD


def _candle_up(close: float, prev_close: Optional[float], open_: float) -> bool:
    try:
        from decision_card_signals import candle_up_taiwan

        return bool(candle_up_taiwan(close, prev_close, open_))
    except Exception:
        if prev_close is None:
            return float(close) >= float(open_)
        return float(close) >= float(prev_close)


def clear_vol_zone_render_cache() -> None:
    with _VZ_RENDER_LOCK:
        _VZ_RENDER_MEMO.clear()


def _vz_memo_key(
    sid: str,
    zone: Dict[str, Any],
    last: Optional[Dict[str, Any]],
    *,
    with_nav_signals: bool,
    lookback: int,
    bars: int,
    lookup_portrait: bool = False,
    with_parallel_channel: bool = False,
    with_ma5_ma10: bool = True,
    card_fp: Tuple[Any, ...] = (),
    channel_fp: Tuple[Any, ...] = (),
) -> Tuple[Any, ...]:
    last_d = _bar_ymd((last or {}).get("date"))
    return (
        str(sid),
        last_d,
        _bar_ymd(zone.get("date")),
        round(float(zone.get("high") or 0), 4),
        round(float(zone.get("low") or 0), 4),
        bool(with_nav_signals),
        int(lookback),
        int(bars),
        int(VOL_ZONE_DPI),
        int(VOL_ZONE_JPEG_QUALITY),
        int(_VZ_PAINT_VER),
        int(bool(lookup_portrait)),
        int(bool(with_parallel_channel)),
        int(bool(with_ma5_ma10)),
        tuple(card_fp or ()),
        tuple(channel_fp or ()),
    )


def _bars_face_records(bars_face) -> list[Dict[str, Any]]:
    out: list[Dict[str, Any]] = []
    for r in list(bars_face or []):
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "date": str(r.get("date") or "").replace("-", "")[:8],
                "open": float(r.get("open") or 0),
                "high": float(r.get("high") or 0),
                "low": float(r.get("low") or 0),
                "close": float(r.get("close") or 0),
                "volume": float(r.get("volume") or 0),
            }
        )
    return out


def _channel_remap_to_view(
    ch: Dict[str, Any], date_to_i: Dict[str, int]
) -> Optional[Dict[str, Any]]:
    """把長窗通道的連點 index 對到大量區近窗；對不上就空（改近窗重算）。"""
    if not ch or not date_to_i:
        return None

    def _pt(pt) -> Optional[Tuple[int, float, str]]:
        if not pt or len(pt) < 3:
            return None
        key = str(pt[2] or "").replace("-", "")[:8]
        if key not in date_to_i:
            return None
        return (int(date_to_i[key]), float(pt[1]), key)

    upper = ch.get("upper") or ()
    lower = ch.get("lower") or ()
    if len(upper) < 2 or len(lower) < 2:
        return None
    u1, u2 = _pt(upper[0]), _pt(upper[1])
    l1, l2 = _pt(lower[0]), _pt(lower[1])
    if None in (u1, u2, l1, l2):
        return None
    touch_raw = ch.get("touch")
    touch = _pt(touch_raw) if touch_raw else None
    base_raw = ch.get("base") or ()
    base = None
    if len(base_raw) >= 2:
        b1, b2 = _pt(base_raw[0]), _pt(base_raw[1])
        if b1 and b2:
            base = (b1, b2)
    out = dict(ch)
    out["upper"] = (u1, u2)
    out["lower"] = (l1, l2)
    if touch:
        out["touch"] = touch
    if base:
        out["base"] = base
    return out


def infer_vol_zone_parallel_channel(
    view,
    *,
    bars_face=None,
    db_path: str = "",
    stock_id: str = "",
) -> Dict[str, Any]:
    """大量區近窗可疊的平行軌：算法＝結構圖 infer_parallel_channel（可重算；不數浪）。

    加權／TWII：若他自己寫過「M/D M/D兩天低點來畫」，優先用那兩天官方低連線；
    官方收破升軌則升通道失效、改判下降（與結構圖同一套）。否則長窗推算→近窗對日期。
    映不上才直接用近窗算。不准發明沒說過的價／浪號。盤中未收不當收。
    """
    from biaoke_chart import (
        channel_prefer_named_rising_or_infer,
        infer_parallel_channel,
        latest_biaoke_named_rising_lows,
        structure_visible_bars,
    )

    if view is None or getattr(view, "empty", True) or len(view) < 24:
        return {}
    date_to_i = {
        str(view.iloc[i].get("date") or "").replace("-", "")[:8]: i for i in range(len(view))
    }
    face = _bars_face_records(bars_face)
    # 與結構圖同一固定可視窗（新日進／最左出）；大量區近窗 show_n 仍走 VOL_ZONE_BARS
    work = structure_visible_bars(face)
    if len(work) < 24:
        work = _bars_face_records(view.to_dict("records"))

    sid = str(stock_id or "").strip().upper()
    if sid in ("TWII", "TAIEX", "^TWII") and db_path:
        named = latest_biaoke_named_rising_lows(str(db_path))
        if named:
            d1, d2, _pid = named
            ch_named = channel_prefer_named_rising_or_infer(work, d1, d2)
            if not ch_named:
                rows_v = _bars_face_records(view.to_dict("records"))
                ch_named = channel_prefer_named_rising_or_infer(rows_v, d1, d2)
            if ch_named:
                mapped = _channel_remap_to_view(ch_named, date_to_i)
                return mapped or ch_named

    if len(face) >= 24:
        ch = infer_parallel_channel(work)
        mapped = _channel_remap_to_view(ch, date_to_i) if ch else None
        if mapped:
            return mapped
    rows = _bars_face_records(view.to_dict("records"))
    return infer_parallel_channel(rows) or {}


def _channel_anchor_md(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{int(t[4:6])}/{int(t[6:8])}"
    return str(raw or "").strip()


def _market_channel_anchor_caption(ch: Dict[str, Any], *, upper: bool) -> str:
    """大盤軌標：寫這條線實際連的日期與價，不寫右緣延伸價。"""
    kind = str((ch or {}).get("kind") or "")
    if kind == "desc":
        name = str(ch.get("name_u") if upper else ch.get("name_l") or "")
        if upper:
            pts = ch.get("base") or ch.get("upper") or ()
            lines = [name] if name else []
            for pt in list(pts)[:2]:
                if pt and len(pt) >= 3:
                    lines.append(f"{_channel_anchor_md(pt[2])}高{_fmt_price(pt[1])}")
            return "\n".join(lines) if lines else name
        touch = ch.get("touch") or ()
        if touch and len(touch) >= 3:
            head = name or "平行撐"
            return f"{head}\n{_channel_anchor_md(touch[2])}低{_fmt_price(touch[1])}"
        return name
    name = str(ch.get("name_l") if not upper else ch.get("name_u") or "")
    if not upper:
        pts = ch.get("base") or ch.get("lower") or ()
        lines = [name or "上升軌"]
        for pt in list(pts)[:2]:
            if pt and len(pt) >= 3:
                lines.append(f"{_channel_anchor_md(pt[2])}低{_fmt_price(pt[1])}")
        return "\n".join(lines)
    touch = ch.get("touch") or ()
    head = name or "平行壓"
    if touch and len(touch) >= 3:
        return f"{head}\n{_channel_anchor_md(touch[2])}高{_fmt_price(touch[1])}"
    return head


def _channel_text_box_data(
    ax, text: str, *, n: int, ymin: float, ymax: float, fs: float = 7.6
) -> Tuple[float, float]:
    """軌標盒寬高（資料座標）。對齊最終 xlim（-0.8, n-0.2），不把 K 往左擠。"""
    pos = ax.get_position()
    fw, fh = ax.figure.get_size_inches()
    ax_w = max(float(pos.width) * float(fw), 0.1)
    ax_h = max(float(pos.height) * float(fh), 0.1)
    lines = [ln for ln in str(text or "").split("\n")] or [""]
    widths = []
    for line in lines:
        w_pt = fs * 0.45
        for ch in line:
            w_pt += fs if ord(ch) > 127 else fs * 0.56
        widths.append(w_pt)
    w_pt = max(widths) if widths else fs
    h_pt = fs * 1.28 * max(len(lines), 1) + fs * 0.55
    x_span = max(float(n) - 0.2 - (-0.8), 1.0)
    y_span = max(float(ymax) - float(ymin), 1.0)
    dx = (w_pt / 72.0) / ax_w * x_span
    dy = (h_pt / 72.0) / ax_h * y_span
    return dx * 1.08, dy * 1.12


def _channel_seg_y(seg, x: float, fallback: float) -> float:
    try:
        (x1, y1, _a), (x2, y2, _b) = seg
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
        if abs(x2 - x1) < 1e-9:
            return y2
        return y1 + (y2 - y1) * (float(x) - x1) / (x2 - x1)
    except Exception:
        return float(fallback)


def _channel_box_k_hits(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    *,
    n: int,
    highs: np.ndarray,
    lows: np.ndarray,
    mark_pad: float = 0.0,
    span: float = 1.0,
) -> int:
    """資料座標粗估：盒蓋到幾根 K（含影線 high–low）。交審以像素 hit 為準。"""
    pad_y = max(float(span), 1.0) * 0.008
    mpad = max(float(mark_pad or 0.0), 0.0)
    # 含影線半寬；略放寬避免低估
    i0 = max(0, int(np.floor(x0 - 0.42)))
    i1 = min(int(n) - 1, int(np.ceil(x1 + 0.42)))
    hits = 0
    for i in range(i0, i1 + 1):
        hk = float(highs[i]) if i < len(highs) and np.isfinite(highs[i]) else np.nan
        lk = float(lows[i]) if i < len(lows) and np.isfinite(lows[i]) else np.nan
        if not (np.isfinite(hk) and np.isfinite(lk)):
            continue
        if lk - pad_y - mpad <= y1 and hk + pad_y + mpad >= y0:
            hits += 1
    return int(hits)


def _channel_artist_pixel_hits(
    ax,
    artist,
    *,
    n: int,
    highs: np.ndarray,
    lows: np.ndarray,
    renderer=None,
    bar_half: float = 0.38,
) -> Tuple[List[int], Tuple[float, float, float, float]]:
    """畫完後：artist 像素 bbox ∩ 每根 K high–low（同座標轉換）。

    回傳 (hit 索引列, display bbox x0,y0,x1,y1)。
    """
    fig = ax.figure
    if renderer is None:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
    bb = artist.get_window_extent(renderer=renderer)
    # bbox 內邊略外擴 1px，對齊肉眼「壓到影線」
    x0 = float(bb.x0) - 1.0
    x1 = float(bb.x1) + 1.0
    y0 = float(bb.y0) - 1.0
    y1 = float(bb.y1) + 1.0
    hits: List[int] = []
    half = float(bar_half)
    for i in range(int(n)):
        hk = float(highs[i]) if i < len(highs) and np.isfinite(highs[i]) else np.nan
        lk = float(lows[i]) if i < len(lows) and np.isfinite(lows[i]) else np.nan
        if not (np.isfinite(hk) and np.isfinite(lk) and hk >= lk):
            continue
        p_lo = ax.transData.transform((float(i) - half, float(lk)))
        p_hi = ax.transData.transform((float(i) + half, float(hk)))
        kx0, kx1 = min(float(p_lo[0]), float(p_hi[0])), max(
            float(p_lo[0]), float(p_hi[0])
        )
        ky0, ky1 = min(float(p_lo[1]), float(p_hi[1])), max(
            float(p_lo[1]), float(p_hi[1])
        )
        if kx1 < x0 or kx0 > x1 or ky1 < y0 or ky0 > y1:
            continue
        hits.append(int(i))
    return hits, (x0, y0, x1, y1)


def _probe_channel_label_dxdy(
    ax,
    text: str,
    *,
    n: int,
    ymin: float,
    ymax: float,
    fs: float,
    color: str = "#6a1b9a",
) -> Tuple[float, float]:
    """實畫隱形標→window_extent→資料座標 dx/dy（比字寬粗估準）。"""
    y_mid = 0.5 * (float(ymin) + float(ymax))
    x_mid = max(float(n) * 0.5, 1.0)
    art = ax.text(
        x_mid,
        y_mid,
        str(text),
        ha="center",
        va="center",
        fontproperties=_fp(fs, "bold"),
        color=color,
        alpha=0.0,
        zorder=0,
        clip_on=False,
        linespacing=1.12,
        bbox=dict(
            boxstyle="round,pad=0.22",
            facecolor="#ffffff",
            edgecolor=color,
            linewidth=0.9,
            alpha=0.0,
        ),
    )
    try:
        ax.figure.canvas.draw()
        renderer = ax.figure.canvas.get_renderer()
        bb = art.get_window_extent(renderer=renderer)
        inv = ax.transData.inverted()
        (dx0, dy0) = inv.transform((bb.x0, bb.y0))
        (dx1, dy1) = inv.transform((bb.x1, bb.y1))
        dx = abs(float(dx1) - float(dx0))
        dy = abs(float(dy1) - float(dy0))
        # 略放大當碰撞盒，避免低估
        return max(dx * 1.12, 1.0), max(dy * 1.12, 1.0)
    except Exception:
        return _channel_text_box_data(
            ax, text, n=int(n), ymin=float(ymin), ymax=float(ymax), fs=float(fs)
        )
    finally:
        try:
            art.remove()
        except Exception:
            pass


def draw_channel_label_hits_overlay(
    ax,
    *,
    n: int,
    highs: np.ndarray,
    lows: np.ndarray,
    label_artists: Sequence[Any],
    renderer=None,
) -> List[Dict[str, Any]]:
    """半透明紅框＝標籤像素 bbox；紅豎線＝被算到的 K。回傳 hit 報告。"""
    from matplotlib.patches import Rectangle

    if renderer is None:
        ax.figure.canvas.draw()
        renderer = ax.figure.canvas.get_renderer()
    report: List[Dict[str, Any]] = []
    inv = ax.transData.inverted()
    for art in label_artists:
        if art is None:
            continue
        try:
            txt = str(art.get_text() or "")
        except Exception:
            txt = ""
        hits, (px0, py0, px1, py1) = _channel_artist_pixel_hits(
            ax, art, n=n, highs=highs, lows=lows, renderer=renderer
        )
        (dx0, dy0) = inv.transform((px0, py0))
        (dx1, dy1) = inv.transform((px1, py1))
        x0, x1 = min(float(dx0), float(dx1)), max(float(dx0), float(dx1))
        y0, y1 = min(float(dy0), float(dy1)), max(float(dy0), float(dy1))
        ax.add_patch(
            Rectangle(
                (x0, y0),
                x1 - x0,
                y1 - y0,
                fill=True,
                facecolor="#ff1744",
                edgecolor="#d50000",
                alpha=0.28,
                linewidth=1.4,
                zorder=20,
                clip_on=False,
            )
        )
        for i in hits:
            ax.plot(
                [float(i), float(i)],
                [float(lows[i]), float(highs[i])],
                color="#ff1744",
                lw=2.2,
                alpha=0.85,
                zorder=21,
                solid_capstyle="round",
            )
        report.append(
            {
                "text": txt,
                "k_hits": int(len(hits)),
                "hit_bars": list(hits),
                "data_box": (x0, y0, x1, y1),
            }
        )
    return report


def _channel_box_k_depth(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    *,
    n: int,
    highs: np.ndarray,
    lows: np.ndarray,
    span: float = 1.0,
) -> float:
    """盒與 K 重疊深度總和／軸高：擦邊影線遠小於貫穿實體。"""
    pad_y = max(float(span), 1.0) * 0.004
    i0 = max(0, int(np.floor(x0 - 0.15)))
    i1 = min(int(n) - 1, int(np.ceil(x1 + 0.15)))
    depth = 0.0
    for i in range(i0, i1 + 1):
        hk = float(highs[i]) if i < len(highs) and np.isfinite(highs[i]) else np.nan
        lk = float(lows[i]) if i < len(lows) and np.isfinite(lows[i]) else np.nan
        if not (np.isfinite(hk) and np.isfinite(lk)):
            continue
        ov0 = max(float(y0), lk - pad_y)
        ov1 = min(float(y1), hk + pad_y)
        if ov1 > ov0:
            depth += (ov1 - ov0) / max(float(span), 1.0)
    return float(depth)


def _channel_box_blocked(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    *,
    n: int,
    ymin: float,
    ymax: float,
    highs: np.ndarray,
    lows: np.ndarray,
    mas: List[np.ndarray],
    placed: List[Tuple[float, float, float, float]],
    mark_pad: float = 0.0,
    ignore_ma: bool = False,
    ignore_k: bool = False,
) -> bool:
    """盒碰到 K、導航箭帶、左上／左下壓撐標、已放軌標＝堵住。

    mark_pad：K 高低再外擴（導航箭／殘影約在 high+gap～low−gap），不准軌標壓箭頭。
    ignore_ma：線旁空窗候選可略過均線硬擋（均線常穿過空窗；仍避 K／箭）。
    ignore_k：只擋界／已放標；K 成本改由 _channel_box_k_hits 評分（準許比遮擋）。
    """
    span = max(float(ymax) - float(ymin), 1.0)
    x_lo, x_hi = -0.8, float(n) - 0.2
    if x0 < x_lo + 0.15 or x1 > x_hi - 0.05:
        return True
    if y0 < float(ymin) + span * 0.012 or y1 > float(ymax) - span * 0.012:
        return True
    xf0 = (x0 - x_lo) / max(x_hi - x_lo, 1e-6)
    yf0 = (y0 - float(ymin)) / span
    yf1 = (y1 - float(ymin)) / span
    # 大量區壓／撐標在左上、左下
    if xf0 < 0.30 and yf1 > 0.84:
        return True
    if xf0 < 0.30 and yf0 < 0.16:
        return True
    pad_y = span * 0.006
    mpad = max(float(mark_pad or 0.0), 0.0)
    i0 = max(0, int(np.floor(x0 - 0.35)))
    i1 = min(int(n) - 1, int(np.ceil(x1 + 0.35)))
    for i in range(i0, i1 + 1):
        if not ignore_k:
            hk = float(highs[i]) if i < len(highs) and np.isfinite(highs[i]) else np.nan
            lk = float(lows[i]) if i < len(lows) and np.isfinite(lows[i]) else np.nan
            if np.isfinite(hk) and np.isfinite(lk):
                # 外擴含導航上下箭／殘影佔位
                if lk - pad_y - mpad <= y1 and hk + pad_y + mpad >= y0:
                    return True
        if not ignore_ma:
            for arr in mas:
                if i >= len(arr):
                    continue
                v = float(arr[i]) if np.isfinite(arr[i]) else np.nan
                if np.isfinite(v) and v > 0 and (y0 - pad_y) <= v <= (y1 + pad_y):
                    return True
    # 已放標互壓：留小墊，避免兩標「貼邊」仍被評測判重疊
    pad_x_lab = 0.25
    pad_y_lab = max(span * 0.005, 0.08)
    for ox0, ox1, oy0, oy1 in placed:
        if not (
            x1 + pad_x_lab < ox0
            or ox1 + pad_x_lab < x0
            or y1 + pad_y_lab < oy0
            or oy1 + pad_y_lab < y0
        ):
            return True
    return False


def _blank_for_channel_label(
    *,
    text: str,
    seg,
    y_now: float,
    outside: int,
    n: int,
    ymin: float,
    ymax: float,
    dx: float,
    dy: float,
    highs: np.ndarray,
    lows: np.ndarray,
    mas: List[np.ndarray],
    placed: List[Tuple[float, float, float, float]],
    near_last: bool = False,
    mark_pad: float = 0.0,
    pair_x: Optional[float] = None,
) -> Tuple[float, float]:
    """沿所屬軌線掃「線旁空窗」；不准壓 K、均線、導航箭。

    優先：軌與 K／箭帶之間的空隙（下軌常在軌上方空窗，如上拉離軌後的 2300–2400 帶）。
    near_last：上升軌文字右緣貼最後幾根。
    mark_pad：避開導航箭／殘影帶（與 _channel_box_blocked 同源）。
    pair_x／已放軌標：成對標必須同垂直帶（水平靠近），不准一左一右拉開半張圖。
    """
    span = max(float(ymax) - float(ymin), 1.0)
    x_hi = float(n) - 0.2
    gap = max(span * 0.008, dy * 0.08)
    mpad = max(float(mark_pad or 0.0), 0.0)
    pref = int(outside) or 1
    # 硬驗收：標心／盒邊須落在軌上（線旁 ≤ 半個字高）；不准浮空／只認 y_now
    rail_soft = max(dy * 0.50, span * 0.012)
    # 箭尖縫：碰撞／硬擋用接近真箭高；口袋底邊用較小 tip，免得把線旁空窗吃光
    tip_arrow = max(mpad * 0.70, dy * 0.30, span * 0.018) if mpad > 0 else 0.0
    tip = max(span * 0.010, dy * 0.08, min(max(tip_arrow * 0.45, span * 0.012), span * 0.020))
    y_vis_lo = float(ymin) + max(dy * 0.55, span * 0.02)
    y_vis_hi = float(ymax) - max(dy * 0.55, span * 0.02)
    # 通道樞紐（紫點／接觸）：空窗優先貼近，不准甩遠端或蓋密峰上
    pivot_xs: List[float] = []
    try:
        (px1, _py1, _pa), (px2, _py2, _pb) = seg  # type: ignore[misc]
        pivot_xs = sorted({float(px1), float(px2)})
    except Exception:
        pivot_xs = []
    pivot_lo = min(pivot_xs) if pivot_xs else float(n) * 0.75
    pivot_hi = max(pivot_xs) if pivot_xs else float(n) * 0.85
    # 樞紐落在圖中右才啟用紅圈帶偏好（左緣假樞／水平測試段不強制）
    pivot_band_ok = bool(pivot_xs) and (
        float(n) * 0.28 <= float(pivot_lo) <= float(n) * 0.96
    )
    # 左界＝第一樞接觸前空窗（紅圈）；再左＝通道未成形，硬拒
    x_contact_floor = (
        float(pivot_lo) - 22.0 if pivot_band_ok else float(dx) * 0.5
    )
    # 成對標同帶：已放軌標中心或呼叫端 pair_x
    _pair_mids: List[float] = []
    if pair_x is not None and np.isfinite(float(pair_x)):
        _pair_mids.append(float(pair_x))
    for a, b, _c, _d in placed:
        _pair_mids.append(0.5 * (float(a) + float(b)))
    # 同帶寬：寧窄勿拉開（美感 parallel_pair／alignment）；半圖拉開＝硬拒
    same_band_max = min(max(float(dx) * 0.95, 5.5), 8.0)

    def _pair_anchor() -> Optional[float]:
        return float(_pair_mids[0]) if _pair_mids else None

    def _in_same_band(cx: float) -> bool:
        if not _pair_mids:
            return True
        return all(abs(float(cx) - float(m)) <= same_band_max for m in _pair_mids)

    def _same_band_bonus(cx: float) -> float:
        anc = _pair_anchor()
        if anc is None:
            return 0.0
        d = abs(float(cx) - float(anc))
        return max(0.0, 8.0 - d * 0.65)

    def _rail_visible(cx: float) -> Tuple[bool, float]:
        """該 x 的軌位必須落在可見軸內。

        優先樞紐空窗帶；避 K 可略離 y_now，不准飛出 ylim。
        """
        if pivot_band_ok and float(cx) < float(x_contact_floor) - 0.25:
            return False, float(_channel_seg_y(seg, cx, y_now))
        y_line = float(_channel_seg_y(seg, cx, y_now))
        if not (y_vis_lo <= y_line <= y_vis_hi):
            return False, y_line
        # 樞紐鄰域／左接觸前空窗：下降軌左側常明顯高於 rail_now，放寬
        near_piv = min((abs(cx - p) for p in pivot_xs), default=99.0)
        in_pivot_windows = bool(pivot_xs) and (
            float(x_contact_floor) <= cx <= float(pivot_hi) + 2.0
        )
        if in_pivot_windows:
            lim = span * 0.55
        elif near_piv <= 28.0:
            lim = span * 0.35
        else:
            lim = span * 0.28
        if abs(y_line - float(y_now)) > lim:
            return False, y_line
        return True, y_line

    # 起錨：樞紐左側空窗／兩樞之間（對齊使用者紅圈），再掃全段
    x_anchor = min(float(n) - 1.0, x_hi - dx * 0.55)
    if not near_last:
        found_anchor = False
        best_anchor: Optional[Tuple[float, float, float]] = None  # score, cx, yl
        seed_xs: List[float] = []
        if pivot_band_ok:
            for back in (6, 10, 14, 18, 22, 4):
                seed_xs.append(float(pivot_lo) - float(back))
            if pivot_hi > pivot_lo + 2:
                seed_xs.append(0.5 * (pivot_lo + pivot_hi))
                seed_xs.append(pivot_lo + 2.0)
                seed_xs.append(pivot_hi - 2.0)
        for xf in (0.88, 0.82, 0.76, 0.70, 0.92, 0.64, 0.94, 0.58):
            seed_xs.append(min(float(n - 1) * xf, x_hi - dx * 0.55))
        # 成對第二標：種子優先貼第一標同帶（不准再往更左拉開）
        _anc0 = _pair_anchor()
        if _anc0 is not None:
            seed_xs = [
                float(_anc0),
                float(_anc0) - 1.5,
                float(_anc0) + 1.5,
                float(_anc0) - 3.0,
                float(_anc0) + 3.0,
                float(_anc0) - 5.0,
                float(_anc0) + 5.0,
            ] + seed_xs
        for cx0 in seed_xs:
            cx0 = min(max(float(cx0), max(dx * 0.5, x_contact_floor)), x_hi - dx * 0.45)
            ok, yl0 = _rail_visible(cx0)
            if not ok:
                continue
            if not _in_same_band(cx0):
                continue
            near_piv = min((abs(cx0 - p) for p in pivot_xs), default=40.0)
            sc = 2.5 - abs(yl0 - float(y_now)) / span
            sc += _same_band_bonus(cx0)
            if pivot_band_ok:
                sc -= near_piv * 0.08
                if float(pivot_lo) - 22.0 <= cx0 <= float(pivot_lo) - 3.0:
                    sc += 1.8
                    # 第一標靠接觸帶中段（兩標之後都貼同帶，不再「留給第二標更左」）
                    if _anc0 is None and float(pivot_lo) - 14.0 <= cx0 <= float(pivot_lo) - 5.0:
                        sc += 1.6
                if (
                    pivot_hi > pivot_lo
                    and float(pivot_lo) + 1.0 <= cx0 <= float(pivot_hi) - 1.0
                ):
                    sc += 1.4
            if best_anchor is None or sc > best_anchor[0]:
                best_anchor = (sc, cx0, yl0)
        if best_anchor is not None:
            x_anchor = float(best_anchor[1])
            found_anchor = True
        if not found_anchor:
            x_anchor = min(float(n) - 1.2, x_hi - dx * 0.45)
            if pivot_band_ok:
                x_anchor = min(float(pivot_lo) - 8.0, x_anchor)
            if _anc0 is not None:
                x_anchor = float(_anc0)
            x_anchor = max(dx * 0.5, float(x_contact_floor), float(x_anchor))
    # score, cx, cy, k_hits —— 主序 k_hits；≥1 硬拒
    best: Optional[Tuple[float, float, float, int]] = None
    def _window_hl(cx: float, *, half: Optional[float] = None) -> Tuple[float, float]:
        # 空窗偵測：用標寬半幅掃 K，跟真盒遮擋對齊（窄 ±1.6 會漏估長串 K）
        hw = max(dx / 2.0 + 0.45, 1.6) if half is None else max(float(half), 0.6)
        i0 = max(0, int(np.floor(cx - hw)))
        i1 = min(int(n) - 1, int(np.ceil(cx + hw)))
        loc_hi = -1e18
        loc_lo = 1e18
        for i in range(i0, i1 + 1):
            hk = float(highs[i]) if i < len(highs) and np.isfinite(highs[i]) else np.nan
            lk = float(lows[i]) if i < len(lows) and np.isfinite(lows[i]) else np.nan
            if np.isfinite(hk):
                loc_hi = max(loc_hi, hk)
            if np.isfinite(lk):
                loc_lo = min(loc_lo, lk)
        if loc_hi < -1e17:
            loc_hi = float(y_now)
        if loc_lo > 1e17:
            loc_lo = float(y_now)
        return loc_hi, loc_lo

    def _consider(
        cx: float,
        cy: float,
        score: float,
        *,
        pad: Optional[float] = None,
        ignore_ma: bool = False,
    ) -> None:
        nonlocal best
        # 軟約束：只認該 x 的軌位（下降軌左右高度差大，不准拿 y_now 開後門）
        if pivot_band_ok and float(cx) < float(x_contact_floor) - 0.25:
            return
        ok_vis, y_line = _rail_visible(cx)
        if not ok_vis:
            return
        if abs(cy - y_line) > rail_soft:
            return
        if not (y_vis_lo <= float(cy) <= y_vis_hi):
            return
        # 硬擋買點▲：下軌標底不准伸進 K低−箭高（平行撐不准壓紅／綠▲）
        if tip_arrow > 0 and pref < 0:
            _lh, loc_lo_a = _window_hl(cx)
            if (cy + dy / 2.0) > (loc_lo_a - tip_arrow):
                return
        use_pad = mpad if pad is None else max(float(pad), 0.0)
        box = (cx - dx / 2.0, cx + dx / 2.0, cy - dy / 2.0, cy + dy / 2.0)
        # 成對軌標：必須同垂直帶（水平靠近）；拉開＝不合格
        if not _in_same_band(cx):
            return
        score += _same_band_bonus(cx)
        # 硬擋只留界／已放標盒（2D 互壓）／均線；K 用 hits 主序
        if _channel_box_blocked(
            *box,
            n=n,
            ymin=ymin,
            ymax=ymax,
            highs=highs,
            lows=lows,
            mas=mas,
            placed=placed,
            mark_pad=use_pad,
            ignore_ma=ignore_ma,
            ignore_k=True,
        ):
            return
        k_hits = _channel_box_k_hits(
            *box,
            n=n,
            highs=highs,
            lows=lows,
            mark_pad=0.0,
            span=span,
        )
        # 硬：蓋 ≥1 根實體／影線＝不合格候選（像素驗收同規）
        if k_hits >= 1:
            return
        k_depth = _channel_box_k_depth(
            *box, n=n, highs=highs, lows=lows, span=span
        )
        arrow_hits = 0
        if use_pad > 0:
            arrow_hits = _channel_box_k_hits(
                *box,
                n=n,
                highs=highs,
                lows=lows,
                mark_pad=use_pad,
                span=span,
            )
            if arrow_hits >= 1:
                # 箭帶也當不合格（導航尖）
                return
        score -= float(k_depth) * 10.0
        score += 16.0  # 已通過 0 蓋 K
        loc_hi, loc_lo = _window_hl(cx)
        y0, y1 = float(box[2]), float(box[3])
        # 整盒在 K 外包絡外＝真空白（線旁半格內仍算貼線）
        clear_gap = max(tip * 0.55, span * 0.012, dy * 0.08)
        clear_above = y0 >= loc_hi + clear_gap
        clear_below = y1 <= loc_lo - clear_gap
        if clear_above or clear_below:
            score += 8.0
        else:
            return  # 未離開價區包絡＝不合格
        # 真空不要飄太高（視覺像脫軌）；盒底貼近 loc_hi 上方一小段最佳
        if clear_above:
            float_gap = (y0 - loc_hi) / span
            if float_gap < 0.02:
                score += 1.2
            elif float_gap < 0.08:
                score += 2.2  # 紅圈：軌旁剛離開密峰的空窗
            elif float_gap < 0.14:
                score += 0.6
            else:
                score -= (float_gap - 0.14) * 10.0  # 甩到天際＝差
        # 偏好靠近紫點／接觸空窗（使用者紅圈）；坐上紫點則微罰
        if pivot_band_ok:
            near_piv = min((abs(cx - p) for p in pivot_xs), default=40.0)
            if 3.0 <= near_piv <= 22.0:
                score += 7.5 - near_piv * 0.12
            elif near_piv < 3.0:
                score -= 2.5  # 蓋住紫點本身
            elif near_piv > 32.0:
                score -= min((near_piv - 32.0) * 0.25, 6.0)
            in_left = float(pivot_lo) - 22.0 <= cx <= float(pivot_lo) - 3.0
            in_between = (
                pivot_hi > pivot_lo
                and float(pivot_lo) + 1.0 <= cx <= float(pivot_hi) - 1.0
            )
            # 左接觸前／兩樞間（有真空才加分）；成對第二標只認同帶，不再往更左拉開
            if in_left:
                score += 5.0
                if not _pair_mids:
                    score += min((cx - (float(pivot_lo) - 22.0)) * 0.18, 3.0)
            if in_between:
                score += 4.0  # 有真空的兩樞間＝第二紅圈
            # 甩到第二樞右側／遠端＝對齊紅叉，重罰
            if cx > float(pivot_hi) + 1.5:
                score -= min((cx - float(pivot_hi)) * 0.8, 10.0)
            if cx > float(n) * 0.90:
                score -= 4.0
        # 密 K 柱區振幅
        col_amp = max(loc_hi - loc_lo, 0.0) / span
        if col_amp > 0.08:
            score -= (col_amp - 0.08) * 16.0
        # 貼線分
        dist_h = abs(cy - y_line) / max(dy, 1e-6)
        score -= dist_h * 3.5
        if dist_h <= 0.12:
            score += 1.4
        elif dist_h <= 0.35:
            score += 0.45
        if pref > 0:
            if cy > y_line + dy * 0.08:
                score -= 0.85
            elif cy <= y_line:
                score += 0.30
        else:
            if cy < y_line - dy * 0.08:
                score -= 0.85
            elif cy >= y_line:
                score += 0.30
        # 近端輕罰；樞紐空窗壓過近端
        score -= abs(y_line - float(y_now)) / span * 0.45
        if best is None or score > best[0]:
            best = (score, cx, cy, 0)

    def _stick_offsets() -> Tuple[float, ...]:
        """線心優先；半格內可偏到線旁空白（仍貼線、不准引線）。"""
        # 上軌：略偏下（標在線下空白）；下軌：略偏上（標在線上空白）
        if pref > 0:
            return (0.0, -0.25 * dy, -0.40 * dy, -0.50 * dy, 0.15 * dy)
        return (0.0, 0.25 * dy, 0.40 * dy, 0.50 * dy, -0.15 * dy)

    def _on_rail_candidates(cx: float, y_line: float, base: float) -> None:
        """只評貼線候選（線心／半格內）；碰撞 pad 由大到小。"""
        for off in _stick_offsets():
            cy = float(y_line) + float(off)
            for p in (tip, tip * 0.35, 0.0):
                _consider(
                    cx,
                    cy,
                    base + (1.4 - abs(off) / max(dy, 1e-6)),
                    pad=p,
                    ignore_ma=True,
                )

    def _pocket_candidates(cx: float, y_line: float, loc_hi: float, loc_lo: float) -> None:
        """線旁空窗仍要貼軌：口袋內的 cy 強制夾回半格字高內。"""
        edge = max(gap, span * 0.006, dy * 0.04)
        pockets: List[Tuple[float, float, float]] = []
        if pref < 0:
            top = loc_lo - tip
            bot = y_line + edge * 0.05
            if top > bot + max(dy * 0.15, span * 0.006):
                pockets.append((bot, top, 0.85))
        else:
            top = y_line - edge * 0.05
            bot = loc_hi + tip
            if top > bot + max(dy * 0.15, span * 0.006):
                pockets.append((bot, top, 0.85))
        for p_lo, p_hi, side_bonus in pockets:
            # 只在貼軌帶內取點（不准口袋中段浮空）
            band_lo = max(p_lo, y_line - rail_soft)
            band_hi = min(p_hi, y_line + rail_soft)
            if band_hi <= band_lo + dy * 0.05:
                continue
            for frac, bonus in ((0.15, 0.50), (0.35, 0.35), (0.55, 0.20), (0.75, 0.10)):
                cy = band_lo + (band_hi - band_lo) * frac
                _consider(
                    cx,
                    cy,
                    1.35 + side_bonus + bonus,
                    pad=tip,
                    ignore_ma=True,
                )
                _consider(cx, cy, 1.10 + side_bonus, pad=0.0, ignore_ma=True)
        _on_rail_candidates(cx, y_line, 1.20)

    if near_last:
        # 盒右緣貼最後一根，只准往左挪幾根；垂直挑離最近 K 最近的空白
        last_i = max(int(n) - 1, 0)
        y_ref_hi = float(highs[last_i]) if np.isfinite(highs[last_i]) else float(y_now)
        y_ref_lo = float(lows[last_i]) if np.isfinite(lows[last_i]) else float(y_now)
        best = None
        for shift in (0.0, 0.9, 1.8, 2.8, 4.0):
            x1 = x_hi - 0.08 - shift
            cx = x1 - dx / 2.0
            if x1 < float(n) - 6.0:
                break
            loc_hi, loc_lo = _window_hl(cx)
            hi_w, lo_w = loc_hi, loc_lo
            k_vals = (0.0, 0.45, 0.95, 1.5, 2.2, 3.0) if mpad > 0 else (0.0, 0.45, 0.95, 1.5)
            for k in k_vals:
                for sign in (-1, 1):
                    if sign < 0:
                        cy = lo_w - gap - dy / 2.0 - k * dy * 0.42 - (mpad * 0.35 if mpad else 0.0)
                    else:
                        cy = hi_w + gap + dy / 2.0 + k * dy * 0.42 + (mpad * 0.35 if mpad else 0.0)
                    if y_ref_lo <= cy <= y_ref_hi:
                        dist = 0.0
                    else:
                        dist = min(abs(cy - y_ref_lo), abs(cy - y_ref_hi)) / span
                    _consider(cx, cy, 4.0 - shift * 0.35 - dist * 0.85 - k * 0.2)
            _pocket_candidates(cx, _channel_seg_y(seg, cx, y_now), loc_hi, loc_lo)
        if best is not None:
            return best[1], best[2]
        cy = lo_w - gap - dy / 2.0 - mpad
        return cx, max(float(ymin) + dy / 2.0 + gap, min(cy, float(ymax) - dy / 2.0 - gap))

    # 主掃：整段可見軌；不准提早 break（近端密 K 時必須往左找空窗）
    near_steps = max(int(n * 1.2), 96) if mpad > 0 else max(int(n), 56)
    step_dx = max(dx * 0.10, 0.55)
    for step in range(0, near_steps):
        cx = x_anchor - step * step_dx
        if cx < dx * 0.4:
            break
        ok_vis, y_line = _rail_visible(cx)
        if not ok_vis:
            continue
        near = 1.0 - step / float(near_steps + 8)
        loc_hi, loc_lo = _window_hl(cx)
        _pocket_candidates(cx, y_line, loc_hi, loc_lo)
        _on_rail_candidates(cx, y_line, near)
        # 已找到 0 蓋 K 且貼線夠好 → 可收；否則繼續掃空窗
        if best is not None and best[3] == 0 and best[0] > 8.0 and step >= 12:
            break
    if best is not None and best[3] == 0:
        return best[1], best[2]

    # 放寬：仍只認可見軌＋貼線心；忽略箭硬擋，比最少蓋 K
    saved_tip_arrow = tip_arrow
    tip_arrow = 0.0
    for step in range(0, max(int(n), 40)):
        cx = x_anchor - step * max(dx * 0.12, 0.65)
        ok_vis, y_line = _rail_visible(cx)
        if not ok_vis:
            continue
        _on_rail_candidates(cx, y_line, 0.25 - step * 0.002)
        if best is not None and best[3] == 0:
            tip_arrow = saved_tip_arrow
            return best[1], best[2]
    tip_arrow = saved_tip_arrow
    if best is not None:
        return best[1], best[2]

    # 最後保底：只收 0 蓋 K＋整盒離開價區包絡
    best_fb: Optional[Tuple[float, float, float, float]] = None  # dist, -clear, cx, cy
    for xf in (
        0.94,
        0.90,
        0.86,
        0.82,
        0.78,
        0.74,
        0.70,
        0.66,
        0.62,
        0.58,
        0.54,
        0.50,
        0.45,
        0.40,
    ):
        cx = min(float(n - 1) * xf, x_hi - dx * 0.4)
        ok_vis, y_line = _rail_visible(cx)
        if not ok_vis:
            continue
        for off in _stick_offsets():
            cy = min(max(float(y_line) + float(off), y_vis_lo), y_vis_hi)
            box = (cx - dx / 2.0, cx + dx / 2.0, cy - dy / 2.0, cy + dy / 2.0)
            if not _in_same_band(cx):
                continue
            kh = _channel_box_k_hits(
                *box, n=n, highs=highs, lows=lows, mark_pad=0.0, span=span
            )
            if kh >= 1:
                continue
            # 保底也硬拒互壓（密軌同帶常見）
            if _channel_box_blocked(
                *box,
                n=n,
                ymin=ymin,
                ymax=ymax,
                highs=highs,
                lows=lows,
                mas=mas,
                placed=placed,
                mark_pad=0.0,
                ignore_ma=True,
                ignore_k=True,
            ):
                continue
            loc_hi, loc_lo = _window_hl(cx)
            gap = max(tip * 0.55, span * 0.012, dy * 0.08)
            clear = (box[2] >= loc_hi + gap) or (box[3] <= loc_lo - gap)
            if not clear:
                continue
            dist_now = abs(y_line - float(y_now)) / span
            # 同帶優先：距離錨越近越好
            band_pen = 0.0
            anc = _pair_anchor()
            if anc is not None:
                band_pen = abs(float(cx) - float(anc)) * 0.02
            key = (dist_now + band_pen, float(cx), float(cy))
            if best_fb is None or key[0] < best_fb[0]:
                best_fb = (dist_now + band_pen, float(cx), float(cy), 0.0)
    if best_fb is not None:
        return best_fb[1], best_fb[2]
    # 無真空窗：貼可見軌線心；成對時鎖同帶且不互壓（找不到→NaN 讓呼叫端略過）
    _fb_xs: List[float] = []
    anc = _pair_anchor()
    if anc is not None:
        _fb_xs.extend(
            [
                float(anc),
                float(anc) - 2.0,
                float(anc) + 2.0,
                float(anc) - 4.0,
                float(anc) + 4.0,
            ]
        )
    for xf in (0.90, 0.82, 0.74, 0.66, 0.58, 0.50, 0.94):
        _fb_xs.append(min(float(n - 1) * xf, x_hi - dx * 0.4))
    for cx in _fb_xs:
        cx = min(max(float(cx), dx * 0.4), x_hi - dx * 0.4)
        ok_vis, y_line = _rail_visible(cx)
        if not ok_vis:
            continue
        if not _in_same_band(cx):
            continue
        cy = min(max(float(y_line), y_vis_lo), y_vis_hi)
        box = (cx - dx / 2.0, cx + dx / 2.0, cy - dy / 2.0, cy + dy / 2.0)
        if _channel_box_blocked(
            *box,
            n=n,
            ymin=ymin,
            ymax=ymax,
            highs=highs,
            lows=lows,
            mas=mas,
            placed=placed,
            mark_pad=0.0,
            ignore_ma=True,
            ignore_k=True,
        ):
            continue
        return cx, cy
    # 成對無同帶淨空→回 NaN（像素掃／呼叫端略過，不准硬壓互疊）
    return float("nan"), float("nan")


def paint_vol_zone_parallel_channel(
    ax,
    ch: Dict[str, Any],
    *,
    n: int,
    ymin: float,
    ymax: float,
    labels_outside: bool = False,
    market_style: bool = False,
    highs: Optional[np.ndarray] = None,
    lows: Optional[np.ndarray] = None,
    mas: Optional[List[np.ndarray]] = None,
    paint_rails: bool = True,
    paint_labels: bool = True,
    avoid_nav_marks: bool = False,
) -> List[Tuple[float, float, float, float]]:
    """在大量區 K 上畫兩條平行軌＋軌標。不是買訊、不數 5／9。

    預設／產品：labels_outside=False＝滿版底＋沿線智能定位（擋最少）；
    不准為塞標收窄 GridSpec／加寬黑邊／改 figsize。
    market_style：大盤加粗軌＋錨點日期標；個股滿版仍用結構圖細虛線色。
    avoid_nav_marks：標位避開導航箭／殘影帶（呼叫端宜在疊導航之後再 paint_labels）。
    paint_rails／paint_labels：可拆成先畫線、導航後再掛標。
    labels_outside=True 僅舊備援（軸外 1.085）；新呼叫端不准再開。
    回傳已放標盒 (x0, x1, y0, y1)，給均線短標互讓。
    """
    placed: List[Tuple[float, float, float, float]] = []
    if not ch or ax is None:
        return placed
    from matplotlib.transforms import blended_transform_factory

    from biaoke_chart import _CHANNEL_RAIL_DASH, _paint_parallel_channel

    seam = float(max(n - 1, 0))
    # 軸外標才加右緣空；滿寬不准把 xlim 再撐開把 K 擠瘦
    market_rails = bool(market_style)
    if labels_outside:
        x0, x1 = ax.get_xlim()
        ax.set_xlim(float(x0), max(float(x1), float(n) + 1.35))
        rail_hi = float(n) + 0.35
    else:
        rail_hi = float(n) - 0.35
    kind0 = str(ch.get("kind") or "")
    # 大盤話筒縮圖要看得出兩條平行虛線：加粗、深色、白邊。個股滿版跟結構圖同一細虛線常數。
    rail_kw: Dict[str, Any] = {}
    if market_rails:
        rail_kw = dict(
            rail_lw=3.2,
            rail_dash=_CHANNEL_RAIL_DASH,
            rail_halo=2.3,
            rail_color="#0d47a1" if kind0 == "asc" else "#4a148c",
        )
    if paint_rails:
        _paint_parallel_channel(
            ax,
            ch,
            seam=seam,
            x_lo=-0.05,
            x_hi=rail_hi,
            y_lo=float(ymin),
            y_hi=float(ymax),
            n=int(n),
            **rail_kw,
        )
    if not paint_labels:
        return placed
    # 右緣價標：上升軌／平行壓 或 下降壓／平行撐（跟結構圖用語同一套）
    name_u = str(ch.get("name_u") or "上軌")
    name_l = str(ch.get("name_l") or "下軌")
    rail = float(ch.get("rail_now") or 0)
    base = float(ch.get("base_now") or 0)
    kind = str(ch.get("kind") or "")
    if market_rails:
        color = "#0d47a1" if kind == "asc" else "#4a148c"
        label_fs = 12.5
    else:
        color = "#1565c0" if kind == "asc" else "#6a1b9a"
        if not bool(ch.get("alive")):
            color = "#90a4ae"
        label_fs = 9.2
    # 導航疊完後 ylim 會再外擴；標位用軸上真實範圍
    if avoid_nav_marks and ax is not None:
        try:
            y0_ax, y1_ax = ax.get_ylim()
            if np.isfinite(y0_ax) and np.isfinite(y1_ax) and y1_ax > y0_ax:
                ymin = float(y0_ax)
                ymax = float(y1_ax)
        except Exception:
            pass
    y_span = max(float(ymax) - float(ymin), 1.0)
    # mark_pad 跟「柱高低幅」走（對齊導航 arrow_h+gap≈0.082），不准用整幅 ylim 灌太大
    # 否則軌旁空窗（紅標那種）會被假性塞滿、標被趕到軌下壓買點▲
    if avoid_nav_marks:
        try:
            c_hi = float(np.nanmax(highs)) if highs is not None and len(highs) else 0.0
            c_lo = float(np.nanmin(lows)) if lows is not None and len(lows) else 0.0
            candle_span = max(c_hi - c_lo, y_span * 0.35, 1.0)
        except Exception:
            candle_span = y_span
        mark_pad = float(candle_span) * 0.10
    else:
        mark_pad = 0.0
    # (顯示Y, 標名, 真價)。先放下軌再上軌——下軌真空窗常在左上，不准被上標先佔死
    items: List[Tuple[float, str, float]] = []
    for y, lab in ((base, name_l), (rail, name_u)):
        if y > 0:
            items.append((float(y), str(lab), float(y)))
    if len(items) == 2 and abs(items[0][0] - items[1][0]) < y_span * 0.045:
        mid = (items[0][0] + items[1][0]) / 2.0
        gap = y_span * 0.028
        # 保持下／上順序
        lo_it = items[0] if items[0][1] == name_l else items[1]
        hi_it = items[1] if items[0][1] == name_l else items[0]
        items = [
            (mid - gap, lo_it[1], lo_it[2]),
            (mid + gap, hi_it[1], hi_it[2]),
        ]
    # 樞紐左側空窗常略高於原 ymax：抬到「兩標錯開後更左接觸帶」夠用
    try:
        top_need = float(ymax)
        for _seg in (ch.get("lower"), ch.get("upper")):
            if not _seg:
                continue
            try:
                (qx1, _a, _b), (qx2, _c, _d) = _seg
                p0 = min(float(qx1), float(qx2))
            except Exception:
                p0 = float(n) * 0.78
            for back in (6.0, 10.0, 14.0, 18.0, 22.0):
                yl = float(
                    _channel_seg_y(
                        _seg, p0 - back, float(base or rail or 0)
                    )
                )
                top_need = max(top_need, yl + y_span * 0.055)
        # 抬到紅圈接觸帶左界（pivot−22）軌位可見；不准再往未成形更左抬
        top_cap = float(ymax) + y_span * 0.28
        top_need = min(top_need, top_cap)
        if top_need > float(ymax) + 1.0:
            ax.set_ylim(float(ymin), float(top_need))
            ymax = float(top_need)
            y_span = max(float(ymax) - float(ymin), 1.0)
    except Exception:
        pass
    # 軸外右溝：X＝axes 分數、Y＝價；clip_on=False 才能畫進 GridSpec 預留溝。
    # 滿版改找鄰近空白（資料座標），不准固定貼在最右 K 上、不准收窄底版。
    trans = blended_transform_factory(ax.transAxes, ax.transData)
    hi_arr = np.asarray(highs if highs is not None else [], dtype=float)
    lo_arr = np.asarray(lows if lows is not None else [], dtype=float)
    ma_arrs = [np.asarray(a, dtype=float) for a in (mas or []) if a is not None]
    use_blank = (
        not labels_outside
        and hi_arr.size >= int(n)
        and lo_arr.size >= int(n)
    )
    label_artists: List[Any] = []
    for y_disp, lab, y_px in items:
        if market_rails:
            shown = _market_channel_anchor_caption(
                ch, upper=(lab == str(ch.get("name_u") or ""))
            )
        else:
            shown = f"{lab} {_fmt_price(y_px)}"
        if not use_blank:
            y_draw = min(
                max(float(y_disp), float(ymin) + y_span * 0.02),
                float(ymax) - y_span * 0.02,
            )
            ax.text(
                1.085,
                y_draw,
                shown,
                transform=trans,
                ha="left",
                va="center",
                fontproperties=_fp(7.6, "bold"),
                color=color,
                zorder=12,
                clip_on=False,
                bbox=dict(
                    boxstyle="round,pad=0.14",
                    facecolor="#ffffff",
                    edgecolor=color,
                    linewidth=0.75,
                    alpha=0.96,
                ),
            )
            continue
        if lab == str(ch.get("name_u") or ""):
            seg = ch.get("upper")
            outside = 1
        else:
            seg = ch.get("lower")
            outside = -1
        # 先探真 bbox 尺寸，再口袋；畫完後像素驗收，撞 K 就重試／強制掃真空窗
        dx, dy = _probe_channel_label_dxdy(
            ax,
            shown,
            n=int(n),
            ymin=float(ymin),
            ymax=float(ymax),
            fs=label_fs,
            color=color,
        )
        art = None
        cx = cy = 0.0
        box_kw = dict(
            boxstyle="round,pad=0.22",
            facecolor="#ffffff",
            edgecolor=color,
            linewidth=1.35 if market_rails else 0.9,
            alpha=0.97,
        )

        def _place_at(x: float, y: float):
            nonlocal art
            if art is not None:
                try:
                    art.remove()
                except Exception:
                    pass
            art = ax.text(
                float(x),
                float(y),
                shown,
                ha="center",
                va="center",
                fontproperties=_fp(label_fs, "bold"),
                color=color,
                zorder=12,
                clip_on=True,
                linespacing=1.12,
                bbox=box_kw,
            )
            return art

        def _pixel_hits_of(artist) -> List[int]:
            try:
                ax.figure.canvas.draw()
                renderer = ax.figure.canvas.get_renderer()
                hits, _bb = _channel_artist_pixel_hits(
                    ax,
                    artist,
                    n=int(n),
                    highs=hi_arr,
                    lows=lo_arr,
                    renderer=renderer,
                )
                return list(hits)
            except Exception:
                return []

        ok = False
        # 成對同帶：已放標中心當 pair_x（2026-10-26：不准再錯開 x）
        _pair_x: Optional[float] = None
        if placed:
            _pair_x = 0.5 * (float(placed[0][0]) + float(placed[0][1]))
        _same_band_max = min(max(float(dx) * 0.95, 5.5), 8.0)
        def _overlaps_placed(cx0: float, cy0: float) -> bool:
            box0 = (
                float(cx0) - dx / 2.0,
                float(cx0) + dx / 2.0,
                float(cy0) - dy / 2.0,
                float(cy0) + dy / 2.0,
            )
            return bool(
                _channel_box_blocked(
                    *box0,
                    n=int(n),
                    ymin=float(ymin),
                    ymax=float(ymax),
                    highs=hi_arr,
                    lows=lo_arr,
                    mas=ma_arrs,
                    placed=placed,
                    mark_pad=0.0,
                    ignore_ma=True,
                    ignore_k=True,
                )
            )

        for _try in range(2):
            cx, cy = _blank_for_channel_label(
                text=shown,
                seg=seg,
                y_now=float(y_px),
                outside=outside,
                n=int(n),
                ymin=float(ymin),
                ymax=float(ymax),
                dx=dx,
                dy=dy,
                highs=hi_arr,
                lows=lo_arr,
                mas=ma_arrs,
                placed=placed,
                near_last=bool(market_rails and "上升軌" in shown),
                mark_pad=mark_pad,
                pair_x=_pair_x,
            )
            if not (np.isfinite(float(cx)) and np.isfinite(float(cy))):
                break
            # 拉開同帶＝失敗，進像素掃；靠近＝合格
            far_x = bool(
                _pair_x is not None
                and abs(float(cx) - float(_pair_x)) > _same_band_max
            )
            if _overlaps_placed(cx, cy):
                break
            _place_at(cx, cy)
            hits = _pixel_hits_of(art)
            if not hits and not far_x:
                ok = True
                placed.append(
                    (
                        float(cx) - dx / 2.0,
                        float(cx) + dx / 2.0,
                        float(cy) - dy / 2.0,
                        float(cy) + dy / 2.0,
                    )
                )
                break
            break
        if not ok:
            # 強制沿可見軌像素掃：只收 k_hits==0；成對則鎖同帶
            span = max(float(ymax) - float(ymin), 1.0)
            rail_soft = max(dy * 0.50, span * 0.012)
            best_pix: Optional[Tuple[float, float, float]] = None
            try:
                (sx1, _a, _b), (sx2, _c, _d) = seg  # type: ignore[misc]
                p_lo, p_hi = min(float(sx1), float(sx2)), max(float(sx1), float(sx2))
            except Exception:
                p_lo, p_hi = float(n) * 0.75, float(n) * 0.85
            scan_floor = float(p_lo) - 22.0
            scan_xs: List[float] = []
            if _pair_x is not None:
                for dlt in (0.0, -1.5, 1.5, -3.0, 3.0, -5.0, 5.0, -7.0, 7.0):
                    scan_xs.append(float(_pair_x) + float(dlt))
            scan_xs += [p_lo - b for b in (6, 10, 14, 18, 22, 4)]
            if p_hi > p_lo + 2:
                scan_xs += [p_lo + 2, 0.5 * (p_lo + p_hi), p_hi - 2]
            scan_xs += list(np.linspace(0.88, 0.45, 28) * float(n - 1))
            for tx in scan_xs:
                tx = min(
                    max(float(tx), max(dx * 0.5, scan_floor)),
                    float(n) - 0.4 - dx * 0.5,
                )
                if _pair_x is not None and abs(tx - float(_pair_x)) > _same_band_max:
                    continue
                y_line = float(_channel_seg_y(seg, tx, float(y_px)))
                if not (float(ymin) + dy * 0.55 <= y_line <= float(ymax) - dy * 0.55):
                    continue
                if abs(y_line - float(y_px)) > span * 0.36:
                    continue
                for off in (
                    0.0,
                    0.35 * dy * (-1 if outside > 0 else 1),
                    0.5 * dy * (-1 if outside > 0 else 1),
                ):
                    ty = y_line + float(off)
                    if abs(ty - y_line) > rail_soft:
                        continue
                    if _overlaps_placed(tx, ty):
                        continue
                    _place_at(tx, ty)
                    hits = _pixel_hits_of(art)
                    if hits:
                        continue
                    near_piv = min(abs(tx - p_lo), abs(tx - p_hi))
                    key = near_piv + abs(y_line - float(y_px)) / span * 8.0
                    if _pair_x is not None:
                        key += abs(tx - float(_pair_x)) * 0.35
                    if p_lo - 22 <= tx <= p_lo - 3:
                        key -= 8.0
                    if p_hi > p_lo and p_lo + 1 <= tx <= p_hi - 1:
                        key -= 6.0
                    if tx > p_hi + 1.5:
                        key += 8.0
                    if best_pix is None or key < best_pix[0]:
                        best_pix = (key, float(tx), float(ty))
            if best_pix is not None:
                cx, cy = best_pix[1], best_pix[2]
                _place_at(cx, cy)
                ok = (not _pixel_hits_of(art)) and (not _overlaps_placed(cx, cy))
                if ok:
                    placed.append(
                        (
                            float(cx) - dx / 2.0,
                            float(cx) + dx / 2.0,
                            float(cy) - dy / 2.0,
                            float(cy) + dy / 2.0,
                        )
                    )
            if not ok and placed and _pair_x is not None:
                # 保底：只在同帶內再掃；找不到就略過（不准遠拋／互壓）
                best_soft: Optional[Tuple[float, float, float]] = None
                for dlt in (0.0, -2.0, 2.0, -4.0, 4.0, -6.0, 6.0):
                    tx = float(_pair_x) + float(dlt)
                    tx = min(max(float(tx), scan_floor), float(n) - 0.4 - dx * 0.5)
                    if abs(tx - float(_pair_x)) > _same_band_max:
                        continue
                    y_line = float(_channel_seg_y(seg, tx, float(y_px)))
                    if not (
                        float(ymin) + dy * 0.55 <= y_line <= float(ymax) - dy * 0.55
                    ):
                        continue
                    for off in (0.0, 0.35 * dy * (-1 if outside > 0 else 1)):
                        ty = y_line + float(off)
                        if abs(ty - y_line) > rail_soft:
                            continue
                        if _overlaps_placed(tx, ty):
                            continue
                        _place_at(tx, ty)
                        if _pixel_hits_of(art):
                            continue
                        key = abs(tx - float(_pair_x))
                        if best_soft is None or key < best_soft[0]:
                            best_soft = (key, float(tx), float(ty))
                if best_soft is not None:
                    cx, cy = best_soft[1], best_soft[2]
                    _place_at(cx, cy)
                    ok = (not _pixel_hits_of(art)) and (not _overlaps_placed(cx, cy))
                    if ok:
                        placed.append(
                            (
                                float(cx) - dx / 2.0,
                                float(cx) + dx / 2.0,
                                float(cy) - dy / 2.0,
                                float(cy) + dy / 2.0,
                            )
                        )
        if art is not None and ok:
            # 裁切閘：clip_on 把字切半＝不合格；先關 clip 用圖邊距，仍出 figure→略過
            try:
                ax.figure.canvas.draw()
                ren = ax.figure.canvas.get_renderer()
                bb = art.get_window_extent(renderer=ren)
                abb = ax.get_window_extent(renderer=ren)
                clipped_ax = (
                    bb.x0 < abb.x0 - 1
                    or bb.x1 > abb.x1 + 1
                    or bb.y0 < abb.y0 - 1
                    or bb.y1 > abb.y1 + 1
                )
                if clipped_ax:
                    art.set_clip_on(False)
                    ax.figure.canvas.draw()
                    ren = ax.figure.canvas.get_renderer()
                    bb2 = art.get_window_extent(renderer=ren)
                    fbb = ax.figure.bbox
                    clipped_fig = (
                        bb2.x0 < fbb.x0 - 1
                        or bb2.x1 > fbb.x1 + 1
                        or bb2.y0 < fbb.y0 - 1
                        or bb2.y1 > fbb.y1 + 1
                    )
                    if clipped_fig or _pixel_hits_of(art):
                        ok = False
                        if placed:
                            placed.pop()
            except Exception:
                pass
        if art is not None and ok:
            label_artists.append(art)
            try:
                from smart_label_metrics import record_smart_label

                record_smart_label(
                    ax,
                    kind="channel_u" if outside > 0 else "channel_l",
                    text=str(shown),
                    x0=float(cx) - dx / 2.0,
                    x1=float(cx) + dx / 2.0,
                    y0=float(cy) - dy / 2.0,
                    y1=float(cy) + dy / 2.0,
                    rail_y=float(cy),
                    clipped=False,
                )
            except Exception:
                pass
            try:
                print(
                    f"channel-label-place {shown!r} x={float(art.get_position()[0]):.2f} "
                    f"y={float(art.get_position()[1]):.2f} ok={ok}",
                    flush=True,
                )
            except Exception:
                pass
        elif art is not None and not ok:
            # 像素仍蓋 K／裁切 → 不准留紅叉位，拿掉
            try:
                art.remove()
            except Exception:
                pass
            art = None
            try:
                print(f"channel-label-drop {shown!r} pixel-hits-or-clip", flush=True)
            except Exception:
                pass
    # 供 debug overlay：暫掛在 axes
    try:
        ax._wayne_channel_label_artists = list(label_artists)  # type: ignore[attr-defined]
        ax._wayne_channel_label_ohlc = (hi_arr, lo_arr, int(n))  # type: ignore[attr-defined]
    except Exception:
        pass
    return placed


def _paint_key_zone_smart_tags(
    ax,
    *,
    hi: float,
    lo: float,
    highs: np.ndarray,
    lows: np.ndarray,
    mas: Optional[Sequence[np.ndarray]],
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    occupied: Optional[List[Tuple[float, float, float, float]]] = None,
) -> List[Tuple[float, float, float, float]]:
    """現任主大量區壓／撐（REQUIRED）：依本圖淨空自適應同側；找不到淨空也必須留標。

    硬規則（2026-10-27）：
    - 膚色帶上下緣「大量區壓／撐」不准因智慧定位略過。
    - 壓在上、撐在下（依價位垂直序）。
    - 每圖自揀左／中／右最佳淨空槽（對 K／量）；成對盡量同 X／同側。
      2233 靠左＝該圖適合，不准寫死永遠釘左。
    """
    from biaoke_next_support import (
        _approx_layer_tag_half_w,
        pick_layer_label_along_line,
    )

    placed: List[Tuple[float, float, float, float]] = list(occupied or [])
    prefer_x: Optional[float] = None
    prefer_ha: Optional[str] = None
    y_span = max(float(ymax) - float(ymin), 1.0)
    # 壓先、撐後：保證垂直序（上壓下撐）
    items: List[Tuple[float, str, str]] = []
    if float(hi or 0) > 0:
        items.append((float(hi), _PRESS, f"大量區壓 {_fmt_price(hi)}"))
    if float(lo or 0) > 0:
        items.append((float(lo), _HOLD, f"大量區撐 {_fmt_price(lo)}"))
    _key_tag_box = dict(
        boxstyle=f"round,pad={float(VOL_ZONE_TAG_PAD):.2f}",
        facecolor="#ffffff",
        linewidth=1.05,
        alpha=1.0,
    )
    x_lo = float(xmin)
    x_hi = float(xmax)
    box_right_limit = x_hi - 0.12
    box_left_limit = x_lo - 0.35
    n_bars = min(len(highs), len(lows))

    def _box_for(cx: float, ha: str, half_w: float, y_px: float) -> Tuple[float, float, float, float]:
        # 半高隨價窗：絕對 floor=10 會讓個股盒蓋滿 K → 同棧誤判失敗、改逐標拆左右
        half_h = max(float(y_span) * 0.022, abs(float(y_px)) * 0.0035, 1.15)
        half_h = min(float(half_h), max(float(y_span) * 0.09, 2.8))
        if ha == "left":
            bx0, bx1 = float(cx), float(cx) + 2.0 * half_w
        elif ha == "right":
            bx0, bx1 = float(cx) - 2.0 * half_w, float(cx)
        else:
            bx0, bx1 = float(cx) - half_w, float(cx) + half_w
        return (bx0, bx1, float(y_px) - half_h, float(y_px) + half_h)

    def _clamp_into_view(
        cx: float, ha: str, box: Tuple[float, float, float, float], half_w: float
    ) -> Tuple[float, str, Tuple[float, float, float, float]]:
        bx0, bx1, by0, by1 = (float(v) for v in box)
        shift = 0.0
        if bx1 > box_right_limit:
            shift = box_right_limit - bx1
        if bx0 + shift < box_left_limit:
            shift = box_left_limit - bx0
        if abs(shift) > 1e-9:
            cx = float(cx) + shift
            bx0 += shift
            bx1 += shift
            box = (bx0, bx1, by0, by1)
        if float(box[1]) > box_right_limit + 0.05:
            cx = min(float(cx), box_right_limit)
            ha = "right"
            box = _box_for(cx, ha, half_w, 0.5 * (by0 + by1))
            if float(box[0]) < box_left_limit:
                cx = box_left_limit + 2.0 * half_w
                box = _box_for(cx, ha, half_w, 0.5 * (by0 + by1))
        if float(box[0]) < box_left_limit - 0.05:
            cx = max(float(cx), box_left_limit)
            ha = "left"
            box = _box_for(cx, ha, half_w, 0.5 * (by0 + by1))
        return float(cx), str(ha), box

    def _k_crush_score(box: Tuple[float, float, float, float]) -> float:
        """與 K 實體／影重疊代價（高＝壓死 K）。"""
        if n_bars <= 0:
            return 0.0
        bx0, bx1, by0, by1 = (float(v) for v in box)
        i0 = max(0, int(math.floor(bx0 - 0.55)))
        i1 = min(n_bars, int(math.ceil(bx1 + 0.55)) + 1)
        score = 0.0
        for i in range(i0, i1):
            try:
                hk = float(highs[i])
                lk = float(lows[i])
            except (TypeError, ValueError, IndexError):
                continue
            if hk <= 0 or lk <= 0:
                continue
            if lk > by1 or hk < by0:
                continue
            mid = 0.5 * (hk + lk)
            if by0 <= mid <= by1:
                score += 3.0
            else:
                score += 1.2
        return score

    def _pair_slot_candidates(half_w: float) -> List[Tuple[float, str]]:
        """左／中／右同棧候選（依本圖幾何，不准寫死只左）。"""
        trials: List[Tuple[float, str]] = []
        # 左帶
        trials.extend(
            [
                (max(box_left_limit + 0.02, x_lo + 0.05), "left"),
                (max(0.35, x_lo + 0.2), "left"),
                (min(max(1.5, float(n_bars) * 0.10), 6.0) if n_bars else 1.5, "left"),
                (min(max(2.5, float(n_bars) * 0.18), 10.0) if n_bars else 2.5, "center"),
            ]
        )
        # 中帶
        if n_bars > 0:
            mid = 0.5 * float(n_bars - 1)
            trials.extend(
                [
                    (mid, "center"),
                    (mid - half_w * 0.4, "center"),
                    (mid + half_w * 0.4, "center"),
                    (float(n_bars) * 0.42, "center"),
                    (float(n_bars) * 0.58, "center"),
                ]
            )
        # 右帶（末日左側）＋右溝（末日右側無 K，6274 左半必碾時用）
        if n_bars > 0:
            last = float(n_bars - 1)
            trials.extend(
                [
                    (min(box_right_limit - 0.05, last - 0.35), "right"),
                    (min(box_right_limit, last + 0.35), "left"),
                    (max(last - half_w * 1.1, float(n_bars) * 0.72), "right"),
                    (float(n_bars) * 0.82, "center"),
                    (last + 0.55, "left"),
                    (last + 1.15, "left"),
                    (min(box_right_limit, last + 2.0), "left"),
                    (min(box_right_limit, float(x_hi) - 0.15), "right"),
                ]
            )
        return trials

    def _best_pair_anchor(half_w: float) -> Optional[Tuple[float, str]]:
        """成對同 X：左／中／右／右溝挑壓死 K 最少的共用錨（不准兩標各搬各的）。"""
        best: Optional[Tuple[float, float, str]] = None
        for cx0, ha0 in _pair_slot_candidates(half_w):
            crush = 0.0
            ok = True
            for y_px, _c, _t in items:
                box = _box_for(float(cx0), str(ha0), half_w, float(y_px))
                cx1, ha1, box1 = _clamp_into_view(float(cx0), str(ha0), box, half_w)
                if abs(float(cx1) - float(cx0)) > 2.5:
                    ok = False
                    break
                crush += _k_crush_score(box1)
            if not ok:
                continue
            edge_bias = 0.0
            if n_bars > 0:
                last = float(n_bars - 1)
                # 右溝無 K：同 crush 不准壓過左／中（自适应槽）；crush 更低時仍會贏
                # （舊 -max(2.5,crush) 重獎會讓左淨空圖也永遠釘右溝 → CI 紅）
                if float(cx0) >= last + 0.2:
                    edge_bias = 0.12
                elif float(cx0) / max(last, 1.0) < 0.04:
                    edge_bias = 0.35
            key = crush + edge_bias
            if best is None or key < best[0]:
                best = (key, float(cx0), str(ha0))
        if best is None:
            return None
        return best[1], best[2]

    def _force_keep_slot(
        y_px: float, text: str, half_w: float
    ) -> Tuple[float, str, Tuple[float, float, float, float]]:
        """REQUIRED 保底：同帶優先；再掃左／中／右；最後釘可視左緣。"""
        candidates: List[Tuple[float, str]] = []
        if prefer_x is not None:
            for dlt in (0.0, -2.0, 2.0, -4.0, 4.0):
                candidates.append((float(prefer_x) + dlt, "center"))
                candidates.append((float(prefer_x) + dlt, "left"))
                candidates.append((float(prefer_x) + dlt, "right"))
        candidates.extend(_pair_slot_candidates(half_w))
        # 依 crush 排序再取第一個不互壓
        scored: List[Tuple[float, float, str, Tuple[float, float, float, float]]] = []
        for cx0, ha0 in candidates:
            cx1, ha1, box1 = _clamp_into_view(
                float(cx0), str(ha0), _box_for(float(cx0), str(ha0), half_w, y_px), half_w
            )
            scored.append((_k_crush_score(box1), float(cx1), str(ha1), box1))
        scored.sort(key=lambda t: t[0])
        for _sc, cx1, ha1, box1 in scored:
            overlaps = False
            for ob in placed:
                try:
                    ox0, ox1, oy0, oy1 = (float(v) for v in ob)
                except (TypeError, ValueError, IndexError):
                    continue
                if box1[1] < ox0 or box1[0] > ox1 or box1[3] < oy0 or box1[2] > oy1:
                    continue
                if abs(0.5 * (oy0 + oy1) - float(y_px)) <= y_span * 0.03:
                    continue
                overlaps = True
                break
            if not overlaps:
                return cx1, ha1, box1
        cx_f = max(box_left_limit, x_lo + 0.05)
        return _clamp_into_view(
            cx_f, "left", _box_for(cx_f, "left", half_w, y_px), half_w
        )

    def _nudge_clear(
        y_rail: float,
        text: str,
        cx: float,
        ha: str,
        half_w: float,
        *,
        prefer_up: bool,
    ) -> Tuple[float, float, str, Tuple[float, float, float, float]]:
        """先垂直微移；仍碾 K 再水平縮離（6274 大綠 K 跨過壓線，只上移仍蓋上影）。"""
        sign = 1.0 if prefer_up else -1.0
        step = max(float(y_span) * 0.012, 1.0)
        best_y = float(y_rail)
        best_cx, best_ha = float(cx), str(ha)
        best_box = _box_for(best_cx, best_ha, half_w, best_y)
        best_c = _k_crush_score(best_box)
        if best_c < 0.5:
            return best_y, best_cx, best_ha, best_box
        for k in range(1, 16):
            y2 = float(y_rail) + sign * step * float(k)
            if y2 > float(ymax) - y_span * 0.02 or y2 < float(ymin) + y_span * 0.02:
                break
            box2 = _box_for(best_cx, best_ha, half_w, y2)
            c2 = _k_crush_score(box2)
            if c2 < best_c:
                best_c, best_y, best_box = c2, y2, box2
            if c2 < 0.5:
                return best_y, best_cx, best_ha, best_box
        # 水平：往左緣縮（ha=left 釘左）或略右，縮短蓋到跨線 K 的寬度
        x_trials: List[Tuple[float, str]] = [
            (max(box_left_limit + 0.02, float(x_lo) + 0.05), "left"),
            (max(0.4, float(best_cx) - half_w * 0.8), "left"),
            (max(0.4, float(best_cx) - half_w * 1.4), "left"),
            (min(box_right_limit - 0.05, float(best_cx) + half_w * 0.6), "right"),
            (min(box_right_limit, float(n_bars) * 0.22 if n_bars else best_cx), "left"),
        ]
        for cx2, ha2 in x_trials:
            for k in range(0, 10):
                y2 = float(y_rail) + sign * step * float(k)
                if y2 > float(ymax) - y_span * 0.02 or y2 < float(ymin) + y_span * 0.02:
                    break
                cx3, ha3, box3 = _clamp_into_view(
                    float(cx2), str(ha2), _box_for(float(cx2), str(ha2), half_w, y2), half_w
                )
                c3 = _k_crush_score(box3)
                if c3 < best_c:
                    best_c, best_y, best_cx, best_ha, best_box = c3, y2, cx3, ha3, box3
                if c3 < 0.5:
                    return best_y, best_cx, best_ha, best_box
        return best_y, best_cx, best_ha, best_box

    def _emit(y_px: float, color: str, text: str, cx: float, ha: str, box) -> None:
        ax.text(
            float(cx),
            float(y_px),
            text,
            ha=str(ha),
            va="center",
            fontproperties=_fp(VOL_ZONE_TAG_PT, "bold"),
            color=color,
            zorder=22,
            clip_on=False,
            bbox={**_key_tag_box, "edgecolor": color},
        )
        placed.append(tuple(float(v) for v in box))  # type: ignore[arg-type]
        try:
            from smart_label_metrics import record_smart_label

            record_smart_label(
                ax,
                kind="key",
                text=str(text),
                x0=float(box[0]),
                x1=float(box[1]),
                y0=float(box[2]),
                y1=float(box[3]),
                rail_y=float(y_px),
                clipped=False,
            )
        except Exception:
            pass

    if not items:
        return placed

    half_w_max = max(
        float(_approx_layer_tag_half_w(t, float(VOL_ZONE_TAG_PT))) for _y, _c, t in items
    )
    pair_anchor = _best_pair_anchor(half_w_max)
    def _y_nudge_only(
        y_rail: float,
        cx: float,
        ha: str,
        half_w: float,
        *,
        prefer_up: bool,
    ) -> Tuple[float, Tuple[float, float, float, float]]:
        """成對鎖錨後只准垂直躲：壓抬過盒內局部最高、撐壓過局部最低（6274 今日 K 穿壓線）。"""
        best_y = float(y_rail)
        best_box = _box_for(float(cx), str(ha), half_w, best_y)
        best_c = _k_crush_score(best_box)
        if best_c < 0.5:
            return best_y, best_box
        # 盒蓋到的 K 索引 → 局部高低
        bx0, bx1 = float(best_box[0]), float(best_box[1])
        i0 = max(0, int(math.floor(bx0 - 0.55)))
        i1 = min(n_bars, int(math.ceil(bx1 + 0.55)) + 1)
        local_hi = None
        local_lo = None
        for i in range(i0, i1):
            try:
                hk = float(highs[i])
                lk = float(lows[i])
            except (TypeError, ValueError, IndexError):
                continue
            if hk > 0:
                local_hi = hk if local_hi is None else max(local_hi, hk)
            if lk > 0:
                local_lo = lk if local_lo is None else min(local_lo, lk)
        pad = max(float(y_span) * 0.028, abs(float(y_rail)) * 0.004, 2.0)
        candidates: List[float] = []
        if prefer_up and local_hi is not None:
            candidates.append(float(local_hi) + pad)
        if (not prefer_up) and local_lo is not None:
            candidates.append(float(local_lo) - pad)
        # 再加逐步微移備援
        sign = 1.0 if prefer_up else -1.0
        step = max(float(y_span) * 0.018, 1.5)
        for k in range(1, 18):
            candidates.append(float(y_rail) + sign * step * float(k))
        for y2 in candidates:
            if y2 > float(ymax) - y_span * 0.01:
                # 需要更高 → 呼叫端若已擴 ylim；此處先夾在可視頂下
                y2 = float(ymax) - y_span * 0.015
            if y2 < float(ymin) + y_span * 0.01:
                y2 = float(ymin) + y_span * 0.015
            box2 = _box_for(float(cx), str(ha), half_w, float(y2))
            c2 = _k_crush_score(box2)
            if c2 < best_c:
                best_c, best_y, best_box = c2, float(y2), box2
            if c2 < 0.5:
                break
        return best_y, best_box

    # 成對必共用錨（含右溝）；找不到才退回逐標（仍鎖同側）
    if pair_anchor is None and len(items) >= 2:
        # 保底：末日右溝
        if n_bars > 0:
            pair_anchor = (
                min(box_right_limit, float(n_bars - 1) + 0.55),
                "left",
            )
    if pair_anchor is not None:
        cx_p, ha_p = float(pair_anchor[0]), str(pair_anchor[1])
        prefer_x, prefer_ha = cx_p, ha_p
        for y_px, color, text in items:
            half_w = float(_approx_layer_tag_half_w(text, float(VOL_ZONE_TAG_PT)))
            cx, ha = cx_p, ha_p
            y_draw, box = _y_nudge_only(
                float(y_px), cx, ha, half_w, prefer_up=("壓" in text)
            )
            # 抬過今日高／壓過今日低時擴 ylim，免裁切
            try:
                y0, y1 = ax.get_ylim()
                top_need = float(box[3]) + float(y_span) * 0.025
                bot_need = float(box[2]) - float(y_span) * 0.025
                if top_need > float(y1) or bot_need < float(y0):
                    ax.set_ylim(min(float(y0), bot_need), max(float(y1), top_need))
            except Exception:
                pass
            try:
                _emit(float(y_draw), color, text, cx, ha, box)
            except Exception:
                _emit(float(y_px), color, text, cx, ha, _box_for(cx, ha, half_w, float(y_px)))
        return placed

    # 單標或無錨：逐標掃
    for y_px, color, text in items:
        half_w = float(_approx_layer_tag_half_w(text, float(VOL_ZONE_TAG_PT)))
        if prefer_x is not None and prefer_ha is not None:
            cx, ha, box = _clamp_into_view(
                float(prefer_x),
                str(prefer_ha),
                _box_for(float(prefer_x), str(prefer_ha), half_w, float(y_px)),
                half_w,
            )
            y_draw, box = _y_nudge_only(
                float(y_px), float(prefer_x), str(prefer_ha), half_w, prefer_up=("壓" in text)
            )
            cx, ha = float(prefer_x), str(prefer_ha)
        else:
            picked = pick_layer_label_along_line(
                y=float(y_px),
                text=text,
                xmin=float(xmin),
                xmax=float(xmax),
                highs=highs,
                lows=lows,
                mas=list(mas or []),
                occupied=placed,
                tag_size=float(VOL_ZONE_TAG_PT),
                y_span=float(y_span),
                prefer_x=prefer_x,
                max_score=28.0,
                same_band_max=12.0,
            )
            if picked is None:
                cx, ha, box = _force_keep_slot(float(y_px), text, half_w)
            else:
                cx, ha, box = picked
                cx, ha, box = _clamp_into_view(float(cx), str(ha), box, half_w)
                if float(box[1]) > box_right_limit + 0.55 or float(box[0]) < box_left_limit - 0.55:
                    cx, ha, box = _force_keep_slot(float(y_px), text, half_w)
            y_draw, cx, ha, box = _nudge_clear(
                float(y_px), text, cx, ha, half_w, prefer_up=("壓" in text)
            )
        try:
            _emit(float(y_draw), color, text, cx, ha, box)
        except Exception:
            cx, ha, box = _force_keep_slot(float(y_px), text, half_w)
            _emit(float(y_px), color, text, cx, ha, box)
        if prefer_x is None:
            prefer_x = float(cx)
            prefer_ha = str(ha)
    return placed


def _vz_memo_get(key: Tuple[Any, ...], save_path: str) -> Optional[Tuple[str, str]]:
    now = time.monotonic()
    with _VZ_RENDER_LOCK:
        hit = _VZ_RENDER_MEMO.get(key)
        if not hit:
            return None
        ts, src, cap = hit
        if now - ts > _VZ_RENDER_TTL_SEC or not src or not os.path.isfile(src):
            _VZ_RENDER_MEMO.pop(key, None)
            return None
    out = str(save_path or src)
    try:
        if os.path.abspath(src) != os.path.abspath(out):
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            shutil.copy2(src, out)
        return out, str(cap or "")
    except Exception:
        logger.debug("vol zone memo copy fail", exc_info=True)
        return None


def try_lookup_vol_memo(
    pack: Optional[Dict[str, Any]],
    save_path: str,
    *,
    card: Optional[Dict[str, Any]] = None,
    with_nav_signals: bool = True,
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
    lookup_portrait: bool = False,
    with_parallel_channel: bool = False,
    with_ma5_ma10: bool = True,
    db_path: str = "",
) -> Optional[Tuple[str, str]]:
    """暖路徑：已有 prepare pack 時，短 TTL 命中就複製，不進 paint／Agg。

    miss 回 None → 呼叫端再 submit_mpl_paint。盤中卡指紋變了會 miss。
    """
    if not (
        isinstance(pack, dict)
        and pack.get("zone")
        and pack.get("view") is not None
        and pack.get("bars")
        and save_path
    ):
        return None
    card_fp: Tuple[Any, ...] = ()
    if isinstance(card, dict) and card:
        try:
            from wayne_navigator import _lookup_card_fingerprint

            card_fp = tuple(_lookup_card_fingerprint(card))
        except Exception:
            card_fp = (
                str(card.get("stock_id") or ""),
                str(card.get("latest_date") or card.get("as_of") or ""),
                str(card.get("query_clock") or ""),
                str(card.get("stance") or ""),
            )
    channel_fp: Tuple[Any, ...] = ()
    if with_parallel_channel and str(pack.get("sid") or "").upper() in (
        "TWII",
        "TAIEX",
        "^TWII",
    ):
        try:
            from biaoke_chart import latest_biaoke_named_rising_lows

            named = latest_biaoke_named_rising_lows(str(db_path or ""))
            if named:
                channel_fp = (str(named[0]), str(named[1]))
        except Exception:
            channel_fp = ()
    memo_key = _vz_memo_key(
        pack["sid"],
        pack["zone"],
        pack["last"],
        with_nav_signals=with_nav_signals,
        lookback=lookback,
        bars=bars,
        lookup_portrait=lookup_portrait,
        with_parallel_channel=with_parallel_channel,
        with_ma5_ma10=with_ma5_ma10,
        card_fp=card_fp,
        channel_fp=channel_fp,
    )
    return _vz_memo_get(memo_key, save_path)


def _vz_memo_put(key: Tuple[Any, ...], path: str, cap: str) -> None:
    if not path or not os.path.isfile(path):
        return
    with _VZ_RENDER_LOCK:
        if len(_VZ_RENDER_MEMO) >= _VZ_RENDER_MEMO_MAX:
            oldest = sorted(_VZ_RENDER_MEMO.items(), key=lambda kv: kv[1][0])[
                : _VZ_RENDER_MEMO_MAX // 2
            ]
            for k, _ in oldest:
                _VZ_RENDER_MEMO.pop(k, None)
        _VZ_RENDER_MEMO[key] = (time.monotonic(), str(path), str(cap or ""))


def prepare_lookup_structure_bars(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    *,
    vol_ensure: Optional[Dict[str, Any]] = None,
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
) -> Optional[Dict[str, Any]]:
    """查股第 3 張用的官方柱。不含除權息補抓、不含大量區選窗。

    沒有真開高低收就回 None。不准在這裡發明量或補假柱。
    vol_ensure 由查股提早打過就傳進來，避免再等一輪網路。
    """
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    if not sid or not path:
        return None
    need = lookup_vol_ensure_days(lookback=lookback, bars=bars)
    stats = vol_ensure if isinstance(vol_ensure, dict) else None
    # 例外路徑回的空 dict 沒有 sid，這裡再 ensure 一次（暖命中不打網路）。
    if not stats or "sid" not in stats:
        try:
            stats = ensure_official_volume_window(
                sid,
                path,
                days=need,
                stock_name=str(stock_name or ""),
            )
        except Exception:
            logger.debug("structure bars ensure fail sid=%s", sid, exc_info=True)
            stats = {}
    skip = set((stats or {}).get("confirmed_absent") or [])
    raw = load_official_ohlc(sid, path, need)
    work = official_work(raw, skip_invent_dates=skip or None)
    if work is None or getattr(work, "empty", True) or len(work) < 8:
        return None
    bars_face = [
        {
            "date": r.get("date"),
            "open": r.get("open"),
            "high": r.get("high"),
            "low": r.get("low"),
            "close": r.get("close"),
            "volume": r.get("volume"),
        }
        for r in work.to_dict("records")
    ]
    if len(bars_face) < 8:
        return None
    return {
        "sid": sid,
        "name": str(stock_name or sid),
        "bars": bars_face,
        "work": work,
        "vol_ensure": stats or {},
    }


def prepare_volume_zone(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    save_path: str = None,
    df=None,
    *,
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
    preloaded_work=None,
    known_ensure: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """官方原柱＋除權息完成稿＋壓撐窗。HTTP 補抓在畫布鎖外。

    preloaded_work：查股已為結構圖整理過的官方柱，第 4 張不要再讀一次庫。
    """
    sid = str(stock_id or "").strip()
    if not sid:
        return None
    work = None
    need = lookup_vol_ensure_days(lookback=lookback, bars=bars)
    skip_invent: set = set()
    vol_ensure: Dict[str, Any] = {}
    if (
        preloaded_work is not None
        and not getattr(preloaded_work, "empty", True)
    ):
        work = preloaded_work
        vol_ensure = dict(known_ensure or {})
        skip_invent = set(vol_ensure.get("confirmed_absent") or [])
    elif db_path:
        # 結構／大量區同一 prepare：開市日缺量先官方補，不准對齊發明假量
        # 查股路徑應已提早 ensure（paint 外）；此處暖命中＝0 網路
        try:
            vol_ensure = ensure_official_volume_window(
                sid,
                str(db_path),
                days=need,
                stock_name=str(stock_name or ""),
            )
            skip_invent = set(vol_ensure.get("confirmed_absent") or [])
        except Exception:
            logger.debug("ensure_official_volume_window fail sid=%s", sid, exc_info=True)
            vol_ensure = {}
        raw = load_official_ohlc(sid, db_path, need)
        work = official_work(raw, skip_invent_dates=skip_invent or None)
    if work is None or work.empty:
        if df is None or getattr(df, "empty", True):
            return None
        work = official_work(df, skip_invent_dates=skip_invent or None)
    if work is None or work.empty:
        return None
    work = attach_official_ma5(work)
    work = attach_official_ma10(work)
    work = attach_official_ma20(work)
    work = attach_official_ma60(work)
    ex_events: List[Dict[str, Any]] = []
    if db_path:
        start_d = _bar_ymd(work["date"].iloc[0])
        end_d = _bar_ymd(work["date"].iloc[-1])
        ex_events = load_scale_ex_events(sid, str(db_path), start_d, end_d)
        recent = work.tail(8) if hasattr(work, "tail") else work
        ex_events = hydrate_official_ex_for_gaps(sid, str(db_path), recent, ex_events)
    zone = find_volume_zone(work, lookback=lookback, ex_events=ex_events)
    if not zone:
        return None
    n_all = len(work)
    show_n = min(max(int(bars or VOL_ZONE_BARS), 30), n_all)
    spike_i_all = int(zone["i"])
    start = max(0, n_all - show_n)
    if spike_i_all < start:
        start = max(0, spike_i_all - 8)
    # 近窗第一根就要有月線／季線：能暖機就讓 start 落在 MA60 窗後（仍保住爆大量日在窗內）
    warm = int(VOL_ZONE_MA60)
    if start < warm and spike_i_all >= warm and (n_all - warm) >= 30:
        start = warm
        if spike_i_all < start:
            start = max(0, spike_i_all - 8)
    view = work.iloc[start:].reset_index(drop=True)
    spike_i = int(zone["i"]) - start
    if spike_i < 0 or spike_i >= len(view):
        return None
    name = stock_name or str(view["stock_name"].iloc[-1] if "stock_name" in view.columns else sid)
    out = save_path or os.path.join(".", f"{sid}_vol_zone.png")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    hi = float(zone["high"])
    lo = float(zone["low"])
    spike_date = str(zone["date"] or "")
    n = len(view)
    xs = np.arange(n, dtype=float)
    halt = (
        view["is_halt"].fillna(False).astype(bool)
        if "is_halt" in view.columns
        else pd.Series(False, index=view.index)
    )
    bars_face = [
        {
            "date": r.get("date"),
            "open": r.get("open"),
            "high": r.get("high"),
            "low": r.get("low"),
            "close": r.get("close"),
            "volume": r.get("volume"),
        }
        for r in work.to_dict("records")
    ]
    return {
        "sid": sid,
        "name": name,
        "view": view,
        "zone": zone,
        "spike_i": spike_i,
        "spike_date": spike_date,
        "hi": hi,
        "lo": lo,
        "halt": halt,
        "xs": xs,
        "n": n,
        "ex_events": ex_events,
        "out": out,
        "bars": bars_face,
        "last": bars_face[-1] if bars_face else None,
        "vol_ensure": vol_ensure,
    }


def render_volume_zone_result(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    save_path: str = None,
    df=None,
    *,
    already_normalized: bool = False,
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
    card: Optional[Dict[str, Any]] = None,
    with_nav_signals: bool = False,
    lookup_portrait: bool = False,
    with_parallel_channel: bool = False,
    with_ma5_ma10: bool = True,
    pack: Optional[Dict[str, Any]] = None,
    nav_signal_work=None,
) -> tuple[str, str]:
    """一次準備：圖＋圖說。不准畫完再重抓日K／除權息。

    with_nav_signals＝疊導航箭頭／量能訊號（壓撐觀察用；仍非買訊）。
    lookup_portrait＝舊直式 4:5 畫布（壓區名單仍可走）。查股第 4 張改橫式原版。
    with_parallel_channel＝疊可重算上升軌／下降壓兩條平行線（大盤大量區用；不數浪、非買訊）。
    with_ma5_ma10＝疊官方五日／十日線（橙／青；與月／季並列；非買訊）。
    預設 True＝話筒／勝率／壓撐／大盤同一新臉；測試要舊臉才顯式傳 False。
    """
    del already_normalized
    if not (
        isinstance(pack, dict)
        and pack.get("zone")
        and pack.get("view") is not None
        and pack.get("bars")
    ):
        pack = prepare_volume_zone(
            stock_id, stock_name, db_path, save_path, df, lookback=lookback, bars=bars
        )
    else:
        pack = dict(pack)
        if save_path:
            pack["out"] = save_path
    if not pack:
        return "", ""
    # 卡指紋進鍵：查股必帶 card；舊「有卡就不 memo」讓第二次同檔仍重渲 ~0.4s。
    # 指紋含 query_clock／stance 等，圖說／導航漂移不會互蓋。
    card_fp: Tuple[Any, ...] = ()
    if isinstance(card, dict) and card:
        try:
            from wayne_navigator import _lookup_card_fingerprint

            card_fp = tuple(_lookup_card_fingerprint(card))
        except Exception:
            card_fp = (
                str(card.get("stock_id") or ""),
                str(card.get("latest_date") or card.get("as_of") or ""),
                str(card.get("query_clock") or ""),
                str(card.get("stance") or ""),
            )
    channel_fp: Tuple[Any, ...] = ()
    if with_parallel_channel and str(pack["sid"]).upper() in ("TWII", "TAIEX", "^TWII"):
        try:
            from biaoke_chart import latest_biaoke_named_rising_lows

            named = latest_biaoke_named_rising_lows(str(db_path or ""))
            if named:
                channel_fp = (str(named[0]), str(named[1]))
        except Exception:
            channel_fp = ()
    memo_key = _vz_memo_key(
        pack["sid"],
        pack["zone"],
        pack["last"],
        with_nav_signals=with_nav_signals,
        lookback=lookback,
        bars=bars,
        lookup_portrait=lookup_portrait,
        with_parallel_channel=with_parallel_channel,
        with_ma5_ma10=with_ma5_ma10,
        card_fp=card_fp,
        channel_fp=channel_fp,
    )
    hit = _vz_memo_get(memo_key, pack["out"])
    if hit:
        return hit
    cap = vol_zone_photo_caption(
        pack["sid"],
        str(db_path or ""),
        card,
        zone=pack["zone"],
        last=pack["last"],
        bars=pack["bars"],
        ex_events=pack["ex_events"],
    )
    if with_parallel_channel:
        try:
            ch0 = infer_vol_zone_parallel_channel(
                pack["view"],
                bars_face=pack.get("bars"),
                db_path=str(db_path or ""),
                stock_id=str(pack["sid"] or ""),
            )
            tip = str((ch0 or {}).get("tip") or "").strip()
            if tip and tip not in cap:
                cap = f"{cap}\n{tip}".strip() if cap else tip
        except Exception:
            logger.exception("大量區平行軌圖說失敗 sid=%s", pack.get("sid"))
    with mpl_render():
        path = _paint_volume_zone(
            pack["sid"],
            pack["name"],
            pack["view"],
            pack["zone"],
            pack["spike_i"],
            pack["spike_date"],
            pack["hi"],
            pack["lo"],
            pack["halt"],
            pack["xs"],
            pack["n"],
            pack["ex_events"],
            pack["out"],
            with_nav_signals=with_nav_signals,
            card=card,
            lookup_portrait=lookup_portrait,
            db_path=str(db_path or ""),
            with_parallel_channel=with_parallel_channel,
            with_ma5_ma10=with_ma5_ma10,
            bars_face=pack.get("bars"),
            nav_signal_work=nav_signal_work,
        )
    out_path, out_cap = str(path or ""), str(cap or "")
    if out_path:
        _vz_memo_put(memo_key, out_path, out_cap)
    return out_path, out_cap


def render_volume_zone_png(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    save_path: str = None,
    df=None,
    *,
    already_normalized: bool = False,
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
    with_nav_signals: bool = False,
    card: Optional[Dict[str, Any]] = None,
) -> str:
    """畫大量區專圖。有 db 就只吃官方原柱；失敗回空字串。"""
    path, _cap = render_volume_zone_result(
        stock_id,
        stock_name,
        db_path,
        save_path,
        df,
        already_normalized=already_normalized,
        lookback=lookback,
        bars=bars,
        card=card,
        with_nav_signals=with_nav_signals,
    )
    return path


def render_lookup_vol_result(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    save_path: str = None,
    *,
    card: Optional[Dict[str, Any]] = None,
    pack: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    """查股第 4 張：大量撐壓＝橫式原版（VOL_ZONE_FIG_W×NAV），不是直式 4:5。不是買訊。

    月／季一律畫；五日／十日一併畫（橙／青），短標避讓略過時線仍在。
    """
    return render_volume_zone_result(
        stock_id,
        stock_name,
        db_path,
        save_path,
        card=card,
        with_nav_signals=True,
        lookup_portrait=False,
        with_ma5_ma10=True,
        pack=pack,
    )


def _paint_market_vol_header(fig, ax, *, title: str, ohlc: str, orange: str) -> None:
    """大盤大量區表頭：橘標在上、當天開高低收整行在下，兩段都不互壓。"""
    pos = ax.get_position()
    fig_h_px = max(float(fig.bbox.height), 1.0)
    ohlc_art = fig.text(
        pos.x0,
        pos.y1 + 8.0 / (fig.get_figheight() * 72.0),
        ohlc,
        ha="left",
        va="bottom",
        fontproperties=_fp(12, "bold"),
        color=_TEXT,
        zorder=20,
    )
    title_art = fig.text(
        pos.x0,
        pos.y1 + 36.0 / (fig.get_figheight() * 72.0),
        title,
        ha="left",
        va="bottom",
        fontproperties=_fp(13, "bold"),
        color=_TEXT,
        zorder=20,
    )
    orange_art = None
    if str(orange or "").strip():
        orange_art = fig.text(
            pos.x1,
            pos.y1 + 36.0 / (fig.get_figheight() * 72.0),
            orange,
            ha="right",
            va="bottom",
            fontproperties=_fp(9.0, "bold"),
            color=_CALL,
            zorder=21,
            linespacing=1.15,
            bbox=dict(
                boxstyle="round,pad=0.20",
                facecolor="#fff8e1",
                edgecolor="#ef6c00",
                linewidth=0.85,
                alpha=0.96,
            ),
        )

    def _gap_up(art, floor_y1: float, gap_px: float) -> None:
        bb = art.get_window_extent(renderer=ren)
        if bb.y0 >= floor_y1 + gap_px:
            return
        dy = (floor_y1 + gap_px - bb.y0) / fig_h_px
        x, y = art.get_position()
        art.set_position((x, y + dy))

    try:
        fig.canvas.draw()
        ren = fig.canvas.get_renderer()
        ohlc_bb = ohlc_art.get_window_extent(renderer=ren)
        if orange_art is not None:
            _gap_up(orange_art, ohlc_bb.y1, 10.0)
            fig.canvas.draw()
            ren = fig.canvas.get_renderer()
            title_bb = title_art.get_window_extent(renderer=ren)
            orange_bb = orange_art.get_window_extent(renderer=ren)
            overlap = not (
                title_bb.x1 < orange_bb.x0 - 8
                or orange_bb.x1 < title_bb.x0 - 8
                or title_bb.y1 < orange_bb.y0 - 4
                or orange_bb.y1 < title_bb.y0 - 4
            )
            if overlap:
                _gap_up(orange_art, title_bb.y1, 8.0)
            # 右上時間戳在圖頂；橘標頂不要鑽進那一行
            fig.canvas.draw()
            orange_bb = orange_art.get_window_extent(renderer=ren)
            stamp_floor = fig_h_px * 0.955
            if orange_bb.y1 > stamp_floor:
                dy = (orange_bb.y1 - stamp_floor) / fig_h_px
                x, y = orange_art.get_position()
                orange_art.set_position((x, max(pos.y1 + 0.01, y - dy)))
    except Exception:
        logger.debug("大盤大量區表頭讓位失敗", exc_info=True)


def _paint_volume_zone(
    sid,
    name,
    view,
    zone,
    spike_i,
    spike_date,
    hi,
    lo,
    halt,
    xs,
    n,
    ex_events,
    out,
    *,
    with_nav_signals: bool = False,
    card: Optional[Dict[str, Any]] = None,
    lookup_portrait: bool = False,
    db_path: str = "",
    with_parallel_channel: bool = False,
    with_ma5_ma10: bool = True,
    bars_face=None,
    nav_signal_work=None,
):
    spike_md = _md(spike_date)
    ax_head = None
    channel: Dict[str, Any] = {}
    # 縮圖最後一根 K／量＝決策卡今臉（與圖一／二／表頭同源）；選區已在 prepare 吃官方。
    # 盤中走 overlay；13:30 收後 is_live 可能已關，仍要用卡上今天這根，不准臉柱停在昨收。
    if isinstance(card, dict) and card:
        try:
            from live_quote import overlay_live_face_from_card

            if card.get("is_live"):
                view2 = overlay_live_face_from_card(
                    view if isinstance(view, pd.DataFrame) else view,
                    card,
                    stock_id=str(sid or ""),
                )
                if (
                    isinstance(view2, pd.DataFrame)
                    and not getattr(view2, "empty", True)
                    and len(view2) >= 1
                ):
                    view = view2.reset_index(drop=True)
                    n = len(view)
                    xs = np.arange(n, dtype=float)
                    halt = (
                        view["is_halt"].fillna(False).astype(bool)
                        if "is_halt" in view.columns
                        else pd.Series(False, index=view.index)
                    )
        except Exception:
            logger.debug("大量區臉柱疊盤中報價略過 sid=%s", sid, exc_info=True)
        try:
            view = _apply_card_face_to_view(view, card)
            n = len(view)
            xs = np.arange(n, dtype=float)
            halt = (
                view["is_halt"].fillna(False).astype(bool)
                if "is_halt" in view.columns
                else pd.Series(False, index=view.index)
            )
        except Exception:
            logger.debug("大量區臉柱對齊決策卡略過 sid=%s", sid, exc_info=True)
    # 獨立 Figure＋Agg：可與介紹／高低卡真並行，不准再用 pyplot 全域搶鎖。
    from matplotlib.gridspec import GridSpec
    from wayne_navigator import _close_lookup_figure, _new_lookup_figure

    if lookup_portrait:
        fig_size = VOL_ZONE_FIG_LOOKUP
        # 量柱列加高：高價股矮柱不准被擠沒。表頭不再放收盤晶片。
        head_ratios = [0.78, 4.35, 0.38, 1.72]
        # 底部灰字兩行（含止穩◆／橘六角出現時機）要留空
        head_bottom = 0.078
    else:
        fig_size = (VOL_ZONE_FIG_W, VOL_ZONE_FIG_H_NAV)
        head_ratios = [1.28, 3.38, 0.40, 0.98]
        head_bottom = 0.072

    # 大盤大量區（平行軌、無導航、橫式）：畫布與右緣對齊加權日K。
    # 個股／直式不准走這組 figsize。平行軌標一律軸內智能定位，
    # 不准為塞標把 GridSpec right 收到 0.72（會左右大黑邊、主圖被擠窄）。
    market_wide = bool(
        with_parallel_channel and not lookup_portrait and not with_nav_signals
    )
    if market_wide:
        from wayne_navigator import NAV_CHART_DPI

        _gs_left = MARKET_VOL_ZONE_GS_LEFT
        _gs_right = MARKET_VOL_ZONE_GS_RIGHT
        _paint_dpi = int(NAV_CHART_DPI)
    else:
        _gs_left = 0.050 if with_nav_signals else 0.04
        _gs_right = 0.935 if with_nav_signals else 0.96
        _paint_dpi = int(VOL_ZONE_DPI)
    if with_nav_signals:
        # 獨立標題列：股票介紹＋圖例同一塊；中間整列給 K，不准標題／圖例之間留大空白
        fig = _new_lookup_figure(fig_size, _paint_dpi, _BG)
        gs = GridSpec(
            4,
            1,
            figure=fig,
            height_ratios=head_ratios,
            hspace=0.035,
            left=0.050,
            right=_gs_right,
            top=0.985,
            bottom=head_bottom,
        )
        ax_head = fig.add_subplot(gs[0])
        ax1 = fig.add_subplot(gs[1])
        ax_sig = fig.add_subplot(gs[2], sharex=ax1)
        ax2 = fig.add_subplot(gs[3], sharex=ax1)
        ax_sig.set_facecolor(_BG)
        ax_head.set_facecolor(_BG)
        ax_head.set_axis_off()
    else:
        fig = _new_lookup_figure(
            MARKET_VOL_ZONE_FIG
            if market_wide
            else (
                VOL_ZONE_FIG_LOOKUP
                if lookup_portrait
                else (VOL_ZONE_FIG_W, VOL_ZONE_FIG_H_PLAIN)
            ),
            _paint_dpi,
            _BG,
        )
        gs = GridSpec(
            2,
            1,
            figure=fig,
            height_ratios=[4.85, 1.85] if lookup_portrait else [3.4, 1.05],
            hspace=0.055,
            left=_gs_left,
            right=_gs_right,
            top=0.835 if market_wide else 0.88,
            bottom=0.08,
        )
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax_sig = None
    ax1.set_facecolor(_BG)
    ax2.set_facecolor(_BG)
    for _spine in ax1.spines.values():
        _spine.set_color("#cfd8dc")
        _spine.set_linewidth(0.7)
    for _spine in ax2.spines.values():
        _spine.set_color("#cfd8dc")
        _spine.set_linewidth(0.7)

    # 桃色大量區（略透，K／箭頭更清楚）
    ax1.axhspan(lo, hi, color=_FILL, alpha=0.42, zorder=0)
    # 壓／撐色線再細一點：仍清楚，不搶 K／均線
    ax1.axhline(hi, color=_PRESS, linewidth=0.78, zorder=5, solid_capstyle="round")
    ax1.axhline(lo, color=_HOLD, linewidth=0.78, zorder=5, solid_capstyle="round")
    # 爆大量日豎線：極小間距虛線，避免實線切過 K／量看不清
    ax1.axvline(
        spike_i,
        color=_SPIKE,
        linewidth=1.05,
        alpha=0.72,
        zorder=1,
        linestyle=(0, (1.1, 1.35)),
    )

    # 均線：月線／季線一律畫；五日／十日由 with_ma5_ma10（預設開；關旗才略）
    closes_v = pd.to_numeric(view["close"], errors="coerce")
    ma5_vals = None
    ma10_vals = None
    if with_ma5_ma10:
        if "ma5" in view.columns:
            ma5_vals = pd.to_numeric(view["ma5"], errors="coerce").to_numpy(dtype=float)
        else:
            ma5_vals = closes_v.rolling(VOL_ZONE_MA5, min_periods=VOL_ZONE_MA5).mean().to_numpy(
                dtype=float
            )
        if "ma10" in view.columns:
            ma10_vals = pd.to_numeric(view["ma10"], errors="coerce").to_numpy(dtype=float)
        else:
            ma10_vals = closes_v.rolling(VOL_ZONE_MA10, min_periods=VOL_ZONE_MA10).mean().to_numpy(
                dtype=float
            )
    if "ma20" in view.columns:
        ma20_vals = pd.to_numeric(view["ma20"], errors="coerce").to_numpy(dtype=float)
    else:
        ma20_vals = closes_v.rolling(VOL_ZONE_MA20, min_periods=VOL_ZONE_MA20).mean().to_numpy(
            dtype=float
        )
    ma60_vals = None
    if "ma60" in view.columns:
        ma60_vals = pd.to_numeric(view["ma60"], errors="coerce").to_numpy(dtype=float)
    if ma5_vals is not None:
        ok5 = np.isfinite(ma5_vals) & (ma5_vals > 0)
        if ok5.any():
            ax1.plot(
                xs[ok5],
                ma5_vals[ok5],
                color=_MA5,
                linewidth=1.35,
                zorder=4,
                solid_capstyle="round",
                label="五日",
            )
    if ma10_vals is not None:
        ok10 = np.isfinite(ma10_vals) & (ma10_vals > 0)
        if ok10.any():
            ax1.plot(
                xs[ok10],
                ma10_vals[ok10],
                color=_MA10,
                linewidth=1.45,
                zorder=4,
                solid_capstyle="round",
                label="十日",
            )
    ok20 = np.isfinite(ma20_vals) & (ma20_vals > 0)
    if ok20.any():
        ax1.plot(
            xs[ok20],
            ma20_vals[ok20],
            color=_MA20,
            linewidth=1.75,
            zorder=4,
            solid_capstyle="round",
            label="月線",
        )
    if ma60_vals is not None:
        ok60 = np.isfinite(ma60_vals) & (ma60_vals > 0)
        if ok60.any():
            ax1.plot(
                xs[ok60],
                ma60_vals[ok60],
                color=_MA60,
                linewidth=1.85,
                zorder=4,
                solid_capstyle="round",
                label="季線",
            )

    # 除息／除權：先畫豎線與參考價；文字標等 ylim／疊箭頭後掛軸頂，不准壓 K
    ex_by_date = {_bar_ymd(e.get("ex_date")): e for e in official_scale_events(ex_events)}
    ex_labels: list[tuple[int, str]] = []
    for i in range(n):
        ev = ex_by_date.get(_bar_ymd(view["date"].iloc[i]))
        if not ev:
            continue
        verb = phone_ex_verb(ev.get("kind"))
        if not verb:
            continue
        amt = 0.0
        try:
            amt = float(ev.get("right_plus_div") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        lab = verb if amt <= 0 else f"{verb}{_fmt_price(amt)}元"
        # z 略高於底帶／參考線，豎虛線才不會在上半被蓋到「看不見對哪根」
        ax1.axvline(
            xs[i],
            color="#6a1b9a",
            linewidth=1.05,
            alpha=0.55,
            zorder=3,
            linestyle=(0, (2.5, 1.8)),
        )
        ex_labels.append((i, lab))
        ref = 0.0
        try:
            ref = float(ev.get("ref_price") or 0)
        except (TypeError, ValueError):
            ref = 0.0
        if ref > 0:
            ax1.axhline(ref, color="#6a1b9a", linewidth=0.9, linestyle=(0, (3, 2)), alpha=0.65, zorder=2)

    # 停價日也要可見 K／量槽，不准挖洞；對齊導航灰短橫，不准編振幅假柱
    _span_est = max(
        float(view["high"].max()) - float(view["low"].min()),
        float(hi - lo) if hi > lo else 0.0,
        1.0,
    )
    # 日 K＝查股共用 paint（結構／大量／導航同一套紅綠、柱寬、線寬）
    opens = pd.to_numeric(view["open"], errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(view["close"], errors="coerce").to_numpy(dtype=float)
    highs = pd.to_numeric(view["high"], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(view["low"], errors="coerce").to_numpy(dtype=float)
    halt_arr = (
        halt.fillna(False).astype(bool).to_numpy()
        if hasattr(halt, "fillna")
        else np.asarray(halt, dtype=bool)
    )
    up_mask = paint_lookup_ohlc_candles(
        ax1,
        xs,
        opens,
        highs,
        lows,
        closes,
        halt=halt_arr,
        spike_i=int(spike_i) if spike_i is not None else None,
        span=_span_est,
        z=3,
    )

    last = view.iloc[-1]
    last_hi = float(last["high"] or 0)
    last_cl = float(last["close"] or 0)
    last_md = _md(last.get("date"))
    # 表頭／當日走勢標／圖說同一決策卡臉（盤中現價或已收今天），不准走勢標仍釘前一日收
    hdr_quote = None
    try:
        from live_quote import display_quote_from_card

        hdr_quote = display_quote_from_card(card if isinstance(card, dict) else None)
    except Exception:
        hdr_quote = None
    path_shown = ""
    try:
        last_bar = {
            "date": last.get("date"),
            "open": last.get("open"),
            "high": last.get("high"),
            "low": last.get("low"),
            "close": last.get("close"),
            "volume": last.get("volume"),
        }
        bars_face = [
            {
                "date": r.get("date"),
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": r.get("volume"),
            }
            for r in view.to_dict("records")
        ]
        face_last, face_bars, face_meta = align_vol_zone_caption_face(
            last_bar, bars_face, card if isinstance(card, dict) else None
        )
        if face_last and _px(face_last.get("close")) > 0:
            last_bar = face_last
            bars_face = face_bars or bars_face
            last_hi = float(last_bar.get("high") or last_hi or 0)
            last_cl = float(last_bar.get("close") or last_cl or 0)
        path_msg = vol_zone_day_path_label(
            float(hi),
            float(lo),
            last_bar,
            bars=bars_face,
            zone_date=str(spike_date or ""),
            session_live=bool(face_meta.get("session_live")),
            emerging=bool(face_meta.get("emerging")),
        )
        if path_msg and last_hi > 0 and float(hi) > 0:
            bits = [p for p in path_msg.split("  ") if p]
            # 兩行事實句（壓低高度）：日＋撐／壓｜今高／今低／過未過＋收；整塊掛圖例上方
            if len(bits) >= 3:
                path_shown = f"{bits[0]}  {bits[1]}\n{'  '.join(bits[2:])}"
            else:
                path_shown = "\n".join(bits) if bits else path_msg
    except Exception:
        logger.exception("大量撐壓當日走勢標失敗 sid=%s", sid)
        path_shown = ""

    ypad = max((hi - lo) * 0.16, float(view["high"].max() - view["low"].min()) * 0.035)
    y_hi = float(view["high"].max())
    y_lo = float(view["low"].min())
    for _arr in (ma5_vals, ma10_vals, ma20_vals, ma60_vals):
        if _arr is None:
            continue
        ok_ma = np.isfinite(_arr) & (_arr > 0)
        if ok_ma.any():
            y_hi = max(y_hi, float(np.nanmax(_arr[ok_ma])))
            y_lo = min(y_lo, float(np.nanmin(_arr[ok_ma])))
    ymin = min(y_lo, lo) - ypad
    ymax = max(y_hi, hi) + ypad * (1.35 if with_nav_signals else 1.25)
    # 日標貼主K上框內側：略抬頂，少壓末日K／導航箭（v9 再多一點，橘框不跟箭頭互壓）
    if path_shown:
        ymax = ymax + (ymax - ymin) * (0.12 if with_nav_signals else 0.08)
    # 平行軌現價可能高於壓／低於撐：ylim 先吃進去，線才不會被裁
    if with_parallel_channel:
        try:
            channel = infer_vol_zone_parallel_channel(
                view,
                bars_face=bars_face,
                db_path=str(db_path or ""),
                stock_id=str(sid or ""),
            )
            if channel:
                y_span = max(float(ymax) - float(ymin), 1.0)
                for yv in (channel.get("rail_now"), channel.get("base_now")):
                    try:
                        yf = float(yv or 0)
                    except (TypeError, ValueError):
                        yf = 0.0
                    if yf > 0:
                        ymax = max(ymax, yf + y_span * 0.04)
                        ymin = min(ymin, yf - y_span * 0.04)
        except Exception:
            logger.exception("大量區推平行軌失敗 sid=%s", sid)
            channel = {}
    # D4／D5-T1：原文目標／破撐 NEXT 價也先吃進 ylim
    next_pack: Dict[str, Any] = {}
    try:
        from biaoke_next_support import resolve_next_support, written_targets_for

        face_rows = list(bars_face or [])
        if not face_rows:
            face_rows = [
                {
                    "date": r.get("date"),
                    "open": r.get("open"),
                    "high": r.get("high"),
                    "low": r.get("low"),
                    "close": r.get("close"),
                    "volume": r.get("volume"),
                }
                for r in view.to_dict("records")
            ]
        next_pack = resolve_next_support(
            face_rows,
            sid=str(sid or ""),
            close=float(last_cl or 0),
            support=float(lo or 0),
            pressure=float(hi or 0),
            spike_date=str(spike_date or ""),
            channel=channel if isinstance(channel, dict) else {},
        )
        if not next_pack.get("written"):
            next_pack["written"] = written_targets_for(str(sid or ""))
        y_span = max(float(ymax) - float(ymin), 1.0)
        for row in list(next_pack.get("written") or []):
            try:
                yf = float(row.get("price") or 0)
            except (TypeError, ValueError):
                yf = 0.0
            if yf > 0:
                ymax = max(ymax, yf + y_span * 0.04)
                ymin = min(ymin, yf - y_span * 0.04)
        layer = next_pack.get("layer") or {}
        for key in ("low", "high"):
            try:
                yf = float(layer.get(key) or 0)
            except (TypeError, ValueError):
                yf = 0.0
            if yf > 0:
                ymax = max(ymax, yf + y_span * 0.04)
                ymin = min(ymin, yf - y_span * 0.04)
        prim = next_pack.get("primary") or {}
        try:
            yf = float(prim.get("price") or 0)
        except (TypeError, ValueError):
            yf = 0.0
        if yf > 0:
            ymax = max(ymax, yf + y_span * 0.04)
            ymin = min(ymin, yf - y_span * 0.04)
    except Exception:
        logger.debug("大量區下一層解析略過 sid=%s", sid, exc_info=True)
        next_pack = {}
    ax1.set_ylim(ymin, ymax)
    # 左貼第一根 K、右多留空：最後一根／買點箭不貼死右軸
    # 右略鬆給末日 K／收價；均線標改放左半／中段，不搶近端
    ax1.set_xlim(-0.05, n + 2.15)
    channel_label_rects: List[Tuple[float, float, float, float]] = []
    _ma_for_channel: List[Any] = []
    if with_parallel_channel and channel:
        try:
            _ma_for_channel = [
                a
                for a in (ma5_vals, ma10_vals, ma20_vals, ma60_vals)
                if a is not None
            ]
            # 先畫軌線；標籤等導航箭疊完再掛（避開箭頭，不准壓判定符號）
            paint_vol_zone_parallel_channel(
                ax1,
                channel,
                n=int(n),
                ymin=float(ymin),
                ymax=float(ymax),
                labels_outside=False,
                market_style=bool(market_wide),
                highs=highs,
                lows=lows,
                mas=_ma_for_channel,
                paint_rails=True,
                paint_labels=False,
            )
        except Exception:
            logger.exception("大量區畫平行軌失敗 sid=%s", sid)
    # v9：橘框／壓撐／下一層／原文目標改在導航箭頭之後再畫（高 z＋白底），
    # 優先保文字可讀；水平線仍先畫（見下方 paint 只補標）。
    ax1.yaxis.tick_right()
    ax1.tick_params(labelbottom=False, labelsize=10)
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.45, color=_GRID, zorder=0, alpha=0.85)
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(10))

    # 大量區右軸／表頭：已刪綠匡白底「收」晶片；不准再畫「昨收」白底標
    # v9：下一層／原文線＋標改在導航之後一次畫（見下方關鍵標區塊）

    # 查詢時間：整張底圖右上角（台北）；不進 K 區、不跟除息搶位。
    # hdr_quote 已在走勢標前取過；戳／表頭／臉柱同一張今天棒。
    try:
        from decision_card_signals import format_card_query_stamp

        last_d = _bar_ymd(last.get("date"))
        is_live = bool(hdr_quote and str(hdr_quote.get("label") or "") == "盤中")
        if not is_live and hdr_quote and hdr_quote.get("is_live"):
            is_live = True
        if not is_live and "is_live" in view.columns:
            try:
                is_live = bool(pd.Series(view["is_live"]).fillna(False).iloc[-1])
            except Exception:
                is_live = False
        qs = ""
        if "quote_source" in view.columns:
            try:
                qs = str(view["quote_source"].dropna().iloc[-1] or "")
            except Exception:
                qs = ""
        if not qs and isinstance(card, dict):
            qs = str(card.get("quote_source") or "")
        stamp_date = last_d
        # 表頭有今天日就用今天，不准查詢戳還停在昨收日（含 13:30 已收）
        if hdr_quote and hdr_quote.get("date"):
            stamp_date = _bar_ymd(hdr_quote.get("date")) or stamp_date
        elif isinstance(card, dict) and (card.get("latest_date") or card.get("as_of")):
            stamp_date = _bar_ymd(card.get("latest_date") or card.get("as_of")) or stamp_date
        qd = str((hdr_quote or {}).get("query_date") or (card or {}).get("query_date") or "").strip()
        qc = str((hdr_quote or {}).get("query_clock") or (card or {}).get("query_clock") or "").strip()
        if qd and qc:
            stamp = f"{qd}　{qc}".strip()
        else:
            date_s, clock_s = format_card_query_stamp(
                is_live=is_live,
                latest_date=stamp_date,
                quote_source=qs,
                listing=str((card or {}).get("listing") or "") if isinstance(card, dict) else "",
                stock_id=str(sid or ""),
                emerging=bool((hdr_quote or {}).get("emerging")),
            )
            stamp = f"{date_s}　{clock_s}".strip()
    except Exception:
        stamp = ""
    if stamp:
        fig.text(
            0.985,
            0.992,
            stamp,
            ha="right",
            va="top",
            fontproperties=_fp(10.0, "bold"),
            color=_MUTED,
            zorder=20,
            bbox=dict(
                boxstyle="round,pad=0.20",
                facecolor="#ffffff",
                edgecolor="#cfd8dc",
                linewidth=0.75,
                alpha=0.94,
            ),
        )

    if with_nav_signals:
        if "dt" not in view.columns:
            view = view.copy()
            view["dt"] = pd.to_datetime(view["date"].astype(str), format="%Y%m%d", errors="coerce")
        try:
            from wayne_navigator import _load_ohlc, overlay_nav_marks_on_zone

            # 訊號＝與高低導航同一套 180 日官方柱，再依日期對到近窗；不准短窗重算
            signal_work = nav_signal_work
            if signal_work is None and db_path:
                try:
                    signal_work = _load_ohlc(str(sid), str(db_path), 180)
                except Exception:
                    logger.exception("大量區載入導航 180 日失敗 sid=%s", sid)
                    signal_work = None
            # 盤中：180 日訊號列末日也疊決策卡真報價（與 view 臉柱／#606 同源）
            # 否則止穩／買箭在 signal_work 上算會看不到今日 live 低／收
            if (
                signal_work is not None
                and isinstance(card, dict)
                and card.get("is_live")
            ):
                try:
                    from live_quote import overlay_live_face_from_card

                    sw2 = overlay_live_face_from_card(
                        signal_work, card, stock_id=str(sid or "")
                    )
                    if (
                        isinstance(sw2, pd.DataFrame)
                        and not getattr(sw2, "empty", True)
                    ):
                        signal_work = sw2.reset_index(drop=True)
                except Exception:
                    logger.debug(
                        "大量區訊號列疊盤中臉柱略過 sid=%s", sid, exc_info=True
                    )
            # 外資升級／確認觀察標（測試版）：注入 card 再疊；非買訊
            paint_card = card
            if db_path and sid:
                try:
                    from foreign_sell_display import (
                        stock_observe_bar_index,
                        stock_observe_hit,
                    )

                    hit = stock_observe_hit(str(db_path), str(sid))
                    if hit is not None:
                        dates = [
                            str(view["date"].iloc[i])
                            for i in range(len(view))
                        ]
                        idxs = stock_observe_bar_index(dates, hit)
                        if idxs:
                            paint_card = dict(card or {})
                            paint_card["_foreign_sell_observe_idxs"] = idxs
                            paint_card["stock_id"] = str(sid)
                except Exception:
                    logger.debug(
                        "大量區外資觀察標略過 sid=%s", sid, exc_info=True
                    )
            # 圖例改畫在標題列，不准掛在 K 上方留白；均線已在上方畫好
            overlay_nav_marks_on_zone(
                ax1,
                ax_sig,
                view,
                card=paint_card,
                draw_legend=False,
                draw_ma20=False,
                signal_work=signal_work,
            )
        except Exception:
            logger.exception("大量區疊導航指標失敗 sid=%s", sid)

    # 軌道價標：導航之後再掛，智能避箭頭／殘影；不准壓判定符號
    if with_parallel_channel and channel:
        try:
            channel_label_rects = paint_vol_zone_parallel_channel(
                ax1,
                channel,
                n=int(n),
                ymin=float(ymin),
                ymax=float(ymax),
                labels_outside=False,
                market_style=bool(market_wide),
                highs=highs,
                lows=lows,
                mas=_ma_for_channel,
                paint_rails=False,
                paint_labels=True,
                avoid_nav_marks=bool(with_nav_signals),
            )
        except Exception:
            logger.exception("大量區平行軌標失敗 sid=%s", sid)
            channel_label_rects = []

    # 均線短標：程式自動選位（中左→中→中右靠中）只貼己線；不准動 OHLC／量柱
    highs_a = pd.to_numeric(view["high"], errors="coerce").to_numpy(dtype=float)
    lows_a = pd.to_numeric(view["low"], errors="coerce").to_numpy(dtype=float)
    ma_series: List[Tuple[str, np.ndarray, str, str]] = []
    if ma5_vals is not None and np.isfinite(ma5_vals).any():
        ma_series.append(("5", ma5_vals, _MA5, "#fff3e0"))
    if ma10_vals is not None and np.isfinite(ma10_vals).any():
        ma_series.append(("10", ma10_vals, _MA10, "#e0f7fa"))
    if ma20_vals is not None and np.isfinite(ma20_vals).any():
        ma_series.append(("月", ma20_vals, _MA20, "#fffde7"))
    if ma60_vals is not None and np.isfinite(ma60_vals).any():
        ma_series.append(("季", ma60_vals, _MA60, "#e8eaf6"))
    if ma_series:
        _paint_ma_line_labels(
            ax1,
            xs,
            highs_a,
            lows_a,
            series=ma_series,
            press_hi=float(hi) if hi else None,
            hold_lo=float(lo) if lo else None,
            spike_i=int(spike_i) if spike_i is not None else None,
            avoid_path_box=bool(path_shown) and not market_wide,
            extra_occupied=channel_label_rects,
        )

    # 除息標：必須對準該根 K 的豎虛線（x＝xs[i]）；不准把標平移離開豎線
    # 標在軸頂；豎虛線提高 z，必要時再補標底→K 高連線，對應哪根一眼可讀
    if ex_labels:
        from matplotlib.transforms import blended_transform_factory

        trans = blended_transform_factory(ax1.transData, ax1.transAxes)
        used_x: list[float] = []
        try:
            y0_ax, y1_ax = ax1.get_ylim()
            y_lo_ex = float(y0_ax)
            y_hi_ex = float(y1_ax)
        except Exception:
            y_lo_ex, y_hi_ex = float(ymin), float(ymax)
        y_span_ex = max(y_hi_ex - y_lo_ex, 1.0)
        for i, lab in ex_labels:
            near = sum(1 for ux in used_x if abs(ux - float(xs[i])) < 5.0)
            x_pos = float(xs[i])
            # 仍鎖在該根 x；左／右緣貼豎線（寬標 ha=center 會看起來像飄離虛線）
            if x_pos < max(6.0, float(n) * 0.22):
                ha = "left"
            elif x_pos > float(n) - max(6.0, float(n) * 0.22):
                ha = "right"
            else:
                ha = "center"
            y_ax = 0.965 - 0.055 * (near % 3)
            # 壓線貼軸頂時，除息標抬到軸上方（transAxes>1），減少與「大量區壓」互壓
            try:
                press_ax = (float(hi) - y_lo_ex) / y_span_ex if y_span_ex > 0 else 0.0
                if press_ax >= 0.78:
                    y_ax = min(1.06, max(y_ax + 0.06, 1.02))
            except Exception:
                pass
            # 既有 axvline z 低會被 K／帶蓋住上段；補畫標底→K 高的虛線連杆
            try:
                y_bar = float(highs[i]) if i < len(highs) and float(highs[i] or 0) > 0 else float(
                    closes[i] if i < len(closes) else 0
                )
            except (TypeError, ValueError, IndexError):
                y_bar = 0.0
            if y_bar > 0:
                y_top = y_lo_ex + y_span_ex * float(y_ax)
                y_end = min(y_top - y_span_ex * 0.018, y_hi_ex - y_span_ex * 0.008)
                if y_end > y_bar:
                    ax1.plot(
                        [x_pos, x_pos],
                        [y_bar, y_end],
                        color="#6a1b9a",
                        linewidth=1.05,
                        alpha=0.62,
                        zorder=10,
                        linestyle=(0, (2.5, 1.8)),
                        solid_capstyle="butt",
                        clip_on=False,
                    )
            ax1.text(
                x_pos,
                y_ax,
                lab,
                transform=trans,
                ha=ha,
                va="top",
                fontproperties=_fp(9, "bold"),
                color="#6a1b9a",
                zorder=11,
                clip_on=False,
                bbox=dict(
                    boxstyle="round,pad=0.22",
                    facecolor="#f3e5f5",
                    edgecolor="#6a1b9a",
                    linewidth=0.8,
                    alpha=0.95,
                ),
            )
            used_x.append(float(xs[i]))

    # v12：現任主區壓／撐沿線智能掃位（不准硬釘左緣壓 K）；下一層同套
    _KEY_Z = 22
    _mas_for_layer = [
        a for a in (ma5_vals, ma10_vals, ma20_vals, ma60_vals) if a is not None
    ]
    _key_occ: List[Tuple[float, float, float, float]] = []
    try:
        _key_occ.extend(
            [
                (float(a), float(b), float(c), float(d))
                for a, b, c, d in (channel_label_rects or [])
            ]
        )
    except Exception:
        pass
    try:
        _key_occ = _paint_key_zone_smart_tags(
            ax1,
            hi=float(hi or 0),
            lo=float(lo or 0),
            highs=np.asarray(highs, dtype=float),
            lows=np.asarray(lows, dtype=float),
            mas=_mas_for_layer,
            xmin=float(xs[0]) - 0.35 if len(xs) else -0.35,
            xmax=float(n) + 0.55,
            ymin=float(ymin),
            ymax=float(ymax),
            occupied=_key_occ,
        )
    except Exception:
        logger.debug("大量區主壓撐智能標略過 sid=%s", sid, exc_info=True)
        _key_occ = list(_key_occ or [])
    # 下一層＝小檔（LAYER_TAG_PT）；v11 smart 掃位＋整組同字級。破撐≠立刻換主區。
    if next_pack:
        try:
            from biaoke_next_support import LAYER_TAG_PT, paint_written_and_next_levels

            paint_written_and_next_levels(
                ax1,
                sid=str(sid or ""),
                next_pack=next_pack,
                xmin=float(xs[0]) - 0.35 if len(xs) else -0.35,
                xmax=float(n) + 0.55,
                right_notes=None,
                tag_size=float(LAYER_TAG_PT),
                ymin=float(ymin),
                ymax=float(ymax),
                layer_labels="smart",
                written_labels="right",
                busy_ys=(float(hi or 0), float(lo or 0)),
                highs=highs,
                lows=lows,
                mas=_mas_for_layer,
                occupied=_key_occ,
            )
        except Exception:
            logger.debug("大量區關鍵標略過 sid=%s", sid, exc_info=True)
    # 橘框日標：貼主K上框內側，不准掛表頭壓圖例；上緣擠→試右下／中右；仍撞近端 K→略過（底線不准壓 K）
    if path_shown and not market_wide:
        path_ax_y = 0.985
        path_va = "top"
        _path_place = True
        try:
            y0_ax, y1_ax = ax1.get_ylim()
            y_sp = max(float(y1_ax) - float(y0_ax), 1.0)
            tail_hi = float(
                np.nanmax(highs[max(0, int(n) - 12) : int(n)])
            ) if highs is not None and len(highs) else float(y0_ax)
            tail_lo = float(
                np.nanmin(lows[max(0, int(n) - 12) : int(n)])
            ) if lows is not None and len(lows) else float(y1_ax)
            top_busy = bool(with_nav_signals) or (
                tail_hi >= float(y0_ax) + y_sp * 0.78
            )
            if top_busy:
                path_ax_y = 0.14
                path_va = "bottom"
                mid_lo = float(y0_ax) + y_sp * 0.18
                mid_hi = float(y0_ax) + y_sp * 0.42
                if float(lo or 0) > 0 and mid_lo <= float(lo) <= mid_hi:
                    path_ax_y = 0.08
            # 資料座標粗估橘框高度≈ 0.10*ylim；撞近端高低帶→改試其他槽；再撞略過
            def _path_y_span(axy: float, va: str) -> Tuple[float, float]:
                if va == "top":
                    y_hi = float(y0_ax) + float(axy) * y_sp
                    y_lo = y_hi - y_sp * 0.10
                elif va == "bottom":
                    y_lo = float(y0_ax) + float(axy) * y_sp
                    y_hi = y_lo + y_sp * 0.10
                else:
                    mid = float(y0_ax) + float(axy) * y_sp
                    y_lo, y_hi = mid - y_sp * 0.055, mid + y_sp * 0.055
                return float(y_lo), float(y_hi)

            def _path_hits_tail(axy: float, va: str) -> bool:
                y_lo, y_hi = _path_y_span(axy, va)
                return not (y_hi < float(tail_lo) or y_lo > float(tail_hi))

            def _path_hits_key(axy: float, va: str) -> bool:
                """橘框不准蓋「大量區壓／撐」（6919 右下提示貼壓框底）。"""
                y_lo, y_hi = _path_y_span(axy, va)
                x_lo_path = float(n) * 0.55  # 右半才可能跟右槽壓撐互壓
                for ob in _key_occ or []:
                    try:
                        ox0, ox1, oy0, oy1 = (float(v) for v in ob)
                    except (TypeError, ValueError, IndexError):
                        continue
                    if ox1 < x_lo_path:
                        continue
                    if not (y_hi < oy0 or y_lo > oy1):
                        return True
                return False

            trials = [
                (path_ax_y, path_va),
                (0.14, "bottom"),
                (0.08, "bottom"),
                (0.28, "center"),
                (0.72, "center"),
                (0.85, "top"),
                (0.55, "center"),
            ]
            placed_ok = False
            for axy, va in trials:
                if _path_hits_tail(axy, va) or _path_hits_key(axy, va):
                    continue
                path_ax_y, path_va = float(axy), str(va)
                placed_ok = True
                break
            if not placed_ok:
                _path_place = False
        except Exception:
            path_ax_y, path_va = 0.985, "top"
            _path_place = True
        if _path_place:
            # 長句橘框：略離右緣＋關 clip，不准右框／「收####」被切半
            ax1.text(
                0.978,
                float(path_ax_y),
                path_shown,
                transform=ax1.transAxes,
                ha="right",
                va=str(path_va),
                fontproperties=_fp(8.2, "bold"),
                color=_CALL,
                zorder=int(_KEY_Z),
                clip_on=False,
                linespacing=1.08,
                bbox=dict(
                    boxstyle="round,pad=0.16",
                    facecolor="#fff8e1",
                    edgecolor="#ef6c00",
                    linewidth=0.75,
                    alpha=0.98,
                ),
            )

    layer_i = -1
    try:
        from biaoke_next_support import find_layer_bar_index

        layer_rows = [
            {
                "date": r.get("date"),
                "volume": r.get("volume"),
            }
            for r in view.to_dict("records")
        ]
        layer_i = find_layer_bar_index(
            layer_rows, dict((next_pack or {}).get("layer") or {})
        )
    except Exception:
        layer_i = -1
    vol_heights, vol_ylim, vol_missing = paint_lookup_volume_bars(
        ax2,
        xs,
        view["volume"],
        up_mask,
        halt=halt_arr,
        spike_i=int(spike_i),
        secondary_i=int(layer_i) if layer_i >= 0 else None,
        z=2,
    )
    spike_raw = float(vol_heights[spike_i]) if spike_i < len(vol_heights) else 0.0
    spike_h = (
        float(lookup_vol_to_display([spike_raw], float(vol_ylim))[0]) if spike_raw > 0 else 0.0
    )
    layer_h = 0.0
    if 0 <= layer_i < len(vol_heights) and layer_i != int(spike_i):
        layer_raw = float(vol_heights[layer_i] or 0)
        if layer_raw > 0:
            layer_h = float(lookup_vol_to_display([layer_raw], float(vol_ylim))[0])
    # v8 建議：量標同高並排、貼近柱頂（縮短連線）；相鄰日水平偏移更短
    # v9：量標高度吃進相鄰柱頂，白底不准壓到旁邊高峰量柱
    _peak_h = max(float(spike_h or 0), float(layer_h or 0), float(vol_ylim) * 0.35)
    try:
        _i0 = max(0, min(int(spike_i), int(layer_i if layer_i >= 0 else spike_i)) - 2)
        _i1 = min(int(n), max(int(spike_i), int(layer_i if layer_i >= 0 else spike_i)) + 3)
        for _vi in range(_i0, _i1):
            if _vi < len(vol_heights):
                _peak_h = max(_peak_h, float(vol_heights[_vi] or 0))
    except Exception:
        pass
    # 量標再抬高：白底不准壓鄰柱／右軸數字（2026-10-26 評測底線）
    vol_lab_y = float(_peak_h) * 1.18 + float(vol_ylim) * 0.05
    y_top = max(float(vol_ylim) * 1.22, float(vol_lab_y) * 1.16)
    ax2.set_ylim(0, float(y_top))

    def _vol_day_callout(
        *,
        x: float,
        y: float,
        text: str,
        edge: str,
        face: str,
        ink: str,
        side: str,
        lab_y: Optional[float] = None,
    ) -> None:
        """side=left／right／center；有 lab_y＝資料座標水平並排，否則貼柱頂。"""
        if lab_y is not None:
            # v8 建議：水平並排保留；連線改短、貼近量柱
            # 近右／左緣：文字往窗內長，不准裁成「下一層量日 10」半句
            if side == "left":
                if float(x) <= 6.0:
                    tx = max(-0.15, float(x) - 0.25)
                    ha = "left"
                else:
                    tx = max(-0.2, float(x) - 1.55)
                    ha = "right"
            elif side == "right":
                if float(x) >= float(n) - 8.0:
                    tx = min(float(n) - 0.55, float(x) + 0.25)
                    ha = "right"
                else:
                    tx = min(float(n) - 0.55, float(x) + 1.55)
                    ha = "left"
            else:
                tx = float(x)
                ha = "center"
                # 單標也在末日：改右對齊往左長
                if float(x) >= float(n) - 5.0:
                    tx = min(float(n) - 0.55, float(x) + 0.15)
                    ha = "right"
                elif float(x) <= 4.0:
                    tx = max(-0.15, float(x) - 0.15)
                    ha = "left"
            ax2.annotate(
                str(text),
                xy=(float(x), float(y)),
                xytext=(float(tx), float(lab_y)),
                ha=ha,
                va="center",
                fontproperties=_fp(9.5, "bold"),
                color=ink,
                zorder=16,
                clip_on=False,
                bbox=dict(
                    boxstyle="round,pad=0.16",
                    facecolor=face,
                    edgecolor=edge,
                    linewidth=0.65,
                    alpha=0.98,
                ),
                arrowprops=dict(
                    arrowstyle="-",
                    color=edge,
                    lw=0.85,
                    linestyle=(0, (2.2, 1.6)),
                    shrinkA=1,
                    shrinkB=2,
                ),
            )
            return
        ax2.annotate(
            str(text),
            xy=(float(x), float(y)),
            xytext=(0, 18),
            textcoords="offset points",
            ha="center",
            va="center",
            fontproperties=_fp(10.0, "bold"),
            color=ink,
            zorder=16,
            clip_on=False,
            bbox=dict(
                boxstyle="round,pad=0.16",
                facecolor=face,
                edgecolor=edge,
                linewidth=0.65,
                alpha=0.98,
            ),
            arrowprops=dict(
                arrowstyle="-",
                color=edge,
                lw=0.85,
                linestyle=(0, (2.2, 1.6)),
                shrinkA=1,
                shrinkB=2,
            ),
        )

    spike_side = "center"
    layer_side = "center"
    twin = bool(layer_h > 0 and 0 <= layer_i < int(n) and int(layer_i) != int(spike_i))
    if twin:
        if int(layer_i) < int(spike_i):
            layer_side, spike_side = "left", "right"
        else:
            layer_side, spike_side = "right", "left"

    _vol_day_callout(
        x=float(spike_i),
        y=float(spike_h),
        text=f"爆大量 {spike_md}",
        edge="#f9a825",
        face="#fffde7",
        ink="#5d4037",
        side=spike_side,
        lab_y=vol_lab_y if twin else None,
    )
    if layer_h > 0 and 0 <= layer_i < int(n):
        layer_md = _md(view["date"].iloc[layer_i]) if "date" in view.columns else ""
        _vol_day_callout(
            x=float(layer_i),
            y=float(layer_h),
            text=f"下一層量日 {layer_md}".strip(),
            edge="#42a5f5",
            face="#e3f2fd",
            ink="#0d47a1",
            side=layer_side,
            lab_y=vol_lab_y if twin else None,
        )
        try:
            ax1.axvline(
                float(layer_i),
                color="#42a5f5",
                linewidth=1.0,
                alpha=0.7,
                zorder=1,
                linestyle=(0, (1.1, 1.35)),
            )
        except Exception:
            pass
    ax2.yaxis.tick_right()
    ax2.tick_params(labelsize=10)
    configure_lookup_vol_axis(ax2, float(vol_ylim))
    ax2.set_xlim(-0.8, n - 0.2)
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.45, color=_GRID, alpha=0.85)
    for lab in ax2.get_yticklabels():
        lab.set_fontproperties(_fp(10))

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
    # 爆大量日、最後一根標月日；相鄰（≤2 根）只留最後一根，避免 10/06∥10/07 互壓
    # （爆大量日已有量柱上「爆大量 mm/dd」標，底軸不必再搶）
    last_i = n - 1
    if abs(int(spike_i) - int(last_i)) <= 2:
        _put_tick(last_i, _md(view["date"].iloc[last_i]), prefer=True)
    else:
        _put_tick(spike_i, _md(view["date"].iloc[spike_i]), prefer=True)
        _put_tick(last_i, _md(view["date"].iloc[last_i]), prefer=True)
    # 月標與「mm/dd」太近（≤4 根）→ 丟掉月標，留具體日，避免 10月∥10/07 互壓
    day_idx = {i for i, lab in tick_at.items() if "/" in str(lab)}
    for i, lab in list(tick_at.items()):
        if "/" in str(lab) or "月" not in str(lab):
            continue
        if any(abs(int(i) - int(j)) <= 4 for j in day_idx):
            del tick_at[i]
    tick_pos = sorted(tick_at)
    tick_lab = [tick_at[i] for i in tick_pos]
    # 腳註佔下排：互壓時丟月標／較早日，不准 10/22 掉到「／殘影」上（6148）
    _set_staggered_month_ticks(
        ax2, tick_lab, tick_pos, compact=False, allow_stagger=False
    )
    ax1.tick_params(labelbottom=False)

    src = str(view["quote_source"].iloc[-1] if "quote_source" in view.columns else "")
    src_note = "興櫃日均價／高低" if src == "emerging_quotes" else "官方日K原柱"
    last_ev = _latest_ex_event(official_scale_events(ex_events), last.get("date"))
    ex_title = ""
    ev_d = _bar_ymd((last_ev or {}).get("ex_date"))
    last_d = _bar_ymd(last.get("date"))
    recent_days = {_bar_ymd(x) for x in view["date"].iloc[-5:].tolist()} if n else set()
    show_ex = bool(last_ev and ev_d and (ev_d in {spike_date, last_d} or ev_d in recent_days))
    if show_ex:
        verb = phone_ex_verb(last_ev.get("kind"))
        if verb:
            amt = 0.0
            try:
                amt = float(last_ev.get("right_plus_div") or 0)
            except (TypeError, ValueError):
                amt = 0.0
            ex_title = f"　{verb} {_md(last_ev.get('ex_date'))}"
            if amt > 0:
                ex_title += f" {_fmt_price(amt)}元"
            ex_title += "（原柱不還原）"
    if with_nav_signals and ax_head is not None:
        # 標題列：兩行介紹放大＋圖例三排，緊接 K（橫式原版＝render_lookup_vol_result）
        # 已刪右上綠匡白底「收 XXXX」晶片；表頭第二排「收XXXX」稍大＋漲跌色（同源）
        head = f"{sid} {name}　大量區專圖（非買訊・{src_note}・含導航指標）"
        # 表頭「最近」開高低收：盤中跟決策卡現價同源；無現價才用官方末日柱
        face_row = last
        face_md = _md(last.get("date"))
        close_px = float(last["close"] or 0)
        prev_close_hdr = None
        if n >= 2:
            try:
                prev_close_hdr = float(view.iloc[-2]["close"])
            except (TypeError, ValueError, KeyError, IndexError):
                prev_close_hdr = None
        if hdr_quote and float(hdr_quote.get("close") or 0) > 0:
            face_row = {
                "date": hdr_quote.get("date") or last.get("date"),
                "open": hdr_quote.get("open") if hdr_quote.get("open") else last.get("open"),
                "high": hdr_quote.get("high") if hdr_quote.get("high") else last.get("high"),
                "low": hdr_quote.get("low") if hdr_quote.get("low") else last.get("low"),
                "close": hdr_quote["close"],
            }
            face_md = _md(face_row.get("date"))
            close_px = float(hdr_quote["close"])
            if hdr_quote.get("prev") is not None:
                try:
                    prev_close_hdr = float(hdr_quote["prev"])
                except (TypeError, ValueError):
                    pass
        intro_left = (
            f"爆大量 {_md(spike_date)}　壓 {_fmt_price(hi)}／撐 {_fmt_price(lo)}　"
            f"最近 {face_md} "
            f"開{_fmt_price(face_row['open'])} 高{_fmt_price(face_row['high'])} "
            f"低{_fmt_price(face_row['low'])} "
        )
        close_lab = (
            "現"
            if (hdr_quote and str(hdr_quote.get("label") or "") == "盤中")
            else "收"
        )
        close_bit = f"{close_lab}{_fmt_price(close_px)}"
        try:
            from wayne_navigator import quote_move_ink

            close_ink = quote_move_ink(
                close=float(close_px),
                prev=prev_close_hdr,
                up=_UP,
                down=_DN,
                flat="#455a64",
            )
        except Exception:
            close_ink = _TEXT
        intro_right = str(ex_title or "")
        ax_head.text(
            0.5,
            0.96,
            head,
            transform=ax_head.transAxes,
            ha="center",
            va="top",
            fontproperties=_fp(15.0, "bold"),
            color=_TEXT,
        )
        # 第二排：量測實際字寬後置中，讓「收XXXX」稍大緊接開高低；色＝漲跌
        _fp_intro = _fp(13.0, "bold")
        _fp_close = _fp(15.6, "bold")  # 收XXXX 稍大一點點
        _t_left = ax_head.text(
            0.0,
            0.78,
            intro_left,
            transform=ax_head.transAxes,
            ha="left",
            va="top",
            fontproperties=_fp_intro,
            color=_TEXT,
            zorder=12,
            alpha=0.0,
        )
        _t_close = ax_head.text(
            0.0,
            0.78,
            close_bit,
            transform=ax_head.transAxes,
            ha="left",
            va="top",
            fontproperties=_fp_close,
            color=close_ink,
            zorder=13,
            alpha=0.0,
        )
        _t_right = None
        if intro_right:
            _t_right = ax_head.text(
                0.0,
                0.78,
                intro_right,
                transform=ax_head.transAxes,
                ha="left",
                va="top",
                fontproperties=_fp_intro,
                color=_TEXT,
                zorder=12,
                alpha=0.0,
            )
        try:
            fig.canvas.draw()
            _ren = fig.canvas.get_renderer()
            _bb = ax_head.get_window_extent(renderer=_ren)
            _aw = max(float(_bb.width), 1.0)

            def _ax_w(artist) -> float:
                return float(artist.get_window_extent(renderer=_ren).width) / _aw

            _w_left = _ax_w(_t_left)
            _w_close = _ax_w(_t_close)
            _w_right = _ax_w(_t_right) if _t_right is not None else 0.0
            _w_total = _w_left + _w_close + _w_right
            _x0 = 0.5 - 0.5 * _w_total
            _t_left.set_position((_x0, 0.78))
            _t_left.set_alpha(1.0)
            _t_close.set_position((_x0 + _w_left, 0.78))
            _t_close.set_alpha(1.0)
            if _t_right is not None:
                _t_right.set_position((_x0 + _w_left + _w_close, 0.78))
                _t_right.set_alpha(1.0)
        except Exception:
            logger.exception("大量區表頭收字置中失敗 sid=%s", sid)
            _t_left.set_alpha(1.0)
            _t_close.set_alpha(1.0)
            if _t_right is not None:
                _t_right.set_alpha(1.0)
            _t_left.set_ha("right")
            _t_left.set_position((0.50, 0.78))
            _t_close.set_position((0.50, 0.78))
            if _t_right is not None:
                _t_right.set_position((0.62, 0.78))
        # 日標已改掛主K上框內側；表頭只留介紹＋圖例（原比例）
        try:
            from wayne_navigator import _draw_nav_legend

            _draw_nav_legend(ax_head, panel=True)
        except Exception:
            logger.exception("標題列圖例失敗 sid=%s", sid)
        ax1.set_title("")
    elif market_wide:
        # 左：圖名。右：橘標。下一列整行當天開高低收。橘標不准壓住價那一行。
        ax1.set_title("")
        _paint_market_vol_header(
            fig,
            ax1,
            title=f"{sid} {name}　大量區專圖（非買訊・{src_note}）",
            ohlc=(
                f"爆大量 {_md(spike_date)}　壓 {_fmt_price(hi)}／撐 {_fmt_price(lo)}　"
                f"最近 {_md(last.get('date'))} "
                f"開{_fmt_price(last['open'])} 高{_fmt_price(last['high'])} "
                f"低{_fmt_price(last['low'])} 收{_fmt_price(last['close'])}"
                f"{ex_title}"
            ),
            orange=path_shown,
        )
    else:
        title = (
            f"{sid} {name}　大量區專圖（非買訊・{src_note}）\n"
            f"爆大量 {_md(spike_date)}　壓 {_fmt_price(hi)}／撐 {_fmt_price(lo)}　"
            f"最近 {_md(last.get('date'))} "
            f"開{_fmt_price(last['open'])} 高{_fmt_price(last['high'])} "
            f"低{_fmt_price(last['low'])} 收{_fmt_price(last['close'])}"
            f"{ex_title}"
        )
        ax1.set_title(title, fontproperties=_fp(13, "bold"), pad=14, color=_TEXT)
    if with_ma5_ma10:
        ma_foot = "橙＝五日、青＝十日、黃＝月線(MA20)、藍紫＝季線(MA60)。"
    else:
        ma_foot = "黃＝月線(MA20)、藍紫＝季線(MA60)。"
    if with_nav_signals:
        foot1 = (
            f"桃色帶＝大量區（近窗仍有效爆大量日官方高低）。{ma_foot}"
            "除權／除息缺口是息差不是崩。高觸壓、收未過＝測壓（非買訊）。"
            "買點＝藍▲紅框；60低＝純藍▲。箭頭／殘影＝導航同一套。"
        )
        # 兩觀察標出現時機（灰字；永遠非買訊）
        foot2 = (
            "止穩◆＝近60低首觸後再走≥3日、期間未破該低、收在底上才亮（觀察非買）。"
            "橘六角「觀察」＝外資賣升級（超比爬升／分位）或賣超佔量≥20%才亮"
            "（還在測試・非買；千金不靠5000張）。無成交＝灰短K＋量柱貼底，不准挖洞。"
        )
    else:
        foot1 = f"桃色帶＝大量區（近窗仍有效爆大量日官方高低）。{ma_foot}除權／除息缺口是息差不是崩。"
        if with_parallel_channel:
            foot2 = (
                "高觸壓、收未過＝測壓（非買訊）。雙線＝可重算上升軌／下降壓（不數浪）；"
                "官方收破升軌則升通道失效改畫下降壓。"
                "止穩◆／橘六角見疊導航訊號的大量區或高低導航圖說。"
                "無成交＝灰短K＋量柱貼底，不准挖洞。"
            )
            if channel:
                ch_lab = str(channel.get("label") or "").strip()
                if ch_lab:
                    foot1 = f"{foot1}　{ch_lab}"
        else:
            foot2 = (
                "高觸壓、收未過＝測壓（非買訊）。"
                "止穩◆＝60低首觸後≥3日未破底；橘六角＝外資賣升級／賣超佔量≥20%（還在測試・非買）。"
                "無成交＝灰短K＋量柱貼底，不准挖洞。導航圖另按。"
            )
    fig.text(
        0.5,
        0.022,
        foot1,
        ha="center",
        va="bottom",
        fontproperties=_fp(8.2, "bold"),
        color=_MUTED,
    )
    fig.text(
        0.5,
        0.005,
        foot2,
        ha="center",
        va="bottom",
        fontproperties=_fp(8.2, "bold"),
        color=_MUTED,
    )
    # 查股順序四／壓撐大量區：墨線定稿套皮；失敗略過不准炸出圖／排程
    try:
        from ink_chart_theme import maybe_apply_ink

        maybe_apply_ink(fig, "vol")
    except Exception:
        logger.debug("大量區墨線套皮略過", exc_info=True)

    with mpl_render():
        fig.savefig(
            out,
            format="jpeg",
            dpi=_paint_dpi,
            facecolor=_BG,
            # 停價灰短柱要保得住，不准被 JPEG 抽樣吃成空白
            pil_kwargs={
                "quality": VOL_ZONE_JPEG_QUALITY,
                "optimize": False,
                "subsampling": 0,
            },
        )
    _close_lookup_figure(fig)
    return out
