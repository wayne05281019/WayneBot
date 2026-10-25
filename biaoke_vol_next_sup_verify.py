# -*- coding: utf-8 -*-
"""破大量區撐 → 下一撐到達率／續跌・靜默對質骨架（D4；非買訊）。

事件＝收盤跌破近窗大量區撐（盤中刺穿不算）。
NEXT＝通道平行撐／次大量區／原文目標／近窗樞紐低（見 biaoke_next_support）。
指標：下一撐到達率（前瞻窗低觸及 NEXT）、續跌機率（收＜事件收）、附 h1／h3／h5。
分軌 kind＝biaoke_vol_next_sup；勝率不准混海選／黃金買點。
n≥20 獨立交易日且贏基線才談上臉；本檔只落檔＋算率，不改買訊。
失敗不擋出卡。過程／％不准進對話。Asia/Taipei。
記憶體：逐檔串流；一次只握一根股票的日 K 窗；重活避開 06:30／16:30／DC 03–04。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from biaoke_next_support import (
    NONE_LABEL,
    close_broke_vol_support,
    resolve_next_support,
)
from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "biaoke_vol_next_sup"
VARIANT_WITH_NEXT = "with_next"  # 有 NEXT 候選
VARIANT_NO_NEXT = "no_next"  # 暫無下一官方結構撐（基線對照）
TRACK_VARIANTS = (VARIANT_WITH_NEXT, VARIANT_NO_NEXT)
FORWARD_H = (1, 3, 5)
LOOKBACK_BARS = 80  # 近窗＋前瞻緩衝；逐檔載入
MAX_FORWARD = 5
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
# 重活避開話筒尖峰（台北）
BUSY_WINDOWS_HHMM = (
    (630, 700),  # 海選早報
    (1630, 1700),  # 盤後融合
    (300, 400),  # DC 情境夜窗
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _num(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _taipei_hhmm() -> int:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime

        now = datetime.now(ZoneInfo("Asia/Taipei"))
        return int(now.hour) * 100 + int(now.minute)
    except Exception:
        return -1


def in_busy_window(hhmm: Optional[int] = None) -> bool:
    """重活尖峰：06:30／16:30／DC 03–04（台北）。"""
    t = int(hhmm if hhmm is not None else _taipei_hhmm())
    if t < 0:
        return False
    for a, b in BUSY_WINDOWS_HHMM:
        if int(a) <= t < int(b):
            return True
    return False


def _conn(db_path: str):
    return sqlite3.connect(db_path, timeout=12.0)


def ensure_tables(db_path: str) -> None:
    """事件＋前瞻結果表；輕量，可與 tape 同碟。"""
    path = str(db_path or "").strip()
    if not path:
        return
    store = tape_store_path(path) if os.path.isfile(path) else path
    con = _conn(store)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS biaoke_vol_next_sup_events (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                broken_lo REAL,
                close REAL,
                next_source TEXT,
                next_price REAL,
                next_label TEXT,
                spike_date TEXT,
                o REAL, h REAL, l REAL, c REAL, v REAL,
                PRIMARY KEY (as_of, stock_id, variant)
            );
            CREATE TABLE IF NOT EXISTS biaoke_vol_next_sup_outcomes (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                hit_next INTEGER,
                cont_down INTEGER,
                ret REAL,
                min_low REAL,
                done INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (as_of, stock_id, variant, horizon)
            );
            CREATE INDEX IF NOT EXISTS idx_bvns_events_day
                ON biaoke_vol_next_sup_events(as_of);
            """
        )
        con.commit()
    finally:
        con.close()


