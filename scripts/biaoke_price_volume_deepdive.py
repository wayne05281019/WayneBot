#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WB-29 飆大價量關係特別解析：多檔細部拆解＋裸 K＋量靜默試回測。

硬規則：官方已收 OHLC＋量；盤中未收不當收；無假數；不是買訊；
不准改 leave_zero／golden_buy／海選；勝率分軌；Asia/Taipei。
過程／％不准進對話。預設不上話筒臉。

例：
  python3 scripts/biaoke_price_volume_deepdive.py \\
    --db data/wayne_market.db \\
    --out-json /tmp/pv_deepdive.json \\
    --universe-limit 0
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_track_round3 import (  # noqa: E402
    TripleTrap,
    detect_triple_traps,
    r1e1_at,
    r1e2_at,
    r1g_break_loud,
    r1g_break_quiet,
    v_reversal_hit,
)
from multi_track_step2_candidates import _f, _ymd  # noqa: E402
from vol_zone_chart import find_volume_zone  # noqa: E402

TP = ZoneInfo("Asia/Taipei")
HOLDOFF = 0.20  # 末 20% 時間留白
FORWARD = (1, 3, 5, 10)

# 頭部八檔（186743614）＋近期點名／風向球＋庫內可對大量事件股
HEAD_EIGHT = [
    ("3443", "創意", "head8"),
    ("3653", "健策", "head8"),
    ("8046", "南電", "head8"),
    ("2368", "金像電", "head8"),
    ("3081", "聯亞", "head8"),
    ("2454", "聯發科", "head8"),
    ("3008", "大立光", "head8"),
    ("3017", "奇鋐", "head8"),
]
RECENT_NAMED = [
    ("2330", "台積電", "named"),
    ("2383", "台光電", "named"),
    ("2308", "台達電", "named"),
    ("6223", "旺矽", "named"),
    ("2345", "智邦", "named"),
    ("8210", "勤誠", "named"),
    ("2059", "川湖", "named"),
    ("2408", "南亞科", "named"),
    ("5274", "信驊", "named"),
    ("3037", "欣興", "named"),
    ("3661", "世芯-KY", "named"),
    ("6669", "緯穎", "named"),
    ("3231", "緯創", "named"),
    ("3711", "日月光投控", "named"),
    ("3529", "力旺", "named"),
    ("4966", "譜瑞-KY", "named"),
]


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


def load_stock(con: sqlite3.Connection, sid: str) -> Tuple[pd.DataFrame, str]:
    df = pd.read_sql_query(
        """
        SELECT replace(CAST(date AS TEXT),'-','') AS date,
               stock_name, open, high, low, close,
               COALESCE(volume,0) AS volume
        FROM daily_quotes
        WHERE stock_id=? AND close>0 AND open>0 AND high>0 AND low>0
        ORDER BY date
        """,
        con,
        params=(sid,),
    )
    name = ""
    if not df.empty:
        name = str(df["stock_name"].iloc[-1] or "")
        df["date"] = df["date"].map(_ymd)
        df = df[df["date"].str.len() == 8].reset_index(drop=True)
    return df, name


def load_universe_ids(con: sqlite3.Connection, limit: int = 0) -> List[str]:
    rows = con.execute(
        """
        SELECT stock_id FROM daily_quotes
        WHERE stock_id GLOB '[0-9][0-9][0-9][0-9]'
          AND length(stock_id)=4
          AND market IN ('TW','TWO')
        GROUP BY stock_id
        HAVING COUNT(*) >= 120
           AND MAX(date) >= '20261001'
           AND SUM(CASE WHEN volume>0 THEN 1 ELSE 0 END) >= 100
        ORDER BY stock_id
        """
    ).fetchall()
    # 擋 ETF／特別股樣式：00xx
    ids = []
    for (sid,) in rows:
        s = str(sid)
        if s.startswith("00"):
            continue
        ids.append(s)
    if limit and limit > 0:
        return ids[:limit]
    return ids


def fwd_rets(df: pd.DataFrame, i: int) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    c0 = _f(df["close"].iloc[i])
    if c0 is None or c0 <= 0:
        return {f"h{h}": None for h in FORWARD}
    for h in FORWARD:
        j = i + h
        if j >= len(df):
            out[f"h{h}"] = None
            continue
        cj = _f(df["close"].iloc[j])
        out[f"h{h}"] = None if cj is None or cj <= 0 else (cj / c0 - 1.0)
    return out


