# -*- coding: utf-8 -*-
"""第 3 輪過閘環境濾網（§13）：不改 ma60_lower／hold_l60／leave_zero 公式本體。

可換（2026-10-22 全量雙閘）：
  - A2 ← R3c_keep_pressure（外資壓力日才保留紅箭）
  - A5 ← R3a_twii_down（加權收跌日才保留止穩）

再生下一版靜默候選（同件義務）：
  - A2_NEXT = R3c_keep ∧ 非擁擠高量（R2a 風格）
  - A5_NEXT = R3a ∧ R3d_excl_crowd
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

from foreign_sell_display import DISPLAY_SELL_SHARE_THR
from foreign_sell_escalate import (
    cross_sectional_percentile,
    current_params,
    evaluate_escalate_A,
    sell_share,
)
from foreign_sell_extreme import ExtremeTrack, lit_extreme_day

# 現況啟用濾網（過閘已換）
ACTIVE_A2_FILTER = "R3c_keep_pressure"
ACTIVE_A5_FILTER = "R3a_twii_down"

# 再生下一版（靜默收集；未過閘不上）
NEXT_A2_SILENT = "R3c_keep_and_R2a"
NEXT_A5_SILENT = "R3a_and_R3d_excl_crowd"


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "").strip()[:8]
    return t if len(t) == 8 and t.isdigit() else ""


@lru_cache(maxsize=8)
def _twii_dir_map(db_path: str) -> Dict[str, int]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT replace(CAST(date AS TEXT),'-','') AS d, close
            FROM index_daily WHERE symbol='TWII' AND close>0 ORDER BY d
            """
        ).fetchall()
    finally:
        con.close()
    out: Dict[str, int] = {}
    prev = None
    for d, c in rows:
        dd = _ymd(d)
        if not dd:
            continue
        try:
            cf = float(c)
        except (TypeError, ValueError):
            continue
        if prev is not None and prev > 0:
            out[dd] = 1 if cf > prev else (-1 if cf < prev else 0)
        prev = cf
    return out


def twii_closed_down(db_path: str, day: str) -> Optional[bool]:
    """R3a：加權當日收跌。未知日回 None（不擋）。"""
    d = _ymd(day)
    if not d:
        return None
    m = _twii_dir_map(db_path)
    if d not in m:
        return None
    return m[d] < 0


@lru_cache(maxsize=4)
def _pressure_day_set(db_path: str) -> frozenset:
    """上市櫃：當日橘賣（升級∪極端）佔比 > 近20日中位。"""
    import numpy as np

    con = sqlite3.connect(db_path)
    try:
        df_rows = con.execute(
            """
            SELECT replace(CAST(date AS TEXT),'-','') AS date, stock_id,
                   volume, COALESCE(foreign_net,0) AS foreign_net
            FROM daily_quotes
            WHERE market IN ('TW','TWO') AND close>0 AND volume>0
            ORDER BY date, stock_id
            """
        ).fetchall()
    finally:
        con.close()
    if not df_rows:
        return frozenset()

    from collections import defaultdict

    hist: Dict[str, list] = defaultdict(list)
    by_day: Dict[str, list] = defaultdict(list)
    for d, sid, vol, fn in df_rows:
        dd = _ymd(d)
        if not dd:
            continue
        hist[str(sid)].append((dd, float(vol or 0), float(fn or 0)))
        by_day[dd].append((str(sid), float(vol or 0), float(fn or 0)))

    date_ix = {sid: {t[0]: i for i, t in enumerate(seq)} for sid, seq in hist.items()}
    esc_p = current_params()
    ext_track = ExtremeTrack("share", float(DISPLAY_SELL_SHARE_THR))
    sell_pctl: Dict[Tuple[str, str], float] = {}
    for day, rows in by_day.items():
        sell_vals = []
        sell_map = {}
        for sid, vol, fn in rows:
            ss = sell_share(fn, vol)
            if ss is not None:
                sell_vals.append(float(ss))
                sell_map[sid] = float(ss)
        for sid, ss in sell_map.items():
            sell_pctl[(day, sid)] = cross_sectional_percentile(sell_vals, ss)

    ratios: Dict[str, float] = {}
    for day in sorted(by_day.keys()):
        rows = by_day[day]
        nz = sum(1 for _, _, fn in rows if fn != 0)
        if nz < max(30, int(len(rows) * 0.05)):
            continue
        lit = tot = 0
        for sid, vol, fn in rows:
            seq = hist.get(sid)
            if not seq:
                continue
            ix = date_ix[sid].get(day)
            if ix is None:
                continue
            n = int(esc_p.n_days)
            if ix + 1 < n:
                continue
            tot += 1
            window = seq[ix - n + 1 : ix + 1]
            fns = [t[2] for t in window]
            vols = [t[1] for t in window]
            pctls = [sell_pctl.get((t[0], sid)) for t in window]
            ev_esc = evaluate_escalate_A(
                foreign_nets=fns, volumes=vols, pctls=pctls, params=esc_p
            )
            lit_ext = lit_extreme_day(
                ext_track,
                foreign_net=fn,
                volume=vol,
                foreign_nets_hist=fns,
                foreign_nets_10=[t[2] for t in seq[max(0, ix - 9) : ix + 1]],
            )
            if ev_esc.get("lit") or lit_ext:
                lit += 1
        if tot > 0:
            ratios[day] = lit / tot

    sorted_days = sorted(ratios.keys())
    pressure = set()
    for i, day in enumerate(sorted_days):
        window = [ratios[d] for d in sorted_days[max(0, i - 19) : i + 1]]
        if len(window) < 5:
            continue
        if ratios[day] > float(np.median(window)):
            pressure.add(day)
    return frozenset(pressure)


def foreign_pressure_day(db_path: str, day: str) -> bool:
    """R3c：外資壓力日。"""
    d = _ymd(day)
    if not d:
        return False
    return d in _pressure_day_set(db_path)


def keep_a2_red_arrow(db_path: str, day: str, *, market: str = "") -> bool:
    """A2 現況濾網：上市櫃須為外資壓力日；興櫃無外資壓力定義 → 不套此濾（維持可亮）。"""
    m = str(market or "").upper()
    if m == "EM":
        return True
    if ACTIVE_A2_FILTER != "R3c_keep_pressure":
        return True
    return foreign_pressure_day(db_path, day)


def keep_a5_stabilize(db_path: str, day: str) -> bool:
    """A5 現況濾網：加權收跌日才保留止穩；未知日不擋。"""
    if ACTIVE_A5_FILTER != "R3a_twii_down":
        return True
    v = twii_closed_down(db_path, day)
    if v is None:
        return True
    return bool(v)


def silent_next_keys() -> Dict[str, str]:
    return {"A2": NEXT_A2_SILENT, "A5": NEXT_A5_SILENT}
