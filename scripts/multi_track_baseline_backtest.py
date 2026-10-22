#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多軌勝率長測第 1 步底線（全量；不是買訊；不准改 leave_zero）。

訊號軌 A1–A7＋B 兩階對照＋C 維度；主句＝隔日開盤進場。
興櫃橘六角：本庫無免驗證碼單檔外資 → 標不可測（不准假填）。
時區 Asia/Taipei；盤中未收不當收；全量不准抽樣；張≠股。

用法：
  .venv/bin/python scripts/multi_track_baseline_backtest.py \\
    --db data/wayne_market.db --out /tmp/mt_baseline.json
  .venv/bin/python scripts/multi_track_baseline_backtest.py --smoke
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from buy_exclude import should_exclude_buy  # noqa: E402
from decision_card_signals import leave_zero_bar_indices  # noqa: E402
from foreign_sell_calm import (  # noqa: E402
    BuyEscalateParams,
    current_buy_params,
    evaluate_buy_escalate_A,
)
from foreign_sell_display import DISPLAY_SELL_SHARE_THR  # noqa: E402
from foreign_sell_escalate import (  # noqa: E402
    EscalateParams,
    cross_sectional_percentile,
    current_params,
    evaluate_escalate_A,
    lit_dump_share,
    sell_share,
)
from foreign_sell_extreme import ExtremeTrack, lit_extreme_day  # noqa: E402
from red_arrow_quant import nav_low_ma60_lower_mask  # noqa: E402
from stabilize_watch import (  # noqa: E402
    HOLD_N,
    HOLD_N_NEXT,
    LOOKBACK,
    _held_after_touch,
    _l60_first_touch_indices,
)
from universe import is_screen_equity  # noqa: E402
from winrate_ai_priority import is_winrate_priority  # noqa: E402

TP = ZoneInfo("Asia/Taipei")
HORIZONS: Tuple[int, ...] = (1, 2, 3, 5, 10, 20)
DEDUP_N = 5
EM_SLIP = 0.01  # 興櫃「扣一檔不利」敏感緩衝（日均價進場偏樂觀）
COST_RT = 0.003  # 簡單來回成本附欄（約證交稅＋手續費）
ELEC_INDUSTRIES = {
    "光電業",
    "光電",
    "其他電子業",
    "半導體業",
    "數位雲端",
    "資訊服務業",
    "通信網路業",
    "電子通路業",
    "電子零組件業",
    "電腦及週邊設備業",
    "電機機械",
    "電機機械業",
    "電器電纜",
}
TRACKS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7")


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
class Event:
    track: str
    sid: str
    market: str
    date: str
    i: int
    entry_close: float
    entry_next_open: Optional[float]
    vol: float
    industry: str
    electronic: bool
    year: str
    tag: str = ""
    stage: str = ""  # residual|solid|first|confirm|fade
    holdout: bool = False


@dataclass
class Agg:
    n: int = 0
    n_days: int = 0
    rets: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    dds: List[float] = field(default_factory=list)
    excess: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    incomplete: Dict[str, int] = field(default_factory=lambda: defaultdict(int))


def load_universe(db: str) -> Dict[str, Dict[str, str]]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            """
            SELECT stock_id, COALESCE(stock_name,''), COALESCE(market_type,''),
                   COALESCE(asset_type,''), COALESCE(industry,'')
            FROM stock_universe WHERE is_active=1
            """
        ).fetchall()
    finally:
        con.close()
    out: Dict[str, Dict[str, str]] = {}
    for sid, name, mkt, atype, ind in rows:
        sid = str(sid or "").strip()
        if not sid or not is_screen_equity(sid, name, atype):
            continue
        m = str(mkt or "").strip().upper()
        if m not in ("TW", "TWO", "EM"):
            continue
        out[sid] = {
            "name": str(name or ""),
            "market": m,
            "industry": str(ind or ""),
            "asset_type": str(atype or ""),
        }
    return out


def load_twii(db: str) -> Dict[str, Dict[str, float]]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            """
            SELECT replace(CAST(date AS TEXT),'-','') AS d, open, close
            FROM index_daily WHERE symbol='TWII' AND close>0
            ORDER BY d
            """
        ).fetchall()
    finally:
        con.close()
    by: Dict[str, Dict[str, float]] = {}
    for d, o, c in rows:
        dd = _ymd(d)
        if not dd:
            continue
        by[dd] = {"open": float(o or 0), "close": float(c or 0)}
    return by