def list_stock_ids(db_path: str, *, limit: int = 0) -> List[str]:
    """活躍股票／KY；擋 ETF。limit=0 ＝全取（呼叫端應分批）。"""
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT stock_id FROM stock_universe
            WHERE COALESCE(active,1)=1
              AND UPPER(COALESCE(security_type,'')) IN ('STOCK','','KY')
              AND UPPER(COALESCE(security_type,'')) NOT LIKE '%ETF%'
            ORDER BY stock_id
            """
        ).fetchall()
    except sqlite3.Error:
        try:
            rows = con.execute(
                "SELECT DISTINCT stock_id FROM daily_quotes ORDER BY stock_id"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        con.close()
    out = [str(r[0]).strip() for r in rows if r and str(r[0] or "").strip()]
    if limit and limit > 0:
        return out[: int(limit)]
    return out


def load_bars_thru(
    db_path: str,
    sid: str,
    as_of: str,
    *,
    need: int = LOOKBACK_BARS,
) -> List[Dict[str, Any]]:
    """單檔官方日 K 至 as_of（含）；量小窗，防 OOM。"""
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not sid or not day or not db_path:
        return []
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT date, open, high, low, close, volume, stock_name
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY replace(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (sid, day, int(need) + MAX_FORWARD + 5),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    out: List[Dict[str, Any]] = []
    for r in reversed(rows):
        out.append(
            {
                "date": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
                "stock_name": r[6],
                "stock_id": sid,
            }
        )
    return out


def _infer_channel(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        from biaoke_chart import infer_parallel_channel

        return dict(infer_parallel_channel(list(bars)[-60:]) or {})
    except Exception:
        return {}


def _spike_from_bars(bars: Sequence[Dict[str, Any]]) -> Tuple[float, str]:
    try:
        from biaoke_brain import volume_first_price

        st = volume_first_price(list(bars), lookback=min(40, len(bars)))
        return _num(st.get("spike_low")), _ymd(st.get("spike_date"))
    except Exception:
        return 0.0, ""


def event_for_bar(
    bars: Sequence[Dict[str, Any]],
    *,
    sid: str,
    as_of: str,
) -> Optional[Dict[str, Any]]:
    """若 as_of 收盤破大量區撐 → 事件列；否則 None。"""
    day = _ymd(as_of)
    rows = [r for r in bars if _ymd(r.get("date")) <= day]
    if len(rows) < 16:
        return None
    # 切到 as_of 當末日
    if _ymd(rows[-1].get("date")) != day:
        return None
    spike_lo, spike_d = _spike_from_bars(rows)
    close = _num(rows[-1].get("close"))
    if not close_broke_vol_support(close=close, support=spike_lo):
        return None
    # 前一日須未破（或剛破首日）：避免同一破撐重複記
    if len(rows) >= 2:
        prev_c = _num(rows[-2].get("close"))
        if close_broke_vol_support(close=prev_c, support=spike_lo):
            return None
    channel = _infer_channel(rows)
    pack = resolve_next_support(
        rows,
        sid=sid,
        close=close,
        support=spike_lo,
        spike_date=spike_d,
        channel=channel,
        under_support=True,
    )
    prim = pack.get("primary") or {}
    has_next = bool(prim and _num(prim.get("price")) > 0)
    variant = VARIANT_WITH_NEXT if has_next else VARIANT_NO_NEXT
    return {
        "as_of": day,
        "stock_id": str(sid).strip(),
        "variant": variant,
        "broken_lo": spike_lo,
        "close": close,
        "next_source": str(prim.get("source") or "") if has_next else "",
        "next_price": _num(prim.get("price")) if has_next else 0.0,
        "next_label": str(prim.get("label") or (pack.get("none_label") or NONE_LABEL)),
        "spike_date": spike_d,
        "o": _num(rows[-1].get("open")),
        "h": _num(rows[-1].get("high")),
        "l": _num(rows[-1].get("low")),
        "c": close,
        "v": _num(rows[-1].get("volume")),
        "candidates": list(pack.get("candidates") or []),
    }


def remember_event(db_path: str, event: Dict[str, Any]) -> None:
    if not event:
        return
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO biaoke_vol_next_sup_events (
                as_of, stock_id, variant, broken_lo, close,
                next_source, next_price, next_label, spike_date,
                o, h, l, c, v
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _ymd(event.get("as_of")),
                str(event.get("stock_id") or "").strip(),
                str(event.get("variant") or VARIANT_NO_NEXT),
                _num(event.get("broken_lo")),
                _num(event.get("close")),
                str(event.get("next_source") or ""),
                _num(event.get("next_price")),
                str(event.get("next_label") or ""),
                _ymd(event.get("spike_date")),
                _num(event.get("o")),
                _num(event.get("h")),
                _num(event.get("l")),
                _num(event.get("c")),
                _num(event.get("v")),
            ),
        )
        con.commit()
    finally:
        con.close()


def _forward_slice(
    db_path: str, sid: str, as_of: str, horizon: int
) -> List[Dict[str, Any]]:
    day = _ymd(as_of)
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')>?
            ORDER BY replace(CAST(date AS TEXT),'-','') ASC
            LIMIT ?
            """,
            (sid, day, int(horizon)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    return [
        {
            "date": r[0],
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5],
        }
        for r in rows
    ]


