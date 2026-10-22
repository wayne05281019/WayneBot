#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股裸 K＋量 B 條全量準度測（凍結 2026-10-22）。

必測：B1 B2 B3 B4 B5 B6 B9 B10；不做 B7 B8；不重開 R1e/f/g。
重用第 2 步宇宙／訊號／隔日開進場／全樣＋留白雙閘（step2 on main）。
不准改 leave_zero／紅箭公式；未過閘不上話筒；勝率分軌不准混。
裸 K＋量 only；Asia/Taipei。

用法：
  .venv/bin/python scripts/multi_track_stock_vp_b.py --db data/wayne_market.db --out /tmp/mt_stock_vp_b.json
  .venv/bin/python scripts/multi_track_stock_vp_b.py --smoke
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

from multi_track_baseline_backtest import (  # noqa: E402
    holdout_cut,
    load_stock_df,
    load_twii,
    load_universe,
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
    find_signal_indices,
    score_entries_split,
    verdict_for,
)

TP = ZoneInfo("Asia/Taipei")
PRICE_TRACKS = ("A1", "A2", "A5")  # 止穩＝A5；剛離零／紅箭＝A1／A2
# 觀察／風險形：不當買訊換臉
OBS_CANDS = {
    "B1_no_confirm",
    "B2_force_no_stand",
    "B3_div_n5",
    "B3_div_n8",
    "B3_false_pos",
    "B4_keep_break",
    "B4_fake_break",
    "B5_after_kill",
    "B5_no_kill",
    "B6_v_fail_n5",
    "B6_v_fail_n8",
    "B6_v_ok_n5",
    "B6_v_ok_n8",
    "B9_pierce_only",
    "B10_all",
    "B10_cap_r1e",
    "B10_minus_r1e",
    "ctrl_random_day",
    "ctrl_twii_proxy",
}
B_LOCKED = ("B1", "B2", "B3", "B4", "B5", "B6", "B9", "B10")
B_SKIP = ("B7", "B8")


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


def _own_vol_median(df: pd.DataFrame, i: int, *, lookback: int = 20) -> Optional[float]:
    if i < 1:
        return None
    lo = max(0, i - lookback)
    vols = [_f(v) for v in df["volume"].iloc[lo:i].tolist()]
    vols = [v for v in vols if v is not None and v > 0]
    if len(vols) < 5:
        return None
    return float(np.median(vols))


def _vol_shrunk(df: pd.DataFrame, i: int, v_ref: float) -> bool:
    vt = _f(df["volume"].iloc[i])
    if vt is None or v_ref <= 0:
        return False
    med = _own_vol_median(df, i, lookback=20)
    if vt < v_ref * 0.6:
        return True
    if med is not None and vt < med:
        return True
    return False


# ---- R1e1 代理（僅供 B10 分軌；不重跑 R1e 全套）----


def r1e1_at(df: pd.DataFrame, i: int) -> bool:
    """與第 3 輪同形：長上影＋自身近20量≥80分位＋收漲遠小於衝高。"""
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


# ---- B1 連 2 根確認 ----


