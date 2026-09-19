# -*- coding: utf-8 -*-
"""獲利欄量化鎖：必須等於官方 60 曆日收盤低，不能 0 卻貼 20 高。"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

import pandas as pd

from decision_card_signals import (
    cal60_profit_bundle,
    format_profit_pct,
    is_profit_display_zero,
)

# Cary 2438 翔耀 2026/09/18 卡上的獲利（官方 60 曆日低 16.45）。
CARY_2438_PROFIT = {
    "20260917": 16.7,
    "20260916": 17.0,
    "20260915": 20.4,
    "20260914": 15.5,
    "20260911": 15.8,
    "20260910": 20.4,
    "20260909": 24.0,
    "20260908": 21.6,
    "20260907": 26.7,
    "20260904": 33.1,
    "20260903": 34.0,
    "20260902": 21.9,
    "20260901": 10.9,
    "20260831": 10.3,
    "20260828": 10.3,
    "20260827": 10.0,
    "20260826": 9.7,
    "20260825": 7.6,
    "20260824": 10.6,
}

HIGH_ZERO_MIN_RANGE = 0.08
CLIFF_PROFIT_PP = 15.0
CLIFF_CLOSE_PCT = 0.08


def _ymd(val) -> str:
    return str(val or "").replace("-", "")[:8]


def count_zero_ohlc_bars(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(
            """
            SELECT COUNT(*) FROM daily_quotes
            WHERE COALESCE(close, 0) <= 0
               OR COALESCE(open, 0) <= 0
               OR COALESCE(high, 0) <= 0
               OR COALESCE(low, 0) <= 0
            """
        ).fetchone()[0]
        return int(n or 0)
    finally:
        conn.close()


def _scan_one(sid: str, df: pd.DataFrame, *, lookback: int) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    floors, pct = cal60_profit_bundle(df)
    closes = pd.to_numeric(df["close"], errors="coerce")
    valid = closes.where(closes > 0)
    high20 = valid.rolling(20, min_periods=1).max()
    tail = list(range(max(0, len(df) - lookback), len(df)))
    for i in tail:
        c = float(closes.iloc[i] or 0)
        if c <= 0:
            continue
        p = float(pct.iloc[i])
        floor = float(floors[i] or 0)
        d = _ymd(df["date"].iloc[i])
        h20 = float(high20.iloc[i] or 0)
        if (
            is_profit_display_zero(p)
            and h20 > 0
            and floor > 0
            and c >= h20 * 0.998
            and (h20 / floor - 1.0) >= HIGH_ZERO_MIN_RANGE
        ):
            issues.append(
                {
                    "kind": "high_zero",
                    "sid": sid,
                    "date": d,
                    "close": c,
                    "profit": p,
                    "floor": floor,
                    "high20": h20,
                }
            )
        if i == 0:
            continue
        prev_c = float(closes.iloc[i - 1] or 0)
        prev_p = float(pct.iloc[i - 1])
        if prev_c <= 0:
            continue
        if (p - prev_p) >= CLIFF_PROFIT_PP and abs(c / prev_c - 1.0) < CLIFF_CLOSE_PCT:
            issues.append(
                {
                    "kind": "cliff",
                    "sid": sid,
                    "date": d,
                    "close": c,
                    "profit": p,
                    "prev_profit": prev_p,
                    "prev_close": prev_c,
                }
            )
    return issues


def scan_profit_contradictions(
    db_path: str,
    *,
    limit_names: int = 300,
    lookback: int = 40,
    extra_sids: tuple = ("2438", "2383", "2330", "2454"),
) -> Dict[str, Any]:
    """掃官方日 K：獲利必須對 60 曆日低；0.0% 不能同時貼 20 高。"""
    conn = sqlite3.connect(db_path)
    try:
        sids = [str(x) for x in extra_sids if x]
        sids.extend(
            str(r[0])
            for r in conn.execute(
                """
                SELECT stock_id FROM daily_quotes
                WHERE close > 0
                GROUP BY stock_id
                HAVING COUNT(*) >= 40
                LIMIT ?
                """,
                (int(limit_names),),
            )
        )
        seen = set()
        ordered = []
        for sid in sids:
            if sid in seen:
                continue
            seen.add(sid)
            ordered.append(sid)
        issues: List[Dict[str, Any]] = []
        n = 0
        for sid in ordered:
            rows = conn.execute(
                "SELECT date, close FROM daily_quotes WHERE stock_id=? ORDER BY date",
                (sid,),
            ).fetchall()
            if len(rows) < 20:
                continue
            df = pd.DataFrame(rows, columns=["date", "close"])
            issues.extend(_scan_one(sid, df, lookback=lookback))
            n += 1
        zero_n = count_zero_ohlc_bars(db_path)
    finally:
        conn.close()
    by = {"high_zero": [], "cliff": []}
    for item in issues:
        by.setdefault(str(item.get("kind") or "high_zero"), []).append(item)
    return {
        "names": n,
        "zero_bars": zero_n,
        "high_zero": by.get("high_zero") or [],
        "cliff": by.get("cliff") or [],
        "ok": not ((by.get("high_zero") or []) or (by.get("cliff") or [])),
    }


def report_lines(scan: Dict[str, Any]) -> str:
    lines = [
        f"names={scan.get('names')} zero_bars={scan.get('zero_bars')} "
        f"high_zero={len(scan.get('high_zero') or [])} "
        f"cliff={len(scan.get('cliff') or [])} ok={scan.get('ok')}"
    ]
    for kind in ("high_zero", "cliff"):
        for item in (scan.get(kind) or [])[:12]:
            lines.append(
                f"{kind} {item.get('sid')} {item.get('date')} "
                f"c={item.get('close')} p={item.get('profit')} "
                f"exp={item.get('expected')} prev={item.get('prev_profit')}"
            )
    return "\n".join(lines) + "\n"


def cary_2438_mismatches(db_path: str, as_of: str = "20260917") -> List[str]:
    """Cary 卡上的獲利必須逐日對上。"""
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(db_path).get_decision_card(
        "2438", lookback=20, merge_live=False, as_of=as_of
    )
    tbl = card.get("table")
    if tbl is None or getattr(tbl, "empty", True):
        return ["no 2438 table"]
    bad = []
    for d, want in CARY_2438_PROFIT.items():
        if d > as_of:
            continue
        row = tbl[tbl["date"].astype(str).str.replace("-", "", regex=False) == d]
        if row.empty:
            bad.append(f"{d} missing")
            continue
        got = float(row.iloc[0]["profit_pct"])
        if abs(got - want) > 0.15:
            bad.append(f"{d} got {got} want {want} ({format_profit_pct(got)})")
    return bad
