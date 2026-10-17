# -*- coding: utf-8 -*-
"""小賣→大賣升級｜靜默落檔骨架（不是買訊）。

kind＝foreign_sell_escalate；與 fear_preopen_warn 勝率分開。
沒按也記；空日／空名單不算 n。接 judge_tape → night_tick。
單位：volume／foreign_net＝張；sell_share＝張/張。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path
from fear_composite import FOREIGN_NET_UNIT, SELL_SHARE_UNIT, VOLUME_UNIT, _f, _ymd, sell_share
from foreign_sell_escalate import (
    KIND,
    TAG_PRE_A,
    EscalateParams,
    classify_lead_sync_vs_extreme,
    cross_sectional_percentile,
    current_params,
    evaluate_escalate_A,
    hit_within_k,
    next_silent_params,
    units_banner,
)

MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
TOP_N = 500
LOOKBACK_CAL = 180
MIN_VOLUME_LOTS = 100  # 極小量股濾（張）


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
            CREATE TABLE IF NOT EXISTS foreign_sell_escalate_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                sid TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL DEFAULT '',
                lead_sync TEXT NOT NULL DEFAULT '',
                sell_share REAL,
                pctl REAL,
                foreign_net REAL,
                volume REAL,
                volume_unit TEXT NOT NULL DEFAULT '張',
                foreign_net_unit TEXT NOT NULL DEFAULT '張',
                ex_rights INTEGER NOT NULL DEFAULT 0,
                open REAL, high REAL, low REAL, close REAL,
                PRIMARY KEY (kind, as_of, params_key, sid, tag)
            );
            CREATE TABLE IF NOT EXISTS foreign_sell_escalate_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                lead_sync TEXT NOT NULL DEFAULT '',
                k_ahead INTEGER NOT NULL,
                hit INTEGER,
                hit_day_offset INTEGER,
                verdict TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (kind, as_of, params_key, sid, tag, k_ahead)
            );
            CREATE TABLE IF NOT EXISTS foreign_sell_escalate_rates (
                kind TEXT NOT NULL,
                params_key TEXT NOT NULL DEFAULT '',
                tag TEXT NOT NULL,
                lead_sync TEXT NOT NULL DEFAULT 'all',
                k_ahead INTEGER NOT NULL,
                n INTEGER NOT NULL DEFAULT 0,
                hit INTEGER NOT NULL DEFAULT 0,
                miss INTEGER NOT NULL DEFAULT 0,
                pending INTEGER NOT NULL DEFAULT 0,
                n_days INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, params_key, tag, lead_sync, k_ahead)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def _shift_ymd(day: str, delta: int) -> str:
    from datetime import datetime, timedelta

    d = datetime.strptime(_ymd(day), "%Y%m%d") + timedelta(days=int(delta))
    return d.strftime("%Y%m%d")


def _ex_set(db: str, day: str) -> set:
    day = _ymd(day)
    conn = sqlite3.connect(db, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT stock_id FROM ex_rights WHERE REPLACE(CAST(ex_date AS TEXT),'-','')=?",
            (day,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return {str(r[0]) for r in rows if r and r[0]}


def _top_sids(db: str, day: str, top_n: int = TOP_N) -> List[str]:
    """近半年**日均成交張數** TopN（討論起點；不是日均額）。"""
    day = _ymd(day)
    conn = sqlite3.connect(db, timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT stock_id, AVG(CASE WHEN volume>0 THEN volume END) AS avg_vol_lots
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','')<=?
              AND REPLACE(CAST(date AS TEXT),'-','')>=?
              AND length(stock_id)=4
              AND stock_id GLOB '[0-9][0-9][0-9][0-9]'
            GROUP BY stock_id
            HAVING avg_vol_lots IS NOT NULL AND avg_vol_lots>0
            ORDER BY avg_vol_lots DESC
            LIMIT ?
            """,
            (day, _shift_ymd(day, -LOOKBACK_CAL), int(top_n)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return [str(r[0]) for r in rows if r and r[0]]


def _universe_sids(
    db: str,
    day: str,
    universe: str,
    *,
    panel_day: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """起點三母體。universe＝top500_vol／qianjin／liquid_tw。"""
    from foreign_sell_escalate import (
        LIQUID_MIN_TURNOVER_K,
        LIQUID_MIN_VOL_LOTS,
        QIANJIN_PX,
        UNIVERSE_LIQUID,
        UNIVERSE_QIANJIN,
        UNIVERSE_TOP500_VOL,
    )

    day = _ymd(day)
    if universe == UNIVERSE_TOP500_VOL:
        return _top_sids(db, day, TOP_N)
    # 以下需當日柱
    bars = panel_day
    if bars is None:
        # 載當日全市场過貴；用 Top 擴大池再濾
        pool = _top_sids(db, day, max(TOP_N * 4, 2000))
        bars = (_load_panel(db, [day], pool).get(day) or {})
    if universe == UNIVERSE_QIANJIN:
        out = []
        for sid, b in bars.items():
            if (_f(b.get("close")) or 0) >= QIANJIN_PX and (_f(b.get("volume")) or 0) > 0:
                out.append(sid)
        return sorted(out)
    if universe == UNIVERSE_LIQUID:
        out = []
        for sid, b in bars.items():
            vol = _f(b.get("volume")) or 0
            # turnover_k 可能缺：用 close*volume 近似千元額（close×張≈股價×千股＝千元級需 ×1？）
            # 入庫 turnover_k＝成交金額千元；缺則略過該檔
            to_k = _f(b.get("turnover_k"))
            if to_k is None and (_f(b.get("close")) or 0) > 0 and vol > 0:
                # close 元 × volume 張 ×1000 股/張 / 1000＝close×volume 千元
                to_k = float(b["close"]) * float(vol)
            if vol >= LIQUID_MIN_VOL_LOTS and (to_k or 0) >= LIQUID_MIN_TURNOVER_K:
                out.append(sid)
        return sorted(out)
    return _top_sids(db, day, TOP_N)


def _trading_days(db: str, start: str, end: str) -> List[str]:
    conn = sqlite3.connect(db, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') AS d
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','')>=?
              AND REPLACE(CAST(date AS TEXT),'-','')<=?
              AND foreign_net IS NOT NULL
            GROUP BY d
            HAVING SUM(CASE WHEN foreign_net IS NOT NULL THEN 1 ELSE 0 END)>=200
            ORDER BY d
            """,
            (_ymd(start), _ymd(end)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return [_ymd(r[0]) for r in rows if _ymd(r[0])]


def _load_panel(
    db: str, days: Sequence[str], sids: Sequence[str]
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """day → sid → bar（含 foreign_net／volume 張）。"""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {d: {} for d in days}
    if not days or not sids:
        return out
    conn = sqlite3.connect(db, timeout=60.0)
    try:
        for i in range(0, len(sids), 300):
            chunk = list(sids[i : i + 300])
            marks = ",".join("?" * len(chunk))
            d0, d1 = days[0], days[-1]
            rows = conn.execute(
                f"""
                SELECT REPLACE(CAST(date AS TEXT),'-','') AS d, stock_id, stock_name,
                       open, high, low, close, volume, foreign_net, turnover_k
                FROM daily_quotes
                WHERE REPLACE(CAST(date AS TEXT),'-','')>=?
                  AND REPLACE(CAST(date AS TEXT),'-','')<=?
                  AND stock_id IN ({marks})
                """,
                [d0, d1, *chunk],
            ).fetchall()
            for r in rows:
                d = _ymd(r[0])
                if d not in out:
                    continue
                sid = str(r[1])
                out[d][sid] = {
                    "stock_id": sid,
                    "stock_name": str(r[2] or ""),
                    "open": _f(r[3]),
                    "high": _f(r[4]),
                    "low": _f(r[5]),
                    "close": _f(r[6]),
                    "volume": _f(r[7]),
                    "foreign_net": _f(r[8]),
                    "turnover_k": _f(r[9]) if len(r) > 9 else None,
                }
    finally:
        conn.close()
    return out


def _day_pctls(
    day_bars: Dict[str, Dict[str, Any]], *, min_vol: float = MIN_VOLUME_LOTS
) -> Dict[str, float]:
    """當日 Top 宇宙 sell_share 截面分位（僅賣超且量≥min_vol 張）。"""
    ss_map: Dict[str, float] = {}
    for sid, b in day_bars.items():
        vol = _f(b.get("volume"))
        fn = _f(b.get("foreign_net"))
        if vol is None or vol < min_vol or fn is None or fn >= 0:
            continue
        ss = sell_share(fn, vol)
        if ss is None:
            continue
        ss_map[sid] = float(ss)
    vals = list(ss_map.values())
    return {sid: cross_sectional_percentile(vals, ss) for sid, ss in ss_map.items()}


def snapshot_day(
    db_path: str,
    as_of: str = "",
    *,
    params: Optional[EscalateParams] = None,
) -> Dict[str, Any]:
    """盤後：Top500 掃升級型 A；除權息日該檔不進 lit。"""
    p = params or EscalateParams()
    day = _ymd(as_of)
    if not day:
        try:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(db_path))
        except Exception:
            day = ""
    if not day or not os.path.isfile(db_path):
        return {"as_of": day, "n_lit": 0, "units": units_banner()}

    # 需要 N 日歷史：取密窗最近交易日
    dens = _trading_days(db_path, "20260401", day)
    if day not in dens:
        return {"as_of": day, "n_lit": 0, "skip": "非法人密日", "units": units_banner()}
    i = dens.index(day)
    need = dens[max(0, i - p.n_days + 1) : i + 1]
    if len(need) < p.n_days:
        return {"as_of": day, "n_lit": 0, "skip": "歷史不足", "units": units_banner()}

    sids = _top_sids(db_path, day, TOP_N)
    panel = _load_panel(db_path, need, sids)
    pctls_by_day = {d: _day_pctls(panel.get(d) or {}) for d in need}
    ex = _ex_set(db_path, day)
    rows: List[Dict[str, Any]] = []
    for sid in sids:
        if sid in ex:
            continue
        fns, vols, ps = [], [], []
        ok = True
        for d in need:
            b = (panel.get(d) or {}).get(sid)
            if not b:
                ok = False
                break
            fns.append(b.get("foreign_net"))
            vols.append(b.get("volume"))
            ps.append(pctls_by_day.get(d, {}).get(sid))
        if not ok:
            continue
        ev = evaluate_escalate_A(foreign_nets=fns, volumes=vols, pctls=ps, params=p)
        if not ev.get("lit"):
            continue
        today = (panel.get(day) or {}).get(sid) or {}
        if (_f(today.get("volume")) or 0) < MIN_VOLUME_LOTS:
            continue
        if not today.get("close"):
            continue
        ls = classify_lead_sync_vs_extreme(True, extreme_today=False)
        rows.append(
            {
                "as_of": day,
                "params_key": p.key(),
                "sid": sid,
                "name": today.get("stock_name") or "",
                "tag": TAG_PRE_A,
                "lead_sync": ls,
                "sell_share": ev.get("sell_share"),
                "pctl": ev.get("pctl"),
                "foreign_net": today.get("foreign_net"),
                "volume": today.get("volume"),
                "open": today.get("open"),
                "high": today.get("high"),
                "low": today.get("low"),
                "close": today.get("close"),
                "ex_rights": 0,
            }
        )

    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=30.0)
    try:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO foreign_sell_escalate_tape(
                    kind, as_of, params_key, sid, name, tag, lead_sync,
                    sell_share, pctl, foreign_net, volume,
                    volume_unit, foreign_net_unit, ex_rights,
                    open, high, low, close
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    r["as_of"],
                    r["params_key"],
                    r["sid"],
                    r["name"],
                    r["tag"],
                    r["lead_sync"],
                    r["sell_share"],
                    r["pctl"],
                    r["foreign_net"],
                    r["volume"],
                    VOLUME_UNIT,
                    FOREIGN_NET_UNIT,
                    0,
                    r["open"],
                    r["high"],
                    r["low"],
                    r["close"],
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "as_of": day,
        "n_lit": len(rows),
        "params_key": p.key(),
        "units": units_banner(),
        "sell_share_unit": SELL_SHARE_UNIT,
    }


def score_pending(db_path: str, *, params: Optional[EscalateParams] = None) -> int:
    p = params or EscalateParams()
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        tape = conn.execute(
            """
            SELECT as_of, params_key, sid, tag, lead_sync FROM foreign_sell_escalate_tape
            WHERE kind=? AND params_key=?
            """,
            (KIND, p.key()),
        ).fetchall()
    finally:
        conn.close()
    if not tape:
        return 0
    dens = _trading_days(db_path, "20260401", "20991231")
    dens_i = {d: i for i, d in enumerate(dens)}
    n = 0
    store_c = sqlite3.connect(store, timeout=30.0)
    try:
        for as_of, pkey, sid, tag, lead_sync in tape:
            as_of = _ymd(as_of)
            sid = str(sid)
            if as_of not in dens_i:
                continue
            i0 = dens_i[as_of]
            fut_days = dens[i0 + 1 : i0 + 1 + p.k_ahead]
            # 重算未來分位：需載該股未來日 panel — 簡化：逐日算截面（較慢但正確）
            future_pctls: List[Optional[float]] = []
            for fd in fut_days:
                sids = _top_sids(db_path, fd, TOP_N)
                panel = _load_panel(db_path, [fd], sids)
                pct = _day_pctls(panel.get(fd) or {}).get(sid)
                future_pctls.append(pct)
            h = hit_within_k(future_pctls, k=p.k_ahead, theta_pctl=p.theta_pctl)
            if h.get("verdict") == "pending" or h.get("hit") is None:
                verdict, hit, off = "pending", None, None
            elif h.get("hit"):
                verdict, hit, off = "hit", 1, h.get("hit_day_offset")
            else:
                verdict, hit, off = "miss", 0, None
            store_c.execute(
                """
                INSERT OR REPLACE INTO foreign_sell_escalate_score(
                    kind, as_of, params_key, sid, tag, lead_sync, k_ahead,
                    hit, hit_day_offset, verdict
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (KIND, as_of, pkey, sid, tag, lead_sync or "", int(p.k_ahead), hit, off, verdict),
            )
            n += 1
        store_c.commit()
    finally:
        store_c.close()
    return n


def recompute_rates(db_path: str) -> Dict[str, Any]:
    store = ensure_tables(db_path)
    now = _now_iso()
    conn = sqlite3.connect(store, timeout=8.0)
    out: Dict[str, Any] = {}
    try:
        conn.execute("DELETE FROM foreign_sell_escalate_rates WHERE kind=?", (KIND,))
        keys = conn.execute(
            "SELECT DISTINCT params_key, tag, k_ahead FROM foreign_sell_escalate_score WHERE kind=?",
            (KIND,),
        ).fetchall()
        for pkey, tag, k in keys:
            for ls in ("all", "lead", "sync"):
                clauses = ["kind=?", "params_key=?", "tag=?", "k_ahead=?"]
                args: List[Any] = [KIND, pkey, tag, int(k)]
                if ls != "all":
                    clauses.append("lead_sync=?")
                    args.append(ls)
                where = " AND ".join(clauses)
                row = conn.execute(
                    f"""
                    SELECT
                      SUM(CASE WHEN verdict='hit' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='miss' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN verdict='pending' THEN 1 ELSE 0 END),
                      COUNT(DISTINCT CASE WHEN verdict IN ('hit','miss') THEN as_of END)
                    FROM foreign_sell_escalate_score WHERE {where}
                    """,
                    args,
                ).fetchone()
                hit, miss, pending, n_days = (
                    int(row[0] or 0),
                    int(row[1] or 0),
                    int(row[2] or 0),
                    int(row[3] or 0),
                )
                conn.execute(
                    """
                    INSERT INTO foreign_sell_escalate_rates(
                        kind, params_key, tag, lead_sync, k_ahead,
                        n, hit, miss, pending, n_days, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        pkey,
                        tag,
                        ls,
                        int(k),
                        hit + miss,
                        hit,
                        miss,
                        pending,
                        n_days,
                        now,
                    ),
                )
                out[f"{pkey}|{tag}|{ls}|k{k}"] = {
                    "n": hit + miss,
                    "hit": hit,
                    "miss": miss,
                    "pending": pending,
                    "n_days": n_days,
                }
        conn.commit()
    finally:
        conn.close()
    return out


def night_tick(market_db: str, as_of: str = "") -> Dict[str, Any]:
    """盤後：現況 n3 落檔＋下一版 n5 靜默落檔；有後窗才 score（失敗不擋）。"""
    day = _ymd(as_of)
    snap = snapshot_day(market_db, day, params=current_params())
    out: Dict[str, Any] = dict(snap or {})
    out["buy_signal"] = False
    try:
        nxt = snapshot_day(market_db, day or out.get("as_of") or "", params=next_silent_params())
        out["next_silent"] = {
            "params_key": (nxt or {}).get("params_key") or next_silent_params().key(),
            "n_lit": int((nxt or {}).get("n_lit") or 0),
        }
    except Exception as e:
        out["next_silent_error"] = str(e)[:160]
    try:
        # 只對現況 params score；下一版離線／後續再對，避免夜盤過慢
        scored = score_pending(market_db, params=current_params())
        rates = recompute_rates(market_db)
        out["scored"] = int(scored or 0)
        out["rates_keys"] = len(rates or {})
    except Exception as e:
        out["score_error"] = str(e)[:160]
    return out


def gate_status(db_path: str) -> Dict[str, Any]:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT n_days, n, hit FROM foreign_sell_escalate_rates
            WHERE kind=? AND lead_sync='lead'
            ORDER BY updated_at DESC LIMIT 1
            """,
            (KIND,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    n_days = int(row[0] or 0) if row else 0
    return {
        "kind": KIND,
        "n_days": n_days,
        "min_n": MIN_UNIQUE_DAYS,
        "ready_to_observe": n_days >= MIN_UNIQUE_DAYS,
        "buy_signal": False,
        "promote_golden_buy": False,
        "promote_leave_zero": False,
        "units": units_banner(),
    }


def optimize_status_one_liner(db_path: str) -> str:
    g = gate_status(db_path)
    if g["n_days"] < MIN_UNIQUE_DAYS:
        return (
            f"小賣→大賣：獨立日 n={g['n_days']}/{MIN_UNIQUE_DAYS}，未過閘；"
            f"只觀察、非買訊（單位張）"
        )
    return (
        f"小賣→大賣：獨立日 n={g['n_days']}，"
        f"{'可談觀察形' if g['ready_to_observe'] else '未過閘'}；非買訊、不改黃金買點"
    )