def cont_down(df: pd.DataFrame, i: int, h: int = 5) -> Optional[bool]:
    """前瞻 h 日收盤是否仍低於事件收。"""
    c0 = _f(df["close"].iloc[i])
    j = i + h
    if c0 is None or j >= len(df):
        return None
    cj = _f(df["close"].iloc[j])
    if cj is None:
        return None
    return cj < c0


def classify_spike_path(df: pd.DataFrame, spike_i: int, *, within: int = 15) -> Dict[str, Any]:
    """D10：爆大量後日內外路徑（站撐量縮／破撐放棄／過壓掉回＝出貨／破撐站回＝洗盤）。"""
    n = len(df)
    if spike_i < 0 or spike_i >= n - 1:
        return {"path": "insufficient", "event_i": None}
    hi = _f(df["high"].iloc[spike_i])
    lo = _f(df["low"].iloc[spike_i])
    v0 = _f(df["volume"].iloc[spike_i])
    if None in (hi, lo, v0) or hi <= 0 or lo <= 0 or v0 <= 0:
        return {"path": "insufficient", "event_i": None}
    end = min(n - 1, spike_i + within)
    broke = False
    reclaim = False
    saw_over = False
    hold_shrink_i: Optional[int] = None
    break_i: Optional[int] = None
    for j in range(spike_i + 1, end + 1):
        cj = _f(df["close"].iloc[j])
        lj = _f(df["low"].iloc[j])
        hj = _f(df["high"].iloc[j])
        vj = _f(df["volume"].iloc[j])
        if cj is None:
            continue
        if lo and lj is not None and (cj < lo or lj < lo):
            broke = True
            if break_i is None:
                break_i = j
        if broke and lo and cj >= lo:
            reclaim = True
        if hi and cj >= hi:
            saw_over = True
        # 站撐量縮：收 ≥ 撐且量 < 爆量日 ×0.6
        if (
            hold_shrink_i is None
            and lo
            and cj >= lo
            and vj is not None
            and vj < v0 * 0.6
            and not broke
        ):
            hold_shrink_i = j
    last = _f(df["close"].iloc[end])
    path = "undecided"
    event_i: Optional[int] = None
    if broke and reclaim and last is not None and last >= lo:
        path = "wash"  # 破撐又站回
        event_i = break_i
    elif saw_over and last is not None and last < lo:
        path = "distribution"  # 過壓掉回撐下
        event_i = end
    elif broke and last is not None and last < lo:
        path = "break_abandon"  # 破撐放棄
        event_i = break_i
    elif hold_shrink_i is not None:
        path = "hold_shrink"  # 站撐量縮
        event_i = hold_shrink_i
    elif last is not None and lo and last >= lo:
        path = "hold_no_shrink"
        event_i = end
    else:
        path = "undecided"
        event_i = end
    return {
        "path": path,
        "event_i": event_i,
        "spike_i": spike_i,
        "spike_hi": hi,
        "spike_lo": lo,
        "broke": broke,
        "reclaim": reclaim,
        "saw_over": saw_over,
    }


def find_spike_indices(df: pd.DataFrame, *, lookback: int = 40, pct: float = 90.0) -> List[int]:
    """近窗自身量 ≥ 分位的爆大量日（不含最後一根當未定參考）。"""
    n = len(df)
    out: List[int] = []
    last_emit = -10**9
    for i in range(lookback, n - 1):
        if not _own_vol_ge_pct(df, i, lookback=lookback, pct=pct):
            continue
        if i - last_emit < 5:
            continue
        out.append(i)
        last_emit = i
    return out