def b1_confirm_entry(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    """S 後 S+1 收＞S 收（或收在 S 高之上）→ 進場＝S+2 開。"""
    n = len(df)
    if i_sig + 2 >= n:
        return None
    c0 = _f(df["close"].iloc[i_sig])
    h0 = _f(df["high"].iloc[i_sig])
    c1 = _f(df["close"].iloc[i_sig + 1])
    if None in (c0, h0, c1) or c0 <= 0:
        return None
    if c1 > c0 or c1 > h0:
        return i_sig + 2
    return None


def b1_no_confirm(df: pd.DataFrame, i_sig: int) -> bool:
    """有訊號隔日柱，但未達 B1 確認。"""
    n = len(df)
    if i_sig + 1 >= n:
        return False
    c0 = _f(df["close"].iloc[i_sig])
    h0 = _f(df["high"].iloc[i_sig])
    c1 = _f(df["close"].iloc[i_sig + 1])
    if None in (c0, h0, c1) or c0 <= 0:
        return False
    return not (c1 > c0 or c1 > h0)


# ---- B2 量先價行 ----


def find_vol_spike(df: pd.DataFrame, i_sig: int, *, look: int = 3) -> Optional[int]:
    for j in range(max(0, i_sig - 1), min(len(df), i_sig + look + 1)):
        if _own_vol_ge_pct(df, j, lookback=20, pct=90.0):
            return j
    return None


def b2_stand_entry(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    """爆大量日高低錨 → 縮量站上撐（或壓轉撐）確認日之隔日開。"""
    n = len(df)
    v = find_vol_spike(df, i_sig, look=2)
    if v is None:
        return None
    lo_v = _f(df["low"].iloc[v])
    hi_v = _f(df["high"].iloc[v])
    v0 = _f(df["volume"].iloc[v])
    if None in (lo_v, hi_v, v0) or lo_v <= 0 or v0 <= 0:
        return None
    end = min(n - 2, v + 12)
    pressed_then_support = False
    for j in range(v + 1, end + 1):
        cj = _f(df["close"].iloc[j])
        if cj is None:
            continue
        if cj < lo_v:
            # 破撐＝放棄此錨
            return None
        if cj > hi_v:
            pressed_then_support = True  # 壓轉撐候選
        if not _vol_shrunk(df, j, v0):
            continue
        # 站上撐：收 ≥ 大量日低；或壓轉撐後收回站上大量日高
        ok = cj >= lo_v and (cj >= lo_v * 1.0)
        if pressed_then_support and cj >= hi_v:
            ok = True
        if cj >= lo_v and _vol_shrunk(df, j, v0):
            ok = True
        if ok and j + 1 < n:
            return j + 1
    return None


def b2_force_no_stand(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    """對照：有爆量錨但未站穩仍隔日開（慘度）。"""
    v = find_vol_spike(df, i_sig, look=2)
    if v is None:
        return None
    if b2_stand_entry(df, i_sig) is not None:
        return None
    j = i_sig + 1
    return j if j < len(df) else None


# ---- B3 量價背離（僅攻擊段）----


def _attack_end(
    df: pd.DataFrame, i: int, *, n_up: int, look_vol: int = 60
) -> Optional[int]:
    """若 i 為攻擊段末（連漲≥n_up 且區間漲幅≥近60波動門檻）回傳段起；否則 None。"""
    if i < n_up or i >= len(df):
        return None
    # 連漲：收盤遞增日數
    streak = 0
    for k in range(i, 0, -1):
        c = _f(df["close"].iloc[k])
        p = _f(df["close"].iloc[k - 1])
        if c is None or p is None or c <= p:
            break
        streak += 1
    if streak < n_up:
        return None
    start = i - streak
    c0 = _f(df["close"].iloc[start])
    c1 = _f(df["close"].iloc[i])
    if c0 is None or c1 is None or c0 <= 0:
        return None
    gain = (c1 - c0) / c0
    # 近 60 日波動門檻＝收盤報酬標準差×√n_up（粗；無假數）
    lo = max(1, i - look_vol)
    rets = []
    for k in range(lo, i + 1):
        a = _f(df["close"].iloc[k - 1])
        b = _f(df["close"].iloc[k])
        if a and b and a > 0:
            rets.append((b - a) / a)
    if len(rets) < 20:
        return None
    thr = float(np.std(rets)) * float(np.sqrt(n_up))
    if thr <= 0 or gain < thr:
        return None
    return start


def b3_divergence_at(df: pd.DataFrame, i: int, *, n_up: int) -> bool:
    """攻擊段內價創新高但量明顯縮（≤段內最大量 60% 或 ≤段內中位）。"""
    start = _attack_end(df, i, n_up=n_up)
    if start is None:
        return False
    highs = [_f(df["high"].iloc[j]) for j in range(start, i + 1)]
    vols = [_f(df["volume"].iloc[j]) for j in range(start, i + 1)]
    highs = [h for h in highs if h is not None]
    vols_ok = [v for v in vols if v is not None and v > 0]
    hi_i = _f(df["high"].iloc[i])
    vi = _f(df["volume"].iloc[i])
    if not highs or hi_i is None or vi is None or not vols_ok:
        return False
    # 當日高須為段內最高（價創新高）
    if hi_i < max(highs) - 1e-9:
        return False
    vmax = max(vols_ok)
    vmed = float(np.median(vols_ok))
    return vi <= vmax * 0.6 or vi <= vmed


def b3_false_positive_at(df: pd.DataFrame, i: int) -> bool:
    """非攻擊段的價高量縮（對照假陽性）。"""
    if _attack_end(df, i, n_up=5) is not None:
        return False
    if i < 20:
        return False
    hi_i = _f(df["high"].iloc[i])
    vi = _f(df["volume"].iloc[i])
    if hi_i is None or vi is None:
        return False
    lo = max(0, i - 20)
    prev_hi = max(
        (_f(df["high"].iloc[j]) or 0) for j in range(lo, i)
    )
    if hi_i < prev_hi:
        return False
    med = _own_vol_median(df, i, lookback=20)
    if med is None:
        return False
    return vi < med


# ---- B4 爆大量跌破平台 ----


def platform_box(
    df: pd.DataFrame, i: int, *, look_lo: int = 20, look_hi: int = 60
) -> Tuple[Optional[float], Optional[float]]:
    if i < look_lo:
        return None, None
    lo = max(0, i - look_hi)
    hi = i  # 不含當日
    if hi - lo < look_lo:
        return None, None
    highs = [_f(df["high"].iloc[j]) for j in range(lo, hi)]
    lows = [_f(df["low"].iloc[j]) for j in range(lo, hi)]
    highs = [x for x in highs if x is not None and x > 0]
    lows = [x for x in lows if x is not None and x > 0]
    if len(highs) < look_lo or len(lows) < look_lo:
        return None, None
    # 箱高／箱低：近窗 80／20 分位（可重算）
    box_hi = float(np.percentile(highs, 80))
    box_lo = float(np.percentile(lows, 20))
    if box_hi <= box_lo:
        return None, None
    return box_hi, box_lo


def b4_break_platform(df: pd.DataFrame, i: int) -> bool:
    if not _own_vol_ge_pct(df, i, lookback=20, pct=90.0):
        return False
    _, box_lo = platform_box(df, i)
    if box_lo is None:
        return False
    c = _f(df["close"].iloc[i])
    if c is None:
        return False
    return c < box_lo


def b4_fake_break(df: pd.DataFrame, i: int) -> bool:
    """破後 2 日內收復箱低。"""
    if not b4_break_platform(df, i):
        return False
    _, box_lo = platform_box(df, i)
    if box_lo is None:
        return False
    end = min(len(df) - 1, i + 2)
    for j in range(i + 1, end + 1):
        cj = _f(df["close"].iloc[j])
        if cj is not None and cj >= box_lo:
            return True
    return False


def recent_b4_break(df: pd.DataFrame, i_sig: int, *, look: int = 5) -> bool:
    for j in range(max(0, i_sig - look), i_sig + 1):
        if b4_break_platform(df, j) and not b4_fake_break(df, j):
            return True
    return False


# ---- B5 下殺取量後止跌 ----


def kill_volume_day(df: pd.DataFrame, i: int) -> bool:
    """放量跌：量大＋收跌／長陰。"""
    if not _own_vol_ge_pct(df, i, lookback=20, pct=80.0):
        return False
    o = _f(df["open"].iloc[i])
    c = _f(df["close"].iloc[i])
    h = _f(df["high"].iloc[i])
    l = _f(df["low"].iloc[i])
    if None in (o, c) or o <= 0 or c >= o:
        return False
    body = (o - c) / o
    if body < 0.008:
        return False
    if h is not None and l is not None and h > l:
        if (o - c) / (h - l) < 0.4 and (c - l) / (h - l) > 0.4:
            return False
    return True


def prior_swing_low(df: pd.DataFrame, i: int, *, lookback: int = 20) -> Optional[float]:
    if i < 2:
        return None
    lo = max(0, i - lookback)
    lows = [_f(df["low"].iloc[j]) for j in range(lo, i)]
    lows = [x for x in lows if x is not None and x > 0]
    if not lows:
        return None
    return float(min(lows))


def broke_low_recent(df: pd.DataFrame, i: int, *, look: int = 8) -> bool:
    for j in range(max(1, i - look), i + 1):
        anchor = prior_swing_low(df, j, lookback=20)
        c = _f(df["close"].iloc[j])
        l = _f(df["low"].iloc[j])
        if anchor is None or c is None or l is None:
            continue
        if c < anchor or l < anchor:
            return True
    return False


def b5_stabilize_after_kill(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    """破底／連跌後出現放量跌，再縮量止穩 ≥2 日 → 確認日隔日開。"""
    n = len(df)
    if not broke_low_recent(df, i_sig, look=10):
        return None
    start = max(0, i_sig - 10)
    end = min(n - 3, i_sig + 8)
    for j in range(start, end + 1):
        if not kill_volume_day(df, j):
            continue
        lo_k = _f(df["low"].iloc[j])
        v_k = _f(df["volume"].iloc[j])
        if lo_k is None or v_k is None:
            continue
        held = 0
        for k in range(j + 1, min(n, j + 6)):
            ck = _f(df["close"].iloc[k])
            vk = _f(df["volume"].iloc[k])
            if ck is None or vk is None:
                break
            if ck < lo_k or vk >= v_k * 0.95:
                held = 0
                break
            held += 1
            if held >= 2 and k + 1 < n:
                return k + 1
    return None


def b5_stabilize_no_kill(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    """對照：無下殺取量就標止穩（訊號隔日開），且近窗無 kill。"""
    if any(kill_volume_day(df, j) for j in range(max(0, i_sig - 8), i_sig + 1)):
        return None
    j = i_sig + 1
    return j if j < len(df) else None


# ---- B6 趨勢不易 V 轉 ----


def bear_structure_at(df: pd.DataFrame, i: int, *, n: int) -> bool:
    """連 n 日收跌或低點下移。"""
    if i < n:
        return False
    down_closes = 0
    lower_lows = 0
    for k in range(i - n + 1, i + 1):
        c = _f(df["close"].iloc[k])
        p = _f(df["close"].iloc[k - 1])
        l = _f(df["low"].iloc[k])
        lp = _f(df["low"].iloc[k - 1])
        if c is not None and p is not None and c < p:
            down_closes += 1
        if l is not None and lp is not None and l < lp:
            lower_lows += 1
    return down_closes >= n or lower_lows >= n


def segment_high(df: pd.DataFrame, i: int, *, n: int) -> Optional[float]:
    if i < n:
        return None
    highs = [_f(df["high"].iloc[j]) for j in range(i - n + 1, i + 1)]
    highs = [h for h in highs if h is not None]
    return max(highs) if highs else None


def sharp_v_hit(df: pd.DataFrame, i_end: int, *, n: int, within: int = 3) -> bool:
    """急 V：3 日內收復該段高點。"""
    hi = segment_high(df, i_end, n=n)
    if hi is None:
        return False
    end = min(len(df) - 1, i_end + within)
    for j in range(i_end + 1, end + 1):
        c = _f(df["close"].iloc[j])
        if c is not None and c >= hi:
            return True
    return False


# ---- B9 有效突破前波高 ----


def prior_swing_high(df: pd.DataFrame, i: int, *, lookback: int = 40) -> Optional[float]:
    if i < 5:
        return None
    lo = max(0, i - lookback)
    # 明確高點：近窗最高（排除最近 3 日避免當日刺穿自比）
    hi_end = max(lo + 1, i - 3)
    highs = [_f(df["high"].iloc[j]) for j in range(lo, hi_end)]
    highs = [h for h in highs if h is not None and h > 0]
    if len(highs) < 5:
        return None
    return float(max(highs))


def b9_valid_breakout(df: pd.DataFrame, i: int) -> bool:
    anchor = prior_swing_high(df, i, lookback=40)
    if anchor is None:
        return False
    c = _f(df["close"].iloc[i])
    med = _own_vol_median(df, i, lookback=20)
    vt = _f(df["volume"].iloc[i])
    if c is None or med is None or vt is None:
        return False
    return c > anchor and vt >= med


def b9_pierce_only(df: pd.DataFrame, i: int) -> bool:
    """僅盤中刺穿：高＞前波高但收未站上，或量萎。"""
    anchor = prior_swing_high(df, i, lookback=40)
    if anchor is None:
        return False
    h = _f(df["high"].iloc[i])
    c = _f(df["close"].iloc[i])
    med = _own_vol_median(df, i, lookback=20)
    vt = _f(df["volume"].iloc[i])
    if None in (h, c) or h <= anchor:
        return False
    if c > anchor and med is not None and vt is not None and vt >= med:
        return False  # 有效突破不算刺穿
    return True


def b9_confirm_entry(df: pd.DataFrame, i_sig: int) -> Optional[int]:
    """訊號後近窗出現有效突破 → 突破確認日隔日開。"""
    n = len(df)
    end = min(n - 2, i_sig + 5)
    for j in range(i_sig, end + 1):
        if b9_valid_breakout(df, j):
            return j + 1
    return None


# ---- B10 關鍵 K ----


def b10_key_bar(df: pd.DataFrame, i: int, *, look: int = 90) -> bool:
    """單日振幅與量同達自身近 look 日 ≥90 分位。"""
    if i < look // 2 or i >= len(df):
        return False
    lo = max(0, i - look)
    amps = []
    vols = []
    for j in range(lo, i):
        h = _f(df["high"].iloc[j])
        l = _f(df["low"].iloc[j])
        v = _f(df["volume"].iloc[j])
        if h is not None and l is not None and h > l:
            amps.append(h - l)
        if v is not None and v > 0:
            vols.append(v)
    if len(amps) < 30 or len(vols) < 30:
        return False
    h = _f(df["high"].iloc[i])
    l = _f(df["low"].iloc[i])
    v = _f(df["volume"].iloc[i])
    if None in (h, l, v) or h <= l or v <= 0:
        return False
    amp = h - l
    a_thr = _pctile(amps, 90.0)
    v_thr = _pctile(vols, 90.0)
    if a_thr is None or v_thr is None:
        return False
    return amp >= a_thr and v >= v_thr


# ---- 進場／評分輔助 ----


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
        holdout=bool(sig.holdout),
    )


def _baseline_entry(sig: Sig, df: pd.DataFrame, cand: str) -> Optional[Entry]:
    return _entry_from(sig.track, cand, sig, df, sig.i + 1 if sig.i + 1 < len(df) else None)


def _path_max_dd(df: pd.DataFrame, i_entry: int, entry_px: float, h: int) -> Optional[float]:
    """進場至 h 日內最低收相對進場價的最大回撤（負值）。"""
    if entry_px <= 0:
        return None
    end = min(len(df) - 1, i_entry + h - 1)
    if end < i_entry:
        return None
    lows = []
    for j in range(i_entry, end + 1):
        lo = _f(df["low"].iloc[j])
        if lo is not None and lo > 0:
            lows.append((lo - entry_px) / entry_px)
    if not lows:
        return None
    return float(min(lows))


def run(db: str, out_path: str, *, smoke: bool = False) -> Dict[str, Any]:
    """全量跑 B1–B6／B9／B10；pending_new_R 不含 B7／B8。"""
    t0 = time.time()
    universe = load_universe(db)
    twii = load_twii(db)
    con = sqlite3.connect(db)
    try:
        tw_days = [
            _ymd(r[0])
            for r in con.execute(
                "SELECT DISTINCT replace(CAST(date AS TEXT),'-','') FROM daily_quotes WHERE market='TW' ORDER BY 1"
            )
        ]
        tw_days = [d for d in tw_days if d]
        em_days = [
            _ymd(r[0])
            for r in con.execute(
                "SELECT DISTINCT replace(CAST(date AS TEXT),'-','') FROM emerging_quotes ORDER BY 1"
            )
        ]
        em_days = [d for d in em_days if d]
    finally:
        con.close()

    holdout_from = {
        "TW": holdout_cut(tw_days) or LOCKED_HOLDOUT["TW"],
        "TWO": holdout_cut(tw_days) or LOCKED_HOLDOUT["TWO"],
        "EM": holdout_cut(em_days) or LOCKED_HOLDOUT["EM"],
    }
    # 與第 1／2 步總表對齊鎖定留白窗
    for m, locked in LOCKED_HOLDOUT.items():
        holdout_from[m] = locked

    sids = sorted(universe.keys())
    if smoke:
        picked: List[str] = []
        for m in MARKETS:
            picked.extend([s for s in sids if universe[s]["market"] == m][:8])
        sids = picked

    frames: Dict[str, pd.DataFrame] = {}
    signals: List[Sig] = []
    print(f"[load] stocks={len(sids)}", flush=True)
    con = sqlite3.connect(db)
    try:
        for k, sid in enumerate(sids):
            if (k + 1) % 200 == 0:
                print(f"[load] {k+1}/{len(sids)}", flush=True)
            meta = universe[sid]
            market = meta["market"]
            df = load_stock_df(con, sid, market)
            if df is None or df.empty or len(df) < 80:
                continue
            frames[sid] = df
            hf = holdout_from.get(market, "")
            for track in PRICE_TRACKS:
                idxs = find_signal_indices(
                    df, track, market, meta.get("industry", "")
                )
                for i in idxs:
                    if i + 1 >= len(df):
                        continue
                    d = str(df["date"].iloc[i])
                    signals.append(
                        Sig(
                            track=track,
                            sid=sid,
                            market=market,
                            date=d,
                            i=int(i),
                            holdout=bool(hf and d >= hf),
                        )
                    )
            if smoke and len(signals) > 400:
                break
    finally:
        con.close()

    print(f"[signals] n={len(signals)} frames={len(frames)}", flush=True)
    entries: List[Entry] = []
    # 事件形前向（B3／B6／B10／對照）
    event_fwd: Dict[str, List[float]] = defaultdict(list)
    event_dd: Dict[str, List[float]] = defaultdict(list)
    b6_stats = {
        "n5": {"struct": 0, "v_hit": 0, "rand_hit": 0, "rand_n": 0},
        "n8": {"struct": 0, "v_hit": 0, "rand_hit": 0, "rand_n": 0},
    }
    rng = random.Random(20261022)

    def add(e: Optional[Entry]) -> None:
        if e is not None:
            entries.append(e)

    for si, sig in enumerate(signals):
        if (si + 1) % 5000 == 0:
            print(f"[scan] {si+1}/{len(signals)} entries={len(entries)}", flush=True)
        df = frames[sig.sid]

        # R0 baseline
        add(_baseline_entry(sig, df, "baseline"))

        # B1
        j1 = b1_confirm_entry(df, sig.i)
        add(_entry_from(sig.track, "B1_confirm", sig, df, j1))
        if b1_no_confirm(df, sig.i):
            add(_baseline_entry(sig, df, "B1_no_confirm"))

        # B2
        j2 = b2_stand_entry(df, sig.i)
        add(_entry_from(sig.track, "B2_vol_price", sig, df, j2))
        j2f = b2_force_no_stand(df, sig.i)
        add(_entry_from(sig.track, "B2_force_no_stand", sig, df, j2f))

        # B4 排除濾網
        if not recent_b4_break(df, sig.i, look=5):
            add(_baseline_entry(sig, df, "B4_excl_break"))
        else:
            add(_baseline_entry(sig, df, "B4_keep_break"))
            if any(b4_fake_break(df, j) for j in range(max(0, sig.i - 5), sig.i + 1)):
                add(_baseline_entry(sig, df, "B4_fake_break"))

        # B5（止穩軌為主，其他軌也報）
        j5 = b5_stabilize_after_kill(df, sig.i)
        add(_entry_from(sig.track, "B5_after_kill", sig, df, j5))
        j5n = b5_stabilize_no_kill(df, sig.i)
        add(_entry_from(sig.track, "B5_no_kill", sig, df, j5n))

        # B6 環境排除
        if not bear_structure_at(df, sig.i, n=5):
            add(_baseline_entry(sig, df, "B6_excl_bear_n5"))
        if not bear_structure_at(df, sig.i, n=8):
            add(_baseline_entry(sig, df, "B6_excl_bear_n8"))

        # B9
        j9 = b9_confirm_entry(df, sig.i)
        add(_entry_from(sig.track, "B9_valid_break", sig, df, j9))
        if any(b9_pierce_only(df, j) for j in range(sig.i, min(len(df), sig.i + 3))):
            add(_baseline_entry(sig, df, "B9_pierce_only"))

        if smoke and len(entries) > 8000:
            break

    # 事件掃描：B3／B6／B10／隨機對照（全庫幀）
    print("[events] B3/B6/B10…", flush=True)
    twii_dates = sorted(twii.keys()) if twii else []
    for sid, df in frames.items():
        market = universe[sid]["market"]
        hf = holdout_from.get(market, "")
        n = len(df)
        for i in range(30, n - 3):
            d = str(df["date"].iloc[i])
            holdout = bool(hf and d >= hf)
            px = _f(df["open"].iloc[i + 1]) if i + 1 < n else None
            if px is None or px <= 0:
                continue

            def push_event(tag: str) -> None:
                # 事件形只進前向統計（不當買訊 Entry，避免全庫日掃爆量）
                rr = _fast_forward(df, i + 1, float(px), (1, 5, 20))
                for h, r in rr.items():
                    if r is not None:
                        event_fwd[f"{tag}_h{h}"].append(float(r))
                dd = _path_max_dd(df, i + 1, float(px), 5)
                if dd is not None:
                    event_dd[f"{tag}_dd5"].append(dd)

            if b3_divergence_at(df, i, n_up=5):
                push_event("B3_div_n5")
            if b3_divergence_at(df, i, n_up=8):
                push_event("B3_div_n8")
            if b3_false_positive_at(df, i):
                push_event("B3_false_pos")

            if b10_key_bar(df, i, look=90):
                push_event("B10_all")
                if r1e1_at(df, i):
                    push_event("B10_cap_r1e")
                else:
                    push_event("B10_minus_r1e")

            for n_key, nn in (("n5", 5), ("n8", 8)):
                # 只在結構「剛滿 N 日」的完成點計一次（避免連陰段天天重複）
                if not bear_structure_at(df, i, n=nn):
                    continue
                if i > nn and bear_structure_at(df, i - 1, n=nn):
                    continue
                b6_stats[n_key]["struct"] += 1
                hit = sharp_v_hit(df, i, n=nn, within=3)
                if hit:
                    b6_stats[n_key]["v_hit"] += 1
                    push_event(f"B6_v_ok_{n_key}")
                else:
                    push_event(f"B6_v_fail_{n_key}")
                if n > 40:
                    ri = rng.randint(30, n - 4)
                    b6_stats[n_key]["rand_n"] += 1
                    if sharp_v_hit(df, ri, n=nn, within=3):
                        b6_stats[n_key]["rand_hit"] += 1

            if smoke and sum(len(v) for v in event_fwd.values()) > 400:
                break
        if smoke and sum(len(v) for v in event_fwd.values()) > 400:
            break

    # 加權／隨機日對照（掛在 A1 鍵下方便總表）
    print("[ctrl] twii／random…", flush=True)
    if twii_dates and frames:
        sample_sids = list(frames.keys())[: (40 if smoke else 200)]
        for sid in sample_sids:
            df = frames[sid]
            market = universe[sid]["market"]
            hf = holdout_from.get(market, "")
            for _ in range(5 if smoke else 20):
                if len(df) < 40:
                    break
                i = rng.randint(20, len(df) - 5)
                d = str(df["date"].iloc[i])
                px = _f(df["open"].iloc[i + 1])
                if not px or px <= 0:
                    continue
                entries.append(
                    Entry(
                        "A1",
                        "ctrl_random_day",
                        sid,
                        market,
                        d,
                        i,
                        i + 1,
                        float(px),
                        bool(hf and d >= hf),
                    )
                )
                # 加權代理：同日加權隔日開→+5（只持加權報酬另報）
                if d in twii and i + 1 < len(df):
                    t_row = twii.get(d) or {}
                    # twii dict: date → {open,close,...}；用隔日收相對訊號日收
                    # 簡化：用個股進場日對齊的加權報酬另存在 ctrl_twii_rets
                    pass

    twii_h5: List[float] = []
    if twii and twii_dates:
        # 只持加權：每個交易日「隔日開→+5 收」
        closes = []
        opens = []
        days_sorted = []
        for d in twii_dates:
            row = twii[d]
            c = _f(row.get("close"))
            o = _f(row.get("open")) or c
            if c and c > 0 and o and o > 0:
                days_sorted.append(d)
                closes.append(c)
                opens.append(o)
        for i in range(len(days_sorted) - 6):
            ep = opens[i + 1]
            cl = closes[i + 5]
            if ep > 0 and cl > 0:
                twii_h5.append((cl - ep) / ep)

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
            if cand in OBS_CANDS or cand.startswith("B3_") or cand.startswith("B5_") or cand.startswith("B6_v_") or cand.startswith("B10_"):
                v = dict(v)
                v["verdict"] = "觀察"
                v["reason"] = "風險／事件形或對照，不當買訊換臉"
            verdicts[f"{track}:{cand}"] = v
            if v.get("verdict") == "可換" and cand != "baseline":
                replaceable.append(f"{track}:{cand}")

    # EVT 軌不進可換
    b6_out = {}
    for k, st in b6_stats.items():
        b6_out[k] = {
            "struct_n": st["struct"],
            "v_hit_rate": (st["v_hit"] / st["struct"]) if st["struct"] else None,
            "rand_hit_rate": (st["rand_hit"] / st["rand_n"]) if st["rand_n"] else None,
        }

    # 候選路徑回撤摘要（相對 baseline 的附加欄）
    dd_by_cand: Dict[str, List[float]] = defaultdict(list)
    for e in entries:
        if e.cand == "baseline" or e.track not in PRICE_TRACKS:
            continue
        df = frames.get(e.sid)
        if df is None:
            continue
        dd = _path_max_dd(df, e.i_entry, e.entry_px, 5)
        if dd is not None:
            dd_by_cand[f"{e.track}:{e.cand}:{e.market}"].append(dd)
    dd_summary = {k: summarize_rets(v) for k, v in dd_by_cand.items()}

    result = {
        "generated_at": _now_iso(),
        "db": db,
        "smoke": smoke,
        "elapsed_sec": round(time.time() - t0, 1),
        "holdout_from": holdout_from,
        "primary_h": PRIMARY_H,
        "min_n_days": MIN_N_DAYS,
        "min_wr_lift": MIN_WR_LIFT,
        "bare_k_lock": "B 條只准 OHLC＋量；不准均線／MACD／布林／KD 當主條件",
        "locked_scope": list(B_LOCKED),
        "skipped": list(B_SKIP),
        "no_reopen": ["R1e", "R1f", "R1g"],
        "signal_counts": {
            f"{t}:{m}": sum(1 for s in signals if s.track == t and s.market == m)
            for t in PRICE_TRACKS
            for m in MARKETS
        },
        "candidate_names": cand_names,
        "full": full,
        "train": train,
        "holdout": holdout,
        "verdicts": verdicts,
        "replaceable": replaceable,
        "event_forward": {k: summarize_rets(v) for k, v in event_fwd.items()},
        "event_dd5": {k: summarize_rets(v) for k, v in event_dd.items()},
        "event_counts": {k: len(v) for k, v in event_fwd.items()},
        "path_dd5": dd_summary,
        "b6_v_turn": b6_out,
        "ctrl_twii_h5": summarize_rets(twii_h5),
        "notes": {
            "gate": "可換＝TW／TWO 全樣＋留白 h5 勝率≥現況+1pt 且均報酬≥現況，n_days≥20",
            "buy_formula": "未改 leave_zero／紅箭／止穩公式",
            "round3": "未塞入第3輪；宇宙／進場定義＝step2 on main",
            "B10_split": "B10∩R1e vs B10∖R1e 分軌；不准混成一條勝率",
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
        "/tmp/mt_stock_vp_b_smoke.json" if args.smoke else "/tmp/mt_stock_vp_b.json"
    )
    run(db, out, smoke=bool(args.smoke))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
