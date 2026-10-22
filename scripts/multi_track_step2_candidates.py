#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多軌勝率長測第 2 步：價量時機／可重算候選掃＋留白驗證。

掛在 A1／A2（及允許的 A5／A7）現況訊號之上做時機／微調；
不准改 leave_zero／ma60_lower 公式；買訊不准半透明假買臉。
H7：n≥20 獨立交易日且贏該軌現況；H10：留白（最後約 20%）沒贏＝不可換。
時區 Asia/Taipei；全量不准抽樣；勝率分軌不准混；興櫃橘六角不可測不掃。

用法：
  .venv/bin/python scripts/multi_track_step2_candidates.py \\
    --db data/wayne_market.db --out /tmp/mt_step2.json
  .venv/bin/python scripts/multi_track_step2_candidates.py --smoke
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sqlite3  # noqa: E402

from buy_exclude import should_exclude_buy  # noqa: E402
from decision_card_signals import leave_zero_bar_indices  # noqa: E402
from red_arrow_quant import nav_low_ma60_lower_mask  # noqa: E402
from stabilize_watch import HOLD_N  # noqa: E402
from winrate_ai_priority import is_winrate_priority  # noqa: E402

# 複用第 1 步底線腳本工具（同 repo）
from multi_track_baseline_backtest import (  # noqa: E402
    HORIZONS,
    dedup_indices,
    forward_stats,
    holdout_cut,
    load_stock_df,
    load_twii,
    load_universe,
    stabilize_fire_indices,
    summarize_rets,
    twii_forward,
)

TP = ZoneInfo("Asia/Taipei")
PRIMARY_H = 5
MIN_N_DAYS = 20
MIN_WR_LIFT = 0.01  # +1.0pt
# 鎖定與第 1 步總表同一留白起日（若庫交易日切點變了仍以實算為準並寫進 JSON）
LOCKED_HOLDOUT = {"TW": "20260529", "TWO": "20260529", "EM": "20260730"}
PRICE_TRACKS = ("A1", "A2", "A5", "A7")
MARKETS = ("TW", "TWO", "EM")