def deepdive_one(df: pd.DataFrame, sid: str, name: str, tag: str) -> Dict[str, Any]:
    """單檔細部拆解（官方柱事實）。"""
    n = len(df)
    if n < 40:
        return {"stock_id": sid, "name": name, "tag": tag, "ok": False, "reason": "short_series"}
    # 用 find_volume_zone 對齊產品大量區（截止最後已收）
    work = df.copy()
    work["is_halt"] = False
    zone = find_volume_zone(work, lookback=40)
    spikes = find_spike_indices(df, lookback=40, pct=90.0)
    # 近 90 日窗內事件摘要
    cut = max(0, n - 90)
    recent_spikes = [i for i in spikes if i >= cut]
    paths = []
    for si in recent_spikes[-8:]:
        p = classify_spike_path(df, si, within=15)
        p["spike_date"] = str(df["date"].iloc[si])
        p["spike_ohlcv"] = {
            "o": _f(df["open"].iloc[si]),
            "h": _f(df["high"].iloc[si]),
            "l": _f(df["low"].iloc[si]),
            "c": _f(df["close"].iloc[si]),
            "v": _f(df["volume"].iloc[si]),
        }
        if p.get("event_i") is not None and p["event_i"] < n:
            ei = int(p["event_i"])
            p["event_date"] = str(df["date"].iloc[ei])
            p["fwd"] = fwd_rets(df, ei)
            p["cont_down_h5"] = cont_down(df, ei, 5)
        paths.append(p)

    traps = detect_triple_traps(df)
    recent_traps = []
    for t in traps:
        if t.v3 < cut:
            continue
        recent_traps.append(
            {
                "v1": str(df["date"].iloc[t.v1]),
                "v2": str(df["date"].iloc[t.v2]),
                "v3": str(df["date"].iloc[t.v3]),
                "v_hit_10": v_reversal_hit(df, t, within=10),
                "fwd": fwd_rets(df, t.v3),
                "cont_down_h5": cont_down(df, t.v3, 5),
                "bars": {
                    "v1": {
                        "o": _f(df["open"].iloc[t.v1]),
                        "h": _f(df["high"].iloc[t.v1]),
                        "l": _f(df["low"].iloc[t.v1]),
                        "c": _f(df["close"].iloc[t.v1]),
                        "v": _f(df["volume"].iloc[t.v1]),
                    },
                    "v2": {
                        "o": _f(df["open"].iloc[t.v2]),
                        "h": _f(df["high"].iloc[t.v2]),
                        "l": _f(df["low"].iloc[t.v2]),
                        "c": _f(df["close"].iloc[t.v2]),
                        "v": _f(df["volume"].iloc[t.v2]),
                    },
                    "v3": {
                        "o": _f(df["open"].iloc[t.v3]),
                        "h": _f(df["high"].iloc[t.v3]),
                        "l": _f(df["low"].iloc[t.v3]),
                        "c": _f(df["close"].iloc[t.v3]),
                        "v": _f(df["volume"].iloc[t.v3]),
                    },
                },
            }
        )

    # 沖高倒貨（近窗）
    dumps = []
    for i in range(max(cut, 1), n):
        if r1e1_at(df, i):
            dumps.append(
                {
                    "date": str(df["date"].iloc[i]),
                    "strict_e2": r1e2_at(df, i),
                    "ohlcv": {
                        "o": _f(df["open"].iloc[i]),
                        "h": _f(df["high"].iloc[i]),
                        "l": _f(df["low"].iloc[i]),
                        "c": _f(df["close"].iloc[i]),
                        "v": _f(df["volume"].iloc[i]),
                    },
                    "fwd": fwd_rets(df, i),
                }
            )

    # 破前低未放量 vs 放量
    quiet_breaks = []
    loud_breaks = []
    for i in range(max(cut, 20), n):
        row = {
            "date": str(df["date"].iloc[i]),
            "ohlcv": {
                "o": _f(df["open"].iloc[i]),
                "h": _f(df["high"].iloc[i]),
                "l": _f(df["low"].iloc[i]),
                "c": _f(df["close"].iloc[i]),
                "v": _f(df["volume"].iloc[i]),
            },
            "fwd": fwd_rets(df, i),
            "cont_down_h5": cont_down(df, i, 5),
        }
        if r1g_break_quiet(df, i):
            quiet_breaks.append(row)
        elif r1g_break_loud(df, i):
            loud_breaks.append(row)

    last = {
        "date": str(df["date"].iloc[-1]),
        "o": _f(df["open"].iloc[-1]),
        "h": _f(df["high"].iloc[-1]),
        "l": _f(df["low"].iloc[-1]),
        "c": _f(df["close"].iloc[-1]),
        "v": _f(df["volume"].iloc[-1]),
    }
    zone_out = None
    if zone:
        zi = int(zone["i"])
        zone_out = {
            "date": str(zone.get("date") or df["date"].iloc[zi]),
            "press": zone.get("high"),
            "support": zone.get("low"),
            "volume": zone.get("volume"),
            "active": zone.get("active"),
            "last_vs_support": None
            if last["c"] is None or zone.get("low") is None
            else last["c"] - float(zone["low"]),
            "last_under_support": bool(
                last["c"] is not None
                and zone.get("low") is not None
                and last["c"] < float(zone["low"])
            ),
        }

    return {
        "stock_id": sid,
        "name": name,
        "tag": tag,
        "ok": True,
        "n_bars": n,
        "first_date": str(df["date"].iloc[0]),
        "last": last,
        "volume_zone": zone_out,
        "recent_spike_paths": paths,
        "triple_traps": recent_traps,
        "dump_long_upper": dumps[-6:],
        "break_quiet": quiet_breaks[-6:],
        "break_loud": loud_breaks[-6:],
        "counts_90d": {
            "spikes": len(recent_spikes),
            "triple_traps": len(recent_traps),
            "dump_e1": len(dumps),
            "break_quiet": len(quiet_breaks),
            "break_loud": len(loud_breaks),
        },
    }