def load_stock_df(con: sqlite3.Connection, sid: str, market: str) -> pd.DataFrame:
    if market == "EM":
        q = """
        SELECT replace(CAST(date AS TEXT),'-','') AS date,
               open, high, low, close, volume,
               COALESCE(turnover_k,0) AS turnover_k,
               COALESCE(foreign_net,0) AS foreign_net,
               COALESCE(avg_price, close) AS avg_price
        FROM emerging_quotes
        WHERE stock_id=? AND close>0 AND open>0 AND high>0 AND low>0
        ORDER BY date
        """
    else:
        q = """
        SELECT replace(CAST(date AS TEXT),'-','') AS date,
               open, high, low, close, volume,
               COALESCE(turnover_k,0) AS turnover_k,
               COALESCE(foreign_net,0) AS foreign_net,
               COALESCE(avg_price, close) AS avg_price
        FROM daily_quotes
        WHERE stock_id=? AND market=? AND close>0 AND open>0 AND high>0 AND low>0
        ORDER BY date
        """
    params: Tuple[Any, ...] = (sid,) if market == "EM" else (sid, market)
    df = pd.read_sql_query(q, con, params=params)
    if df.empty:
        return df
    df["date"] = df["date"].map(_ymd)
    df = df[df["date"].str.len() == 8].reset_index(drop=True)
    return df


def stabilize_fire_indices(df: pd.DataFrame, hold_n: int) -> List[int]:
    if df is None or len(df) < 62:
        return []
    touches = _l60_first_touch_indices(df)
    if not touches:
        return []
    out: List[int] = []
    n = len(df)
    for end in range(61, n):
        start_scan = max(0, end - int(LOOKBACK))
        cands = [i for i in touches if start_scan <= i < end]
        if not cands:
            continue
        t0 = int(cands[-1])
        if _held_after_touch(df, t0, end, hold_n=int(hold_n)):
            out.append(int(end))
    return out


def stabilize_first_vs_confirm(fire: Sequence[int]) -> Dict[int, str]:
    """連續亮燈段：第一根＝residual／剛達標；其後＝confirm。"""
    stage: Dict[int, str] = {}
    prev = None
    for i in fire:
        if prev is not None and i == prev + 1:
            stage[i] = "confirm"
        else:
            stage[i] = "residual"
        prev = i
    return stage


def dedup_indices(idxs: Sequence[int], n: int = DEDUP_N) -> List[int]:
    out: List[int] = []
    last = -10**9
    for i in sorted(int(x) for x in idxs):
        if i - last >= int(n):
            out.append(i)
            last = i
    return out


def forward_stats(
    df: pd.DataFrame,
    i: int,
    *,
    entry_px: float,
    horizons: Sequence[int] = HORIZONS,
) -> Tuple[Dict[int, Optional[float]], Optional[float], Dict[int, bool]]:
    """回報各天期收盤報酬、進場後最大回撤（相對進場價）、天期是否可完成。"""
    rets: Dict[int, Optional[float]] = {}
    done: Dict[int, bool] = {}
    n = len(df)
    if entry_px is None or entry_px <= 0:
        for h in horizons:
            rets[h] = None
            done[h] = False
        return rets, None, done
    worst = 0.0
    any_bar = False
    max_h = max(horizons)
    for off in range(1, max_h + 1):
        j = i + 1 + off  # 隔日開盤進場後第 off 根收（i=訊號日；i+1=進場日）
        # 若用隔日開進場：報酬錨在 entry；前瞻 h 用進場日後第 h 根收
        # 訊號日 i，隔日開＝i+1 open；+1 天期＝進場當日收＝i+1 close
        j_close = i + off  # off=1 → i+1 close（進場日收）
        if j_close >= n:
            break
        cl = _f(df["close"].iloc[j_close])
        lo = _f(df["low"].iloc[j_close])
        if cl is None or cl <= 0:
            continue
        any_bar = True
        r = (cl - entry_px) / entry_px
        if off in horizons:
            rets[off] = r
            done[off] = True
        if lo is not None and lo > 0:
            dd = (lo - entry_px) / entry_px
            if dd < worst:
                worst = dd
    for h in horizons:
        if h not in done:
            rets[h] = None
            done[h] = False
    return rets, (worst if any_bar else None), done


