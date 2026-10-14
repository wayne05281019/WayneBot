# -*- coding: utf-8 -*-
"""查股大量區專圖：近窗仍有效的爆大量日高低＝壓／撐。

獨立一張，不改導航圖。不是買訊、不發明 5／9。
畫法對齊教學圖：白底雙欄、桃色帶、洋紅壓／綠撐、量柱黃標爆大量日。

K 棒只認官方日表原柱（daily_quotes／emerging_quotes；加權 TWII＝index_daily）：
不准除權還原、不准 MIS 盤中假柱、不准 sanitize 改高低、不准飆大疊加柱。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

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
VOL_ZONE_TAG_PT = 16  # 壓／撐標要比標題更容易讀（話筒紅圈）
VOL_ZONE_JPEG_QUALITY = 95
VOL_ZONE_FIG_W = 12.4  # 略放大；左側空白回收給 K 區
VOL_ZONE_FIG_H_NAV = 9.35
VOL_ZONE_FIG_H_PLAIN = 7.7
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
_VZ_RENDER_TTL_SEC = 45.0
_VZ_RENDER_LOCK = threading.Lock()
_VZ_RENDER_MEMO: Dict[Tuple[Any, ...], Tuple[float, str, str]] = {}
_VZ_RENDER_MEMO_MAX = 64
# 畫面上線／戳後 bump
_VZ_PAINT_VER = 32  # 平行軌標軸外右溝＋TWII 吃他點的兩天低點
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
) -> None:
    """短標 5／10／月／季：程式自動選位；只貼自己線、互避、不壓 K。不准改 OHLC／量。"""
    occupied: List[Tuple[float, float, float, float]] = []
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
) -> List[str]:
    """開市日曆日 ∩ 窗內，daily_quotes 缺列／量 NULL／櫃買張誤÷1000殘列 的日期。

    週末／休市不列。量 0＝可能真停價，不算缺列。
    source=biaoke_stock_day 且正量卻小到像股數被當張再÷1000 → 當洞重抓（不准留假小量挖洞）。
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
    return [d for d in open_days if d not in have]


# 補洞結果短記：查股暖路徑會二次 prepare，不准每次重打官方月表（CI ~2s）
_ENSURE_VOL_TTL_SEC = 180.0
_ENSURE_VOL_LOCK = threading.Lock()
_ENSURE_VOL_MEMO: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_ENSURE_VOL_MEMO_MAX = 64
# (sid, yyyymm) → 上次成功 STOCK_DAY 的日期集合（空 frozenset＝月表確認無列）
_ENSURE_MONTH_DATES: Dict[Tuple[str, str], frozenset] = {}