@dataclass
class Agg:
    n_events: int = 0
    n_days: int = 0
    n_stocks: int = 0
    cont_down_h5: int = 0
    cont_down_known: int = 0
    v_hit: int = 0
    v_known: int = 0
    sum_h5: float = 0.0
    n_h5: int = 0
    sum_h1: float = 0.0
    n_h1: int = 0
    sum_h3: float = 0.0
    n_h3: int = 0

    def add(
        self,
        *,
        day: str,
        sid: str,
        h1: Optional[float],
        h3: Optional[float],
        h5: Optional[float],
        down: Optional[bool] = None,
        vhit: Optional[bool] = None,
    ) -> None:
        self.n_events += 1
        if h1 is not None:
            self.sum_h1 += h1
            self.n_h1 += 1
        if h3 is not None:
            self.sum_h3 += h3
            self.n_h3 += 1
        if h5 is not None:
            self.sum_h5 += h5
            self.n_h5 += 1
        if down is not None:
            self.cont_down_known += 1
            if down:
                self.cont_down_h5 += 1
        if vhit is not None:
            self.v_known += 1
            if vhit:
                self.v_hit += 1

    def finish(self, days: set, stocks: set) -> Dict[str, Any]:
        self.n_days = len(days)
        self.n_stocks = len(stocks)
        return {
            "n_events": self.n_events,
            "n_unique_days": self.n_days,
            "n_stocks": self.n_stocks,
            "mean_h1": (self.sum_h1 / self.n_h1) if self.n_h1 else None,
            "mean_h3": (self.sum_h3 / self.n_h3) if self.n_h3 else None,
            "mean_h5": (self.sum_h5 / self.n_h5) if self.n_h5 else None,
            "cont_down_h5_rate": (
                self.cont_down_h5 / self.cont_down_known
            )
            if self.cont_down_known
            else None,
            "v_reversal_rate": (self.v_hit / self.v_known) if self.v_known else None,
            "gate_n20": self.n_days >= 20,
        }


