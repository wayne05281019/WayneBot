#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多軌準度第 3 輪：同一輪全量（凍結 R0–R7＋R1e／R1f／R1g）。

硬規則：
- 不准假數；分軌；全樣＋留白雙閘；n≥20；未過閘不准改買訊／不上殘影假買臉
- 不改剛離零／黃金買點公式；不動排程鐘點；興櫃橘六角跳過
- 不重跑第 2 輪已棄 wait_N／粗 hi_vol_shrink 全市場三分位
- 裸 K 鎖死：R1／R1e／R1f／R1g／R4 附加形只准開高低收＋量
- 不准自行加凍結未鎖的新 R 條

用法：
  .venv/bin/python scripts/multi_track_round3.py --db data/wayne_market.db --out /tmp/mt_round3.json
  .venv/bin/python scripts/multi_track_round3.py --smoke
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from foreign_sell_display import DISPLAY_SELL_SHARE_THR  # noqa: E402
from foreign_sell_escalate import (  # noqa: E402
    cross_sectional_percentile,
    current_params,
    evaluate_escalate_A,
    sell_share,
)
from foreign_sell_extreme import ExtremeTrack, lit_extreme_day  # noqa: E402
from stabilize_watch import (  # noqa: E402
    BREAK_TOL,
    HOLD_N,
    HOLD_N_NEXT,
    LOOKBACK,
    _held_after_touch,
    _l60_first_touch_indices,
)

from foreign_sell_calm import (  # noqa: E402
    buy_share as _buy_share,
    current_buy_params,
    evaluate_buy_escalate_A,
)
from multi_track_baseline_backtest import (  # noqa: E402
    DEDUP_N,
    load_stock_df,
    load_twii,
    load_universe,
    stabilize_fire_indices,
    summarize_rets,
)
from multi_track_step2_candidates import (  # noqa: E402
    LOCKED_HOLDOUT,
    MARKETS,
    MIN_N_DAYS,
    MIN_WR_LIFT,
    PRIMARY_H,
    Entry,
    _fast_forward,
    _f,
    _ymd,
    cand_signal_vol_tercile,
    find_signal_indices,
    score_entries_split,
    verdict_for,
)

TP = ZoneInfo("Asia/Taipei")
PRICE_TRACKS = ("A1", "A2", "A5", "A7")
R1_TRACKS = ("A1", "A2")
R2_TRACKS = ("A2", "A7")
R3_TRACKS = ("A1", "A2", "A5", "A7")
TEACH_V1, TEACH_V2, TEACH_V3 = "20261005", "20261013", "20261015"
# 觀察／風險形：不算可換買訊
OBS_CANDS = {
    "R1d_trap_ctrl",
    "R1e1_shape",
    "R1e2_shape",
    "R1e3_after_dump",
    "R1e3_no_dump",
    "R1e4_after_dump",
    "R1e4_no_dump",
    "R1f3_after_triple",
    "R1f4_single_vol",
    "R1g3_break_no_vol",
    "R1g3_break_with_vol",
    "R1g4_triple_then_break_quiet",
    "R5_uncond",
    "R5a_pressure_calm",
    "R5b_pressure_worse",
    "R5_buy_uncond",
    "R5c_buy_hi_vol",
    "R4b_first_light",
}


def _now_iso() -> str:
    return datetime.now(TP).isoformat(timespec="seconds")


def _pctile(xs: Sequence[float], p: float) -> Optional[float]:
    arr = [float(x) for x in xs if x is not None and x == x]
    if len(arr) < 3:
        return None
    return float(np.percentile(np.asarray(arr, dtype=float), p))


def _own_vol_ge_pct(df: pd.DataFrame, i: int, *, lookback: int, pct: float) -> bool:
    if i < 0 or i >= len(df):
        return False
    lo = max(0, i + 1 - lookback)
    vols = [_f(v) for v in df["volume"].iloc[lo:i].tolist()]
    vols = [v for v in vols if v is not None and v > 0]
    vt = _f(df["volume"].iloc[i])
    thr = _pctile(vols, pct) if vols else None
    if vt is None or thr is None or vt <= 0:
        return False
    return vt >= thr


def _own_vol_le_median(df: pd.DataFrame, i: int, *, lookback: int = 20) -> bool:
    if i < 1 or i >= len(df):
        return False
    lo = max(0, i - lookback)
    vols = [_f(v) for v in df["volume"].iloc[lo:i].tolist()]
    vols = [v for v in vols if v is not None and v > 0]
    vt = _f(df["volume"].iloc[i])
    if vt is None or len(vols) < 5:
        return False
    return vt <= float(np.median(vols))


def find_hi_vol_day(df: pd.DataFrame, i_sig: int, *, look: int = 1) -> Optional[int]:
    for j in range(i_sig, min(len(df), i_sig + look + 1)):
        if _own_vol_ge_pct(df, j, lookback=20, pct=90.0):
            return j
    return None


# ---- R1 套牢／換籌（裸 K＋量）----