def clear_ensure_official_volume_cache() -> None:
    with _ENSURE_VOL_LOCK:
        _ENSURE_VOL_MEMO.clear()
        _ENSURE_MONTH_DATES.clear()


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
                for d in month_miss:
                    hit = conn_chk.execute(
                        "SELECT 1 FROM daily_quotes WHERE stock_id=? AND replace(date,'-','')=?",
                        (sid, d),
                    ).fetchone()
                    if hit:
                        force_refetch = True
                        break
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
    missing_after = missing_open_quote_days(sid, path, start, end)
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
    work = align_ohlc_cached(
        work, sid_hint, skip_invent_dates=skip_invent_dates
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


def find_volume_zone(
    work: pd.DataFrame,
    *,
    lookback: int = VOL_ZONE_LOOKBACK,
    ex_events: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """近窗仍對現價有效的爆大量日。壓還在頭上才認；已全部站上才退回絕對最大量。

    準則（鎖死）：
    1. 只用官方日 K 原柱；略過停牌、略過 biaoke_stock_day／is_live。
    2. 近窗＝最近 lookback 根（預設 40），不含「最後一根」（大量區＝過去參考日）。
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
    start = max(0, end - max(int(lookback or 0), 1))
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
        "provisional": bool(provisional),
        "ex_cut": cut,
    }


VOL_ZONE_CAPTION_HEAD = "大量區（近窗仍有效爆大量日高低＝壓／撐；測壓≠站上；非買訊）"
_PRESS_TOUCH = 0.997
_VOL_REAL = 0.70
_VOL_THIN = 0.35
_HEAT_CLAUSE = {
    "peak": "溫度在最高溫",
    "up": "溫度上升中",
    "down": "溫度下降中",
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


def _vol_clause(last_vol: float, zone_vol: float) -> str:
    if zone_vol <= 0 or last_vol <= 0:
        return ""
    ratio = last_vol / zone_vol
    if ratio >= _VOL_REAL:
        return "今天成交量對比前次大量那天仍真"
    if ratio < _VOL_THIN:
        return "今天成交量對比前次大量那天是量縮"
    return "今天成交量對比前次大量那天還是少了點"


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
                return "溫度上升中"
            return "溫度比昨天高"
    return _HEAT_CLAUSE.get(heat, "")


def _vol_heat_tail(vol_c: str, heat_c: str, heat: str) -> str:
    if vol_c and heat_c and "比昨天低" in heat_c:
        return f"{vol_c}，且{heat_c}"
    if vol_c and heat_c and heat in ("up", "peak") and "量縮" in vol_c:
        return f"{vol_c}，但{heat_c}"
    if vol_c and heat_c and heat in ("down", "floor") and "仍真" in vol_c:
        return f"{vol_c}，但{heat_c}"
    if vol_c and heat_c and heat in ("down", "floor") and "量縮" in vol_c:
        return f"{vol_c}，溫度也在退"
    bits = [x for x in (vol_c, heat_c) if x]
    return "，".join(bits)


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


def vol_zone_day_path_label(
    press: float,
    hold: float,
    last: Optional[Dict[str, Any]],
    bars: Optional[List[Dict[str, Any]]] = None,
    *,
    zone_date: str = "",
) -> str:
    """③最後一根走勢標：對應當日官方／MIS 開高低收＋既有壓撐，不是死釘『月/日 壓價』。

    例形：10月6日 撐為2,940  今最高3,055  今最低2,915  收盤未過撐  收2,920
    只留事實句；測壓次數／尚未測／壓轉撐等判斷句一律不打。不是買訊。
    bars／zone_date 保留給呼叫端相容（判斷句已刪，不再用來計次）。
    """
    del bars, zone_date  # 相容舊呼叫；當日標不再做近窗測次判斷
    if not last:
        return ""
    press = _px(press)
    hold = _px(hold)
    cl = _px(last.get("close"))
    hi = _px(last.get("high") or cl)
    lo = _px(last.get("low") or cl)
    if cl <= 0 or hi <= 0 or press <= 0 or hold <= 0 or press < hold:
        return ""
    day_zh = _date_zh_md(last.get("date"))
    if not day_zh:
        return ""
    press_s = _fmt_price(press)
    hold_s = _fmt_price(hold)
    hi_s = _fmt_price(hi)
    cl_s = _fmt_price(cl)
    lo_s = _fmt_price(lo)

    press_touch = _bar_tests_press(last, press)
    hold_touch = _bar_tests_hold(last, hold)
    if press_touch and not (cl < hold):
        side = "press"
    elif hold_touch or cl < hold:
        side = "hold"
    elif cl > press:
        side = "press"
    else:
        side = "press" if abs(cl - press) <= abs(cl - hold) else "hold"

    if side == "hold":
        verb = "收盤已過撐" if cl > hold else "收盤未過撐"
        low_bit = f"  今最低{lo_s}" if lo > 0 and lo <= hold * 1.01 else ""
        line = (
            f"{day_zh} 撐為{hold_s}  今最高{hi_s}{low_bit}  "
            f"{verb}  收{cl_s}"
        )
    else:
        verb = "收盤已過壓" if cl > press else "收盤未過壓"
        line = (
            f"{day_zh} 壓為{press_s}  今最高{hi_s}  "
            f"{verb}  收{cl_s}"
        )
    return "  ".join(line.split())


def vol_zone_position_line(
    zone: Optional[Dict[str, Any]],
    last: Optional[Dict[str, Any]],
    card: Optional[Dict[str, Any]] = None,
    bars: Optional[List[Dict[str, Any]]] = None,
    *,
    on_ex: bool = False,
) -> str:
    """依這檔在帶裡的現況換句，不是同一套填空。不寫抱、不寫賣、不改如何賣。"""
    if not zone or not last:
        return ""
    hi = _px(zone.get("high"))
    lo = _px(zone.get("low"))
    cl = _px(last.get("close"))
    if hi <= 0 or lo <= 0 or hi < lo or cl <= 0:
        return ""
    from wayne_navigator import _fmt_price

    hi_s = _fmt_price(hi)
    lo_s = _fmt_price(lo)
    rows = [dict(x) for x in (bars or _rows_from_last(last)) if isinstance(x, dict)]
    if not rows:
        rows = _rows_from_last(last)
    heat = _heat_key(card)
    heat_c = _heat_clause(card, heat)
    vol_c = _vol_clause(_px(last.get("volume")), _px(zone.get("volume")))
    tail = _vol_heat_tail(vol_c, heat_c, heat)
    last_hi = _px(last.get("high") or cl)
    # 收＝壓＝碰到上緣還沒過；只有收＞壓才算過壓
    test_press = last_hi >= hi * _PRESS_TOUCH and cl <= hi
    near_press = hi > 0 and cl <= hi and (hi - cl) / hi <= 0.015

    def _end(body: str, *, nice: bool = False, test: bool = False) -> str:
        if on_ex:
            body = body.replace("剛站在支撐線上", "剛站在除息後支撐線上")
            body = body.replace("站在支撐線上", "站在除息後支撐線上")
            body = body.replace("跌破撐", "跌破除息後撐")
        if tail:
            body = f"{body}，{tail}" if not body.endswith("。") else body[:-1] + f"，{tail}。"
        if not body.endswith("。"):
            body += "。"
        if nice:
            body += "看起來不錯！"
        elif test:
            body += "今天高碰到上緣、收沒過，只是測壓不是站上。"
        return body

    if cl < lo:
        return _end(f"收盤跌破撐{lo_s}，這根大量區撐先不當還在")
    if cl > hi:
        return _end(f"收盤已過壓{hi_s}上緣。測壓才算碰到、收過仍不是買訊")

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
            body = f"今天剛站在支撐線上，收盤{_fmt_price(cl)}還在撐{lo_s}之上，還沒過{hi_s}上緣"
            return _end(body, test=True)
        body = (
            f"今天剛站在支撐線上，收盤{_fmt_price(cl)}還在撐{lo_s}之上，"
            f"仍沒有突破{hi_s}上緣壓力"
        )
        return _end(body)

    if rising:
        body = (
            f"今天是第{n_ord}天站在支撐線上，且{n_zh}天收盤價持續攀高，"
            f"收盤仍沒有突破{hi_s}上緣壓力"
        )
        return _end(body, nice=nice, test=test_press and not nice)

    if last_down:
        body = f"今天是第{n_ord}天站在支撐線上，但今天收盤 {_fmt_price(cl)} 比昨天低"
        prev = streak[-2] if n >= 2 else {}
        prev_hi = _px(prev.get("high")) if n >= 2 else 0
        if prev_hi >= hi * _PRESS_TOUCH and not _is_zone_bar(prev, zone):
            body += f"；昨天盤中高點有碰到上緣 {hi_s}，這{n_zh}天收盤價沒有持續攀高"
            return _end(body, test=False)
        body += f"，這{n_zh}天收盤價沒有持續攀高，收盤仍沒有突破{hi_s}上緣壓力"
        return _end(body, test=test_press)

    if near_press:
        body = (
            f"今天是第{n_ord}天站在支撐線上，收盤{_fmt_price(cl)}靠近{hi_s}上緣但沒過，"
            f"仍在撐{lo_s}之上，這{n_zh}天收盤價沒有持續攀高"
        )
        return _end(body, test=test_press)

    body = (
        f"今天是第{n_ord}天站在支撐線上，收盤{_fmt_price(cl)}仍在撐{lo_s}之上，"
        f"但這{n_zh}天收盤價沒有持續攀高，收盤仍沒有突破{hi_s}上緣壓力"
    )
    return _end(body, test=test_press)


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
    """第三張圖說：原句＋除權息／跳空＋收盤口吻。如何賣仍只在介紹圖／高低卡。"""
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
    on_ex = False
    last_d = _bar_ymd((last or {}).get("date"))
    zd = _bar_ymd((zone or {}).get("date"))
    ev = _latest_ex_event(official_scale_events(events), last_d or zd)
    if ev and phone_ex_verb((ev or {}).get("kind")) and _bar_ymd(ev.get("ex_date")) in {zd, last_d}:
        on_ex = True
    note = _ex_gap_note(events, gaps, last_d or zd, zd, voice="zone")
    pos = vol_zone_position_line(zone, last, card, bars=bars, on_ex=on_ex)
    if pos:
        return f"{VOL_ZONE_CAPTION_HEAD}\n{note}{pos}" if note else f"{VOL_ZONE_CAPTION_HEAD}\n{pos}"
    if note:
        return f"{VOL_ZONE_CAPTION_HEAD}\n{note}"
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
    否則長窗推算→近窗對日期。映不上才直接用近窗算。不准發明沒說過的價／浪號。
    """
    from biaoke_chart import (
        _BARS,
        build_asc_channel_from_low_dates,
        infer_parallel_channel,
        latest_biaoke_named_rising_lows,
    )

    if view is None or getattr(view, "empty", True) or len(view) < 24:
        return {}
    date_to_i = {
        str(view.iloc[i].get("date") or "").replace("-", "")[:8]: i for i in range(len(view))
    }
    face = _bars_face_records(bars_face)
    work = face[-int(_BARS) :] if len(face) > int(_BARS) else face
    if len(work) < 24:
        work = _bars_face_records(view.to_dict("records"))

    sid = str(stock_id or "").strip().upper()
    if sid in ("TWII", "TAIEX", "^TWII") and db_path:
        named = latest_biaoke_named_rising_lows(str(db_path))
        if named:
            d1, d2, _pid = named
            ch_named = build_asc_channel_from_low_dates(work, d1, d2)
            if not ch_named:
                rows_v = _bars_face_records(view.to_dict("records"))
                ch_named = build_asc_channel_from_low_dates(rows_v, d1, d2)
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


def paint_vol_zone_parallel_channel(
    ax,
    ch: Dict[str, Any],
    *,
    n: int,
    ymin: float,
    ymax: float,
) -> None:
    """在大量區 K 上畫兩條平行軌＋右緣價標。不是買訊、不數 5／9。

    標籤（平行壓／上升軌）放軸外右溝（axesX×dataY），字級略縮；
    呼叫端須把 GridSpec right 收窄留溝，整盒才不會被圖框切斷。
    """
    if not ch or ax is None:
        return
    from matplotlib.transforms import blended_transform_factory

    from biaoke_chart import _paint_parallel_channel

    seam = float(max(n - 1, 0))
    # K 右略留空；線不過軸外標
    x0, x1 = ax.get_xlim()
    ax.set_xlim(float(x0), max(float(x1), float(n) + 1.35))
    rail_hi = float(n) + 0.35
    _paint_parallel_channel(
        ax,
        ch,
        seam=seam,
        x_lo=-0.05,
        x_hi=rail_hi,
        y_lo=float(ymin),
        y_hi=float(ymax),
        n=int(n),
    )
    # 右緣價標：上升軌／平行壓 或 下降壓／平行撐（跟結構圖用語同一套）
    name_u = str(ch.get("name_u") or "上軌")
    name_l = str(ch.get("name_l") or "下軌")
    rail = float(ch.get("rail_now") or 0)
    base = float(ch.get("base_now") or 0)
    kind = str(ch.get("kind") or "")
    color = "#1565c0" if kind == "asc" else "#6a1b9a"
    if not bool(ch.get("alive")):
        color = "#90a4ae"
    y_span = max(float(ymax) - float(ymin), 1.0)
    # (顯示Y, 標名, 真價)——錯開只動顯示Y，價標仍用真價
    items: List[Tuple[float, str, float]] = []
    for y, lab in ((rail, name_u), (base, name_l)):
        if y > 0:
            items.append((float(y), str(lab), float(y)))
    if len(items) == 2 and abs(items[0][0] - items[1][0]) < y_span * 0.045:
        mid = (items[0][0] + items[1][0]) / 2.0
        gap = y_span * 0.028
        if items[0][0] >= items[1][0]:
            items = [
                (mid + gap, items[0][1], items[0][2]),
                (mid - gap, items[1][1], items[1][2]),
            ]
        else:
            items = [
                (mid - gap, items[0][1], items[0][2]),
                (mid + gap, items[1][1], items[1][2]),
            ]
    # 軸外右溝：X＝axes 分數、Y＝價；clip_on=False 才能畫進 GridSpec 預留溝
    trans = blended_transform_factory(ax.transAxes, ax.transData)
    for y_disp, lab, y_px in items:
        y_draw = min(
            max(float(y_disp), float(ymin) + y_span * 0.02),
            float(ymax) - y_span * 0.02,
        )
        ax.text(
            1.085,
            y_draw,
            f"{lab} {_fmt_price(y_px)}",
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


def prepare_volume_zone(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    save_path: str = None,
    df=None,
    *,
    lookback: int = VOL_ZONE_LOOKBACK,
    bars: int = VOL_ZONE_BARS,
) -> Optional[Dict[str, Any]]:
    """官方原柱＋除權息完成稿＋壓撐窗。HTTP 補抓在畫布鎖外。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return None
    work = None
    need = lookup_vol_ensure_days(lookback=lookback, bars=bars)
    skip_invent: set = set()
    vol_ensure: Dict[str, Any] = {}
    if db_path:
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
) -> tuple[str, str]:
    """一次準備：圖＋圖說。不准畫完再重抓日K／除權息。

    with_nav_signals＝疊導航箭頭／量能訊號（壓撐觀察用；仍非買訊）。
    lookup_portrait＝舊直式 4:5 畫布（壓區名單仍可走）。查股第 4 張改橫式原版。
    with_parallel_channel＝疊可重算上升軌／下降壓兩條平行線（大盤大量區用；不數浪、非買訊）。
    with_ma5_ma10＝疊官方五日／十日線（橙／青；與月／季並列；非買訊）。
    預設 True＝話筒／勝率／壓撐／大盤同一新臉；測試要舊臉才顯式傳 False。
    """
    del already_normalized
    pack = prepare_volume_zone(
        stock_id, stock_name, db_path, save_path, df, lookback=lookback, bars=bars
    )
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
    )


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
):
    spike_md = _md(spike_date)
    ax_head = None
    channel: Dict[str, Any] = {}
    # 獨立 Figure＋Agg：可與介紹／高低卡真並行，不准再用 pyplot 全域搶鎖。
    from matplotlib.gridspec import GridSpec
    from wayne_navigator import _close_lookup_figure, _new_lookup_figure

    if lookup_portrait:
        fig_size = VOL_ZONE_FIG_LOOKUP
        # 量柱列加高：高價股矮柱不准被擠沒。表頭不再放收盤晶片。
        head_ratios = [0.78, 4.35, 0.38, 1.72]
        head_bottom = 0.072
    else:
        fig_size = (VOL_ZONE_FIG_W, VOL_ZONE_FIG_H_NAV)
        head_ratios = [1.28, 3.38, 0.40, 0.98]
        head_bottom = 0.065

    # 平行軌右緣標（平行壓／上升軌）要完整：右溝加寬（過右軸刻度），標放軸外不進 K
    _gs_right = 0.72 if with_parallel_channel else (0.935 if with_nav_signals else 0.96)
    if with_nav_signals:
        # 獨立標題列：股票介紹＋圖例同一塊；中間整列給 K，不准標題／圖例之間留大空白
        fig = _new_lookup_figure(fig_size, VOL_ZONE_DPI, _BG)
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
            VOL_ZONE_FIG_LOOKUP if lookup_portrait else (VOL_ZONE_FIG_W, VOL_ZONE_FIG_H_PLAIN),
            VOL_ZONE_DPI,
            _BG,
        )
        gs = GridSpec(
            2,
            1,
            figure=fig,
            height_ratios=[4.85, 1.85] if lookup_portrait else [3.4, 1.05],
            hspace=0.055,
            left=0.04,
            right=_gs_right,
            top=0.88,
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
        ax1.axvline(xs[i], color="#6a1b9a", linewidth=1.05, alpha=0.5, zorder=1, linestyle=(0, (2.5, 1.8)))
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
        path_msg = vol_zone_day_path_label(
            float(hi), float(lo), last_bar, bars=bars_face, zone_date=str(spike_date or "")
        )
        if path_msg and last_hi > 0 and float(hi) > 0:
            bits = [p for p in path_msg.split("  ") if p]
            # 兩行事實句：日＋撐／壓｜今高（今低）過未過＋收；不准再堆第三行判斷
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
    # 狀況簡述已改掛表頭時不再為它抬 K 頂；無表頭才略留空
    if path_shown and not with_nav_signals:
        ymax = ymax + (ymax - ymin) * 0.08
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
    ax1.set_ylim(ymin, ymax)
    # 左貼第一根 K、右多留空：最後一根／買點箭不貼死右軸
    # 右略鬆給末日 K／收價；均線標改放左半／中段，不搶近端
    ax1.set_xlim(-0.05, n + 2.15)
    if with_parallel_channel and channel:
        try:
            paint_vol_zone_parallel_channel(
                ax1, channel, n=int(n), ymin=float(ymin), ymax=float(ymax)
            )
        except Exception:
            logger.exception("大量區畫平行軌失敗 sid=%s", sid)
    # 有獨立表頭時狀況簡述只掛表頭右下；無表頭才掛 K 頂外。不准壓末日導航箭。
    if path_shown and not (with_nav_signals and ax_head is not None):
        ax1.text(
            0.995,
            1.012,
            path_shown,
            transform=ax1.transAxes,
            ha="right",
            va="bottom",
            fontproperties=_fp(9.0, "bold"),
            color=_CALL,
            zorder=12,
            clip_on=False,
            linespacing=1.15,
            bbox=dict(
                boxstyle="round,pad=0.20",
                facecolor="#fff8e1",
                edgecolor="#ef6c00",
                linewidth=0.85,
                alpha=0.96,
            ),
        )
    ax1.yaxis.tick_right()
    ax1.tick_params(labelbottom=False, labelsize=10)
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.45, color=_GRID, zorder=0, alpha=0.85)
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(10))

    # 壓／撐標：回圖內左上／左下原位（微調內縮），不准挪到軸外把 K 擠小
    _tag_box = dict(
        boxstyle="round,pad=0.30",
        facecolor="#ffffff",
        linewidth=1.15,
        alpha=0.94,
    )
    ax1.text(
        0.012,
        0.975,
        f"大量區壓 {_fmt_price(hi)}",
        transform=ax1.transAxes,
        ha="left",
        va="top",
        fontproperties=_fp(VOL_ZONE_TAG_PT, "bold"),
        color=_PRESS,
        zorder=10,
        bbox={**_tag_box, "edgecolor": _PRESS},
    )
    ax1.text(
        0.012,
        0.025,
        f"大量區撐 {_fmt_price(lo)}",
        transform=ax1.transAxes,
        ha="left",
        va="bottom",
        fontproperties=_fp(VOL_ZONE_TAG_PT, "bold"),
        color=_HOLD,
        zorder=10,
        bbox={**_tag_box, "edgecolor": _HOLD},
    )

    # 大量區右軸／表頭：已刪綠匡白底「收」晶片；不准再畫「昨收」白底標

    # 查詢時間：整張底圖右上角（台北）；不進 K 區、不跟除息搶位。
    # 盤中有決策卡現價時，戳與高低卡／介紹同源（含興櫃）；K 主體仍只吃官方原柱。
    hdr_quote = None
    try:
        from live_quote import display_quote_from_card

        hdr_quote = display_quote_from_card(card if isinstance(card, dict) else None)
    except Exception:
        hdr_quote = None
    try:
        from decision_card_signals import format_card_query_stamp

        last_d = _bar_ymd(last.get("date"))
        is_live = bool(hdr_quote and hdr_quote.get("is_live"))
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
        if hdr_quote and hdr_quote.get("is_live") and hdr_quote.get("date"):
            stamp_date = _bar_ymd(hdr_quote.get("date"))
        elif isinstance(card, dict) and card.get("is_live") and card.get("latest_date"):
            stamp_date = _bar_ymd(card.get("latest_date"))
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
            signal_work = None
            if db_path:
                try:
                    signal_work = _load_ohlc(str(sid), str(db_path), 180)
                except Exception:
                    logger.exception("大量區載入導航 180 日失敗 sid=%s", sid)
                    signal_work = None
            # 圖例改畫在標題列，不准掛在 K 上方留白；均線已在上方畫好
            overlay_nav_marks_on_zone(
                ax1,
                ax_sig,
                view,
                card=card,
                draw_legend=False,
                draw_ma20=False,
                signal_work=signal_work,
            )
        except Exception:
            logger.exception("大量區疊導航指標失敗 sid=%s", sid)

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
            avoid_path_box=bool(path_shown),
        )

    # 除息標：貼豎線上方、避開左上壓標；不准大抬 ylim 把 K 壓扁
    if ex_labels:
        from matplotlib.transforms import blended_transform_factory

        trans = blended_transform_factory(ax1.transData, ax1.transAxes)
        left_guard = max(n * 0.20, 14.0)
        used_x: list[float] = []
        for i, lab in ex_labels:
            near = sum(1 for ux in used_x if abs(ux - float(xs[i])) < 5.0)
            x_pos = float(xs[i])
            ha = "center"
            # 除息標貼軸頂，避開 K 頂／壓標
            y_ax = 0.965 - 0.055 * (near % 3)
            if x_pos < left_guard:
                x_pos = left_guard
                ha = "left"
                y_ax = 0.94 - 0.05 * (near % 3)
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

    vol_heights, vol_ylim, vol_missing = paint_lookup_volume_bars(
        ax2,
        xs,
        view["volume"],
        up_mask,
        halt=halt_arr,
        spike_i=int(spike_i),
        z=2,
    )
    spike_raw = float(vol_heights[spike_i]) if spike_i < len(vol_heights) else 0.0
    spike_h = (
        float(lookup_vol_to_display([spike_raw], float(vol_ylim))[0]) if spike_raw > 0 else 0.0
    )
    # 爆大量標貼柱頂再上移一截，右下不貼底軸；ylim 以視窗 max 顯示高為準
    ax2.set_ylim(0, max(vol_ylim * 1.30, spike_h * 1.38 if spike_h > 0 else vol_ylim * 1.30))
    ax2.annotate(
        f"爆大量 {spike_md}",
        xy=(float(spike_i), spike_h),
        xytext=(0, 18),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontproperties=_fp(10.0, "bold"),
        color="#5d4037",
        zorder=6,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.16",
            facecolor="#fffde7",
            edgecolor="#f9a825",
            linewidth=0.65,
            alpha=0.95,
        ),
    )
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
    # 與導航同一套：能排下單排；會互壓才錯開
    _set_staggered_month_ticks(ax2, tick_lab, tick_pos, compact=False)
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
        close_lab = "現" if (hdr_quote and hdr_quote.get("is_live")) else "收"
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
        # 狀況簡述掛表頭中右（圖例右側／介紹列下），離開 K 頂與末日導航箭
        if path_shown:
            ax_head.text(
                0.995,
                0.48,
                path_shown,
                transform=ax_head.transAxes,
                ha="right",
                va="center",
                fontproperties=_fp(8.6, "bold"),
                color=_CALL,
                zorder=15,
                clip_on=True,
                linespacing=1.10,
                bbox=dict(
                    boxstyle="round,pad=0.16",
                    facecolor="#fff8e1",
                    edgecolor="#ef6c00",
                    linewidth=0.75,
                    alpha=0.96,
                ),
            )
        try:
            from wayne_navigator import _draw_nav_legend

            _draw_nav_legend(ax_head, panel=True)
        except Exception:
            logger.exception("標題列圖例失敗 sid=%s", sid)
        ax1.set_title("")
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
        foot1 = f"桃色帶＝大量區（近窗仍有效爆大量日官方高低）。{ma_foot}除權／除息缺口是息差不是崩。"
        foot2 = (
            "高觸壓、收未過＝測壓（非買訊）。買點＝藍▲紅框、60低＝純藍▲。"
            "箭頭／殘影＝導航同一套。無成交＝灰短K＋量柱貼底，不准挖洞。"
        )
    else:
        foot1 = f"桃色帶＝大量區（近窗仍有效爆大量日官方高低）。{ma_foot}除權／除息缺口是息差不是崩。"
        if with_parallel_channel:
            foot2 = (
                "高觸壓、收未過＝測壓（非買訊）。雙線＝可重算上升軌／下降壓（不數浪）。"
                "無成交＝灰短K＋量柱貼底，不准挖洞。"
            )
            if channel:
                ch_lab = str(channel.get("label") or "").strip()
                if ch_lab:
                    foot1 = f"{foot1}　{ch_lab}"
        else:
            foot2 = "高觸壓、收未過＝測壓（非買訊）。無成交＝灰短K＋量柱貼底，不准挖洞。導航圖另按。"
    fig.text(
        0.5,
        0.022,
        foot1,
        ha="center",
        va="bottom",
        fontproperties=_fp(8.5, "bold"),
        color=_MUTED,
    )
    fig.text(
        0.5,
        0.006,
        foot2,
        ha="center",
        va="bottom",
        fontproperties=_fp(8.5, "bold"),
        color=_MUTED,
    )
    with mpl_render():
        fig.savefig(
            out,
            format="jpeg",
            dpi=VOL_ZONE_DPI,
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
