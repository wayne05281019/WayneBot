# -*- coding: utf-8 -*-
"""極端大賣→D+1～D+5｜靜默落檔骨架（不是買訊）。

kind＝foreign_sell_extreme_dplus；與 fear／escalate 勝率分開。
接 judge_tape → night_tick。單位：張。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path
from foreign_sell_escalate import GRID_LOTS_THR
from foreign_sell_escalate_verify import (
    MIN_VOLUME_LOTS,
    TOP_N,
    _ex_set,
    _load_panel,
    _top_sids,
    _trading_days,
)
from foreign_sell_extreme import (
    KIND,
    TAG_CONT_EXTREME,
    TAG_PRICE_DD,
    ExtremeTrack,
    hit_continue_extreme,
    hit_price_dd,
    lit_extreme_day,
    sync_same_day_crash,
    units_banner,
)
from fear_composite import _f, _ymd

MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
# 靜默預設：lots 5000 張軌＋價回撤 -5%＠K=5（離線網格另掃）
DEFAULT_TRACK = ExtremeTrack("lots", float(GRID_LOTS_THR[2] if len(GRID_LOTS_THR) > 2 else 5000))
DEFAULT_K = 5
DEFAULT_DD = -0.05


def _now_iso() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS foreign_sell_extreme_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                track_key TEXT NOT NULL DEFAULT '',
                sid TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL DEFAULT '',
                sync_crash INTEGER NOT NULL DEFAULT 0,
                sell_lots REAL,
                foreign_net REAL,
                volume REAL,
                volume_unit TEXT NOT NULL DEFAULT '張',
                foreign_net_unit TEXT NOT NULL DEFAULT '張',
                ex_rights INTEGER NOT NULL DEFAULT 0,
                open REAL, high REAL, low REAL, close REAL,
                PRIMARY KEY (kind, as_of, track_key, sid, tag)
            );
            CREATE TABLE IF NOT EXISTS foreign_sell_extreme_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                track_key TEXT NOT NULL DEFAULT '',
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                k_ahead INTEGER NOT NULL,
                hit INTEGER,
                dd REAL,
                verdict TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (kind, as_of, track_key, sid, tag, k_ahead)
            );
            CREATE TABLE IF NOT EXISTS foreign_sell_extreme_rates (
                kind TEXT NOT NULL,
                track_key TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL,
                k_ahead INTEGER NOT NULL,
                n INTEGER NOT NULL DEFAULT 0,
                hit INTEGER NOT NULL DEFAULT 0,
                miss INTEGER NOT NULL DEFAULT 0,
                pending INTEGER NOT NULL DEFAULT 0,
                n_days INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, track_key, tag, k_ahead)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def night_tick(market_db: str, day: str = "") -> Dict[str, Any]:
    """盤後：掃描極端 lit → 落 tape；有後窗則 score。失敗吞掉。"""
    out: Dict[str, Any] = {"ok": False, "kind": KIND, "n_lit": 0}
    if not market_db or not os.path.isfile(market_db):
        return out
    try:
        ensure_tables(market_db)
        days = _trading_days(market_db)
        if not days:
            return out
        as_of = _ymd(day) or days[-1]
        if as_of not in days:
            return out
        di = days.index(as_of)
        panel = _load_panel(market_db, days[max(0, di - 30) : di + 1])
        ex = _ex_set(market_db, as_of)
        top = _top_sids(market_db, as_of, n=TOP_N)
        track = DEFAULT_TRACK
        tk = track.key()
        bars_today = panel.get(as_of) or {}
        lit_rows: List[Dict[str, Any]] = []
        for sid in top:
            if sid in ex:
                continue
            b = bars_today.get(sid) or {}
            vol = _f(b.get("volume")) or 0
            if vol < MIN_VOLUME_LOTS:
                continue
            # 近窗 nets
            hist = []
            nets10 = []
            for d in days[max(0, di - 14) : di + 1]:
                bb = (panel.get(d) or {}).get(sid) or {}
                hist.append(bb.get("foreign_net"))
            nets10 = hist[-10:] if len(hist) >= 10 else hist
            if not lit_extreme_day(
                track,
                foreign_net=b.get("foreign_net"),
                volume=b.get("volume"),
                foreign_nets_hist=hist,
                foreign_nets_10=nets10,
            ):
                continue
            crash = sync_same_day_crash(open_=b.get("open"), close=b.get("close"))
            lit_rows.append(
                {
                    "sid": sid,
                    "name": str(b.get("stock_name") or ""),
                    "sync_crash": 1 if crash else 0,
                    "sell_lots": sell_lots_safe(b.get("foreign_net")),
                    "foreign_net": _f(b.get("foreign_net")),
                    "volume": vol,
                    "open": _f(b.get("open")),
                    "high": _f(b.get("high")),
                    "low": _f(b.get("low")),
                    "close": _f(b.get("close")),
                    "ex_rights": 0,
                }
            )
        store = tape_store_path(market_db)
        conn = sqlite3.connect(store, timeout=8.0)
        try:
            for r in lit_rows:
                for tag in (TAG_PRICE_DD, TAG_CONT_EXTREME):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO foreign_sell_extreme_tape(
                            kind, as_of, track_key, sid, name, tag, sync_crash,
                            sell_lots, foreign_net, volume, open, high, low, close, ex_rights
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            KIND,
                            as_of,
                            tk,
                            r["sid"],
                            r["name"],
                            tag,
                            r["sync_crash"],
                            r["sell_lots"],
                            r["foreign_net"],
                            r["volume"],
                            r["open"],
                            r["high"],
                            r["low"],
                            r["close"],
                            0,
                        ),
                    )
            # score pending windows when future days exist
            future_days = days[di + 1 : di + 1 + DEFAULT_K]
            if future_days and lit_rows:
                fut_panel = _load_panel(market_db, future_days)
                for r in lit_rows:
                    sid = r["sid"]
                    closes = [
                        ((fut_panel.get(d) or {}).get(sid) or {}).get("close")
                        for d in future_days
                    ]
                    fut_lits: List[Optional[bool]] = []
                    for d in future_days:
                        bb = (fut_panel.get(d) or {}).get(sid) or {}
                        if not bb:
                            fut_lits.append(None)
                            continue
                        # 簡易：同軌 lots 再 lit
                        fut_lits.append(
                            lit_extreme_day(
                                track,
                                foreign_net=bb.get("foreign_net"),
                                volume=bb.get("volume"),
                                foreign_nets_hist=[bb.get("foreign_net")],
                                foreign_nets_10=[bb.get("foreign_net")],
                            )
                        )
                    h1 = hit_price_dd(
                        r["close"], closes, k=DEFAULT_K, thr_dd=DEFAULT_DD
                    )
                    h2 = hit_continue_extreme(fut_lits, k=DEFAULT_K)
                    for h in (h1, h2):
                        hit_v = h.get("hit")
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO foreign_sell_extreme_score(
                                kind, as_of, track_key, sid, tag, k_ahead, hit, dd, verdict
                            ) VALUES (?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                KIND,
                                as_of,
                                tk,
                                sid,
                                h.get("tag") or "",
                                DEFAULT_K,
                                None if hit_v is None else (1 if hit_v else 0),
                                h.get("dd"),
                                h.get("verdict") or "pending",
                            ),
                        )
            conn.commit()
        finally:
            conn.close()
        out["ok"] = True
        out["n_lit"] = len(lit_rows)
        out["as_of"] = as_of
        out["track"] = tk
        out["units"] = units_banner()
        return out
    except Exception as e:
        out["error"] = str(e)[:200]
        return out


def sell_lots_safe(fn: Any) -> Optional[float]:
    from foreign_sell_extreme import sell_lots

    return sell_lots(fn)


def optimize_status_one_liner(market_db: str = "") -> str:
    """明確優化狀態一句；過程／％不准堆。"""
    n_days = 0
    if market_db and os.path.isfile(market_db):
        try:
            ensure_tables(market_db)
            store = tape_store_path(market_db)
            conn = sqlite3.connect(store, timeout=5.0)
            try:
                r = conn.execute(
                    "SELECT COUNT(DISTINCT as_of) FROM foreign_sell_extreme_tape WHERE kind=?",
                    (KIND,),
                ).fetchone()
                n_days = int(r[0] or 0) if r else 0
            finally:
                conn.close()
        except Exception:
            n_days = 0
    gate = "n夠" if n_days >= MIN_UNIQUE_DAYS else "n不夠"
    return f"明確優化狀態：極端大賣D+確認層 {gate}（獨立日{n_days}）；未過閘只靜默；個人本不進勝率"


__all__ = [
    "KIND",
    "ensure_tables",
    "night_tick",
    "optimize_status_one_liner",
    "MIN_UNIQUE_DAYS",
    "DEFAULT_TRACK",
]
