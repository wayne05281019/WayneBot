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
import shutil
import sqlite3
import threading
import time
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
VOL_ZONE_TAG_PT = 16  # 壓／撐標要比標題更容易讀（話筒紅圈）
VOL_ZONE_JPEG_QUALITY = 95
VOL_ZONE_FIG_W = 12.4  # 略放大；左側空白回收給 K 區
VOL_ZONE_FIG_H_NAV = 9.35
VOL_ZONE_FIG_H_PLAIN = 7.7
# 查股單張：對齊高低卡 4:5（220DPI → 1920×2400），Telegram 縮圖寬才不獨大／變窄
VOL_ZONE_FIG_LOOKUP = (1920 / 220.0, 2400 / 220.0)
# 月線／季線＝官方收盤 MA20／MA60；畫圖前多抓暖機柱，近窗第一根就要有線
VOL_ZONE_MA20 = 20
VOL_ZONE_MA60 = 60
VOL_ZONE_MA60_WARM = 70
# 同檔同 as_of 壓力區圖短快取（名單→點股三張可複用）
_VZ_RENDER_TTL_SEC = 45.0
_VZ_RENDER_LOCK = threading.Lock()
_VZ_RENDER_MEMO: Dict[Tuple[Any, ...], Tuple[float, str, str]] = {}
_VZ_RENDER_MEMO_MAX = 64
# 畫面上線／戳後 bump
_VZ_PAINT_VER = 18

_BG = "#ffffff"
_UP = "#e53935"
_DN = "#00897b"
_FILL = "#ffe0b2"
_PRESS = "#ad1457"
_HOLD = "#1b5e20"
_SPIKE = "#f9a825"
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


def attach_official_ma20(work: pd.DataFrame, *, window: int = VOL_ZONE_MA20) -> pd.DataFrame:
    """官方收盤 SMA20（月線）。不滿窗不畫假線。"""
    if work is None or getattr(work, "empty", True):
        return work
    out = work if "ma20" in work.columns else work.copy()
    if "ma20" not in out.columns:
        out = out.copy()
    closes = pd.to_numeric(out["close"], errors="coerce")
    out["ma20"] = closes.rolling(int(window), min_periods=int(window)).mean()
    return out


