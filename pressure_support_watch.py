# -*- coding: utf-8 -*-
"""壓撐觀察：同一顆鈕三種標籤（壓力橫盤／測壓未破／剛站上撐）。

只觀察，不是買訊。接既有 find_volume_zone；上市／上櫃／興櫃同一套。
只用官方日Ｋ原柱；盤中未收不當收。不准改黃金買點／海選進場。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from vol_zone_chart import VOL_ZONE_LOOKBACK, find_volume_zone, official_work

logger = logging.getLogger("WayneBot.PressureSupport")

# 大數據定案門檻（見 docs/pressure-support-three-tags-recommend.md）
SIDEWAYS_N = 2
TEST_PRESS_DIST_PCT = 0.5  # 收離壓 ≤0.5%
STAND_SUPPORT_W = 5
TEST_PRESS_TOUCH_MULT = 1.0  # 高 ≥ 壓

TAG_SIDEWAYS = "sideways"
TAG_TEST_PRESS = "test_press"
TAG_STAND_SUPPORT = "stand_support"

TAG_LABELS = {
    TAG_SIDEWAYS: "壓力橫盤",
    TAG_TEST_PRESS: "測壓未破",
    TAG_STAND_SUPPORT: "剛站上撐",
}

TAG_ORDER = (TAG_SIDEWAYS, TAG_TEST_PRESS, TAG_STAND_SUPPORT)

TAG_SUBTITLES = {
    TAG_SIDEWAYS: (
        f"同一大量區內，收在〔撐,壓〕恰好 {SIDEWAYS_N} 根日Ｋ。"
        "只觀察，不是買訊。"
    ),
    TAG_TEST_PRESS: (
        f"高≥壓、收≤壓且≥撐、收離壓≤{TEST_PRESS_DIST_PCT:g}%。"
        "量縮可加分不強制。只觀察，不是買訊。"
    ),
    TAG_STAND_SUPPORT: (
        f"從破撐回來後，收≥撐連站恰好 {STAND_SUPPORT_W} 根日Ｋ。"
        "只觀察，不是買訊。"
    ),
}

# 名單上限：話筒可讀、不塞爆
MAX_ROWS = 12
_LOOKBACK_CAL_DAYS = 120
# 同標籤短快取：連按／雙人不會重掃兩千檔（門檻／排序不變；鍵含 as_of＋是否 first 鍵）
_SCREEN_TTL_SEC = 45.0
_SCREEN_LOCK = threading.Lock()
_SCREEN_CACHE: Dict[Tuple[Any, ...], Tuple[float, List[Dict[str, Any]]]] = {}
# 同 as_of 日Ｋ框快取：換標籤不重讀庫（正確性不變）
_FRAME_TTL_SEC = 60.0
_FRAME_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, pd.DataFrame]]] = {}


def clear_pressure_screen_cache() -> None:
    with _SCREEN_LOCK:
        _SCREEN_CACHE.clear()
        _FRAME_CACHE.clear()


def tag_label(tag: str) -> str:
    return TAG_LABELS.get(str(tag or "").strip(), "")


def normalize_tag(raw: str) -> str:
    t = str(raw or "").strip()
    if t in TAG_LABELS:
        return t
    for key, label in TAG_LABELS.items():
        if t == label:
            return key
    aliases = {
        "橫盤": TAG_SIDEWAYS,
        "壓力": TAG_SIDEWAYS,
        "測壓": TAG_TEST_PRESS,
        "未破": TAG_TEST_PRESS,
        "站上撐": TAG_STAND_SUPPORT,
        "剛站": TAG_STAND_SUPPORT,
        "stand": TAG_STAND_SUPPORT,
        "test": TAG_TEST_PRESS,
        "side": TAG_SIDEWAYS,
    }
    return aliases.get(t, "")


def _ymd(val: Any) -> str:
    s = str(val or "").replace("-", "").replace("/", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _px(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def classify_bars(
    work: pd.DataFrame,
    zone: Dict[str, Any],
    *,
    tag: str,
) -> Optional[Dict[str, Any]]:
    """依最後一根官方收判斷是否符合指定標籤。zone＝find_volume_zone 結果。"""
    if work is None or getattr(work, "empty", True) or not zone:
        return None
    tag = normalize_tag(tag) or str(tag or "").strip()
    hi = _px(zone.get("high"))
    lo = _px(zone.get("low"))
    zd = _ymd(zone.get("date"))
    if hi <= 0 or lo <= 0 or hi < lo or not zd:
        return None
    dates = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    closes = pd.to_numeric(work["close"], errors="coerce")
    highs = pd.to_numeric(work["high"], errors="coerce")
    vols = (
        pd.to_numeric(work["volume"], errors="coerce").fillna(0.0)
        if "volume" in work.columns
        else pd.Series(0.0, index=work.index)
    )
    halt = (
        work["is_halt"].fillna(False).astype(bool)
        if "is_halt" in work.columns
        else pd.Series(False, index=work.index)
    )
    n = len(work)
    i = n - 1
    if halt.iloc[i]:
        return None
    cl = float(closes.iloc[i] or 0)
    hi_bar = float(highs.iloc[i] or 0)
    last_d = _ymd(dates.iloc[i])
    if cl <= 0 or not last_d or last_d <= zd:
        return None

    def _same_zone_streak_in_band() -> int:
        """同參考日壓撐下，從最新往回連續收在〔撐,壓〕天數。"""
        streak = 0
        for k in range(i, -1, -1):
            if halt.iloc[k]:
                break
            dk = _ymd(dates.iloc[k])
            if not dk or dk <= zd:
                break
            ck = float(closes.iloc[k] or 0)
            if lo <= ck <= hi:
                streak += 1
            else:
                break
        return streak

    def _stand_streak() -> Tuple[int, bool]:
        """收≥撐連站天數；回傳 (streak, from_break_ok)。

        對齊掃檔：連站前一根若在參考日之後且收仍≥撐 → 不是剛站上；
        前一根是參考日邊界則可起算。
        """
        streak = 0
        for k in range(i, -1, -1):
            if halt.iloc[k]:
                break
            dk = _ymd(dates.iloc[k])
            if not dk or dk <= zd:
                break
            ck = float(closes.iloc[k] or 0)
            if ck >= lo:
                streak += 1
            else:
                break
        if streak <= 0:
            return 0, False
        start = i - streak + 1
        ok = True
        if start - 1 >= 0:
            prev_d = _ymd(dates.iloc[start - 1])
            if prev_d and prev_d > zd and not bool(halt.iloc[start - 1]):
                if float(closes.iloc[start - 1] or 0) >= lo:
                    ok = False
        return streak, ok

    zone_vol = _px(zone.get("volume"))
    last_vol = float(vols.iloc[i] or 0)
    vol_ratio = (last_vol / zone_vol) if zone_vol > 0 and last_vol > 0 else 0.0
    dist_pct = ((hi - cl) / hi * 100.0) if hi > 0 else 99.0

    meta: Dict[str, Any] = {
        "tag": tag,
        "tag_label": tag_label(tag) or tag,
        "zone_date": zd,
        "pressure": hi,
        "support": lo,
        "close": cl,
        "high": hi_bar,
        "volume": int(last_vol),
        "vol_ratio": round(vol_ratio, 4),
        "dist_to_press_pct": round(dist_pct, 4),
        "as_of": last_d,
        "zone_active": bool(zone.get("active")),
    }

    if tag == TAG_SIDEWAYS:
        if not (lo <= cl <= hi):
            return None
        streak = _same_zone_streak_in_band()
        if streak != SIDEWAYS_N:
            return None
        meta["streak"] = streak
        meta["why"] = f"同區橫盤滿{SIDEWAYS_N}根"
        return meta

    if tag == TAG_TEST_PRESS:
        if hi_bar < hi * TEST_PRESS_TOUCH_MULT:
            return None
        if cl > hi or cl < lo:
            return None
        if dist_pct > TEST_PRESS_DIST_PCT + 1e-9:
            return None
        meta["streak"] = 1
        thin = vol_ratio > 0 and vol_ratio < 0.35
        meta["vol_thin_bonus"] = bool(thin)
        meta["why"] = (
            f"測壓貼壓{dist_pct:.2f}%" + ("、量縮加分" if thin else "")
        )
        return meta

    if tag == TAG_STAND_SUPPORT:
        streak, came = _stand_streak()
        if streak != STAND_SUPPORT_W or not came:
            return None
        meta["streak"] = streak
        meta["in_band"] = bool(cl <= hi)
        meta["why"] = f"破撐回來連站{STAND_SUPPORT_W}根"
        return meta

    return None


def _universe_ids(db_path: str) -> List[Tuple[str, str]]:
    """活躍 STOCK（上市／上櫃／興櫃）。"""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT stock_id, IFNULL(stock_name,'')
            FROM stock_universe
            WHERE is_active=1 AND UPPER(IFNULL(asset_type,''))='STOCK'
            ORDER BY stock_id
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out: List[Tuple[str, str]] = []
    for sid, name in rows:
        s = str(sid or "").strip()
        if not s:
            continue
        try:
            from universe import is_screen_equity

            if not is_screen_equity(s, str(name or "")):
                continue
        except Exception:
            pass
        out.append((s, str(name or "")))
    return out


def _load_frames(
    db_path: str, as_of: str, codes: Sequence[str]
) -> Dict[str, pd.DataFrame]:
    """批量讀官方日Ｋ（daily_quotes + emerging_quotes），不含未收／假柱。

    庫內 date 已是 YYYYMMDD 字串；直接比對、略過 REPLACE，掃檔更快。
    同 as_of 短快取：換標籤不重讀。
    """
    codes = [str(c).strip() for c in codes if str(c).strip()]
    as_of = _ymd(as_of)
    if not codes or not as_of:
        return {}
    lo = ""
    try:
        lo = (
            datetime.strptime(as_of, "%Y%m%d") - timedelta(days=_LOOKBACK_CAL_DAYS)
        ).strftime("%Y%m%d")
    except ValueError:
        lo = ""
    cache_key = (str(db_path), as_of, lo)
    now = time.monotonic()
    with _SCREEN_LOCK:
        hit = _FRAME_CACHE.get(cache_key)
        if hit and now - hit[0] <= _FRAME_TTL_SEC and hit[1]:
            return hit[1]
    conn = sqlite3.connect(db_path, timeout=60.0)
    frames: Dict[str, pd.DataFrame] = {}
    try:
        conn.execute("PRAGMA busy_timeout=15000;")
        placeholders = ",".join("?" * len(codes))
        params: List[Any] = list(codes) + [as_of]
        # 官方庫 date＝YYYYMMDD；不用 REPLACE 才能吃到索引／少掃字
        extra = " AND date <= ?"
        if lo:
            extra += " AND date >= ?"
            params.append(lo)
        for table in ("daily_quotes", "emerging_quotes"):
            try:
                df = pd.read_sql_query(
                    f"""
                    SELECT stock_id, stock_name, date, open, high, low, close, volume
                    FROM {table}
                    WHERE stock_id IN ({placeholders}) AND close > 0{extra}
                    ORDER BY stock_id, date
                    """,
                    conn,
                    params=params,
                )
            except Exception:
                continue
            if df is None or df.empty:
                continue
            df["date"] = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
            for sid, g in df.groupby("stock_id", sort=False):
                key = str(sid)
                if key in frames:
                    continue  # 已有上市櫃就不用興櫃撞號
                g = g.reset_index(drop=True)
                if str(g["date"].iloc[-1] or "")[:8] != as_of:
                    continue
                frames[key] = g
    finally:
        conn.close()
    with _SCREEN_LOCK:
        _FRAME_CACHE[cache_key] = (time.monotonic(), frames)
    return frames


def _bars_from_frame(
    df: pd.DataFrame,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """篩選用：一次抽出 numpy 柱，避開 pandas 逐格取值。"""
    if df is None or getattr(df, "empty", True):
        return None
    need = ("open", "high", "low", "close", "volume", "date")
    if any(c not in df.columns for c in need):
        return None
    dates = df["date"].astype(str).str.replace("-", "", regex=False).str[:8].to_numpy()
    o = pd.to_numeric(df["open"], errors="coerce").to_numpy(dtype=float, copy=False)
    h = pd.to_numeric(df["high"], errors="coerce").to_numpy(dtype=float, copy=False)
    l = pd.to_numeric(df["low"], errors="coerce").to_numpy(dtype=float, copy=False)
    c = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float, copy=False)
    v = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).to_numpy(dtype=float, copy=False)
    if "is_live" in df.columns:
        live = df["is_live"].fillna(False).astype(bool).to_numpy()
    else:
        live = np.zeros(len(df), dtype=bool)
    if "source" in df.columns:
        src = df["source"].astype(str).to_numpy()
        bad_src = src == "biaoke_stock_day"
    else:
        bad_src = np.zeros(len(df), dtype=bool)
    ok = (
        (c > 0)
        & (h > 0)
        & (l > 0)
        & (h >= l)
        & np.isfinite(o)
        & np.isfinite(h)
        & np.isfinite(l)
        & np.isfinite(c)
        & (~live)
        & (~bad_src)
    )
    dates, o, h, l, c, v = dates[ok], o[ok], h[ok], l[ok], c[ok], v[ok]
    if len(c) == 0:
        return None
    order = np.argsort(dates, kind="mergesort")
    dates, o, h, l, c, v = dates[order], o[order], h[order], l[order], c[order], v[order]
    halt = (v <= 0) & (np.abs(h - l) <= 1e-8)
    return dates, o, h, l, c, v, halt


def _find_volume_zone_np(
    dates: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    halt: np.ndarray,
    *,
    lookback: int = VOL_ZONE_LOOKBACK,
) -> Optional[Dict[str, Any]]:
    """與 vol_zone_chart.find_volume_zone 同準則（篩選略過除權切窗＝fast 路徑）。"""
    n = len(closes)
    if n < 2:
        return None
    end = n - 1
    start = max(0, end - max(int(lookback or 0), 1))
    last_close = float(closes[-1] or 0)
    best_i = None
    best_v = -1.0
    active_i = None
    active_v = -1.0
    for i in range(start, end):
        if bool(halt[i]):
            continue
        vv = float(vols[i] or 0)
        if vv <= 0:
            continue
        hi = float(highs[i] or 0)
        lo = float(lows[i] or 0)
        if hi <= 0 or lo <= 0 or hi < lo:
            continue
        if vv > best_v:
            best_v = vv
            best_i = i
        if hi >= last_close and vv > active_v:
            active_v = vv
            active_i = i
    pick = active_i if active_i is not None else best_i
    if pick is None:
        return None
    hi = float(highs[pick] or 0)
    lo = float(lows[pick] or 0)
    if hi <= 0 or lo <= 0 or hi < lo:
        return None
    return {
        "i": int(pick),
        "date": str(dates[pick] or ""),
        "high": hi,
        "low": lo,
        "volume": float(vols[pick] or 0),
        "active": bool(active_i is not None and pick == active_i),
    }


def _classify_bars_np(
    dates: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    halt: np.ndarray,
    zone: Dict[str, Any],
    *,
    tag: str,
) -> Optional[Dict[str, Any]]:
    """classify_bars 的 numpy 版；門檻與話筒排序欄一致。"""
    if not zone:
        return None
    tag = normalize_tag(tag) or str(tag or "").strip()
    hi = _px(zone.get("high"))
    lo = _px(zone.get("low"))
    zd = _ymd(zone.get("date"))
    if hi <= 0 or lo <= 0 or hi < lo or not zd:
        return None
    n = len(closes)
    i = n - 1
    if bool(halt[i]):
        return None
    cl = float(closes[i] or 0)
    hi_bar = float(highs[i] or 0)
    last_d = _ymd(dates[i])
    if cl <= 0 or not last_d or last_d <= zd:
        return None

    def _same_zone_streak_in_band() -> int:
        streak = 0
        for k in range(i, -1, -1):
            if bool(halt[k]):
                break
            dk = _ymd(dates[k])
            if not dk or dk <= zd:
                break
            ck = float(closes[k] or 0)
            if lo <= ck <= hi:
                streak += 1
            else:
                break
        return streak

    def _stand_streak() -> Tuple[int, bool]:
        streak = 0
        for k in range(i, -1, -1):
            if bool(halt[k]):
                break
            dk = _ymd(dates[k])
            if not dk or dk <= zd:
                break
            ck = float(closes[k] or 0)
            if ck >= lo:
                streak += 1
            else:
                break
        if streak <= 0:
            return 0, False
        start = i - streak + 1
        ok = True
        if start - 1 >= 0:
            prev_d = _ymd(dates[start - 1])
            if prev_d and prev_d > zd and not bool(halt[start - 1]):
                if float(closes[start - 1] or 0) >= lo:
                    ok = False
        return streak, ok

    zone_vol = _px(zone.get("volume"))
    last_vol = float(vols[i] or 0)
    vol_ratio = (last_vol / zone_vol) if zone_vol > 0 and last_vol > 0 else 0.0
    dist_pct = ((hi - cl) / hi * 100.0) if hi > 0 else 99.0
    meta: Dict[str, Any] = {
        "tag": tag,
        "tag_label": tag_label(tag) or tag,
        "zone_date": zd,
        "pressure": hi,
        "support": lo,
        "close": cl,
        "high": hi_bar,
        "volume": int(last_vol),
        "vol_ratio": round(vol_ratio, 4),
        "dist_to_press_pct": round(dist_pct, 4),
        "as_of": last_d,
        "zone_active": bool(zone.get("active")),
    }
    if tag == TAG_SIDEWAYS:
        if not (lo <= cl <= hi):
            return None
        streak = _same_zone_streak_in_band()
        if streak != SIDEWAYS_N:
            return None
        meta["streak"] = streak
        meta["why"] = f"同區橫盤滿{SIDEWAYS_N}根"
        return meta
    if tag == TAG_TEST_PRESS:
        if hi_bar < hi * TEST_PRESS_TOUCH_MULT:
            return None
        if cl > hi or cl < lo:
            return None
        if dist_pct > TEST_PRESS_DIST_PCT + 1e-9:
            return None
        meta["streak"] = 1
        thin = vol_ratio > 0 and vol_ratio < 0.35
        meta["vol_thin_bonus"] = bool(thin)
        meta["why"] = (
            f"測壓貼壓{dist_pct:.2f}%" + ("、量縮加分" if thin else "")
        )
        return meta
    if tag == TAG_STAND_SUPPORT:
        streak, came = _stand_streak()
        if streak != STAND_SUPPORT_W or not came:
            return None
        meta["streak"] = streak
        meta["in_band"] = bool(cl <= hi)
        meta["why"] = f"破撐回來連站{STAND_SUPPORT_W}根"
        return meta
    return None


def _ex_events_for(sid: str, db_path: str, d0: str, d1: str) -> List[Dict[str, Any]]:
    try:
        from ex_rights import load_scale_ex_events

        return list(load_scale_ex_events(sid, db_path, d0, d1) or [])
    except Exception:
        return []


def light_work(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """篩選用輕量整理：官方柱升冪＋停牌旗，不跑開市日對齊（對齊太慢）。

    出圖仍走 vol_zone_chart.official_work。
    """
    if df is None or getattr(df, "empty", True):
        return None
    work = df.copy()
    if "is_live" in work.columns:
        work = work.loc[~work["is_live"].fillna(False).astype(bool)].copy()
    if "source" in work.columns:
        work = work.loc[work["source"].astype(str) != "biaoke_stock_day"].copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in work.columns:
            return None
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work["date"] = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    work = work.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if work.empty:
        return None
    work = work.sort_values("date", kind="mergesort").reset_index(drop=True)
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


def classify_frame(
    df: pd.DataFrame,
    *,
    tag: str,
    db_path: str = "",
    sid: str = "",
    fast: bool = True,
) -> Optional[Dict[str, Any]]:
    """掃檔預設 numpy 快路徑（與舊 pandas 路徑門檻一致）；fast=False 才走除權切窗。"""
    tag = normalize_tag(tag) or str(tag or "").strip()
    if fast:
        bars = _bars_from_frame(df)
        if bars is None:
            return None
        dates, _o, highs, lows, closes, vols, halt = bars
        if len(closes) < VOL_ZONE_LOOKBACK + SIDEWAYS_N + 2:
            return None
        zone = _find_volume_zone_np(
            dates, highs, lows, closes, vols, halt, lookback=VOL_ZONE_LOOKBACK
        )
        if not zone:
            return None
        if _ymd(zone.get("date")) >= _ymd(dates[-1]):
            return None
        return _classify_bars_np(
            dates, highs, lows, closes, vols, halt, zone, tag=tag
        )
    work = official_work(df)
    if work is None or work.empty or len(work) < VOL_ZONE_LOOKBACK + SIDEWAYS_N + 2:
        return None
    d0 = _ymd(work["date"].iloc[0])
    d1 = _ymd(work["date"].iloc[-1])
    ex: List[Dict[str, Any]] = []
    if sid and db_path:
        ex = _ex_events_for(sid, db_path, d0, d1)
    zone = find_volume_zone(work, ex_events=ex or None)
    if not zone:
        return None
    if _ymd(zone.get("date")) >= d1:
        return None
    return classify_bars(work, zone, tag=tag)


def rank_key_current(r: Dict[str, Any]) -> Tuple[Any, ...]:
    """現況話筒排序：離壓近 → 量縮加分 → 代號。"""
    dist = float(r.get("dist_to_press_pct") or 99)
    thin = 0 if r.get("vol_thin_bonus") else 1
    return (dist, thin, str(r.get("stock_id") or ""))


def _attach_rank_features(df: pd.DataFrame, hit: Dict[str, Any]) -> Dict[str, Any]:
    """給靜默對質用的可重跑特徵；話筒排序不讀這些欄。"""
    work = light_work(df)
    if work is None or work.empty:
        return hit
    i = len(work) - 1
    o = float(pd.to_numeric(work["open"], errors="coerce").iloc[i] or 0)
    h = float(pd.to_numeric(work["high"], errors="coerce").iloc[i] or 0)
    l = float(pd.to_numeric(work["low"], errors="coerce").iloc[i] or 0)
    c = float(hit.get("close") or 0)
    press = float(hit.get("pressure") or 0)
    support = float(hit.get("support") or 0)
    vol_ratio = float(hit.get("vol_ratio") or 0)
    rng = h - l
    upper = h - max(o, c) if rng > 0 else 0.0
    weak_k = bool(rng > 0 and (upper / rng) >= 0.55 and ((min(o, c) - l) / rng) <= 0.25)
    dump_pause = bool(vol_ratio >= 0.8 and weak_k)
    past_pct = ((c - press) / press * 100.0) if press > 0 else 0.0
    half_mountain = bool(past_pct >= 2.0 and vol_ratio >= 0.5)
    vol_asphyx = bool(0 < vol_ratio < 0.35 and c >= support > 0)
    # 區內振幅（橫盤連站窗）
    streak = int(hit.get("streak") or 1)
    start = max(0, i - max(1, streak) + 1)
    hi_w = float(pd.to_numeric(work["high"], errors="coerce").iloc[start : i + 1].max() or 0)
    lo_w = float(pd.to_numeric(work["low"], errors="coerce").iloc[start : i + 1].min() or 0)
    mid = (press + support) / 2.0 if press > 0 and support > 0 else max(c, 1e-9)
    band_amp_pct = ((hi_w - lo_w) / mid * 100.0) if mid > 0 else 99.0
    # 洗盤站回：近窗曾收破撐、之後收站回
    wash = False
    closes = pd.to_numeric(work["close"], errors="coerce")
    for k in range(max(0, i - 10), i):
        ck = float(closes.iloc[k] or 0)
        if support > 0 and ck < support:
            later = [float(closes.iloc[j] or 0) for j in range(k + 1, i + 1)]
            if later and all(x >= support for x in later if x > 0):
                wash = True
                break
    # 無整理爆量追：量噴但近窗區內整理不足 3 根
    zd = _ymd(hit.get("zone_date"))
    dates = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    in_band = 0
    for k in range(i - 1, max(-1, i - 12), -1):
        dk = _ymd(dates.iloc[k])
        if not dk or (zd and dk <= zd):
            break
        ck = float(closes.iloc[k] or 0)
        if support > 0 and press > 0 and support <= ck <= press:
            in_band += 1
        else:
            break
    chase_no_consol = bool(vol_ratio >= 0.8 and in_band < 3 and c > press > 0)
    # 關前／歷史高附近：近 60 根高點 3% 內且無 wash／窒息
    look = work.iloc[max(0, i - 59) : i + 1]
    hist_hi = float(pd.to_numeric(look["high"], errors="coerce").max() or 0)
    near_hist_high = bool(hist_hi > 0 and c >= hist_hi * 0.97)
    # 攻擊量：整理≥3 後突破轉強第一根（收近高、量相對爆）
    attack_vol = bool(
        in_band >= 3
        and vol_ratio >= 0.8
        and rng > 0
        and c >= o
        and ((c - l) / rng) >= 0.7
    )
    dead_weak = bool(vol_ratio > 0 and vol_ratio < 0.15 and weak_k)
    hit["weak_k"] = weak_k
    hit["dump_pause"] = dump_pause
    hit["half_mountain"] = half_mountain
    hit["vol_asphyx"] = vol_asphyx
    hit["band_amp_pct"] = round(band_amp_pct, 4)
    hit["wash"] = wash
    hit["chase_no_consol"] = chase_no_consol
    hit["near_hist_high"] = near_hist_high
    hit["attack_vol"] = attack_vol
    hit["dead_weak"] = dead_weak
    hit["past_press_pct"] = round(past_pct, 4)
    hit["vol_thin_bonus"] = bool(
        hit.get("vol_thin_bonus") or (0 < vol_ratio < 0.35)
    )
    return hit


def collect_pressure_pool(
    db_path: str,
    tag: str,
    *,
    as_of: str = "",
    enrich: bool = False,
) -> List[Dict[str, Any]]:
    """資格池：結構門檻過關的全部列（未排序、未截斷）。不是買訊。"""
    tag = normalize_tag(tag)
    if not tag or not db_path:
        return []
    if not as_of:
        try:
            from import_health import latest_complete_quote_date

            as_of = str(latest_complete_quote_date(db_path) or "")
        except Exception:
            as_of = ""
    as_of = _ymd(as_of)
    if not as_of:
        return []
    universe = _universe_ids(db_path)
    if not universe:
        return []
    codes = [s for s, _ in universe]
    name_map = {s: n for s, n in universe}
    frames = _load_frames(db_path, as_of, codes)
    out: List[Dict[str, Any]] = []
    for sid, df in frames.items():
        try:
            hit = classify_frame(df, tag=tag, db_path=db_path, sid=sid)
        except Exception:
            logger.debug("pressure classify fail %s", sid, exc_info=True)
            hit = None
        if not hit:
            continue
        if enrich:
            try:
                hit = _attach_rank_features(df, hit)
            except Exception:
                pass
        name = str(name_map.get(sid) or "")
        if not name and "stock_name" in df.columns:
            name = str(df["stock_name"].iloc[-1] or "")
        item = {
            "stock_id": sid,
            "code": sid,
            "stock_name": name,
            "name": name,
            "close": hit.get("close"),
            "volume": hit.get("volume"),
            "as_of": hit.get("as_of") or as_of,
            "bucket_key": f"pressure_{tag}",
            "entry_stage_label": tag_label(tag),
            "tag": tag,
            "tag_label": tag_label(tag),
            "pressure": hit.get("pressure"),
            "support": hit.get("support"),
            "zone_date": hit.get("zone_date"),
            "dist_to_press_pct": hit.get("dist_to_press_pct"),
            "vol_ratio": hit.get("vol_ratio"),
            "vol_thin_bonus": hit.get("vol_thin_bonus"),
            "streak": hit.get("streak"),
            "why": hit.get("why"),
            "pattern": hit.get("why"),
            "entry_stars": 0,
            "buy_gate": "no",
            "buy_gate_note": "壓撐觀察不是買訊",
        }
        for fk in (
            "weak_k",
            "dump_pause",
            "half_mountain",
            "vol_asphyx",
            "band_amp_pct",
            "wash",
            "chase_no_consol",
            "near_hist_high",
            "attack_vol",
            "dead_weak",
            "past_press_pct",
        ):
            if fk in hit:
                item[fk] = hit.get(fk)
        out.append(item)
    return out


def screen_pressure_support(
    db_path: str,
    tag: str,
    *,
    as_of: str = "",
    max_rows: int = MAX_ROWS,
) -> List[Dict[str, Any]]:
    """掃活躍 STOCK，回傳符合標籤的觀察名單（非買訊）。

    預設 ``rank_key_current``＋截 ``MAX_ROWS``。
    靜默對質過閘時話筒改對應排序鍵（first／second）；飆大軌永不觸發改碼。
    """
    tag = normalize_tag(tag)
    if not tag or not db_path:
        return []
    as_of_key = _ymd(as_of)
    if not as_of_key:
        try:
            from import_health import latest_complete_quote_date

            as_of_key = _ymd(latest_complete_quote_date(db_path) or "")
        except Exception:
            as_of_key = ""
    use_first = False
    use_second = False
    try:
        from pressure_rank_verify import phone_uses_first, phone_uses_second

        use_second = bool(phone_uses_second(db_path))
        use_first = bool(phone_uses_first(db_path)) and not use_second
    except Exception:
        use_first = False
        use_second = False
    cache_key = (
        str(db_path),
        tag,
        as_of_key,
        int(max_rows or MAX_ROWS),
        bool(use_first),
        bool(use_second),
    )
    now = time.monotonic()
    with _SCREEN_LOCK:
        hit = _SCREEN_CACHE.get(cache_key)
        if hit and now - hit[0] <= _SCREEN_TTL_SEC:
            return [dict(r) for r in hit[1]]

    out = collect_pressure_pool(db_path, tag, as_of=as_of, enrich=False)
    try:
        from pressure_rank_verify import (
            SECOND_MAX_ROWS,
            phone_uses_first,
            phone_uses_second,
            rank_key_first,
            rank_key_second,
        )

        if bool(phone_uses_second(db_path)):
            out.sort(key=lambda r, t=tag: rank_key_second(t, r))
            cap = min(int(max_rows or MAX_ROWS), int(SECOND_MAX_ROWS))
            out = out[: max(1, cap)]
        elif bool(phone_uses_first(db_path)):
            out.sort(key=lambda r, t=tag: rank_key_first(t, r))
            out = out[: max(1, int(max_rows or MAX_ROWS))]
        else:
            out.sort(key=rank_key_current)
            out = out[: max(1, int(max_rows or MAX_ROWS))]
    except Exception:
        out.sort(key=rank_key_current)
        out = out[: max(1, int(max_rows or MAX_ROWS))]
    with _SCREEN_LOCK:
        _SCREEN_CACHE[cache_key] = (time.monotonic(), [dict(r) for r in out])
    return out


def pressure_card_html(item: Dict[str, Any], idx: int) -> str:
    """觀察名單卡：單位對齊、不寫買訊星等。"""
    from html import escape as html_escape

    from tg_layout import html_qty_tight
    from wayne_navigator import _fmt_price

    sid = str(item.get("stock_id") or item.get("code") or "")
    sname = str(item.get("stock_name") or item.get("name") or "")
    try:
        from stock_links import html_stock_anchor

        title = html_stock_anchor(sid, sname)
    except Exception:
        title = f"{html_escape(sid)} {html_escape(sname)}"
    tag_l = html_escape(str(item.get("tag_label") or tag_label(str(item.get("tag") or "")) or "壓撐觀察"))
    close_s = _fmt_price(item.get("close"))
    press_s = _fmt_price(item.get("pressure"))
    supp_s = _fmt_price(item.get("support"))
    vol = int(item.get("volume") or 0)
    dist = item.get("dist_to_press_pct")
    try:
        dist_s = f"{float(dist):.2f}%"
    except (TypeError, ValueError):
        dist_s = "—"
    why = html_escape(str(item.get("why") or "").strip())
    zd = _ymd(item.get("zone_date"))
    zd_s = f"{zd[4:6]}/{zd[6:8]}" if zd else "—"
    lines = [
        f"<b>{idx}.</b> {title}",
        f"標籤　{tag_l}　大量區　{zd_s}",
        f"收盤　{close_s}　壓　{press_s}　撐　{supp_s}",
        f"離壓　{dist_s}　量能　{html_qty_tight(vol, signed=False)}",
    ]
    if why:
        lines.append(f"說明　{why}")
    lines.append("<i>只觀察，不是買訊。</i>")
    return "\n".join(lines)