def _now_iso() -> str:
    return datetime.now(TP).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "").strip()[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or math.isinf(x):
        return None
    return x


@dataclass
class Signal:
    track: str
    sid: str
    market: str
    date: str
    i: int
    holdout: bool


@dataclass
class Entry:
    """候選進場點（訊號日 i_sig；進場日索引 i_entry＝開盤進場那根）。"""

    track: str
    cand: str
    sid: str
    market: str
    date_sig: str
    i_sig: int
    i_entry: int
    entry_px: float
    holdout: bool


def _ma(series: Sequence[float], n: int, i: int) -> Optional[float]:
    if i + 1 < n:
        return None
    xs = [float(x) for x in series[i + 1 - n : i + 1] if x is not None]
    if len(xs) < n or any(x <= 0 for x in xs):
        return None
    return sum(xs) / n


def find_signal_indices(df: pd.DataFrame, track: str, market: str, industry: str) -> List[int]:
    if df is None or len(df) < 2:
        return []
    if track == "A1":
        return dedup_indices(leave_zero_bar_indices(df) or [])
    if track == "A2":
        if len(df) < 60:
            return []
        mask = nav_low_ma60_lower_mask(df)
        hits = [i for i, v in enumerate(mask.tolist()) if v]
        return dedup_indices(hits)
    if track == "A5":
        return dedup_indices(stabilize_fire_indices(df, HOLD_N))
    if track == "A7":
        if not is_winrate_priority(industry):
            return []
        lz = leave_zero_bar_indices(df) or []
        hits = []
        for i in lz:
            try:
                if should_exclude_buy(
                    df,
                    i,
                    emerging=(market == "EM"),
                    quote_source=("emerging_quotes" if market == "EM" else ""),
                ):
                    continue
            except Exception:
                continue
            hits.append(i)
        return dedup_indices(hits)
    return []


# ---- 候選：回傳進場索引（開盤那根），或 None＝此訊號不進樣 ----


def cand_baseline(_df: pd.DataFrame, i_sig: int) -> Optional[int]:
    """現況：訊號隔日開盤進場。"""
    j = i_sig + 1
    return j if j < len(_df) else None


def cand_wait_n(n: int) -> Callable[[pd.DataFrame, int], Optional[int]]:
    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        j = i_sig + 1 + int(n)
        return j if j < len(df) else None

    return _fn


def cand_hi_vol_shrink_down(
    *,
    down_n: int,
    look_ahead: int = 8,
    vol_spike: float = 1.5,
    ma_vol: int = 20,
) -> Callable[[pd.DataFrame, int], Optional[int]]:
    """大量（≥均量×spike）後日連跌縮量 down_n 日；確認日隔日開進場。"""

    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        n = len(df)
        closes = df["close"].tolist()
        vols = df["volume"].tolist()
        end = min(n - 2, i_sig + look_ahead)
        for t in range(i_sig, end + 1):
            vma = _ma(vols, ma_vol, t)
            vt = _f(vols[t])
            if vma is None or vt is None or vt < vol_spike * vma:
                continue
            # 從 t+1 起找 down_n 連跌且量遞減
            if t + down_n >= n - 1:
                continue
            ok = True
            prev_c = _f(closes[t])
            prev_v = vt
            if prev_c is None or prev_c <= 0:
                continue
            last = t
            for k in range(1, down_n + 1):
                j = t + k
                cj = _f(closes[j])
                vj = _f(vols[j])
                if cj is None or vj is None or cj <= 0 or cj >= prev_c or vj >= prev_v:
                    ok = False
                    break
                prev_c, prev_v, last = cj, vj, j
            if not ok:
                continue
            entry = last + 1
            if entry < n:
                return entry
        return None

    return _fn


def cand_wait_after_shrink_down(
    *,
    down_n: int,
    wait_after: int,
    look_ahead: int = 8,
    vol_spike: float = 1.5,
) -> Callable[[pd.DataFrame, int], Optional[int]]:
    """大量後日連跌縮量後再隔 wait_after 日開盤進場。"""
    base = cand_hi_vol_shrink_down(down_n=down_n, look_ahead=look_ahead, vol_spike=vol_spike)

    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        j = base(df, i_sig)
        if j is None:
            return None
        # base 已是確認日隔日；再往後 wait_after
        k = j + int(wait_after)
        return k if k < len(df) else None

    return _fn


def cand_pv_confirm_up_shrink(
    *, look_ahead: int = 5
) -> Callable[[pd.DataFrame, int], Optional[int]]:
    """訊號後 look_ahead 內：收＞訊號收且量＜訊號量 → 該日隔日開。"""

    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        n = len(df)
        c0 = _f(df["close"].iloc[i_sig])
        v0 = _f(df["volume"].iloc[i_sig])
        if c0 is None or v0 is None or c0 <= 0 or v0 <= 0:
            return None
        end = min(n - 2, i_sig + look_ahead)
        for j in range(i_sig + 1, end + 1):
            cj = _f(df["close"].iloc[j])
            vj = _f(df["volume"].iloc[j])
            if cj is None or vj is None:
                continue
            if cj > c0 and vj < v0:
                return j + 1 if j + 1 < n else None
        return None

    return _fn


def cand_pullback_then_regain(
    *, look_ahead: int = 6
) -> Callable[[pd.DataFrame, int], Optional[int]]:
    """訊號後至少一日收跌，再一日收＞該跌日高 → 隔日開。"""

    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        n = len(df)
        end = min(n - 2, i_sig + look_ahead)
        c_sig = _f(df["close"].iloc[i_sig])
        if c_sig is None:
            return None
        down_i = None
        for j in range(i_sig + 1, end + 1):
            cj = _f(df["close"].iloc[j])
            if cj is None:
                continue
            if down_i is None:
                if cj < c_sig:
                    down_i = j
                continue
            hi_d = _f(df["high"].iloc[down_i])
            if hi_d is not None and cj > hi_d:
                return j + 1 if j + 1 < n else None
        return None

    return _fn


def cand_signal_vol_tercile(
    *, want: str, lookback: int = 60
) -> Callable[[pd.DataFrame, int], Optional[int]]:
    """訊號日量在該檔近 lookback 三分位：low/mid/high；過則隔日開。"""

    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        if i_sig + 1 >= len(df):
            return None
        lo = max(0, i_sig + 1 - lookback)
        vols = [_f(v) for v in df["volume"].iloc[lo : i_sig + 1].tolist()]
        vols = [v for v in vols if v is not None and v > 0]
        vt = _f(df["volume"].iloc[i_sig])
        if vt is None or vt <= 0 or len(vols) < 9:
            return None
        xs = sorted(vols)
        a = xs[len(xs) // 3]
        b = xs[(2 * len(xs)) // 3]
        if vt <= a:
            band = "low"
        elif vt <= b:
            band = "mid"
        else:
            band = "high"
        if band != want:
            return None
        return i_sig + 1

    return _fn


def cand_close_above_ma20(*, within: int = 3) -> Callable[[pd.DataFrame, int], Optional[int]]:
    """訊號後 within 日內收站上 20 均 → 該日隔日開。"""

    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        n = len(df)
        closes = df["close"].tolist()
        end = min(n - 2, i_sig + within)
        for j in range(i_sig, end + 1):
            m = _ma(closes, 20, j)
            cj = _f(closes[j])
            if m is None or cj is None:
                continue
            if cj >= m:
                return j + 1 if j + 1 < n else None
        return None

    return _fn


def cand_two_day_vol_shrink() -> Callable[[pd.DataFrame, int], Optional[int]]:
    """訊號後連續兩日量縮（不論漲跌）→ 第二日隔日開。"""

    def _fn(df: pd.DataFrame, i_sig: int) -> Optional[int]:
        n = len(df)
        if i_sig + 3 >= n:
            return None
        v0 = _f(df["volume"].iloc[i_sig])
        v1 = _f(df["volume"].iloc[i_sig + 1])
        v2 = _f(df["volume"].iloc[i_sig + 2])
        if v0 is None or v1 is None or v2 is None:
            return None
        if v1 < v0 and v2 < v1:
            return i_sig + 3
        return None

    return _fn


# 候選表：鍵＝名稱；適用軌；函式
CANDIDATE_SPECS: List[Tuple[str, Tuple[str, ...], Callable[[pd.DataFrame, int], Optional[int]]]] = [
    ("baseline", PRICE_TRACKS, cand_baseline),
    ("wait_1", PRICE_TRACKS, cand_wait_n(1)),
    ("wait_2", PRICE_TRACKS, cand_wait_n(2)),
    ("wait_3", PRICE_TRACKS, cand_wait_n(3)),
    ("wait_5", ("A1", "A2"), cand_wait_n(5)),
    (
        "hi_vol_shrink_down2",
        ("A1", "A2"),
        cand_hi_vol_shrink_down(down_n=2),
    ),
    (
        "hi_vol_shrink_down3",
        ("A1", "A2"),
        cand_hi_vol_shrink_down(down_n=3),
    ),
    (
        "hi_vol_down2_wait1",
        ("A1", "A2"),
        cand_wait_after_shrink_down(down_n=2, wait_after=1),
    ),
    (
        "hi_vol_down2_wait2",
        ("A1", "A2"),
        cand_wait_after_shrink_down(down_n=2, wait_after=2),
    ),
    ("pv_confirm_up_shrink", ("A1", "A2", "A7"), cand_pv_confirm_up_shrink()),
    ("pullback_regain", ("A1", "A2"), cand_pullback_then_regain()),
    ("sig_vol_high", PRICE_TRACKS, cand_signal_vol_tercile(want="high")),
    ("sig_vol_mid", PRICE_TRACKS, cand_signal_vol_tercile(want="mid")),
    ("sig_vol_low", PRICE_TRACKS, cand_signal_vol_tercile(want="low")),
    ("close_above_ma20", ("A1", "A2", "A5"), cand_close_above_ma20()),
    ("two_day_vol_shrink", ("A1", "A2"), cand_two_day_vol_shrink()),
]


def score_entries(
    entries: Sequence[Entry],
    frames: Dict[str, pd.DataFrame],
    twii: Dict[str, Dict[str, float]],
    *,
    holdout_only: Optional[bool] = None,
) -> Dict[str, Any]:
    """依 track×cand×market 彙總；holdout_only True/False 切留白／訓練窗。"""
    buckets: Dict[Tuple[str, str, str], List[Entry]] = defaultdict(list)
    for e in entries:
        if holdout_only is True and not e.holdout:
            continue
        if holdout_only is False and e.holdout:
            continue
        buckets[(e.track, e.cand, e.market)].append(e)

    out: Dict[str, Any] = {}
    for key, evs in sorted(buckets.items()):
        track, cand, market = key
        rows: Dict[str, List[float]] = defaultdict(list)
        rows_ex: Dict[str, List[float]] = defaultdict(list)
        n_days = len({e.date_sig for e in evs})
        for e in evs:
            df = frames.get(e.sid)
            if df is None or e.i_entry >= len(df) or e.entry_px <= 0:
                continue
            # forward_stats 以訊號日 i 為錨、進場＝i+1 open；
            # 此處進場已在 i_entry，改用「假訊號日＝i_entry-1」對齊同一函式語意
            i_fake = e.i_entry - 1
            if i_fake < 0:
                continue
            rets, _, done = forward_stats(df, i_fake, entry_px=float(e.entry_px))
            days = [str(x) for x in df["date"].tolist()]
            for h in HORIZONS:
                if not done.get(h) or rets.get(h) is None:
                    continue
                r = float(rets[h])
                rows[str(h)].append(r)
                tx = twii_forward(twii, days, i_fake, h, entry_open=True)
                if tx is not None:
                    rows_ex[str(h)].append(r - float(tx))
        out[f"{track}:{cand}:{market}"] = {
            "n_events": len(evs),
            "n_days": n_days,
            "horizons": {h: summarize_rets(rows[str(h)]) for h in map(str, HORIZONS)},
            "excess_vs_twii": {
                h: summarize_rets(rows_ex[str(h)]) for h in map(str, HORIZONS)
            },
        }
    return out


def _cell_h(cell: Optional[Dict[str, Any]], h: int = PRIMARY_H) -> Tuple[Optional[float], Optional[float], int, int]:
    if not cell:
        return None, None, 0, 0
    hs = (cell.get("horizons") or {}).get(str(h)) or {}
    return hs.get("win_rate"), hs.get("mean"), int(cell.get("n_days") or 0), int(hs.get("n") or 0)


def verdict_for(
    track: str,
    cand: str,
    full: Dict[str, Any],
    holdout: Dict[str, Any],
) -> Dict[str, Any]:
    """逐市場比 baseline；可換＝TW／TWO 留白皆贏且 n_days≥20，且全樣也贏。"""
    if cand == "baseline":
        return {
            "verdict": "維持",
            "reason": "現況對照列",
            "markets": {},
        }

    markets_detail: Dict[str, Any] = {}
    pass_m: List[str] = []
    fail_m: List[str] = []
    for m in MARKETS:
        b_full = full.get(f"{track}:baseline:{m}")
        c_full = full.get(f"{track}:{cand}:{m}")
        b_ho = holdout.get(f"{track}:baseline:{m}")
        c_ho = holdout.get(f"{track}:{cand}:{m}")
        b_wr, b_mean, b_nd, _ = _cell_h(b_full)
        c_wr, c_mean, c_nd, c_n = _cell_h(c_full)
        bh_wr, bh_mean, bh_nd, _ = _cell_h(b_ho)
        ch_wr, ch_mean, ch_nd, ch_n = _cell_h(c_ho)

        def _beats(cwr, cmean, bwr, bmean) -> Optional[bool]:
            if cwr is None or bwr is None or cmean is None or bmean is None:
                return None
            return (cwr >= bwr + MIN_WR_LIFT) and (cmean >= bmean)

        full_win = _beats(c_wr, c_mean, b_wr, b_mean)
        ho_win = _beats(ch_wr, ch_mean, bh_wr, bh_mean)
        enough = (ch_nd >= MIN_N_DAYS) if m != "EM" else (ch_nd >= max(10, MIN_N_DAYS // 2))
        # 興櫃：樣短，門檻放寬 n_days；仍須留白贏才算該市場過
        status = "na"
        if c_nd == 0 or c_n == 0:
            status = "無樣本"
        elif ho_win is True and full_win is True and enough:
            status = "過閘"
            pass_m.append(m)
        elif ho_win is False or full_win is False:
            status = "未贏"
            fail_m.append(m)
        elif not enough:
            status = "n不足"
            fail_m.append(m)
        else:
            status = "未定"
            fail_m.append(m)
        markets_detail[m] = {
            "status": status,
            "full": {
                "n_days": c_nd,
                "h5_wr": c_wr,
                "h5_mean": c_mean,
                "base_wr": b_wr,
                "base_mean": b_mean,
                "beats": full_win,
            },
            "holdout": {
                "n_days": ch_nd,
                "h5_wr": ch_wr,
                "h5_mean": ch_mean,
                "base_wr": bh_wr,
                "base_mean": bh_mean,
                "beats": ho_win,
            },
        }

    # 可換：TW 必過；TWO 有樣則必過；EM 不擋（缺樣可）
    tw_ok = markets_detail.get("TW", {}).get("status") == "過閘"
    two_st = markets_detail.get("TWO", {}).get("status")
    two_nd = (markets_detail.get("TWO", {}).get("full") or {}).get("n_days") or 0
    two_ok = two_st == "過閘" or (two_st == "無樣本" and two_nd == 0)

    if tw_ok and two_ok:
        verdict = "可換"
        reason = "TW／TWO 全樣＋留白皆贏現況且 n 夠"
    elif all(markets_detail[m]["status"] in ("未贏", "n不足", "無樣本", "未定") for m in MARKETS):
        # 全面未贏或無樣 → 放棄（明顯差）vs 維持（接近）
        any_near = False
        for m in ("TW", "TWO"):
            f = markets_detail[m]["full"]
            if f.get("h5_wr") is not None and f.get("base_wr") is not None:
                if f["h5_wr"] + 0.005 >= f["base_wr"]:
                    any_near = True
        verdict = "維持" if any_near else "放棄"
        reason = "留白或全樣未穩贏現況"
    else:
        verdict = "維持"
        reason = "未同時過 TW／TWO 留白閘"

    return {"verdict": verdict, "reason": reason, "markets": markets_detail}


def run(db: str, out_path: str, *, smoke: bool = False) -> Dict[str, Any]:
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
    # 與第 1 步總表對齊：若實算切點不同，仍採用鎖定窗（H10 已標）
    for m, locked in LOCKED_HOLDOUT.items():
        if holdout_from.get(m) != locked:
            holdout_from[m] = locked

    sids = sorted(universe.keys())
    if smoke:
        picked: List[str] = []
        for m in MARKETS:
            picked.extend([s for s in sids if universe[s]["market"] == m][:6])
        sids = picked

    frames: Dict[str, pd.DataFrame] = {}
    signals: List[Signal] = []
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
            for track in PRICE_TRACKS:
                for ix in find_signal_indices(df, track, market, industry):
                    if ix < 0 or ix >= len(df) - 1:
                        continue
                    d = days[ix]
                    signals.append(
                        Signal(
                            track=track,
                            sid=sid,
                            market=market,
                            date=d,
                            i=ix,
                            holdout=bool(hf and d >= hf),
                        )
                    )
            if smoke and i >= 18:
                break
            if (i + 1) % 200 == 0:
                print(f"[sig] {i+1}/{len(sids)} signals={len(signals)}", flush=True)
    finally:
        con.close()

    print(f"[cand] signals={len(signals)} applying {len(CANDIDATE_SPECS)} specs", flush=True)
    entries: List[Entry] = []
    for sig in signals:
        df = frames[sig.sid]
        for name, tracks, fn in CANDIDATE_SPECS:
            if sig.track not in tracks:
                continue
            i_entry = fn(df, sig.i)
            if i_entry is None or i_entry >= len(df):
                continue
            px = _f(df["open"].iloc[i_entry])
            if px is None or px <= 0:
                continue
            entries.append(
                Entry(
                    track=sig.track,
                    cand=name,
                    sid=sig.sid,
                    market=sig.market,
                    date_sig=sig.date,
                    i_sig=sig.i,
                    i_entry=int(i_entry),
                    entry_px=float(px),
                    holdout=sig.holdout,
                )
            )
        if smoke and len(entries) > 800:
            break

    print(f"[score] entries={len(entries)}", flush=True)
    full = score_entries(entries, frames, twii, holdout_only=None)
    train = score_entries(entries, frames, twii, holdout_only=False)
    holdout = score_entries(entries, frames, twii, holdout_only=True)

    verdicts: Dict[str, Any] = {}
    for name, tracks, _ in CANDIDATE_SPECS:
        for track in tracks:
            key = f"{track}:{name}"
            verdicts[key] = verdict_for(track, name, full, holdout)

    replaceable = [
        k for k, v in verdicts.items() if v.get("verdict") == "可換" and not k.endswith(":baseline")
    ]

    result = {
        "generated_at": _now_iso(),
        "db": db,
        "smoke": smoke,
        "elapsed_sec": round(time.time() - t0, 1),
        "holdout_from": holdout_from,
        "primary_h": PRIMARY_H,
        "min_n_days": MIN_N_DAYS,
        "min_wr_lift": MIN_WR_LIFT,
        "signal_counts": {
            f"{t}:{m}": sum(1 for s in signals if s.track == t and s.market == m)
            for t in PRICE_TRACKS
            for m in MARKETS
        },
        "candidate_names": [c[0] for c in CANDIDATE_SPECS],
        "full": full,
        "train": train,
        "holdout": holdout,
        "verdicts": verdicts,
        "replaceable": replaceable,
        "notes": {
            "A3_A4": "興櫃橘六角不可測；本步不掃外資軌時機",
            "formula": "未改 leave_zero／ma60_lower；時機僅旁註候選",
            "gate": "可換＝TW／TWO 全樣＋留白 h5 勝率≥現況+1pt 且平均報酬≥現況，n_days≥20",
        },
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(
        f"[done] wrote {out_path} elapsed={result['elapsed_sec']}s "
        f"replaceable={replaceable}",
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
        "/tmp/mt_step2_smoke.json" if args.smoke else "/tmp/mt_step2.json"
    )
    run(db, out, smoke=bool(args.smoke))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