def cand_r1a(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    n = len(df)
    hv = find_hi_vol_day(df, i_sig, look=1)
    if hv is None:
        return None
    lo_hv = _f(df["low"].iloc[hv])
    hi_hv = _f(df["high"].iloc[hv])
    if lo_hv is None or hi_hv is None or lo_hv <= 0:
        return None
    broke = False
    end = min(n - 2, hv + 8)
    for j in range(hv + 1, end + 1):
        cj = _f(df["close"].iloc[j])
        if cj is None:
            continue
        if not broke:
            if cj < lo_hv:
                broke = True
            continue
        if cj > hi_hv:
            return j + 1 if j + 1 < n else None
    return None


def cand_r1b(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    n = len(df)
    hv = find_hi_vol_day(df, i_sig, look=1)
    if hv is None:
        return None
    lo_hv = _f(df["low"].iloc[hv])
    hi_hv = _f(df["high"].iloc[hv])
    if lo_hv is None or hi_hv is None or lo_hv <= 0:
        return None
    sideways = 0
    end = min(n - 2, hv + 10)
    for j in range(hv + 1, end + 1):
        cj = _f(df["close"].iloc[j])
        if cj is None:
            continue
        if lo_hv <= cj <= hi_hv:
            sideways += 1
            continue
        if sideways >= 2 and cj > hi_hv:
            return j + 1 if j + 1 < n else None
        if cj < lo_hv:
            return None
        if cj > hi_hv and sideways < 2:
            return None
    return None


def cand_r1c(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    n = len(df)
    hv = find_hi_vol_day(df, i_sig, look=1)
    if hv is None or hv + 3 >= n:
        return None
    lo_hv = _f(df["low"].iloc[hv])
    v0 = _f(df["volume"].iloc[hv])
    c0 = _f(df["close"].iloc[hv])
    if lo_hv is None or v0 is None or c0 is None:
        return None
    v1 = _f(df["volume"].iloc[hv + 1])
    v2 = _f(df["volume"].iloc[hv + 2])
    c1 = _f(df["close"].iloc[hv + 1])
    c2 = _f(df["close"].iloc[hv + 2])
    if None in (v1, v2, c1, c2):
        return None
    if not (v1 < v0 and v2 < v1 and c1 < c0 and c2 < c1):
        return None
    if c1 < lo_hv or c2 < lo_hv:
        return None
    return hv + 3


def cand_r1d_trap_control(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    n = len(df)
    hv = find_hi_vol_day(df, i_sig, look=1)
    if hv is None or hv + 2 >= n:
        return None
    lo_hv = _f(df["low"].iloc[hv])
    c1 = _f(df["close"].iloc[hv + 1])
    if lo_hv is None or c1 is None:
        return None
    if c1 < lo_hv:
        return hv + 2
    return None


# ---- R1e 沖高倒貨（裸 K＋量）----


def r1e1_at(df: pd.DataFrame, i: int) -> bool:
    if i < 1 or i >= len(df):
        return False
    o = _f(df["open"].iloc[i])
    h = _f(df["high"].iloc[i])
    l = _f(df["low"].iloc[i])
    c = _f(df["close"].iloc[i])
    prev = _f(df["close"].iloc[i - 1])
    if None in (o, h, l, c, prev) or prev <= 0 or h <= l:
        return False
    if (h - c) / (h - l) < 0.6:
        return False
    if not _own_vol_ge_pct(df, i, lookback=20, pct=80.0):
        return False
    max_gain = (h - prev) / prev
    close_gain = (c - prev) / prev
    open_run = (h - o) / o if o > 0 else 0.0
    if max_gain <= 0.01:
        return False
    if open_run < 0.015 and max_gain < 0.03:
        return False
    if close_gain > max_gain * 0.4:
        return False
    return True


def r1e2_at(df: pd.DataFrame, i: int) -> bool:
    if not r1e1_at(df, i):
        return False
    o = _f(df["open"].iloc[i])
    h = _f(df["high"].iloc[i])
    l = _f(df["low"].iloc[i])
    c = _f(df["close"].iloc[i])
    if None in (o, h, l, c) or h <= l:
        return False
    return c < o or c <= l + (h - l) / 3.0


# ---- R1f 買方三連套（裸 K＋量）----


@dataclass
class TripleTrap:
    v1: int
    v2: int
    v3: int


def _is_big_down(df: pd.DataFrame, i: int) -> bool:
    o = _f(df["open"].iloc[i])
    c = _f(df["close"].iloc[i])
    prev = _f(df["close"].iloc[i - 1]) if i >= 1 else None
    h = _f(df["high"].iloc[i])
    l = _f(df["low"].iloc[i])
    if None in (o, c) or o <= 0:
        return False
    body = (o - c) / o
    if c >= o:
        return False
    if body < 0.01 and (prev is None or prev <= 0 or (c - prev) / prev > -0.015):
        return False
    if h is not None and l is not None and h > l:
        # 大陰：實體佔振幅偏大或收近低
        if (o - c) / (h - l) < 0.45 and (c - l) / (h - l) > 0.35:
            if prev is None or (c - prev) / prev > -0.02:
                return False
    return True


def detect_triple_traps(
    df: pd.DataFrame,
    *,
    lookback: int = 40,
    max_gap: int = 25,
) -> List[TripleTrap]:
    """掃描買方三連套（僅 OHLC＋量）。回傳以 V3 日為完成點的事件。"""
    n = len(df)
    if n < lookback + 5:
        return []
    vols = [_f(v) or 0.0 for v in df["volume"].tolist()]
    closes = [_f(c) for c in df["close"].tolist()]
    out: List[TripleTrap] = []
    last_v3 = -10**9
    for i in range(lookback, n):
        # V1：近 lookback 窗上漲段自身最大量（窗內最高收附近、量最大）
        w0 = i - lookback
        window = list(range(w0, i + 1))
        # 只在完成點往回找：要求存在 V1<V2<V3=i
        # 候選 V3＝當日量＝近窗最大（或 ≥ 近窗 95 分位）且大陰
        wvols = [vols[j] for j in window if vols[j] > 0]
        if len(wvols) < 10:
            continue
        vmax = max(wvols)
        if vols[i] < vmax * 0.98 or not _is_big_down(df, i):
            continue
        # 找 V1：在 i 之前、收盤相對高、量為當時窗最大之一
        v1 = None
        best_v = -1.0
        for j in range(w0, i - 2):
            cj = closes[j]
            if cj is None or vols[j] <= 0:
                continue
            # 上漲段近似：收 ≥ 近 5 日低＋半幅，或相對 10 日前上漲
            c_back = closes[j - 5] if j >= 5 else None
            upish = c_back is not None and cj >= c_back
            if not upish:
                continue
            if vols[j] > best_v:
                best_v = vols[j]
                v1 = j
        if v1 is None or best_v <= 0:
            continue
        c_v1 = closes[v1]
        if c_v1 is None:
            continue
        # V2：V1 後、V3 前，次大量且收在 V1 之下
        v2 = None
        second = -1.0
        for j in range(v1 + 1, i):
            cj = closes[j]
            if cj is None or vols[j] <= 0:
                continue
            if cj >= c_v1:
                continue
            # 次大量：≥ V1 量的 0.7 或近窗 85 分位
            thr = max(best_v * 0.7, _pctile([vols[k] for k in range(v1, j + 1) if vols[k] > 0], 85) or 0)
            if vols[j] < thr:
                continue
            if vols[j] > second:
                second = vols[j]
                v2 = j
        if v2 is None:
            continue
        if i - v1 > max_gap:
            continue
        if vols[i] < max(best_v, second) * 0.95:
            continue
        if i - last_v3 < 5:
            continue
        out.append(TripleTrap(v1=int(v1), v2=int(v2), v3=int(i)))
        last_v3 = i
    return out


def v_reversal_hit(df: pd.DataFrame, trap: TripleTrap, *, within: int = 10) -> bool:
    """V 轉：收復 V3 高，或連 3 陽且收破 V2 高。"""
    n = len(df)
    hi_v3 = _f(df["high"].iloc[trap.v3])
    hi_v2 = _f(df["high"].iloc[trap.v2])
    if hi_v3 is None or hi_v2 is None:
        return False
    end = min(n - 1, trap.v3 + within)
    up_streak = 0
    for j in range(trap.v3 + 1, end + 1):
        c = _f(df["close"].iloc[j])
        o = _f(df["open"].iloc[j])
        if c is None:
            continue
        if c > hi_v3:
            return True
        if o is not None and c > o:
            up_streak += 1
        else:
            up_streak = 0
        if up_streak >= 3 and c > hi_v2:
            return True
    return False


def kill_volume_then_stabilize(
    df: pd.DataFrame, start_i: int, *, within: int = 15
) -> Optional[int]:
    """下殺取量：放量跌後，之後縮量且收不破該殺日低 ≥2 日 → 回傳止跌確認日。"""
    n = len(df)
    end = min(n - 3, start_i + within)
    for j in range(start_i + 1, end + 1):
        if not _own_vol_ge_pct(df, j, lookback=20, pct=80.0):
            continue
        o = _f(df["open"].iloc[j])
        c = _f(df["close"].iloc[j])
        if o is None or c is None or c >= o:
            continue
        lo_k = _f(df["low"].iloc[j])
        v_k = _f(df["volume"].iloc[j])
        if lo_k is None or v_k is None:
            continue
        # 之後縮量站穩
        held = 0
        for k in range(j + 1, min(n, j + 6)):
            ck = _f(df["close"].iloc[k])
            vk = _f(df["volume"].iloc[k])
            if ck is None or vk is None:
                break
            if ck < lo_k or vk >= v_k:
                held = 0
                break
            held += 1
            if held >= 2:
                return k
    return None


def single_vol_no_triple(df: pd.DataFrame, i: int, traps: Sequence[TripleTrap]) -> bool:
    """單日大量但非三連套完成日（R1f4 對照）。"""
    if not _own_vol_ge_pct(df, i, lookback=20, pct=90.0):
        return False
    trap_v3s = {t.v3 for t in traps}
    return i not in trap_v3s


# ---- R1g 破前低未放量（裸 K＋量）----


def prior_swing_low(df: pd.DataFrame, i: int, *, lookback: int = 20) -> Optional[float]:
    if i < 2:
        return None
    lo = max(0, i - lookback)
    lows = [_f(df["low"].iloc[j]) for j in range(lo, i)]
    lows = [x for x in lows if x is not None and x > 0]
    if not lows:
        return None
    return float(min(lows))


def r1g_break_quiet(df: pd.DataFrame, i: int) -> bool:
    """破前低且量 ≤ 近20日中位。"""
    anchor = prior_swing_low(df, i, lookback=20)
    if anchor is None:
        return False
    c = _f(df["close"].iloc[i])
    l = _f(df["low"].iloc[i])
    if c is None or l is None:
        return False
    if not (c < anchor or l < anchor):
        return False
    return _own_vol_le_median(df, i, lookback=20)


def r1g_break_loud(df: pd.DataFrame, i: int) -> bool:
    """破前低且放量（≥ 近20日 80 分位）。"""
    anchor = prior_swing_low(df, i, lookback=20)
    if anchor is None:
        return False
    c = _f(df["close"].iloc[i])
    l = _f(df["low"].iloc[i])
    if c is None or l is None:
        return False
    if not (c < anchor or l < anchor):
        return False
    return _own_vol_ge_pct(df, i, lookback=20, pct=80.0)


# ---- 共用載入／評分 ----


def load_twii_df(db: str) -> pd.DataFrame:
    con = sqlite3.connect(db)
    try:
        df = pd.read_sql_query(
            """
            SELECT replace(CAST(date AS TEXT),'-','') AS date,
                   open, high, low, close, COALESCE(volume,0) AS volume
            FROM index_daily WHERE symbol='TWII' AND close>0
            ORDER BY date
            """,
            con,
        )
    finally:
        con.close()
    if df.empty:
        return df
    df["date"] = df["date"].map(_ymd)
    df = df[df["date"].str.len() == 8].reset_index(drop=True)
    # 缺 OHLC 時用 close 填（仍是官方收；高開低缺則無法做影線，破低／量仍可）
    for col in ("open", "high", "low"):
        df[col] = df[col].fillna(df["close"])
    return df


@dataclass
class Sig:
    track: str
    sid: str
    market: str
    date: str
    i: int
    holdout: bool


def _entry_from(
    track: str, cand: str, sig: Sig, df: pd.DataFrame, i_entry: Optional[int]
) -> Optional[Entry]:
    if i_entry is None or i_entry < 0 or i_entry >= len(df):
        return None
    px = _f(df["open"].iloc[i_entry])
    if px is None or px <= 0:
        return None
    return Entry(
        track=track,
        cand=cand,
        sid=sig.sid,
        market=sig.market,
        date_sig=sig.date,
        i_sig=sig.i,
        i_entry=int(i_entry),
        entry_px=float(px),
        holdout=sig.holdout,
    )


def _baseline_entry(sig: Sig, df: pd.DataFrame, cand: str = "baseline") -> Optional[Entry]:
    return _entry_from(sig.track, cand, sig, df, sig.i + 1)


def build_day_lit_counts(signals: Sequence[Sig]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in signals:
        out[s.track][s.date] += 1
    return out


def day_count_threshold(day_counts: Dict[str, int], pct: float) -> float:
    xs = list(day_counts.values())
    if len(xs) < 5:
        return float("inf")
    return float(np.percentile(np.asarray(xs, dtype=float), pct))


def compute_foreign_bundle(
    db: str,
    universe: Dict[str, Dict[str, str]],
    *,
    smoke: bool = False,
) -> Tuple[Dict[str, bool], List[Tuple[str, str, str]], List[Tuple[str, str, str]], Dict[str, Any]]:
    """單遍：外資壓力日＋A3／A4 亮燈（sid, market, date）。避免再跑 build_foreign_events。"""
    note = {
        "EM": "缺官方免驗證碼單檔外資 → 橘六角興櫃不可測",
        "pass": "single-pass pressure+A3/A4",
    }
    listed = {s: m for s, m in universe.items() if m["market"] in ("TW", "TWO")}
    if not listed:
        return {}, [], [], note
    sids = sorted(listed.keys())
    if smoke:
        sids = sids[:40]
    con = sqlite3.connect(db)
    try:
        ph = ",".join("?" * len(sids))
        df = pd.read_sql_query(
            f"""
            SELECT replace(CAST(date AS TEXT),'-','') AS date, stock_id, market,
                   volume, COALESCE(foreign_net,0) AS foreign_net
            FROM daily_quotes
            WHERE stock_id IN ({ph}) AND market IN ('TW','TWO')
              AND close>0 AND volume>0
            ORDER BY date, stock_id
            """,
            con,
            params=tuple(sids),
        )
    finally:
        con.close()
    if df.empty:
        return {}, [], [], note
    df["date"] = df["date"].map(_ymd)
    df = df[df["date"].str.len() == 8]
    esc_p = current_params()
    buy_p = current_buy_params()
    ext_track = ExtremeTrack("share", float(DISPLAY_SELL_SHARE_THR))
    hist: Dict[str, List[Tuple[str, float, float, str]]] = defaultdict(list)
    for r in df.itertuples(index=False):
        hist[str(r.stock_id)].append(
            (str(r.date), float(r.volume), float(r.foreign_net), str(r.market))
        )
    date_ix = {sid: {t[0]: i for i, t in enumerate(seq)} for sid, seq in hist.items()}
    sell_pctl: Dict[Tuple[str, str], float] = {}
    buy_pctl: Dict[Tuple[str, str], float] = {}
    for day, g in df.groupby("date", sort=True):
        sell_vals: List[float] = []
        buy_vals: List[float] = []
        sell_map: Dict[str, float] = {}
        buy_map: Dict[str, float] = {}
        for r in g.itertuples(index=False):
            sid = str(r.stock_id)
            ss = sell_share(r.foreign_net, r.volume)
            if ss is not None:
                sell_vals.append(float(ss))
                sell_map[sid] = float(ss)
            bs = _buy_share(r.foreign_net, r.volume)
            if bs is not None:
                buy_vals.append(float(bs))
                buy_map[sid] = float(bs)
        for sid, ss in sell_map.items():
            sell_pctl[(str(day), sid)] = cross_sectional_percentile(sell_vals, ss)
        for sid, bs in buy_map.items():
            buy_pctl[(str(day), sid)] = cross_sectional_percentile(buy_vals, bs)

    ratios: Dict[str, float] = {}
    a3_hits: List[Tuple[str, str, str]] = []
    a4_hits: List[Tuple[str, str, str]] = []
    last_a3: Dict[str, int] = {}
    last_a4: Dict[str, int] = {}
    for day in sorted(df["date"].unique().tolist()):
        day_df = df[df["date"] == day]
        nz = int((day_df["foreign_net"] != 0).sum())
        if nz < max(30, int(len(day_df) * 0.05)):
            continue
        lit = tot = 0
        for sid in day_df["stock_id"].astype(str).unique():
            seq = hist.get(sid)
            if not seq:
                continue
            ix = date_ix[sid].get(day)
            if ix is None:
                continue
            market = listed.get(sid, {}).get("market") or seq[ix][3]
            n = int(esc_p.n_days)
            if ix + 1 < n:
                continue
            tot += 1
            window = seq[ix - n + 1 : ix + 1]
            fns = [t[2] for t in window]
            vols = [t[1] for t in window]
            pctls = [sell_pctl.get((t[0], sid)) for t in window]
            row = seq[ix]
            ev_esc = evaluate_escalate_A(
                foreign_nets=fns, volumes=vols, pctls=pctls, params=esc_p
            )
            lit_ext = lit_extreme_day(
                ext_track,
                foreign_net=row[2],
                volume=row[1],
                foreign_nets_hist=fns,
                foreign_nets_10=[t[2] for t in seq[max(0, ix - 9) : ix + 1]],
            )
            sell_lit = bool(ev_esc.get("lit") or lit_ext)
            if sell_lit:
                lit += 1
                if ix - last_a3.get(sid, -10**9) >= DEDUP_N:
                    a3_hits.append((sid, market, day))
                    last_a3[sid] = ix
            n2 = int(buy_p.n_days)
            if ix + 1 >= n2:
                window_b = seq[ix - n2 + 1 : ix + 1]
                fns_b = [t[2] for t in window_b]
                vols_b = [t[1] for t in window_b]
                pctls_b = [buy_pctl.get((t[0], sid)) for t in window_b]
                ev_b = evaluate_buy_escalate_A(
                    foreign_nets=fns_b, volumes=vols_b, pctls=pctls_b, params=buy_p
                )
                if ev_b.get("lit") and ix - last_a4.get(sid, -10**9) >= DEDUP_N:
                    a4_hits.append((sid, market, day))
                    last_a4[sid] = ix
        if tot > 0:
            ratios[day] = lit / tot

    sorted_days = sorted(ratios.keys())
    pressure: Dict[str, bool] = {}
    for i, day in enumerate(sorted_days):
        window = [ratios[d] for d in sorted_days[max(0, i - 19) : i + 1]]
        if len(window) < 5:
            pressure[day] = False
            continue
        pressure[day] = bool(ratios[day] > float(np.median(window)))
    return pressure, a3_hits, a4_hits, note


def stabilize_touch_low(df: pd.DataFrame, fire_i: int) -> Optional[float]:
    if fire_i < 61 or fire_i >= len(df):
        return None
    touches = _l60_first_touch_indices(df.iloc[: fire_i + 1])
    if not touches:
        return None
    start_scan = max(0, fire_i - int(LOOKBACK))
    cands = [i for i in touches if start_scan <= i < fire_i]
    if not cands:
        return None
    t0 = int(cands[-1])
    if not _held_after_touch(df, t0, fire_i, hold_n=HOLD_N):
        return None
    return _f(df["low"].iloc[t0])


def _twii_ret_n(twii: Dict[str, Dict[str, float]], days: Sequence[str], i: int, n: int) -> Optional[float]:
    if i < n or i >= len(days):
        return None
    c0 = twii.get(days[i - n], {}).get("close")
    c1 = twii.get(days[i], {}).get("close")
    if not c0 or not c1 or c0 <= 0:
        return None
    return (c1 - c0) / c0


def _stock_ret_n(df: pd.DataFrame, i: int, n: int) -> Optional[float]:
    if i < n or i >= len(df):
        return None
    c0 = _f(df["close"].iloc[i - n])
    c1 = _f(df["close"].iloc[i])
    if c0 is None or c1 is None or c0 <= 0:
        return None
    return (c1 - c0) / c0


def _max_dd_lookback(df: pd.DataFrame, i: int, n: int) -> Optional[float]:
    if i < 1:
        return None
    lo = max(0, i - n + 1)
    peak = None
    worst = 0.0
    any_bar = False
    for j in range(lo, i + 1):
        h = _f(df["high"].iloc[j])
        l = _f(df["low"].iloc[j])
        if h is None or l is None or h <= 0:
            continue
        peak = h if peak is None else max(peak, h)
        dd = (l - peak) / peak
        any_bar = True
        if dd < worst:
            worst = dd
    return worst if any_bar else None


def _median_dd60(df: pd.DataFrame, i: int) -> Optional[float]:
    if i < 10:
        return None
    xs = []
    for j in range(max(5, i - 59), i + 1):
        dd = _max_dd_lookback(df, j, 5)
        if dd is not None:
            xs.append(dd)
    return float(np.median(xs)) if len(xs) >= 5 else None


def _vol_pctile_rank(df: pd.DataFrame, i: int, lookback: int = 60) -> Optional[float]:
    lo = max(0, i + 1 - lookback)
    vols = [_f(v) for v in df["volume"].iloc[lo : i + 1].tolist()]
    vols = [v for v in vols if v is not None and v > 0]
    vt = _f(df["volume"].iloc[i])
    if vt is None or vt <= 0 or len(vols) < 9:
        return None
    return float(sum(1 for v in vols if v <= vt) / len(vols))


def _dd5_pctile_rank(df: pd.DataFrame, i: int, lookback: int = 60) -> Optional[float]:
    cur = _max_dd_lookback(df, i, 5)
    if cur is None or i < 10:
        return None
    xs = []
    for j in range(max(5, i - lookback + 1), i + 1):
        dd = _max_dd_lookback(df, j, 5)
        if dd is not None:
            xs.append(-dd)
    if len(xs) < 9:
        return None
    cur_d = -cur
    return float(sum(1 for d in xs if d <= cur_d) / len(xs))


def portfolio_day_stats(
    picks: Dict[str, List[Tuple[str, float]]],
    frames: Dict[str, pd.DataFrame],
    *,
    horizons: Sequence[int] = (5, 20),
) -> Dict[str, Any]:
    day_rets: Dict[str, List[float]] = {str(h): [] for h in horizons}
    day_dds: List[float] = []
    n_days = 0
    for day, items in sorted(picks.items()):
        if not items:
            continue
        n_days += 1
        hs: Dict[str, List[float]] = {str(h): [] for h in horizons}
        dds: List[float] = []
        for sid, px in items:
            df = frames.get(sid)
            if df is None or px <= 0:
                continue
            days = [str(x) for x in df["date"].tolist()]
            if day not in days:
                continue
            i_sig = days.index(day)
            i_entry = i_sig + 1
            if i_entry >= len(df):
                continue
            rets = _fast_forward(df, i_entry, float(px), horizons)
            for h, r in rets.items():
                if r is not None:
                    hs[str(h)].append(float(r))
            lo_px = None
            for off in range(0, 5):
                j = i_entry + off
                if j >= len(df):
                    break
                lo = _f(df["low"].iloc[j])
                if lo is not None and lo > 0:
                    lo_px = lo if lo_px is None else min(lo_px, lo)
            if lo_px is not None:
                dds.append((lo_px - px) / px)
        for h in horizons:
            if hs[str(h)]:
                day_rets[str(h)].append(float(np.mean(hs[str(h)])))
        if dds:
            day_dds.append(float(np.mean(dds)))
    return {
        "n_days": n_days,
        "horizons": {str(h): summarize_rets(day_rets[str(h)]) for h in horizons},
        "max_drawdown": summarize_rets(day_dds),
    }


def analyze_index_patterns(twii_df: pd.DataFrame) -> Dict[str, Any]:
    """R1f1／R1f2／R1g1／R1g2 加權優先。"""
    traps = detect_triple_traps(twii_df)
    days = [str(x) for x in twii_df["date"].tolist()]
    teach = {
        "V1_date": TEACH_V1,
        "V2_date": TEACH_V2,
        "V3_date": TEACH_V3,
        "matched": False,
        "nearest": None,
    }
    for t in traps:
        d1, d2, d3 = days[t.v1], days[t.v2], days[t.v3]
        if d1 == TEACH_V1 and d2 == TEACH_V2 and d3 == TEACH_V3:
            teach["matched"] = True
            teach["nearest"] = {"v1": d1, "v2": d2, "v3": d3}
            break
    if not teach["matched"] and traps:
        # 近鄰：V3 落在教學窗
        for t in traps:
            if days[t.v3] in {TEACH_V1, TEACH_V2, TEACH_V3} or abs(
                int(days[t.v3]) - int(TEACH_V3)
            ) <= 5:
                teach["nearest"] = {
                    "v1": days[t.v1],
                    "v2": days[t.v2],
                    "v3": days[t.v3],
                }
                break

    # R1f1：連套後否決 V 轉 vs 無條件盼反彈
    v_hit = 0
    v_n = 0
    uncond_up = 0  # 之後 10 日任一收 > 事件日收
    uncond_n = 0
    kill_then_ok = 0
    kill_n = 0
    after_rets: List[float] = []
    after_kill_rets: List[float] = []
    for t in traps:
        v_n += 1
        if v_reversal_hit(twii_df, t, within=10):
            v_hit += 1
        # 無條件盼反彈：V3 後 10 日內收 > V3 收
        c0 = _f(twii_df["close"].iloc[t.v3])
        rebound = False
        if c0 and c0 > 0:
            uncond_n += 1
            for j in range(t.v3 + 1, min(len(twii_df), t.v3 + 11)):
                cj = _f(twii_df["close"].iloc[j])
                if cj is not None and cj > c0:
                    rebound = True
                    break
            if rebound:
                uncond_up += 1
            # 隔日開→+5
            if t.v3 + 1 < len(twii_df):
                px = _f(twii_df["open"].iloc[t.v3 + 1])
                if px and px > 0:
                    rr = _fast_forward(twii_df, t.v3 + 1, float(px), (5, 20))
                    if rr.get(5) is not None:
                        after_rets.append(float(rr[5]))
        # R1f2 下殺取量
        kill_n += 1
        stab = kill_volume_then_stabilize(twii_df, t.v3, within=15)
        if stab is not None:
            kill_then_ok += 1
            if stab + 1 < len(twii_df):
                px = _f(twii_df["open"].iloc[stab + 1])
                if px and px > 0:
                    rr = _fast_forward(twii_df, stab + 1, float(px), (5,))
                    if rr.get(5) is not None:
                        after_kill_rets.append(float(rr[5]))

    # R1g1／g2
    quiet_cont: List[float] = []
    loud_cont: List[float] = []
    quiet_fake_v = 0
    quiet_n = 0
    loud_n = 0
    g2_kill = 0
    g2_n = 0
    for i in range(25, len(twii_df) - 6):
        quiet = r1g_break_quiet(twii_df, i)
        loud = r1g_break_loud(twii_df, i)
        if not quiet and not loud:
            continue
        c0 = _f(twii_df["close"].iloc[i])
        if c0 is None or c0 <= 0:
            continue
        # 續跌：+5 收更低
        c5 = _f(twii_df["close"].iloc[i + 5]) if i + 5 < len(twii_df) else None
        # 假 V：5 日內收復前低錨上方後又跌破事件收
        if quiet:
            quiet_n += 1
            if c5 is not None:
                quiet_cont.append((c5 - c0) / c0)
            # 假 V 粗標：5 日內曾收 > 事件開 且最終 c5 < c0
            o0 = _f(twii_df["open"].iloc[i])
            saw_up = False
            for j in range(i + 1, i + 6):
                cj = _f(twii_df["close"].iloc[j])
                if cj is not None and o0 is not None and cj > o0:
                    saw_up = True
            if saw_up and c5 is not None and c5 < c0:
                quiet_fake_v += 1
            g2_n += 1
            if kill_volume_then_stabilize(twii_df, i, within=15) is not None:
                g2_kill += 1
        if loud:
            loud_n += 1
            if c5 is not None:
                loud_cont.append((c5 - c0) / c0)

    return {
        "n_traps": len(traps),
        "teach_anchor": teach,
        "R1f1": {
            "triple_v_hit_rate": (v_hit / v_n) if v_n else None,
            "uncond_rebound_rate": (uncond_up / uncond_n) if uncond_n else None,
            "n": v_n,
            "reject_v_better": (
                (v_hit / v_n) < (uncond_up / uncond_n) if v_n and uncond_n else None
            ),
            "h5_after_triple": summarize_rets(after_rets),
        },
        "R1f2": {
            "kill_then_stabilize_rate": (kill_then_ok / kill_n) if kill_n else None,
            "n": kill_n,
            "h5_after_kill_path": summarize_rets(after_kill_rets),
        },
        "R1g1": {
            "quiet_n": quiet_n,
            "loud_n": loud_n,
            "quiet_h5": summarize_rets(quiet_cont),
            "loud_h5": summarize_rets(loud_cont),
            "quiet_fake_v_rate": (quiet_fake_v / quiet_n) if quiet_n else None,
        },
        "R1g2": {
            "after_quiet_kill_stabilize_rate": (g2_kill / g2_n) if g2_n else None,
            "n": g2_n,
        },
    }


def run(db: str, out_path: str, *, smoke: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    universe = load_universe(db)
    twii = load_twii(db)
    twii_df = load_twii_df(db)
    holdout_from = dict(LOCKED_HOLDOUT)

    con = sqlite3.connect(db)
    try:
        mb_n = int(con.execute("SELECT COUNT(*) FROM minute_bars").fetchone()[0])
        mb_sids = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT stock_id FROM minute_bars WHERE interval IN ('15','60')"
            )
        ]
    finally:
        con.close()

    sids = sorted(universe.keys())
    if smoke:
        picked: List[str] = []
        for m in MARKETS:
            picked.extend([s for s in sids if universe[s]["market"] == m][:6])
        sids = picked

    frames: Dict[str, pd.DataFrame] = {}
    signals: List[Sig] = []
    a5_touch_low: Dict[Tuple[str, int], float] = {}
    stock_traps: Dict[str, List[TripleTrap]] = {}
    fire5_by_sid: Dict[str, List[int]] = {}
    fire6_by_sid: Dict[str, List[int]] = {}

    con = sqlite3.connect(db)
    try:
        for i, sid in enumerate(sids):
            meta = universe[sid]
            market = meta["market"]
            df = load_stock_df(con, sid, market)
            if df.empty or len(df) < 30:
                continue
            frames[sid] = df
            industry = meta.get("industry") or ""
            hf = holdout_from.get(market, "")
            days = [str(x) for x in df["date"].tolist()]
            got_r1 = False
            got_a5 = False
            for track in PRICE_TRACKS:
                for ix in find_signal_indices(df, track, market, industry):
                    if ix < 0 or ix >= len(df) - 1:
                        continue
                    d = days[ix]
                    signals.append(
                        Sig(track, sid, market, d, ix, bool(hf and d >= hf))
                    )
                    if track in R1_TRACKS:
                        got_r1 = True
                    if track == "A5":
                        got_a5 = True
                        tl = stabilize_touch_low(df, ix)
                        if tl is not None:
                            a5_touch_low[(sid, ix)] = float(tl)
            if got_r1:
                stock_traps[sid] = detect_triple_traps(df)
            if got_a5:
                fire5_by_sid[sid] = stabilize_fire_indices(df, HOLD_N)
                fire6_by_sid[sid] = stabilize_fire_indices(df, HOLD_N_NEXT)
            if smoke and i >= 18:
                break
            if (i + 1) % 200 == 0:
                print(f"[sig] {i+1}/{len(sids)} signals={len(signals)}", flush=True)
    finally:
        con.close()

    print(f"[prep] signals={len(signals)} frames={len(frames)}", flush=True)
    lit_counts = build_day_lit_counts(signals)
    thr40 = {t: day_count_threshold(lit_counts[t], 40.0) for t in PRICE_TRACKS}
    thr60 = {t: day_count_threshold(lit_counts[t], 60.0) for t in PRICE_TRACKS}

    print("[index] R1f/R1g on TWII…", flush=True)
    index_block = analyze_index_patterns(twii_df) if not twii_df.empty else {}

    print("[foreign-bundle] pressure+A3/A4 one pass…", flush=True)
    pressure_days, a3_hits, a4_hits, f_note = compute_foreign_bundle(
        db, universe, smoke=smoke
    )
    print(
        f"[foreign-bundle] pressure_days={len(pressure_days)} a3={len(a3_hits)} a4={len(a4_hits)}",
        flush=True,
    )

    sorted_tw = sorted(twii.keys())
    twii_dir: Dict[str, int] = {}
    for i, d in enumerate(sorted_tw):
        if i == 0:
            continue
        c0 = twii[sorted_tw[i - 1]].get("close")
        c1 = twii[d].get("close")
        if c0 and c1 and c0 > 0:
            twii_dir[d] = 1 if c1 > c0 else (-1 if c1 < c0 else 0)

    def _hits_to_sigs(track: str, hits: List[Tuple[str, str, str]]) -> List[Sig]:
        out: List[Sig] = []
        for sid, market, day in hits:
            df = frames.get(sid)
            if df is None:
                continue
            days = [str(x) for x in df["date"].tolist()]
            if day not in days:
                continue
            ix = days.index(day)
            if ix >= len(df) - 1:
                continue
            hf = holdout_from.get(market, "")
            out.append(Sig(track, sid, market, day, ix, bool(hf and day >= hf)))
        return out

    a3_sigs = _hits_to_sigs("A3", a3_hits)
    a4_sigs = _hits_to_sigs("A4", a4_hits)

    entries: List[Entry] = []
    r1e_forward: Dict[str, List[float]] = defaultdict(list)
    r4_compare: Dict[str, List[float]] = defaultdict(list)
    r6_scored: Dict[str, List[Tuple[str, float, float, str]]] = defaultdict(list)
    r2d_set: Set[Tuple[str, str]] = set()
    r3a_set: Set[Tuple[str, str]] = set()

    sig_vol_high_fn = cand_signal_vol_tercile(want="high")

    def add(e: Optional[Entry]) -> None:
        if e is not None:
            entries.append(e)
            if e.track == "A7" and e.cand == "R2d":
                r2d_set.add((e.sid, e.date_sig))
            if e.track == "A7" and e.cand == "R3a_twii_down":
                r3a_set.add((e.sid, e.date_sig))

    for si, sig in enumerate(signals):
        if (si + 1) % 50000 == 0:
            print(f"[cand] {si+1}/{len(signals)} entries={len(entries)}", flush=True)
        df = frames[sig.sid]
        days = [str(x) for x in df["date"].tolist()]
        traps = stock_traps.get(sig.sid, [])

        if sig.track in PRICE_TRACKS:
            add(_baseline_entry(sig, df, "baseline"))

        if sig.track in R1_TRACKS:
            for name, fn in (
                ("R1a", cand_r1a),
                ("R1b", cand_r1b),
                ("R1c", cand_r1c),
                ("R1d_trap_ctrl", cand_r1d_trap_control),
            ):
                j = fn(df, sig.i)
                add(_entry_from(sig.track, name, sig, df, j))

            hit_e = any(r1e1_at(df, j) for j in range(sig.i + 1, min(len(df), sig.i + 6)))
            add(_baseline_entry(sig, df, "R1e3_after_dump" if hit_e else "R1e3_no_dump"))
            dump_s = r1e1_at(df, sig.i) or (
                sig.i + 1 < len(df) and r1e1_at(df, sig.i + 1)
            )
            dump2 = r1e2_at(df, sig.i) or (
                sig.i + 1 < len(df) and r1e2_at(df, sig.i + 1)
            )
            if not dump_s:
                add(_baseline_entry(sig, df, "R1e_excl_e1"))
            if not dump2:
                add(_baseline_entry(sig, df, "R1e_excl_e2"))

            # R1f3／f4／排除
            recent_triple = any(
                0 <= sig.i - t.v3 <= 5 for t in traps
            )
            if recent_triple:
                add(_baseline_entry(sig, df, "R1f3_after_triple"))
            else:
                add(_baseline_entry(sig, df, "R1f_excl_triple"))
            if single_vol_no_triple(df, sig.i, traps):
                add(_baseline_entry(sig, df, "R1f4_single_vol"))

            # R1g3 排除／對照
            if r1g_break_quiet(df, sig.i):
                add(_baseline_entry(sig, df, "R1g3_break_no_vol"))
            else:
                add(_baseline_entry(sig, df, "R1g_excl_quiet_break"))
            if r1g_break_loud(df, sig.i):
                add(_baseline_entry(sig, df, "R1g3_break_with_vol"))
            # R1g4：三連套後又破低未放量
            if recent_triple and any(
                r1g_break_quiet(df, j) for j in range(sig.i, min(len(df), sig.i + 3))
            ):
                add(_baseline_entry(sig, df, "R1g4_triple_then_break_quiet"))

        if sig.track in R2_TRACKS:
            i_hv = sig_vol_high_fn(df, sig.i)
            if i_hv is not None:
                add(_entry_from(sig.track, "sig_vol_high", sig, df, i_hv))
                cnt = lit_counts[sig.track].get(sig.date, 0)
                non_crowd = cnt <= thr40[sig.track]
                s_ret = _stock_ret_n(df, sig.i, 5)
                t_ret = _twii_ret_n(twii, days, sig.i, 5)
                rel_strong = (
                    s_ret is not None and t_ret is not None and (s_ret - t_ret) > 0
                )
                dd5 = _max_dd_lookback(df, sig.i, 5)
                med = _median_dd60(df, sig.i)
                shallow = dd5 is not None and med is not None and dd5 > med
                if non_crowd:
                    add(_entry_from(sig.track, "R2a", sig, df, i_hv))
                if rel_strong:
                    add(_entry_from(sig.track, "R2b", sig, df, i_hv))
                if shallow:
                    add(_entry_from(sig.track, "R2c", sig, df, i_hv))
                if non_crowd and rel_strong:
                    add(_entry_from(sig.track, "R2d", sig, df, i_hv))

        if sig.track in R3_TRACKS:
            ddir = twii_dir.get(sig.date, 0)
            if ddir < 0:
                add(_baseline_entry(sig, df, "R3a_twii_down"))
            if ddir > 0:
                add(_baseline_entry(sig, df, "R3b_twii_up"))
            if sig.market in ("TW", "TWO"):
                if pressure_days.get(sig.date, False):
                    add(_baseline_entry(sig, df, "R3c_keep_pressure"))
                else:
                    add(_baseline_entry(sig, df, "R3c_excl_pressure"))
            cnt = lit_counts[sig.track].get(sig.date, 0)
            if not (cnt > thr60[sig.track]):
                add(_baseline_entry(sig, df, "R3d_excl_crowd"))

        if sig.track == "A5":
            tl = a5_touch_low.get((sig.sid, sig.i))
            i_entry = sig.i + 1
            if tl is not None and i_entry < len(df):
                px = _f(df["open"].iloc[i_entry])
                if px and px > 0:
                    invalid_i = None
                    for j in range(i_entry, min(len(df), i_entry + 20)):
                        cj = _f(df["close"].iloc[j])
                        if cj is not None and cj < tl * BREAK_TOL:
                            invalid_i = j
                            break
                    # hold thru
                    rr = _fast_forward(df, i_entry, float(px), (5, 20))
                    if rr.get(5) is not None:
                        r4_compare["R4a_hold_thru_h5"].append(float(rr[5]))
                    if rr.get(20) is not None:
                        r4_compare["R4a_hold_thru_h20"].append(float(rr[20]))
                    if invalid_i is not None:
                        cl = _f(df["close"].iloc[invalid_i])
                        if cl and cl > 0:
                            r4_compare["R4a_exit_invalid"].append(
                                (cl - float(px)) / float(px)
                            )
                        lim = min(len(df) - 1, invalid_i + 40)
                        for j in fire5_by_sid.get(sig.sid, []):
                            if invalid_i < j <= lim:
                                add(_entry_from("A5", "R4b_relight", sig, df, j + 1))
                                break
                        for j in fire6_by_sid.get(sig.sid, []):
                            if invalid_i < j <= lim:
                                add(
                                    _entry_from(
                                        "A5", "R4c_tight_confirm", sig, df, j + 1
                                    )
                                )
                                break
                    add(_baseline_entry(sig, df, "R4b_first_light"))
                    dump_after = any(
                        r1e1_at(df, j) for j in range(sig.i + 1, min(len(df), sig.i + 6))
                    )
                    add(
                        _baseline_entry(
                            sig, df, "R1e4_after_dump" if dump_after else "R1e4_no_dump"
                        )
                    )
                    # R1g3 on stabilize：破低未放量排除
                    if not r1g_break_quiet(df, sig.i):
                        add(_baseline_entry(sig, df, "R1g_excl_quiet_break"))

        if sig.track == "A7":
            vp = _vol_pctile_rank(df, sig.i)
            dp = _dd5_pctile_rank(df, sig.i)
            if vp is not None and dp is not None and sig.i + 1 < len(df):
                px = _f(df["open"].iloc[sig.i + 1])
                if px and px > 0:
                    r6_scored[sig.date].append(
                        (sig.sid, float(px), float(vp - dp), sig.market)
                    )

        if smoke and len(entries) > 2500:
            break

    # R1e shape forward
    print("[R1e] shape forward…", flush=True)
    for sid, df in frames.items():
        market = universe[sid]["market"]
        hf = holdout_from.get(market, "")
        for i in range(1, len(df) - 2):
            if not r1e1_at(df, i):
                continue
            d = str(df["date"].iloc[i])
            px = _f(df["open"].iloc[i + 1])
            if not px or px <= 0:
                continue
            rr = _fast_forward(df, i + 1, float(px), (1, 5))
            for h, r in rr.items():
                if r is None:
                    continue
                r1e_forward[f"R1e1_h{h}"].append(float(r))
                if r1e2_at(df, i):
                    r1e_forward[f"R1e2_h{h}"].append(float(r))
            holdout = bool(hf and d >= hf)
            for tag, ok in (("R1e1_shape", True), ("R1e2_shape", r1e2_at(df, i))):
                if not ok:
                    continue
                entries.append(
                    Entry("R1e", tag, sid, market, d, i, i + 1, float(px), holdout)
                )
        if smoke and len(r1e_forward.get("R1e1_h5", [])) > 80:
            break

    # R5
    print(f"[R5] a3={len(a3_sigs)} a4={len(a4_sigs)}", flush=True)

    def add_orange(sig: Sig, tag: str) -> None:
        df = frames.get(sig.sid)
        if df is None:
            return
        e = _baseline_entry(sig, df, tag)
        if e:
            entries.append(
                Entry(
                    sig.track,
                    tag,
                    e.sid,
                    e.market,
                    e.date_sig,
                    e.i_sig,
                    e.i_entry,
                    e.entry_px,
                    e.holdout,
                )
            )

    for sig in a3_sigs:
        df = frames[sig.sid]
        add_orange(sig, "R5_uncond")
        lo0 = _f(df["low"].iloc[sig.i])
        v0 = _f(df["volume"].iloc[sig.i])
        if lo0 and v0 and sig.i + 3 < len(df):
            ok = True
            for k in range(1, 4):
                vj = _f(df["volume"].iloc[sig.i + k])
                cj = _f(df["close"].iloc[sig.i + k])
                if vj is None or cj is None or vj >= v0 or cj < lo0:
                    ok = False
                    break
            if ok:
                add_orange(sig, "R5a_pressure_calm")
        if lo0 and v0 and sig.i + 1 < len(df):
            v1 = _f(df["volume"].iloc[sig.i + 1])
            c1 = _f(df["close"].iloc[sig.i + 1])
            if v1 is not None and c1 is not None and v1 > v0 and c1 < lo0:
                add_orange(sig, "R5b_pressure_worse")
    for sig in a4_sigs:
        add_orange(sig, "R5_buy_uncond")
        if sig_vol_high_fn(frames[sig.sid], sig.i) is not None:
            add_orange(sig, "R5c_buy_hi_vol")

    # R6 portfolios
    print("[R6]…", flush=True)
    rng = random.Random(20261022)
    r6_picks: Dict[str, Dict[str, List[Tuple[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for day, items in r6_scored.items():
        listed = [x for x in items if x[3] in ("TW", "TWO")]
        if not listed:
            continue
        ranked = sorted(listed, key=lambda x: x[2], reverse=True)
        r6_picks["R6c_all"][day] = [(s, px) for s, px, _, _ in listed]
        for k in (3, 5):
            r6_picks[f"R6a_top{k}"][day] = [(s, px) for s, px, _, _ in ranked[:k]]
            pool = listed[:]
            rng.shuffle(pool)
            r6_picks[f"R6c_rand{k}"][day] = [(s, px) for s, px, _, _ in pool[:k]]
        for filt_name, filt_set in (("R2d", r2d_set), ("R3a", r3a_set)):
            filtered = [x for x in ranked if (x[0], day) in filt_set]
            for k in (3, 5):
                r6_picks[f"R6b_{filt_name}_top{k}"][day] = [
                    (s, px) for s, px, _, _ in filtered[:k]
                ]
    r6_stats = {name: portfolio_day_stats(picks, frames) for name, picks in r6_picks.items()}

    # 個股 R1f3 V 轉失敗率
    stock_f3 = {"n": 0, "v_hit": 0, "h5": [], "h20": []}
    for sid, traps in stock_traps.items():
        df = frames.get(sid)
        if df is None:
            continue
        for t in traps:
            stock_f3["n"] += 1
            if v_reversal_hit(df, t, within=10):
                stock_f3["v_hit"] += 1
            if t.v3 + 1 < len(df):
                px = _f(df["open"].iloc[t.v3 + 1])
                if px and px > 0:
                    rr = _fast_forward(df, t.v3 + 1, float(px), (5, 20))
                    if rr.get(5) is not None:
                        stock_f3["h5"].append(float(rr[5]))
                    if rr.get(20) is not None:
                        stock_f3["h20"].append(float(rr[20]))
        if smoke and stock_f3["n"] > 40:
            break
    stock_f3_out = {
        "n": stock_f3["n"],
        "v_hit_rate": (stock_f3["v_hit"] / stock_f3["n"]) if stock_f3["n"] else None,
        "h5": summarize_rets(stock_f3["h5"]),
        "h20": summarize_rets(stock_f3["h20"]),
    }

    print(f"[score] entries={len(entries)}", flush=True)
    full, train, holdout = score_entries_split(entries, frames)

    cand_names = sorted({e.cand for e in entries})
    track_names = sorted({e.track for e in entries})
    verdicts: Dict[str, Any] = {}
    replaceable: List[str] = []
    for track in track_names:
        if track not in PRICE_TRACKS:
            continue
        for cand in cand_names:
            if not any(e.track == track and e.cand == cand for e in entries):
                continue
            v = verdict_for(track, cand, full, holdout)
            if cand in OBS_CANDS or cand.startswith("R1e3") or cand.startswith("R1e4"):
                v = dict(v)
                v["verdict"] = "觀察"
                v["reason"] = "風險形／對照，不當買訊換臉"
            verdicts[f"{track}:{cand}"] = v
            if v.get("verdict") == "可換" and cand != "baseline":
                replaceable.append(f"{track}:{cand}")

    result = {
        "generated_at": _now_iso(),
        "db": db,
        "smoke": smoke,
        "elapsed_sec": round(time.time() - t0, 1),
        "holdout_from": holdout_from,
        "primary_h": PRIMARY_H,
        "min_n_days": MIN_N_DAYS,
        "min_wr_lift": MIN_WR_LIFT,
        "bare_k_lock": "R1/R1e/R1f/R1g/R4 附加形只准 OHLC＋量；不准均線／指標當主條件",
        "locked_scope": "R0–R7 + R1e/R1f/R1g only；未鎖新 R 不加",
        "minute_bars_note": {
            "rows": mb_n,
            "sids_15_60": mb_sids,
            "policy": "全市場無個股分時覆蓋 → R1e 日 K 代理；不准 invent 鎖漲停分鐘",
        },
        "signal_counts": {
            f"{t}:{m}": sum(1 for s in signals if s.track == t and s.market == m)
            for t in PRICE_TRACKS
            for m in MARKETS
        },
        "orange_counts": {
            f"{t}:{m}": sum(
                1 for s in (a3_sigs if t == "A3" else a4_sigs) if s.market == m
            )
            for t in ("A3", "A4")
            for m in ("TW", "TWO")
        },
        "candidate_names": cand_names,
        "full": full,
        "train": train,
        "holdout": holdout,
        "verdicts": verdicts,
        "replaceable": replaceable,
        "index_R1f_R1g": index_block,
        "stock_R1f3": stock_f3_out,
        "r1e_shape_forward": {k: summarize_rets(v) for k, v in r1e_forward.items()},
        "r4_invalid_compare": {k: summarize_rets(v) for k, v in r4_compare.items()},
        "r6_portfolios": r6_stats,
        "emerging_foreign_note": f_note,
        "notes": {
            "R8_skip": "未重跑 wait_1～5／粗 hi_vol_shrink 全市場三分位",
            "pending_new_R": "連2根確認／平台爆量等未鎖條目 → 等協調者彙整定案再加",
            "gate": "可換＝TW／TWO 全樣＋留白 h5 勝率≥現況+1pt 且均報酬≥現況，n_days≥20",
            "buy_formula": "未改 leave_zero／黃金買點",
        },
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(
        f"[done] wrote {out_path} elapsed={result['elapsed_sec']}s replaceable={replaceable}",
        flush=True,
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--out", default="")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    db = str(Path(args.db))
    if not Path(db).is_file():
        print(f"missing db {db}", file=sys.stderr)
        return 2
    out = args.out or (
        "/tmp/mt_round3_smoke.json" if args.smoke else "/tmp/mt_round3.json"
    )
    run(db, out, smoke=bool(args.smoke))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
