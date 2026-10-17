# -*- coding: utf-8 -*-
"""Calm／小買→大買｜靜默落檔骨架（不是買訊）。

kind＝foreign_sell_calm_env；與 Fear／escalate／extreme 分開。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path
from fear_composite import _f, _ymd
from foreign_sell_calm import (
    KIND,
    TAG_BUY_ESC,
    TAG_CALM,
    BuyEscalateParams,
    current_buy_params,
    evaluate_buy_escalate_A,
    evaluate_calm_fear_fade,
    hit_buy_within_k,
    next_silent_buy_params,
    units_banner,
)
from foreign_sell_escalate import cross_sectional_percentile
from foreign_sell_escalate_verify import (
    MIN_VOLUME_LOTS,
    TOP_N,
    _ex_set,
    _load_panel,
    _top_sids,
    _trading_days,
)
from foreign_sell_calm import buy_share

MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N


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
            CREATE TABLE IF NOT EXISTS foreign_sell_calm_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                sid TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                buy_share REAL,
                pctl REAL,
                foreign_net REAL,
                volume REAL,
                PRIMARY KEY (kind, as_of, params_key, sid, tag)
            );
            CREATE TABLE IF NOT EXISTS foreign_sell_calm_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                k_ahead INTEGER NOT NULL,
                hit INTEGER,
                verdict TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (kind, as_of, params_key, sid, tag, k_ahead)
            );
            CREATE TABLE IF NOT EXISTS foreign_sell_calm_rates (
                kind TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL,
                k_ahead INTEGER NOT NULL,
                n INTEGER NOT NULL DEFAULT 0,
                hit INTEGER NOT NULL DEFAULT 0,
                miss INTEGER NOT NULL DEFAULT 0,
                pending INTEGER NOT NULL DEFAULT 0,
                n_days INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, params_key, tag, k_ahead)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def _buy_day_pctls(day_bars: Dict[str, Dict[str, Any]], *, min_vol: float = MIN_VOLUME_LOTS) -> Dict[str, float]:
    ss_map: Dict[str, float] = {}
    for sid, b in day_bars.items():
        vol = _f(b.get("volume"))
        fn = _f(b.get("foreign_net"))
        if vol is None or vol < min_vol or fn is None or fn <= 0:
            continue
        ss = buy_share(fn, vol)
        if ss is None:
            continue
        ss_map[sid] = float(ss)
    vals = list(ss_map.values())
    return {sid: cross_sectional_percentile(vals, ss) for sid, ss in ss_map.items()}


def night_tick(market_db: str, day: str = "") -> Dict[str, Any]:
    """盤後：Calm（若有 fear tape）＋小買升級掃 Top500。失敗吞掉。"""
    out: Dict[str, Any] = {"ok": False, "kind": KIND, "n_buy": 0, "calm": False}
    if not market_db or not os.path.isfile(market_db):
        return out
    try:
        ensure_tables(market_db)
        as_of = _ymd(day)
        dens = _trading_days(market_db, "20200101", as_of or "20991231")
        if not dens:
            return out
        as_of = as_of or dens[-1]
        if as_of not in dens:
            return out
        di = dens.index(as_of)
        p = current_buy_params()
        p_next = next_silent_buy_params()
        need_n = max(int(p.n_days), int(p_next.n_days))
        win = dens[max(0, di - need_n + 1) : di + 1]
        top = _top_sids(market_db, as_of, TOP_N)
        panel = _load_panel(market_db, win, top)
        ex = _ex_set(market_db, as_of)
        pctls_by_day = {d: _buy_day_pctls(panel.get(d) or {}) for d in win}

        def _scan_buy(params: BuyEscalateParams) -> List[Dict[str, Any]]:
            lit: List[Dict[str, Any]] = []
            for sid in top:
                if sid in ex:
                    continue
                fns, vols, ps = [], [], []
                ok = True
                for d in win[-params.n_days :]:
                    b = (panel.get(d) or {}).get(sid)
                    if not b:
                        ok = False
                        break
                    fns.append(b.get("foreign_net"))
                    vols.append(b.get("volume"))
                    ps.append(pctls_by_day.get(d, {}).get(sid))
                if not ok:
                    continue
                today = (panel.get(as_of) or {}).get(sid) or {}
                if (_f(today.get("volume")) or 0) < MIN_VOLUME_LOTS:
                    continue
                ev = evaluate_buy_escalate_A(
                    foreign_nets=fns, volumes=vols, pctls=ps, params=params
                )
                if not ev.get("lit"):
                    continue
                lit.append(
                    {
                        "sid": sid,
                        "buy_share": ev.get("buy_share"),
                        "pctl": ev.get("pctl"),
                        "foreign_net": today.get("foreign_net"),
                        "volume": today.get("volume"),
                        "params_key": params.key(),
                        "k_ahead": int(params.k_ahead),
                        "theta_pctl": float(params.theta_pctl),
                    }
                )
            return lit

        lit_buy = _scan_buy(p)
        lit_buy_next = _scan_buy(p_next)

        # Calm：讀 fear_preopen_tape 若存在
        calm_lit = False
        calm_note = ""
        store = tape_store_path(market_db)
        try:
            conn_f = sqlite3.connect(store, timeout=5.0)
            try:
                def _fear_row(d: str) -> tuple:
                    try:
                        r = conn_f.execute(
                            "SELECT lit, votes FROM fear_preopen_tape WHERE kind=? AND as_of=? ORDER BY params_key LIMIT 1",
                            ("fear_preopen_warn", d),
                        ).fetchone()
                        if not r:
                            return None, None
                        return (bool(int(r[0] or 0)), int(r[1]) if r[1] is not None else None)
                    except sqlite3.Error:
                        return None, None

                yest = dens[di - 1] if di >= 1 else ""
                lit_t, edges_t = _fear_row(as_of)
                lit_y, edges_y = _fear_row(yest) if yest else (None, None)
                ev = evaluate_calm_fear_fade(
                    fear_edges_today=edges_t,
                    fear_edges_yest=edges_y,
                    lit_today=lit_t,
                    lit_yest=lit_y,
                )
                calm_lit = bool(ev.get("lit"))
                calm_note = str(ev.get("reason") or "")
            finally:
                conn_f.close()
        except Exception:
            pass

        conn = sqlite3.connect(store, timeout=8.0)
        try:
            if calm_lit:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO foreign_sell_calm_tape(
                        kind, as_of, params_key, sid, tag, note
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (KIND, as_of, "calm", "", TAG_CALM, calm_note),
                )
            for r in lit_buy + lit_buy_next:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO foreign_sell_calm_tape(
                        kind, as_of, params_key, sid, tag, note, buy_share, pctl, foreign_net, volume
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        as_of,
                        r["params_key"],
                        r["sid"],
                        TAG_BUY_ESC,
                        "小買升級",
                        r.get("buy_share"),
                        r.get("pctl"),
                        r.get("foreign_net"),
                        r.get("volume"),
                    ),
                )
            # score：現況＋下一版分 params_key；勝率不准混
            for bundle in (lit_buy, lit_buy_next):
                if not bundle:
                    continue
                k_ah = int(bundle[0]["k_ahead"])
                th = float(bundle[0]["theta_pctl"])
                fut = dens[di + 1 : di + 1 + k_ah]
                if not fut:
                    continue
                fut_panel = _load_panel(market_db, fut, [r["sid"] for r in bundle])
                fut_pctls = {d: _buy_day_pctls(fut_panel.get(d) or {}) for d in fut}
                for r in bundle:
                    fps = [fut_pctls.get(d, {}).get(r["sid"]) for d in fut]
                    h = hit_buy_within_k(fps, k=k_ah, theta_pctl=th)
                    hit_v = h.get("hit")
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO foreign_sell_calm_score(
                            kind, as_of, params_key, sid, tag, k_ahead, hit, verdict
                        ) VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            KIND,
                            as_of,
                            r["params_key"],
                            r["sid"],
                            TAG_BUY_ESC,
                            k_ah,
                            None if hit_v is None else (1 if hit_v else 0),
                            "pending"
                            if hit_v is None
                            else ("hit" if hit_v else "miss"),
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
        out["ok"] = True
        out["n_buy"] = len(lit_buy)
        out["n_buy_next"] = len(lit_buy_next)
        out["next_silent"] = p_next.key()
        out["calm"] = calm_lit
        out["as_of"] = as_of
        out["units"] = units_banner()
        out["buy_signal"] = False
        return out
    except Exception as e:
        out["error"] = str(e)[:200]
        return out


def optimize_status_one_liner(market_db: str = "") -> str:
    n_days = 0
    if market_db and os.path.isfile(market_db):
        try:
            ensure_tables(market_db)
            store = tape_store_path(market_db)
            conn = sqlite3.connect(store, timeout=5.0)
            try:
                r = conn.execute(
                    "SELECT COUNT(DISTINCT as_of) FROM foreign_sell_calm_tape WHERE kind=?",
                    (KIND,),
                ).fetchone()
                n_days = int(r[0] or 0) if r else 0
            finally:
                conn.close()
        except Exception:
            n_days = 0
    gate = "n夠" if n_days >= MIN_UNIQUE_DAYS else "n不夠"
    return f"明確優化狀態：Calm／小買環境 {gate}（獨立日{n_days}）；未過閘只靜默；非買訊"


__all__ = ["KIND", "ensure_tables", "night_tick", "optimize_status_one_liner", "MIN_UNIQUE_DAYS"]