def silent_universe_backtest(
    con: sqlite3.Connection, stock_ids: Sequence[str]
) -> Dict[str, Any]:
    """全量仔細：D10 路徑、D11a 三連套、D11g 洗盤vs出貨、破前低無量、沖高倒貨。"""
    tracks = {
        "D10_hold_shrink": Agg(),
        "D10_break_abandon": Agg(),
        "D10_wash": Agg(),
        "D10_distribution": Agg(),
        "D10_baseline_any_spike": Agg(),
        "D11a_triple_trap": Agg(),
        "D11a_baseline_random_big_down": Agg(),
        "D11g_wash": Agg(),
        "D11g_distribution": Agg(),
        "R1g_break_quiet": Agg(),
        "R1g_break_loud": Agg(),
        "R1e_dump": Agg(),
    }
    days: Dict[str, set] = defaultdict(set)
    stocks: Dict[str, set] = defaultdict(set)
    # 另存留白子集
    hold_tracks = {k: Agg() for k in tracks}
    hold_days: Dict[str, set] = defaultdict(set)
    hold_stocks: Dict[str, set] = defaultdict(set)

    def _push(key: str, df: pd.DataFrame, i: int, *, vhit: Optional[bool] = None) -> None:
        if i is None or i < 0 or i + 5 >= len(df):
            return
        rets = fwd_rets(df, i)
        down = cont_down(df, i, 5)
        day = str(df["date"].iloc[i])
        # 全樣
        tracks[key].add(
            day=day,
            sid="",
            h1=rets.get("h1"),
            h3=rets.get("h3"),
            h5=rets.get("h5"),
            down=down,
            vhit=vhit,
        )
        days[key].add(day)
        # 留白：日期落在末 20% 時間軸
        t0 = str(df["date"].iloc[0])
        t1 = str(df["date"].iloc[-1])
        # 用序位近似
        cut_i = int(len(df) * (1.0 - HOLDOFF))
        if i >= cut_i:
            hold_tracks[key].add(
                day=day,
                sid="",
                h1=rets.get("h1"),
                h3=rets.get("h3"),
                h5=rets.get("h5"),
                down=down,
                vhit=vhit,
            )
            hold_days[key].add(day)

    n_ok = 0
    for idx, sid in enumerate(stock_ids):
        df, _name = load_stock(con, sid)
        if len(df) < 120:
            continue
        n_ok += 1
        spikes = find_spike_indices(df, lookback=40, pct=90.0)
        for si in spikes:
            path = classify_spike_path(df, si, within=15)
            ei = path.get("event_i")
            if ei is None:
                continue
            _push("D10_baseline_any_spike", df, int(ei))
            stocks["D10_baseline_any_spike"].add(sid)
            pk = path.get("path")
            key_map = {
                "hold_shrink": "D10_hold_shrink",
                "break_abandon": "D10_break_abandon",
                "wash": "D10_wash",
                "distribution": "D10_distribution",
            }
            k = key_map.get(str(pk))
            if k:
                _push(k, df, int(ei))
                stocks[k].add(sid)
                # D11g 同義（洗盤 vs 出貨）
                if k == "D10_wash":
                    _push("D11g_wash", df, int(ei))
                    stocks["D11g_wash"].add(sid)
                elif k == "D10_distribution":
                    _push("D11g_distribution", df, int(ei))
                    stocks["D11g_distribution"].add(sid)

        traps = detect_triple_traps(df)
        for t in traps:
            hit = v_reversal_hit(df, t, within=10)
            _push("D11a_triple_trap", df, t.v3, vhit=hit)
            stocks["D11a_triple_trap"].add(sid)

        # 基線：大陰大量日（非三連套 V3）；每檔最多 12 事件，序列仍全掃
        trap_v3 = {t.v3 for t in traps}
        base_n = 0
        for i in range(40, len(df) - 5):
            if base_n >= 12:
                break
            if i in trap_v3:
                continue
            if not _own_vol_ge_pct(df, i, lookback=40, pct=90.0):
                continue
            o = _f(df["open"].iloc[i])
            c = _f(df["close"].iloc[i])
            if o is None or c is None or c >= o:
                continue
            _push("D11a_baseline_random_big_down", df, i)
            stocks["D11a_baseline_random_big_down"].add(sid)
            base_n += 1

        for i in range(20, len(df) - 5):
            if r1g_break_quiet(df, i):
                _push("R1g_break_quiet", df, i)
                stocks["R1g_break_quiet"].add(sid)
            elif r1g_break_loud(df, i):
                _push("R1g_break_loud", df, i)
                stocks["R1g_break_loud"].add(sid)
            if r1e1_at(df, i):
                _push("R1e_dump", df, i)
                stocks["R1e_dump"].add(sid)

        if (idx + 1) % 200 == 0:
            print(f"[bt] {idx+1}/{len(stock_ids)} stocks…", flush=True)

    full = {k: tracks[k].finish(days[k], stocks[k]) for k in tracks}
    hold = {k: hold_tracks[k].finish(hold_days[k], hold_stocks[k]) for k in hold_tracks}

    # 對質一句狀態（對話可講的只有這層）
    verdicts = {}
    for k, full_row in full.items():
        base_key = None
        if k.startswith("D10_") and k != "D10_baseline_any_spike":
            base_key = "D10_baseline_any_spike"
        elif k == "D11a_triple_trap":
            base_key = "D11a_baseline_random_big_down"
        elif k == "D11g_wash":
            base_key = "D11g_distribution"
        elif k == "R1g_break_quiet":
            base_key = "R1g_break_loud"
        base = full.get(base_key) if base_key else None
        better = None
        if base and full_row.get("cont_down_h5_rate") is not None and base.get("cont_down_h5_rate") is not None:
            # 避險軌：續跌機率更高＝較像風險標（對 D11a／破撐）
            if k in ("D11a_triple_trap", "D10_break_abandon", "D10_distribution", "D11g_distribution", "R1g_break_quiet"):
                better = full_row["cont_down_h5_rate"] > base["cont_down_h5_rate"]
            elif k in ("D10_hold_shrink", "D10_wash", "D11g_wash"):
                # 站穩／洗盤：續跌應較低
                better = full_row["cont_down_h5_rate"] < base["cont_down_h5_rate"]
        verdicts[k] = {
            "n_unique_days": full_row.get("n_unique_days"),
            "gate_n20": full_row.get("gate_n20"),
            "vs_baseline": base_key,
            "better_than_baseline_cont_down": better,
            "face": False,  # 預設不上臉
            "note": "n≥20 且贏基線才談上臉；本回合只靜默",
        }

    return {
        "stocks_scanned": n_ok,
        "universe_requested": len(stock_ids),
        "full": full,
        "holdout_last20pct": hold,
        "verdicts": verdicts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("WAYNE_MARKET_DB", "data/wayne_market.db"))
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--universe-limit", type=int, default=0, help="0＝全宇宙；>0 截斷")
    ap.add_argument("--skip-bt", action="store_true")
    ap.add_argument("--deepdive-only-named", action="store_true")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print(f"missing db: {db}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db)
    try:
        named = HEAD_EIGHT + RECENT_NAMED
        # 去重保序
        seen = set()
        named_u = []
        for sid, nm, tag in named:
            if sid in seen:
                continue
            seen.add(sid)
            named_u.append((sid, nm, tag))

        deepdives = []
        for sid, nm, tag in named_u:
            df, db_name = load_stock(con, sid)
            name = db_name or nm
            if df.empty:
                deepdives.append({"stock_id": sid, "name": nm, "tag": tag, "ok": False, "reason": "no_bars"})
                continue
            deepdives.append(deepdive_one(df, sid, name, tag))
            print(f"[dd] {sid} {name} ok={deepdives[-1].get('ok')}", flush=True)

        # 額外：近窗爆大量最多的檔（庫內可對大量事件股）
        extra_ids = []
        if not args.deepdive_only_named:
            rows = con.execute(
                """
                SELECT stock_id, MAX(volume) AS mv
                FROM daily_quotes
                WHERE date >= '20260901' AND date <= '20261022'
                  AND length(stock_id)=4 AND stock_id NOT GLOB '00*'
                  AND volume > 0 AND close > 0
                GROUP BY stock_id
                ORDER BY mv DESC
                LIMIT 40
                """
            ).fetchall()
            for sid, _mv in rows:
                if sid in seen:
                    continue
                extra_ids.append(sid)
                seen.add(sid)
            for sid in extra_ids[:20]:
                df, name = load_stock(con, sid)
                if df.empty:
                    continue
                deepdives.append(deepdive_one(df, sid, name or sid, "hi_vol_event"))
                print(f"[dd+] {sid} {name}", flush=True)

        bt = None
        if not args.skip_bt:
            uni = load_universe_ids(con, limit=int(args.universe_limit or 0))
            # 確保頭部／點名進宇宙
            for sid, _, _ in named_u:
                if sid not in uni:
                    uni.append(sid)
            print(f"[bt] universe={len(uni)}", flush=True)
            bt = silent_universe_backtest(con, uni)

        out = {
            "generated_at": _now_iso(),
            "tz": "Asia/Taipei",
            "db": db,
            "as_of_last_bar": "20261022",
            "rules": {
                "official_ohlcv_only": True,
                "no_intraday_as_close": True,
                "not_buy_signal": True,
                "no_leave_zero_change": True,
                "face_default": False,
                "min_n_days": 20,
            },
            "deepdives": deepdives,
            "backtest": bt,
        }
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out_path} deepdives={len(deepdives)}", flush=True)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
