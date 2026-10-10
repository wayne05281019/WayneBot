# -*- coding: utf-8 -*-
"""查股結構／導航出圖精確度・靜默對質骨架（不是買訊）。

對質用官方柱數字，不產 PNG（碟規）。分軌：
  structure_levels ＝爆大量壓／撐／昨收／今收是否等於官方柱
  stance_rel       ＝查股落檔的 stance／rel_kind 是否與官方柱重算一致

按了才記（沒打代號＝沒名單）。失敗不擋出卡。過閘也不自動改黃金買點／海選／買訊。
Asia/Taipei；盤中未收不當收。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "lookup_chart"
VARIANT_STRUCTURE = "structure_levels"
VARIANT_STANCE = "stance_rel"
TRACK_VARIANTS = (VARIANT_STRUCTURE, VARIANT_STANCE)
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
# 價差容差（跳動／浮點）；萬元股 5 元跳動
_PRICE_EPS = 0.51


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


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
            CREATE TABLE IF NOT EXISTS lookup_chart_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                variant TEXT NOT NULL,
                name TEXT DEFAULT '',
                close REAL,
                press REAL,
                hold REAL,
                prev_close REAL,
                stance TEXT DEFAULT '',
                rel_kind TEXT DEFAULT '',
                ok INTEGER NOT NULL DEFAULT 0,
                detail TEXT DEFAULT '',
                ran_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, as_of, sid, variant)
            );
            CREATE TABLE IF NOT EXISTS lookup_chart_rates (
                kind TEXT NOT NULL,
                variant TEXT NOT NULL,
                n_days INTEGER NOT NULL DEFAULT 0,
                n_rows INTEGER NOT NULL DEFAULT 0,
                ok_rate REAL,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, variant)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def _load_bars(db_path: str, sid: str, as_of: str, need: int = 80) -> List[Dict[str, Any]]:
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not sid or not day or not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=12.0)
    try:
        rows = conn.execute(
            """
            SELECT date, stock_name, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY replace(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (sid, day, need),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for date, name, o, h, l, c, v in reversed(rows):
        out.append(
            {
                "date": date,
                "stock_name": name,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return out


def structure_levels_from_bars(bars: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """與結構圖同一套：近窗有效爆大量日高低＝壓／撐；昨收／今收取官方柱。"""
    if not bars or len(bars) < 3:
        return None
    from biaoke_brain import volume_first_price

    struct = volume_first_price(list(bars), lookback=min(40, len(bars)))
    if not struct:
        return None
    last = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else {}
    press = _f(struct.get("spike_high"))
    hold = _f(struct.get("spike_low"))
    close = _f(last.get("close"))
    prev_c = _f(prev.get("close"))
    if press is None or hold is None or close is None:
        return None
    return {
        "press": press,
        "hold": hold,
        "close": close,
        "prev_close": prev_c,
        "spike_date": _ymd(struct.get("spike_date") or struct.get("date")),
        "name": str(last.get("stock_name") or ""),
    }


def _price_match(a: Optional[float], b: Optional[float], eps: float = _PRICE_EPS) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= float(eps)


def verify_structure_levels(db_path: str, sid: str, as_of: str) -> Dict[str, Any]:
    """壓／撐必須等於官方 spike 日高／低；今收／昨收等於官方柱。"""
    bars = _load_bars(db_path, sid, as_of)
    levels = structure_levels_from_bars(bars)
    if not levels:
        return {"ok": False, "reason": "no_bars"}
    spike_day = _ymd(levels.get("spike_date"))
    spike_bar = None
    for b in bars:
        if _ymd(b.get("date")) == spike_day:
            spike_bar = b
            break
    if spike_bar is None:
        return {"ok": False, "reason": "spike_bar_missing", **levels}
    hi = _f(spike_bar.get("high"))
    lo = _f(spike_bar.get("low"))
    last = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else {}
    press_ok = _price_match(levels["press"], hi)
    hold_ok = _price_match(levels["hold"], lo)
    close_ok = _price_match(levels["close"], _f(last.get("close")))
    prev_ok = (
        levels.get("prev_close") is None
        or _price_match(levels.get("prev_close"), _f(prev.get("close")))
    )
    ok = bool(press_ok and hold_ok and close_ok and prev_ok)
    return {
        "ok": ok,
        "press": levels["press"],
        "hold": levels["hold"],
        "close": levels["close"],
        "prev_close": levels.get("prev_close"),
        "name": levels.get("name") or "",
        "press_ok": press_ok,
        "hold_ok": hold_ok,
        "close_ok": close_ok,
        "prev_ok": prev_ok,
        "spike_date": spike_day,
    }


def verify_stance_rel(
    db_path: str, sid: str, as_of: str, *, stored_stance: str = "", stored_rel: str = ""
) -> Dict[str, Any]:
    """重算 stance_kind／rel_kind，對齊查股落檔（不准當買訊改碼）。"""
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    out: Dict[str, Any] = {
        "ok": False,
        "stance": "",
        "rel_kind": "",
        "stored_stance": str(stored_stance or ""),
        "stored_rel": str(stored_rel or ""),
    }
    if not sid or not day:
        out["reason"] = "bad_args"
        return out
    try:
        from wayne_navigator import NavigatorEngine

        eng = NavigatorEngine(db_path)
        card = eng.get_decision_card(sid, merge_live=False)
    except Exception as e:
        out["reason"] = f"card_err:{e}"
        return out
    if not card or card.get("error"):
        out["reason"] = "no_card"
        return out
    stance = str(card.get("stance_kind") or "")
    rel = str(card.get("relative_buy_kind") or "")
    out["stance"] = stance
    out["rel_kind"] = rel
    out["close"] = _f(card.get("close"))
    out["name"] = str(card.get("name") or card.get("stock_name") or "")
    # 沒有舊值＝只落檔；有舊值才比對
    if not stored_stance and not stored_rel:
        out["ok"] = True
        out["reason"] = "snapshot_only"
        return out
    stance_ok = (not stored_stance) or (stance == stored_stance)
    rel_ok = (not stored_rel) or (rel == stored_rel)
    out["ok"] = bool(stance_ok and rel_ok)
    out["stance_ok"] = stance_ok
    out["rel_ok"] = rel_ok
    return out


def _recent_lookup_rows(market_db: str, as_of: str, *, limit: int = 40) -> List[Dict[str, Any]]:
    """從 live_judge 取查股列（按了才有）。"""
    from judge_tape import store_path

    day = _ymd(as_of)
    store = store_path(market_db)
    if not day or not os.path.isfile(store):
        return []
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT as_of, sid, name, px, pick, extra
            FROM live_judge
            WHERE kind='lookup' AND as_of=?
            ORDER BY ran_at DESC
            LIMIT ?
            """,
            (day, int(limit)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for as_of_r, sid, name, px, pick, extra in rows:
        stance = ""
        rel = ""
        try:
            blob = json.loads(extra) if extra else {}
            if isinstance(blob, dict):
                stance = str(blob.get("stance") or "")
                rel = str(blob.get("rel_kind") or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            blob = {}
        if not rel and pick and str(pick) != stance:
            # remember_rows pick＝rel_kind or stance_kind
            rel = str(pick)
        elif not stance and pick:
            stance = str(pick)
        out.append(
            {
                "as_of": _ymd(as_of_r),
                "sid": str(sid or ""),
                "name": str(name or ""),
                "close": _f(px),
                "stance": stance,
                "rel_kind": rel,
            }
        )
    return out


def remember_chart_row(
    db_path: str,
    as_of: str,
    sid: str,
    variant: str,
    *,
    name: str = "",
    close: Optional[float] = None,
    press: Optional[float] = None,
    hold: Optional[float] = None,
    prev_close: Optional[float] = None,
    stance: str = "",
    rel_kind: str = "",
    ok: bool = False,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO lookup_chart_tape(
                kind, as_of, sid, variant, name, close, press, hold, prev_close,
                stance, rel_kind, ok, detail, ran_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                KIND,
                _ymd(as_of),
                str(sid),
                str(variant),
                str(name or ""),
                close,
                press,
                hold,
                prev_close,
                str(stance or ""),
                str(rel_kind or ""),
                1 if ok else 0,
                json.dumps(detail or {}, ensure_ascii=False),
                _now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def recompute_rates(db_path: str) -> None:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute("DELETE FROM lookup_chart_rates WHERE kind=?", (KIND,))
        rows = conn.execute(
            """
            SELECT variant,
                   COUNT(DISTINCT as_of) AS n_days,
                   COUNT(*) AS n_rows,
                   AVG(ok) AS ok_rate
            FROM lookup_chart_tape
            WHERE kind=?
            GROUP BY variant
            """,
            (KIND,),
        ).fetchall()
        now = _now_iso()
        for variant, n_days, n_rows, ok_rate in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO lookup_chart_rates(
                    kind, variant, n_days, n_rows, ok_rate, updated_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    KIND,
                    str(variant),
                    int(n_days or 0),
                    int(n_rows or 0),
                    float(ok_rate or 0),
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def snapshot_day(market_db: str, as_of: str = "") -> Dict[str, Any]:
    """對當日查股列跑結構／stance 對質並落檔。空名單不算。"""
    from judge_tape import _as_of

    day = _ymd(as_of) or _as_of(market_db, as_of)
    out = {"as_of": day, "n": 0, "structure_ok": 0, "stance_ok": 0}
    if not day:
        return out
    rows = _recent_lookup_rows(market_db, day)
    if not rows:
        return out
    for row in rows:
        sid = str(row.get("sid") or "")
        if not sid:
            continue
        st = verify_structure_levels(market_db, sid, day)
        remember_chart_row(
            market_db,
            day,
            sid,
            VARIANT_STRUCTURE,
            name=str(st.get("name") or row.get("name") or ""),
            close=_f(st.get("close") if st.get("close") is not None else row.get("close")),
            press=_f(st.get("press")),
            hold=_f(st.get("hold")),
            prev_close=_f(st.get("prev_close")),
            ok=bool(st.get("ok")),
            detail={k: st.get(k) for k in ("press_ok", "hold_ok", "close_ok", "prev_ok", "spike_date", "reason") if k in st},
        )
        if st.get("ok"):
            out["structure_ok"] += 1
        sr = verify_stance_rel(
            market_db,
            sid,
            day,
            stored_stance=str(row.get("stance") or ""),
            stored_rel=str(row.get("rel_kind") or ""),
        )
        remember_chart_row(
            market_db,
            day,
            sid,
            VARIANT_STANCE,
            name=str(sr.get("name") or row.get("name") or ""),
            close=_f(sr.get("close") if sr.get("close") is not None else row.get("close")),
            stance=str(sr.get("stance") or ""),
            rel_kind=str(sr.get("rel_kind") or ""),
            ok=bool(sr.get("ok")),
            detail={
                k: sr.get(k)
                for k in ("stance_ok", "rel_ok", "stored_stance", "stored_rel", "reason")
                if k in sr
            },
        )
        if sr.get("ok"):
            out["stance_ok"] += 1
        out["n"] += 1
    recompute_rates(market_db)
    return out


def gate_status(market_db: str) -> Dict[str, Any]:
    """明確優化狀態。本軌永不自動改買訊／話筒。"""
    store = ensure_tables(market_db)
    by: Dict[str, Dict[str, Any]] = {}
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT variant, n_days, n_rows, ok_rate FROM lookup_chart_rates WHERE kind=?",
            (KIND,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for variant, n_days, n_rows, ok_rate in rows:
        by[str(variant)] = {
            "n_days": int(n_days or 0),
            "n_rows": int(n_rows or 0),
            "ok_rate": float(ok_rate) if ok_rate is not None else None,
        }
    n = max((int(v.get("n_days") or 0) for v in by.values()), default=0)
    n_ok = n >= MIN_UNIQUE_DAYS
    return {
        "kind": KIND,
        "n_days": n,
        "n_ok": n_ok,
        "min_n": MIN_UNIQUE_DAYS,
        "by_variant": by,
        "promote_buy_signals": False,
        "promote_ready": False,
        "gate_ready_for_review": bool(n_ok),
        "note": (
            "獨立日 n 夠 → 僅可複審出圖精確度；不准自動改黃金買點／海選／買訊"
            if n_ok
            else "繼續收集／尚未改碼；查股結構／導航精確度靜默對質中"
        ),
    }


def night_tick(market_db: str, as_of: str = "") -> Dict[str, Any]:
    """接默默落檔節奏。失敗吞掉。"""
    out: Dict[str, Any] = {"snap": {}, "gate": {}}
    try:
        out["snap"] = snapshot_day(market_db, as_of)
        out["gate"] = gate_status(market_db)
    except Exception:
        return out
    return out


def optimize_status_one_liner(market_db: str) -> str:
    g = gate_status(market_db)
    n = int(g.get("n_days") or 0)
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    if n < need:
        return f"查股結構／導航精確度靜默對質：n={n}/{need}，繼續收集／尚未改碼。"
    return (
        f"查股結構／導航精確度靜默對質：n≥{need} 可複審；"
        "未自動改黃金買點／海選／買訊。"
    )