def attach_official_ma60(work: pd.DataFrame, *, window: int = VOL_ZONE_MA60) -> pd.DataFrame:
    """官方收盤 SMA60（季線）。缺柱／停牌收不當正量時仍用當日官方收。"""
    if work is None or getattr(work, "empty", True):
        return work
    out = work
    if "ma60" not in out.columns:
        out = out.copy()
    closes = pd.to_numeric(out["close"], errors="coerce")
    # min_periods=window：不滿 60 根不畫假季線
    out["ma60"] = closes.rolling(int(window), min_periods=int(window)).mean()
    return out


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
) -> None:
    """月線／季線標在大圖偏左：y 一律貼在所屬均線上；只挪 x 找不壓 K 的空檔。"""
    ok = np.flatnonzero(np.isfinite(vals) & (vals > 0))
    if ok.size == 0 or len(xs) == 0:
        return
    n = len(xs)
    y0, y1 = ax.get_ylim()
    span = max(float(y1 - y0), 1.0)
    # 標盒半高（字級 11＋round pad）；左右約蓋 1.6 根，方便在線上找空檔
    half_h = span * 0.045
    pad = span * 0.012
    x_half = 1.6
    lo_i = max(0, int(n * 0.03))
    hi_i = max(lo_i + 1, int(n * 0.36))

    def _cover_range(x_lab: float) -> tuple[int, int]:
        j0 = max(0, int(np.floor(x_lab - x_half)))
        j1 = min(n - 1, int(np.ceil(x_lab + x_half)))
        return j0, j1

    def _clear_of_bars(x_lab: float, y_lab: float) -> bool:
        j0, j1 = _cover_range(x_lab)
        y_bot, y_top = y_lab - half_h, y_lab + half_h
        for k in range(j0, j1 + 1):
            hk = float(highs[k]) if np.isfinite(highs[k]) else np.nan
            lk = float(lows[k]) if np.isfinite(lows[k]) else np.nan
            if not (np.isfinite(hk) and np.isfinite(lk)):
                continue
            if y_bot < hk + pad and y_top > lk - pad:
                return False
        return True

    def _signed_gap(x_lab: float, y_lab: float) -> float:
        """線在 K 外的最小空隙；穿進 K 回負值（越負越糟）。"""
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
                # 穿進影線：負穿透深度
                best = min(best, -(min(y_top, hk) - max(y_bot, lk)))
        return float(best)

    # 只認貼線：y = 該根均線價；在左側挑最不壓 K 的 x
    clear_best = None  # (score, x, y)
    soft_best = None
    for j in ok:
        jj = int(j)
        if jj < lo_i or jj > hi_i:
            continue
        y_lab = float(vals[jj])
        if not np.isfinite(y_lab):
            continue
        yf = (y_lab - y0) / span
        if yf < 0.10 or yf > 0.92:
            continue
        x_lab = float(xs[jj])
        gap = _signed_gap(x_lab, y_lab)
        left_bonus = (hi_i - jj) / max(hi_i - lo_i, 1)
        score = gap / span + 0.22 * left_bonus
        cand = (score, x_lab, y_lab)
        if _clear_of_bars(x_lab, y_lab) and gap >= pad:
            if clear_best is None or cand[0] > clear_best[0]:
                clear_best = cand
        if soft_best is None or cand[0] > soft_best[0]:
            soft_best = cand

    if clear_best is not None:
        _, x_lab, y_lab = clear_best
    elif soft_best is not None:
        # 左側線上仍難完全淨空：仍貼線，取空隙最大處（不准離線）
        _, x_lab, y_lab = soft_best
    else:
        jj = int(ok[min(3, ok.size - 1)])
        x_lab, y_lab = float(xs[jj]), float(vals[jj])

    ax.text(
        x_lab,
        y_lab,
        lab,
        ha="center",
        va="center",
        fontproperties=_fp(11.0, "bold"),
        color=color,
        zorder=12,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.28",
            facecolor=face,
            edgecolor=color,
            linewidth=1.05,
            alpha=0.96,
        ),
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
    # 開市日軸連續（與導航同一套）：缺列＝前收停價＋量0，不准編振幅／假量
    from wayne_navigator import align_ohlc_cached

    sid_hint = ""
    if "stock_id" in work.columns:
        try:
            sid_hint = str(work["stock_id"].dropna().iloc[-1] or "")
        except Exception:
            sid_hint = ""
    work = align_ohlc_cached(work, sid_hint)
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
    need = max(int(bars) + int(lookback) + VOL_ZONE_MA60_WARM, 180)
    if db_path:
        raw = load_official_ohlc(sid, db_path, need)
        work = official_work(raw)
    if work is None or work.empty:
        if df is None or getattr(df, "empty", True):
            return None
        work = official_work(df)
    if work is None or work.empty:
        return None
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
) -> tuple[str, str]:
    """一次準備：圖＋圖說。不准畫完再重抓日K／除權息。

    with_nav_signals＝疊導航箭頭／量能訊號（壓撐觀察用；仍非買訊）。
    lookup_portrait＝舊直式 4:5 畫布（壓區名單仍可走）。查股第 4 張改橫式原版。
    """
    del already_normalized
    pack = prepare_volume_zone(
        stock_id, stock_name, db_path, save_path, df, lookback=lookback, bars=bars
    )
    if not pack:
        return "", ""
    memo_key = _vz_memo_key(
        pack["sid"],
        pack["zone"],
        pack["last"],
        with_nav_signals=with_nav_signals,
        lookback=lookback,
        bars=bars,
        lookup_portrait=lookup_portrait,
    )
    # card 會進圖說／導航；有卡就不走無卡快取，避免圖說漂移
    if not card:
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
        )
    out_path, out_cap = str(path or ""), str(cap or "")
    if out_path and not card:
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
    """查股第 4 張：大量撐壓＝橫式原版（VOL_ZONE_FIG_W×NAV），不是直式 4:5。不是買訊。"""
    return render_volume_zone_result(
        stock_id,
        stock_name,
        db_path,
        save_path,
        card=card,
        with_nav_signals=True,
        lookup_portrait=False,
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
):
    spike_md = _md(spike_date)
    ax_head = None
    # 獨立 Figure＋Agg：可與介紹／高低卡真並行，不准再用 pyplot 全域搶鎖。
    from matplotlib.gridspec import GridSpec
    from wayne_navigator import _close_lookup_figure, _new_lookup_figure

    if lookup_portrait:
        fig_size = VOL_ZONE_FIG_LOOKUP
        # 量柱列加高：高價股矮柱不准被擠沒。表頭留漲停晶片。
        head_ratios = [0.78, 4.35, 0.38, 1.72]
        head_bottom = 0.072
    else:
        fig_size = (VOL_ZONE_FIG_W, VOL_ZONE_FIG_H_NAV)
        head_ratios = [1.28, 3.38, 0.40, 0.98]
        head_bottom = 0.065

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
            right=0.935,
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
            right=0.96,
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
    # 壓／撐色線微細：仍清楚，不搶 K／均線
    ax1.axhline(hi, color=_PRESS, linewidth=1.35, zorder=5, solid_capstyle="round")
    ax1.axhline(lo, color=_HOLD, linewidth=1.35, zorder=5, solid_capstyle="round")
    # 爆大量日豎線：極小間距虛線，避免實線切過 K／量看不清
    ax1.axvline(
        spike_i,
        color=_SPIKE,
        linewidth=1.05,
        alpha=0.72,
        zorder=1,
        linestyle=(0, (1.1, 1.35)),
    )

    # 月線 MA20＋季線 MA60：近窗第一根起就要畫滿（暖機在 prepare）
    closes_v = pd.to_numeric(view["close"], errors="coerce")
    if "ma20" in view.columns:
        ma20_vals = pd.to_numeric(view["ma20"], errors="coerce").to_numpy(dtype=float)
    else:
        ma20_vals = closes_v.rolling(VOL_ZONE_MA20, min_periods=VOL_ZONE_MA20).mean().to_numpy(
            dtype=float
        )
    ma60_vals = None
    if "ma60" in view.columns:
        ma60_vals = pd.to_numeric(view["ma60"], errors="coerce").to_numpy(dtype=float)
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
    for _arr in (ma20_vals, ma60_vals):
        if _arr is None:
            continue
        ok_ma = np.isfinite(_arr) & (_arr > 0)
        if ok_ma.any():
            y_hi = max(y_hi, float(np.nanmax(_arr[ok_ma])))
            y_lo = min(y_lo, float(np.nanmin(_arr[ok_ma])))
    ymin = min(y_lo, lo) - ypad
    ymax = max(y_hi, hi) + ypad * (1.35 if with_nav_signals else 1.25)
    # 當日撐壓標抬到 K 上緣空白：多留一頭，不准壓 K／量柱／其他標
    if path_shown:
        ymax = ymax + (ymax - ymin) * 0.12
    ax1.set_ylim(ymin, ymax)
    # 左貼第一根 K、右多留空：最後一根／買點箭不貼死右軸
    ax1.set_xlim(-0.05, n + 1.65)
    if path_shown:
        # 不畫最後一根橘色豎虛線：會蓋住最新收盤 K，改只留右上事實句
        ax1.text(
            0.985,
            0.968,
            path_shown,
            transform=ax1.transAxes,
            ha="right",
            va="top",
            fontproperties=_fp(9.6, "bold"),
            color=_CALL,
            zorder=12,
            clip_on=False,
            linespacing=1.22,
            bbox=dict(
                boxstyle="round,pad=0.26",
                facecolor="#fff8e1",
                edgecolor="#ef6c00",
                linewidth=0.9,
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

    # 右軸空位補昨收（有官方昨收、且離壓／撐／現收夠遠才標，不准互壓）
    try:
        prev_c = float(view["close"].iloc[-2]) if n >= 2 else 0.0
    except (TypeError, ValueError, IndexError):
        prev_c = 0.0
    if prev_c > 0 and last_cl > 0:
        y0, y1 = ax1.get_ylim()
        span_y = max(y1 - y0, 1.0)
        near = span_y * 0.045
        anchors = [float(hi), float(lo), float(last_cl)]
        if all(abs(prev_c - a) >= near for a in anchors if a > 0):
            ax1.axhline(
                prev_c,
                color="#78909c",
                linewidth=0.85,
                linestyle=(0, (2.5, 2.0)),
                alpha=0.75,
                zorder=4,
            )
            ax1.text(
                0.995,
                prev_c,
                f"昨收 {_fmt_price(prev_c)}",
                transform=ax1.get_yaxis_transform(),
                ha="right",
                va="center",
                fontproperties=_fp(9.0, "bold"),
                color="#546e7a",
                zorder=11,
                clip_on=False,
                bbox=dict(
                    boxstyle="round,pad=0.18",
                    facecolor="#ffffff",
                    edgecolor="#90a4ae",
                    linewidth=0.8,
                    alpha=0.94,
                ),
            )

    # 查詢時間：整張底圖右上角（台北）；不進 K 區、不跟除息搶位
    try:
        from decision_card_signals import format_card_query_stamp

        last_d = _bar_ymd(last.get("date"))
        is_live = False
        if "is_live" in view.columns:
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
        date_s, clock_s = format_card_query_stamp(
            is_live=is_live,
            latest_date=last_d,
            quote_source=qs,
            listing=str((card or {}).get("listing") or "") if isinstance(card, dict) else "",
            stock_id=str(sid or ""),
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

    # 月線／季線左標：偏左、可貼均線，不准壓 K
    highs_a = pd.to_numeric(view["high"], errors="coerce").to_numpy(dtype=float)
    lows_a = pd.to_numeric(view["low"], errors="coerce").to_numpy(dtype=float)
    if ma20_vals is not None and np.isfinite(ma20_vals).any():
        _label_ma_left(
            ax1,
            xs,
            highs_a,
            lows_a,
            lab="月線",
            vals=ma20_vals,
            color=_MA20,
            face="#fffde7",
        )
    if ma60_vals is not None and np.isfinite(ma60_vals).any():
        _label_ma_left(
            ax1,
            xs,
            highs_a,
            lows_a,
            lab="季線",
            vals=ma60_vals,
            color=_MA60,
            face="#e8eaf6",
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
    spike_h = float(vol_heights[spike_i]) if spike_i < len(vol_heights) else 0.0
    # 爆大量標貼柱頂再上移一截，右下不貼底軸
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
        # 標題列：兩行介紹放大＋圖例三排，緊接 K（橫式原版）
        head = f"{sid} {name}　大量區專圖（非買訊・{src_note}・含導航指標）"
        intro = (
            f"爆大量 {_md(spike_date)}　壓 {_fmt_price(hi)}／撐 {_fmt_price(lo)}　"
            f"最近 {_md(last.get('date'))} "
            f"開{_fmt_price(last['open'])} 高{_fmt_price(last['high'])} "
            f"低{_fmt_price(last['low'])} 收{_fmt_price(last['close'])}"
            f"{ex_title}"
        )
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
        ax_head.text(
            0.5,
            0.78,
            intro,
            transform=ax_head.transAxes,
            ha="center",
            va="top",
            fontproperties=_fp(13.0, "bold"),
            color=_TEXT,
            zorder=12,
        )
        # 收盤晶片：只漲停紅底／跌停綠底，同高低卡 quote_limit_chip_colors
        try:
            from wayne_navigator import (
                _card_is_emerging,
                quote_limit_chip_colors,
                quote_limit_side,
            )

            prev_c = None
            if n >= 2:
                try:
                    prev_c = float(view["close"].iloc[-2])
                except (TypeError, ValueError, IndexError):
                    prev_c = None
            pct = None
            if prev_c and prev_c > 0 and last_cl > 0:
                pct = (last_cl - prev_c) / prev_c * 100.0
            emerging = _card_is_emerging(card) if isinstance(card, dict) else False
            side = quote_limit_side(last_cl, prev_c, pct, emerging=emerging)
            chip = quote_limit_chip_colors(side)
            up = bool(last_cl >= (prev_c or last_cl))
            if chip:
                fill, ink = chip
            else:
                fill, ink = "#ffffff", (_UP if up else _DN)
            ax_head.text(
                0.98,
                0.18,
                f"收 {_fmt_price(last_cl)}",
                transform=ax_head.transAxes,
                ha="right",
                va="center",
                fontproperties=_fp(13.0, "bold"),
                color=ink,
                zorder=14,
                bbox=dict(
                    boxstyle="round,pad=0.28",
                    facecolor=fill,
                    edgecolor=ink,
                    linewidth=1.15,
                    alpha=0.97,
                ),
            )
        except Exception:
            logger.exception("大量撐壓表頭漲停晶片失敗 sid=%s", sid)
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
    if with_nav_signals:
        foot1 = "桃色帶＝大量區（近窗仍有效爆大量日官方高低）。黃＝月線(MA20)、藍紫＝季線(MA60)。除權／除息缺口是息差不是崩。"
        foot2 = (
            "高觸壓、收未過＝測壓（非買訊）。買點＝藍▲紅框、60低＝純藍▲。"
            "箭頭／殘影＝導航同一套。無成交＝灰短K＋量柱貼底，不准挖洞。"
        )
    else:
        foot1 = "桃色帶＝大量區（近窗仍有效爆大量日官方高低）。黃＝月線(MA20)、藍紫＝季線(MA60)。除權／除息缺口是息差不是崩。"
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