def score_event(
    db_path: str,
    event: Dict[str, Any],
    *,
    horizons: Sequence[int] = FORWARD_H,
) -> List[Dict[str, Any]]:
    """前瞻走完才記；不足根數 done=0。"""
    sid = str(event.get("stock_id") or "").strip()
    day = _ymd(event.get("as_of"))
    entry = _num(event.get("close"))
    next_px = _num(event.get("next_price"))
    out: List[Dict[str, Any]] = []
    for h in horizons:
        fwd = _forward_slice(db_path, sid, day, int(h))
        done = 1 if len(fwd) >= int(h) else 0
        hit = 0
        cont = 0
        ret = None
        min_low = None
        if fwd:
            lows = [_num(r.get("low")) for r in fwd]
            closes = [_num(r.get("close")) for r in fwd]
            min_low = min(lows) if lows else None
            if next_px > 0 and min_low is not None and min_low <= next_px + 1e-9:
                hit = 1
            last_c = closes[-1] if closes else 0.0
            if entry > 0 and last_c > 0:
                ret = (last_c / entry) - 1.0
                cont = 1 if last_c < entry else 0
        out.append(
            {
                "as_of": day,
                "stock_id": sid,
                "variant": str(event.get("variant") or ""),
                "horizon": int(h),
                "hit_next": hit,
                "cont_down": cont,
                "ret": ret,
                "min_low": min_low,
                "done": done,
            }
        )
    return out