def twii_forward(twii: Dict[str, Dict[str, float]], days: Sequence[str], i: int, h: int, entry_open: bool) -> Optional[float]:
    """加權同窗報酬（對齊股票天期）。"""
    if i < 0 or i >= len(days):
        return None
    d0 = days[i]
    if entry_open:
        # 隔日開進場：錨＝隔日開；h 天＝訊號後第 h 個交易日收
        if i + 1 >= len(days):
            return None
        d_entry = days[i + 1]
        if i + h >= len(days):
            return None
        d_h = days[i + h]
        e = twii.get(d_entry, {}).get("open") or twii.get(d_entry, {}).get("close")
        c = twii.get(d_h, {}).get("close")
    else:
        e = twii.get(d0, {}).get("close")
        if i + h >= len(days):
            return None
        c = twii.get(days[i + h], {}).get("close")
    if not e or not c or e <= 0:
        return None
    return (c - e) / e


def vol_tercile_edges(vols: Sequence[float]) -> Tuple[float, float]:
    xs = sorted(float(v) for v in vols if v is not None and v > 0)
    if len(xs) < 3:
        return 0.0, 0.0
    a = xs[len(xs) // 3]
    b = xs[(2 * len(xs)) // 3]
    return float(a), float(b)


def summarize_rets(xs: Sequence[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0, "win_rate": None, "median": None, "mean": None}
    arr = np.asarray(xs, dtype=float)
    return {
        "n": int(len(arr)),
        "win_rate": float((arr > 0).mean()),
        "median": float(np.median(arr)),
        "mean": float(arr.mean()),
    }


def holdout_cut(days: Sequence[str]) -> str:
    """最後約 20% 時間留白：回傳留白起日（含）。"""
    if not days:
        return ""
    k = max(1, int(round(len(days) * 0.2)))
    return str(days[-k])


def process_price_tracks(
    sid: str,
    meta: Dict[str, str],
    df: pd.DataFrame,
    *,
    twii: Dict[str, Dict[str, float]],
    holdout_from: Dict[str, str],
    smoke_max_events: int = 0,
) -> List[Event]:
    if df is None or len(df) < 2:
        return []
    market = meta["market"]
    industry = meta.get("industry") or ""
    electronic = industry in ELEC_INDUSTRIES or is_winrate_priority(industry)
    days = [str(x) for x in df["date"].tolist()]
    events: List[Event] = []

    def _mk(track: str, i: int, tag: str = "", stage: str = "") -> Optional[Event]:
        if i < 0 or i >= len(df) - 1:
            return None
        # 需有隔日開（主句）
        nxt = _f(df["open"].iloc[i + 1])
        cl = _f(df["close"].iloc[i])
        vol = _f(df["volume"].iloc[i]) or 0.0
        if cl is None or cl <= 0:
            return None
        d = days[i]
        hf = holdout_from.get(market, "")
        return Event(
            track=track,
            sid=sid,
            market=market,
            date=d,
            i=i,
            entry_close=float(cl),
            entry_next_open=float(nxt) if nxt and nxt > 0 else None,
            vol=float(vol),
            industry=industry,
            electronic=bool(electronic),
            year=d[:4],
            tag=tag,
            stage=stage,
            holdout=bool(hf and d >= hf),
        )

    # A1 leave_zero
    lz = leave_zero_bar_indices(df) or []
    for i in dedup_indices(lz):
        ev = _mk("A1", i, tag="leave_zero")
        if ev:
            events.append(ev)

    # A2 ma60_lower
    if len(df) >= 60:
        mask = nav_low_ma60_lower_mask(df)
        hits = [i for i, v in enumerate(mask.tolist()) if v]
        for i in dedup_indices(hits):
            ev = _mk("A2", i, tag="ma60_lower")
            if ev:
                events.append(ev)

    # A5 / A6 stabilize
    fire5 = stabilize_fire_indices(df, HOLD_N)
    stage5 = stabilize_first_vs_confirm(fire5)
    for i in dedup_indices(fire5):
        ev = _mk("A5", i, tag="hold_l60", stage=stage5.get(i, ""))
        if ev:
            events.append(ev)
    fire6 = stabilize_fire_indices(df, HOLD_N_NEXT)
    stage6 = stabilize_first_vs_confirm(fire6)
    for i in dedup_indices(fire6):
        ev = _mk("A6", i, tag="hold_l60_tight", stage=stage6.get(i, ""))
        if ev:
            events.append(ev)

    # A7 勝率買點：leave_zero ∩ buy_exclude ∩ AI 生態系
    # （話筒另有出圖剝紅框；歷史全量以公式＋排除＋產業為現況可重算近似）
    if is_winrate_priority(industry):
        a7_hits = []
        for i in lz:
            try:
                if should_exclude_buy(
                    df, i, emerging=(market == "EM"), quote_source=("emerging_quotes" if market == "EM" else "")
                ):
                    continue
            except Exception:
                continue
            a7_hits.append(i)
        for i in dedup_indices(a7_hits):
            ev = _mk("A7", i, tag="winrate_buypoint")
            if ev:
                events.append(ev)

    if smoke_max_events > 0 and len(events) > smoke_max_events:
        events = events[:smoke_max_events]
    return events


def build_foreign_events(
    db: str,
    universe: Dict[str, Dict[str, str]],
    *,
    holdout_from: Dict[str, str],
    smoke: bool = False,
) -> Tuple[List[Event], Dict[str, Any]]:
    """A3 賣側升級／極端；A4 買側升級。僅上市櫃；興櫃缺外資。"""
    note = {
        "EM": "缺官方免驗證碼單檔外資（emerging_quotes.foreign_net 全 0；OpenAPI／公開日表無興櫃個股法人；商店 EMGMAININST 為付費彙總）→ 橘六角興櫃不可測",
        "A3_rules": {
            "escalate": "current_params n=3 theta=90",
            "extreme": f"share_th{DISPLAY_SELL_SHARE_THR:g}（話筒顯示相對極端軌）",
        },
        "A4_rules": "current_buy_params n=3 theta=90（話筒預設不亮買升級）",
    }
    listed = {s: m for s, m in universe.items() if m["market"] in ("TW", "TWO")}
    if not listed:
        return [], note
    con = sqlite3.connect(db)
    try:
        # 載入外資可測窗
        sids = sorted(listed.keys())
        if smoke:
            sids = sids[:40]
        ph = ",".join("?" * len(sids))
        df = pd.read_sql_query(
            f"""
            SELECT replace(CAST(date AS TEXT),'-','') AS date, stock_id, market,
                   open, high, low, close, volume, COALESCE(foreign_net,0) AS foreign_net
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
        return [], note
    df["date"] = df["date"].map(_ymd)
    df = df[df["date"].str.len() == 8]
    # 有效外資日起
    days_all = sorted(df["date"].unique().tolist())
    # 分市場外資覆蓋
    events: List[Event] = []
    esc_p = current_params()
    buy_p = current_buy_params()
    ext_track = ExtremeTrack("share", float(DISPLAY_SELL_SHARE_THR))

    from foreign_sell_calm import buy_share as _buy_share

    # 每檔序列 (date, open, high, low, close, vol, foreign, market)
    hist: Dict[str, List[Tuple[str, float, float, float, float, float, float, str]]] = defaultdict(list)
    for row in df.itertuples(index=False):
        hist[str(row.stock_id)].append(
            (
                str(row.date),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.volume),
                float(row.foreign_net),
                str(row.market),
            )
        )
    date_ix: Dict[str, Dict[str, int]] = {
        sid: {t[0]: i for i, t in enumerate(seq)} for sid, seq in hist.items()
    }

    # 逐日截面分位（只用當日已公布；無未來函數）
    sell_pctl: Dict[Tuple[str, str], float] = {}
    buy_pctl: Dict[Tuple[str, str], float] = {}
    by_day = df.groupby("date", sort=True)
    for day, g in by_day:
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

    last_a3: Dict[str, int] = {}
    last_a4: Dict[str, int] = {}
    nonzero_days = 0
    for di, day in enumerate(days_all):
        # 略過外資尚未覆蓋之日（當日非零 foreign_net 檔數過低）
        day_df = df[df["date"] == day]
        if day_df.empty:
            continue
        nz = int((day_df["foreign_net"] != 0).sum())
        if nz < max(30, int(len(day_df) * 0.05)):
            continue
        nonzero_days += 1
        if smoke and nonzero_days > 25:
            break
        day_sids = list(day_df["stock_id"].astype(str).unique())
        for sid in day_sids:
            meta = listed.get(sid)
            if not meta:
                continue
            seq = hist[sid]
            ix = date_ix[sid][day]
            if ix + 1 >= len(seq):
                continue
            row = seq[ix]
            market = meta["market"]
            industry = meta.get("industry") or ""
            electronic = industry in ELEC_INDUSTRIES or is_winrate_priority(industry)
            hf = holdout_from.get(market, "")
            n = int(esc_p.n_days)
            if ix + 1 >= n:
                window = seq[ix - n + 1 : ix + 1]
                fns = [t[6] for t in window]
                vols = [t[5] for t in window]
                pctls = [sell_pctl.get((t[0], sid)) for t in window]
                ev_esc = evaluate_escalate_A(
                    foreign_nets=fns, volumes=vols, pctls=pctls, params=esc_p
                )
                lit_ext = lit_extreme_day(
                    ext_track,
                    foreign_net=row[6],
                    volume=row[5],
                    foreign_nets_hist=fns,
                    foreign_nets_10=[t[6] for t in seq[max(0, ix - 9) : ix + 1]],
                )
                if (ev_esc.get("lit") or lit_ext) and (
                    ix - last_a3.get(sid, -10**9) >= DEDUP_N
                ):
                    nxt_o = seq[ix + 1][1]
                    if ev_esc.get("lit") and lit_ext:
                        tag, stage = "escalate+extreme", "solid"
                    elif lit_ext:
                        tag, stage = "extreme_share", "solid"
                    else:
                        tag, stage = "escalate_pre_A", "residual"
                    events.append(
                        Event(
                            track="A3",
                            sid=sid,
                            market=market,
                            date=day,
                            i=ix,
                            entry_close=float(row[4]),
                            entry_next_open=float(nxt_o) if nxt_o > 0 else None,
                            vol=float(row[5]),
                            industry=industry,
                            electronic=bool(electronic),
                            year=day[:4],
                            tag=tag,
                            stage=stage,
                            holdout=bool(hf and day >= hf),
                        )
                    )
                    last_a3[sid] = ix
            n2 = int(buy_p.n_days)
            if ix + 1 >= n2:
                window = seq[ix - n2 + 1 : ix + 1]
                fns = [t[6] for t in window]
                vols = [t[5] for t in window]
                pctls = [buy_pctl.get((t[0], sid)) for t in window]
                ev_b = evaluate_buy_escalate_A(
                    foreign_nets=fns, volumes=vols, pctls=pctls, params=buy_p
                )
                if ev_b.get("lit") and (ix - last_a4.get(sid, -10**9) >= DEDUP_N):
                    nxt_o = seq[ix + 1][1]
                    events.append(
                        Event(
                            track="A4",
                            sid=sid,
                            market=market,
                            date=day,
                            i=ix,
                            entry_close=float(row[4]),
                            entry_next_open=float(nxt_o) if nxt_o > 0 else None,
                            vol=float(row[5]),
                            industry=industry,
                            electronic=bool(electronic),
                            year=day[:4],
                            tag="buy_escalate_A",
                            stage="residual",
                            holdout=bool(hf and day >= hf),
                        )
                    )
                    last_a4[sid] = ix
    return events, note


def score_events(
    events: Sequence[Event],
    frames: Dict[str, pd.DataFrame],
    twii: Dict[str, Dict[str, float]],
    *,
    entry: str = "next_open",
    apply_em_slip: bool = False,
) -> Dict[str, Any]:
    """依 track×market 彙總。"""
    buckets: Dict[Tuple[str, str], List[Event]] = defaultdict(list)
    for ev in events:
        buckets[(ev.track, ev.market)].append(ev)

    out: Dict[str, Any] = {}
    for (track, market), evs in sorted(buckets.items()):
        # crowding: 同日同軌亮燈數
        day_cnt: Dict[str, int] = defaultdict(int)
        for e in evs:
            day_cnt[e.date] += 1
        # vol tercile within track×market
        vols = [e.vol for e in evs if e.vol > 0]
        lo_e, hi_e = vol_tercile_edges(vols)

        def _slice_key(e: Event) -> Dict[str, str]:
            if e.vol <= 0 or hi_e <= 0:
                vt = "na"
            elif e.vol <= lo_e:
                vt = "low"
            elif e.vol <= hi_e:
                vt = "mid"
            else:
                vt = "high"
            crowd = day_cnt.get(e.date, 1)
            crowd_b = "crowded" if crowd >= 20 else ("sparse" if crowd <= 3 else "normal")
            return {
                "vol_tercile": vt,
                "electronic": "elec" if e.electronic else "non_elec",
                "year": e.year,
                "crowd": crowd_b,
                "stage": e.stage or "na",
                "holdout": "holdout" if e.holdout else "train",
            }

        rows_main: Dict[str, List[float]] = defaultdict(list)
        rows_dd: List[float] = []
        rows_ex: Dict[str, List[float]] = defaultdict(list)
        incomplete: Dict[str, int] = defaultdict(int)
        by_slice: Dict[str, Dict[str, Dict[str, List[float]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        n_days = len({e.date for e in evs})
        for e in evs:
            df = frames.get(e.sid)
            if df is None or e.i >= len(df):
                continue
            if entry == "next_open":
                px = e.entry_next_open
                if px is None or px <= 0:
                    continue
                if apply_em_slip and e.market == "EM":
                    px = px * (1.0 + EM_SLIP)  # 不利買進＝更高進場價
            else:
                px = e.entry_close
                if apply_em_slip and e.market == "EM":
                    px = px * (1.0 + EM_SLIP)
            rets, dd, done = forward_stats(df, e.i, entry_px=float(px))
            days = [str(x) for x in df["date"].tolist()]
            sk = _slice_key(e)
            if dd is not None:
                rows_dd.append(float(dd))
            for h in HORIZONS:
                if not done.get(h) or rets.get(h) is None:
                    incomplete[str(h)] += 1
                    continue
                r = float(rets[h])
                rows_main[str(h)].append(r)
                tx = twii_forward(twii, days, e.i, h, entry_open=(entry == "next_open"))
                if tx is not None:
                    rows_ex[str(h)].append(r - float(tx))
                for dim, val in sk.items():
                    by_slice[dim][val][str(h)].append(r)

        cell: Dict[str, Any] = {
            "n_events": len(evs),
            "n_days": n_days,
            "entry": entry,
            "horizons": {h: summarize_rets(rows_main[str(h)]) for h in map(str, HORIZONS)},
            "max_drawdown": {
                "median": float(np.median(rows_dd)) if rows_dd else None,
                "mean": float(np.mean(rows_dd)) if rows_dd else None,
                "worst": float(min(rows_dd)) if rows_dd else None,
                "n": len(rows_dd),
            },
            "excess_vs_twii": {h: summarize_rets(rows_ex[str(h)]) for h in map(str, HORIZONS)},
            "incomplete_horizon": dict(incomplete),
            "slices": {},
        }
        for dim, groups in by_slice.items():
            cell["slices"][dim] = {
                g: {h: summarize_rets(xs) for h, xs in hs.items()} for g, hs in groups.items()
            }
        # 成本附欄：主句毛報酬 − COST_RT
        cell["net_of_cost_h1"] = None
        h1 = rows_main.get("1") or []
        if h1:
            net = [r - COST_RT for r in h1]
            cell["net_of_cost_h1"] = summarize_rets(net)
        out[f"{track}:{market}"] = cell
    return out


def cooccurrence(events: Sequence[Event]) -> Dict[str, Any]:
    by: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for e in events:
        by[(e.sid, e.date)].add(e.track)
    pairs = [("A1", "A3"), ("A1", "A5"), ("A3", "A5"), ("A7", "A3"), ("A7", "A5"), ("A2", "A5")]
    out: Dict[str, int] = {}
    for a, b in pairs:
        n = sum(1 for s in by.values() if a in s and b in s)
        out[f"{a}∩{b}"] = n
    return out


def stage_compare(events: Sequence[Event], frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """B1／B2：residual vs confirm／solid 主句 h5。"""
    out: Dict[str, Any] = {}
    for track, dim in (("A5", "B1_stabilize"), ("A3", "B2_orange")):
        groups: Dict[str, List[float]] = defaultdict(list)
        for e in events:
            if e.track != track or not e.stage:
                continue
            if e.entry_next_open is None or e.entry_next_open <= 0:
                continue
            df = frames.get(e.sid)
            if df is None:
                continue
            rets, _, done = forward_stats(df, e.i, entry_px=float(e.entry_next_open))
            if done.get(5) and rets.get(5) is not None:
                groups[e.stage].append(float(rets[5]))
        out[dim] = {k: summarize_rets(v) for k, v in groups.items()}
    return out


def run(db: str, out_path: str, *, smoke: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    universe = load_universe(db)
    twii = load_twii(db)
    # 交易日（上市）供留白切
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
        "TW": holdout_cut(tw_days),
        "TWO": holdout_cut(tw_days),
        "EM": holdout_cut(em_days),
    }

    sids = sorted(universe.keys())
    if smoke:
        # 每市場各取少量
        picked = []
        for m in ("TW", "TWO", "EM"):
            picked.extend([s for s in sids if universe[s]["market"] == m][:8])
        sids = picked

    frames: Dict[str, pd.DataFrame] = {}
    events: List[Event] = []
    con = sqlite3.connect(db)
    try:
        for i, sid in enumerate(sids):
            meta = universe[sid]
            df = load_stock_df(con, sid, meta["market"])
            if df.empty or len(df) < 30:
                continue
            frames[sid] = df
            evs = process_price_tracks(
                sid,
                meta,
                df,
                twii=twii,
                holdout_from=holdout_from,
                smoke_max_events=30 if smoke else 0,
            )
            events.extend(evs)
            if smoke and i >= 24:
                break
            if (i + 1) % 200 == 0:
                print(f"[price] {i+1}/{len(sids)} events={len(events)}", flush=True)
    finally:
        con.close()

    print(f"[foreign] start events_price={len(events)}", flush=True)
    f_events, f_note = build_foreign_events(
        db, universe, holdout_from=holdout_from, smoke=smoke
    )
    events.extend(f_events)
    print(f"[score] total_events={len(events)}", flush=True)

    main = score_events(events, frames, twii, entry="next_open", apply_em_slip=False)
    close_entry = score_events(events, frames, twii, entry="signal_close", apply_em_slip=False)
    em_slip = score_events(
        [e for e in events if e.market == "EM"],
        frames,
        twii,
        entry="next_open",
        apply_em_slip=True,
    )

    # 大盤對照：同窗只持 TWII
    mkt_only: Dict[str, Any] = {}
    for h in HORIZONS:
        xs = []
        days = tw_days
        for i in range(len(days) - h - 1):
            r = twii_forward(twii, days, i, h, entry_open=True)
            if r is not None:
                xs.append(r)
        mkt_only[str(h)] = summarize_rets(xs)

    result = {
        "generated_at": _now_iso(),
        "db": db,
        "smoke": smoke,
        "elapsed_sec": round(time.time() - t0, 1),
        "universe_n": {m: sum(1 for v in universe.values() if v["market"] == m) for m in ("TW", "TWO", "EM")},
        "holdout_from": holdout_from,
        "dedup_n": DEDUP_N,
        "horizons": list(HORIZONS),
        "em_slip": EM_SLIP,
        "cost_rt": COST_RT,
        "emerging_foreign_note": f_note,
        "event_counts": {
            f"{t}:{m}": sum(1 for e in events if e.track == t and e.market == m)
            for t in TRACKS
            for m in ("TW", "TWO", "EM")
        },
        "main_next_open": main,
        "aux_signal_close": close_entry,
        "em_slip_sensitive": em_slip,
        "market_only_twii": mkt_only,
        "cooccurrence": cooccurrence(events),
        "stage_compare_h5": stage_compare(events, frames),
        "methods": {
            "A1": "leave_zero_bar_indices",
            "A2": "nav_low_ma60_lower_mask",
            "A3": "escalate_pre_A current_params ∪ extreme share_th0.20",
            "A4": "buy_escalate_A current_buy_params",
            "A5": "hold_l60",
            "A6": "hold_l60_tight",
            "A7": "leave_zero ∩ ¬buy_exclude ∩ is_winrate_priority（歷史近似；未重跑導航出圖剝框）",
            "primary_entry": "隔日開盤",
            "dedup": f"{DEDUP_N} 交易日內同檔同軌只算第一次",
        },
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[done] wrote {out_path} elapsed={result['elapsed_sec']}s", flush=True)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument(
        "--out",
        default="",
        help="JSON 輸出路徑",
    )
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    db = str(Path(args.db))
    if not Path(db).is_file():
        print(f"missing db {db}", file=sys.stderr)
        return 2
    out = args.out or (
        "/tmp/mt_baseline_smoke.json" if args.smoke else "/tmp/mt_baseline.json"
    )
    run(db, out, smoke=bool(args.smoke))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