def remember_outcomes(db_path: str, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        return
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        for r in rows:
            con.execute(
                """
                INSERT OR REPLACE INTO biaoke_vol_next_sup_outcomes (
                    as_of, stock_id, variant, horizon,
                    hit_next, cont_down, ret, min_low, done
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    _ymd(r.get("as_of")),
                    str(r.get("stock_id") or "").strip(),
                    str(r.get("variant") or ""),
                    int(r.get("horizon") or 0),
                    int(r.get("hit_next") or 0),
                    int(r.get("cont_down") or 0),
                    r.get("ret"),
                    r.get("min_low"),
                    int(r.get("done") or 0),
                ),
            )
        con.commit()
    finally:
        con.close()


def rates_summary(db_path: str) -> Dict[str, Any]:
    """分軌到達率／續跌；獨立日 n。過程％不准進對話——只給內部／閘用。"""
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        rows = con.execute(
            """
            SELECT variant, horizon,
                   COUNT(*) AS n,
                   SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) AS n_done,
                   SUM(CASE WHEN done=1 AND hit_next=1 THEN 1 ELSE 0 END) AS hits,
                   SUM(CASE WHEN done=1 AND cont_down=1 THEN 1 ELSE 0 END) AS downs,
                   COUNT(DISTINCT as_of) AS days
            FROM biaoke_vol_next_sup_outcomes
            GROUP BY variant, horizon
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    out: Dict[str, Any] = {"kind": KIND, "tracks": {}}
    for variant, horizon, n, n_done, hits, downs, days in rows:
        key = f"{variant}:h{horizon}"
        nd = int(n_done or 0)
        out["tracks"][key] = {
            "variant": variant,
            "horizon": int(horizon),
            "n": int(n or 0),
            "n_done": nd,
            "unique_days": int(days or 0),
            "hit_next_rate": (float(hits) / nd) if nd else None,
            "cont_down_rate": (float(downs) / nd) if nd else None,
            "gate_ready": int(days or 0) >= MIN_UNIQUE_DAYS,
        }
    return out


def scan_stock_history(
    db_path: str,
    sid: str,
    *,
    max_events: int = 40,
) -> int:
    """單檔歷史破撐事件＋已走完前瞻；回寫入筆數。"""
    bars = load_bars_thru(db_path, sid, "20991231", need=400)
    if len(bars) < 30:
        return 0
    n_wrote = 0
    # 從第 20 根起掃；逐日輕量
    for i in range(20, len(bars)):
        if n_wrote >= int(max_events):
            break
        window = bars[: i + 1]
        day = _ymd(window[-1].get("date"))
        ev = event_for_bar(window, sid=sid, as_of=day)
        if not ev:
            continue
        remember_event(db_path, ev)
        outs = score_event(db_path, ev)
        remember_outcomes(db_path, outs)
        n_wrote += 1
    return n_wrote


def run_skeleton(
    db_path: str,
    *,
    stock_ids: Optional[Sequence[str]] = None,
    limit_stocks: int = 30,
    max_events_per_stock: int = 20,
    skip_busy: bool = True,
) -> Dict[str, Any]:
    """記憶體安全骨架跑：預設少數檔；全市場請分批＋skip_busy。"""
    if skip_busy and in_busy_window():
        return {
            "ok": False,
            "skipped": "busy_window",
            "hhmm": _taipei_hhmm(),
            "kind": KIND,
        }
    ensure_tables(db_path)
    sids = list(stock_ids) if stock_ids else list_stock_ids(db_path, limit=limit_stocks)
    # 樣本錨：聯亞／奇鋐優先（有原文目標）
    prefer = ["3081", "3017"]
    ordered = []
    for p in prefer:
        if p in sids and p not in ordered:
            ordered.append(p)
    for s in sids:
        if s not in ordered:
            ordered.append(s)
    if limit_stocks > 0:
        ordered = ordered[: int(limit_stocks)]
    total = 0
    t0 = time.time()
    for sid in ordered:
        if skip_busy and in_busy_window():
            break
        total += scan_stock_history(
            db_path, sid, max_events=max_events_per_stock
        )
    summary = rates_summary(db_path)
    summary.update(
        {
            "ok": True,
            "events_written": total,
            "stocks": len(ordered),
            "elapsed_sec": round(time.time() - t0, 2),
            "kind": KIND,
        }
    )
    return summary


def snapshot_day(market_db: str, as_of: str = "", *, limit: int = 80) -> int:
    """當日破撐事件落檔（沒按也留）；回筆數。失敗吞掉。"""
    try:
        day = _ymd(as_of)
        if not day:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(market_db))
        if not day:
            return 0
        if in_busy_window():
            # 尖峰只記錨檔，不全掃
            sids = ["3081", "3017"]
        else:
            sids = list_stock_ids(market_db, limit=limit)
            for p in ("3081", "3017"):
                if p not in sids:
                    sids.insert(0, p)
        n = 0
        for sid in sids:
            bars = load_bars_thru(market_db, sid, day, need=LOOKBACK_BARS)
            ev = event_for_bar(bars, sid=sid, as_of=day)
            if not ev:
                continue
            remember_event(market_db, ev)
            remember_outcomes(market_db, score_event(market_db, ev))
            n += 1
        return n
    except Exception:
        return 0
