# -*- coding: utf-8 -*-
"""默默畫、覆盤、檢討。不到能講的那天不准開口。

大盤／洞燭／海選／AI倉各做各的、各自對質、勝率不准混。
AI倉假錢對照組保留。不推話筒、不改黃金買點、現在不在話筒發明 5／9。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

_CTX_DDL = """
CREATE TABLE IF NOT EXISTS silent_review_ctx (
    as_of TEXT PRIMARY KEY,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
"""

_US_KEEP = (
    "as_of",
    "ixic_pct",
    "sox_pct",
    "dji_pct",
    "spx_pct",
    "vix",
    "tsm_pct",
    "nvda_pct",
    "nq_f_pct",
    "regime",
    "brent_px",
    "brent_pct",
    "dx_f_px",
    "dx_f_pct",
    "usdtwd_px",
    "usdtwd_pct",
)
_TWII_KEEP = ("date", "open", "high", "low", "close", "volume")
_FUT_KEEP = ("date", "symbol", "session", "open", "high", "low", "close", "pct_change")
_BIAOKE_KEEP = ("tag", "direc", "date")

# 覆盤要的欄：缺完整官方收可以之後補；盤中未收不准凍。
REVIEW_SLOTS = ("twii", "biaoke", "legs", "tx_day", "tx_night", "te_day", "te_night", "us")
REVIEW_STEPS = (
    "complete_as_of",
    "score_old",
    "freeze_twii",
    "freeze_biaoke",
    "freeze_legs",
    "freeze_tx_day",
    "freeze_tx_night",
    "freeze_te_day",
    "freeze_te_night",
    "freeze_us",
    "write_pack",
    "record_forecast",
    "never_speak",
)

# 現在還沒到：神經元還沒對上飆大，話筒不准畫 5／9，也不准主動講大盤預測。
WAVE_NEURONS_MATCH = False
SPEAK_MIN_N = 20


def speak_ready(kind: str, db_path: str = "") -> bool:
    """能講的那天才 True。現在大盤／洞燭／黃金買點都還不准主動講。"""
    k = str(kind or "").strip()
    if k == "twii":
        return bool(WAVE_NEURONS_MATCH) and _forecast_n(db_path, "twii") >= SPEAK_MIN_N
    if k == "dongzhu":
        return False
    if k in {"leave_zero", "golden_buy"}:
        return False
    return False


def speak_line(
    *,
    path: str,
    level: str,
    maybe: str,
    prep: str,
    because: str,
    result: str,
) -> str:
    """能講的那天用這句。現在呼叫端拿不到，因為 speak_ready 仍是假。"""
    return (
        f"預計大盤走勢會是{path}，到{level}有可能會發生{maybe}，"
        f"所以建議現在要提前{prep}，因為依照{because}的觀察和分析，"
        f"得到預測結果可能會是{result}。"
    )


def maybe_speak(kind: str, db_path: str = "") -> str:
    """不到能講的那天回空字。不准推話筒。"""
    if not speak_ready(kind, db_path):
        return ""
    return ""


def simulate_next_legs(
    last_tag: str,
    last_close: float,
    rays: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """每一段還沒走完的走法。只沿他自己點過的水平，不准補新價、不准發明段號。"""
    out: List[Dict[str, Any]] = []
    seen = set()
    for r in rays or []:
        try:
            y = float(r.get("y") or 0)
        except (TypeError, ValueError):
            continue
        if y <= 0:
            continue
        lab = str(r.get("label") or r.get("kind") or "").strip()
        key = (round(y, 2), lab)
        if key in seen:
            continue
        seen.add(key)
        out.append({"y": y, "lab": lab, "kind": str(r.get("kind") or "")})
    tag = str(last_tag or "")
    if not out and last_close > 0:
        if any(k in tag for k in ("逃命波C-2", "C-3", "C-1", "細微波主跌", "大A-c", "C-5低點")):
            out.append({"y": 43500.0, "lab": "最差43500", "kind": "worst"})
        if "C-5低點" in tag:
            out.append({"y": 45398.43, "lab": "C-5若守45398", "kind": "fork"})
        elif any(k in tag for k in ("第五波測底", "修正末端", "頭肩底", "逃命波C-2", "C-3")):
            out.append({"y": 45839.36, "lab": "若守45839", "kind": "fork"})
    return out


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _num(val: Any) -> Optional[float]:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    return n


def _pick(row: Optional[Dict[str, Any]], keys: Sequence[str]) -> Dict[str, Any]:
    if not row:
        return {}
    out: Dict[str, Any] = {}
    for k in keys:
        v = row.get(k)
        if v is None or v == "":
            continue
        if k.endswith("_pct") or k in {"close", "high", "low", "open", "volume", "vix"}:
            n = _num(v)
            if n is None:
                continue
            out[k] = n
        else:
            out[k] = v
    return out


def _fill_missing(old: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    """已凍的數不准改；缺的欄才補，事後覆盤才不用重抓。"""
    out = dict(old or {})
    for k, v in (fresh or {}).items():
        if v in (None, "", {}, []):
            continue
        if isinstance(v, dict):
            out[k] = _fill_missing(out.get(k) if isinstance(out.get(k), dict) else {}, v)
        elif k not in out or out.get(k) in (None, "", {}, []):
            out[k] = v
    return out


def _store_path(market_db: str) -> str:
    """默默覆盤寫另一顆檔，不進行情庫、不進公開 zip、不跟查股海選共用表。"""
    path = os.path.abspath(str(market_db or "data/wayne_market.db"))
    root = os.path.dirname(path) or "."
    name = os.path.basename(path)
    if name == "wayne_evolve.db":
        return path
    return os.path.join(root, "wayne_evolve.db")


def ensure_review_ctx(db_path: str) -> None:
    store = _store_path(db_path)
    if not store:
        return
    parent = os.path.dirname(os.path.abspath(store))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(store, timeout=30.0)
    try:
        conn.executescript(_CTX_DDL)
        conn.commit()
    finally:
        conn.close()


def load_review_context(db_path: str, as_of: str) -> Dict[str, Any]:
    day = _ymd(as_of)
    store = _store_path(db_path)
    if not store or not os.path.isfile(store) or not day:
        return {}
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT payload FROM silent_review_ctx WHERE as_of=?", (day,)
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row:
        return {}
    try:
        data = json.loads(row[0] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def pack_holes(ctx: Optional[Dict[str, Any]]) -> List[str]:
    """覆盤前先看缺哪一欄。缺的跳過，不准補。"""
    pack = ctx or {}
    missing: List[str] = []
    tw = pack.get("twii") if isinstance(pack.get("twii"), dict) else {}
    if not tw.get("close"):
        missing.append("twii")
    bk = pack.get("biaoke") if isinstance(pack.get("biaoke"), dict) else {}
    if not (bk.get("tag") or bk.get("direc")):
        missing.append("biaoke")
    legs = pack.get("legs") if isinstance(pack.get("legs"), list) else []
    if not legs:
        missing.append("legs")
    for slot in ("tx_day", "tx_night", "te_day", "te_night"):
        row = pack.get(slot) if isinstance(pack.get(slot), dict) else {}
        if not row.get("close"):
            missing.append(slot)
    us = pack.get("us") if isinstance(pack.get("us"), dict) else {}
    if not any(us.get(k) is not None for k in ("ixic_pct", "sox_pct", "tsm_pct", "dji_pct", "spx_pct")):
        missing.append("us")
    return missing


def _read_live_context(db_path: str, as_of: str) -> Dict[str, Any]:
    """只讀已經進庫的官方欄。沒有就不寫。不准現場打外網。"""
    day = _ymd(as_of)
    out: Dict[str, Any] = {"as_of": day} if day else {}
    if not db_path or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        for sym, sess, key in (
            ("TX", "regular", "tx_day"),
            ("TX", "night", "tx_night"),
            ("TE", "regular", "te_day"),
            ("TE", "night", "te_night"),
        ):
            try:
                if day:
                    row = conn.execute(
                        """
                        SELECT date, symbol, session, open, high, low, close, pct_change
                        FROM futures_daily
                        WHERE symbol=? AND session=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                        ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1
                        """,
                        (sym, sess, day),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        SELECT date, symbol, session, open, high, low, close, pct_change
                        FROM futures_daily
                        WHERE symbol=? AND session=?
                        ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1
                        """,
                        (sym, sess),
                    ).fetchone()
            except sqlite3.Error:
                row = None
            if not row:
                continue
            bit = _pick(
                {
                    "date": row[0],
                    "symbol": row[1],
                    "session": row[2],
                    "open": row[3],
                    "high": row[4],
                    "low": row[5],
                    "close": row[6],
                    "pct_change": row[7],
                },
                _FUT_KEEP,
            )
            if bit.get("close"):
                out[key] = bit
        try:
            tw = None
            if day:
                tw = conn.execute(
                    """
                    SELECT date, open, high, low, close, volume
                    FROM index_daily
                    WHERE (symbol='TWII' OR symbol='^TWII')
                      AND REPLACE(CAST(date AS TEXT),'-','')=?
                    LIMIT 1
                    """,
                    (day,),
                ).fetchone()
            if tw:
                tw_b = _pick(
                    {
                        "date": tw[0],
                        "open": tw[1],
                        "high": tw[2],
                        "low": tw[3],
                        "close": tw[4],
                        "volume": tw[5],
                    },
                    _TWII_KEEP,
                )
                if tw_b.get("close"):
                    out["twii"] = tw_b
        except sqlite3.Error:
            pass
        us_row = None
        try:
            if day:
                us_row = conn.execute(
                    "SELECT as_of, ixic_pct, sox_pct, dji_pct, spx_pct, vix, "
                    "tsm_pct, nvda_pct, nq_f_pct, regime FROM us_overnight WHERE as_of=?",
                    (day,),
                ).fetchone()
            if not us_row:
                us_row = conn.execute(
                    "SELECT as_of, ixic_pct, sox_pct, dji_pct, spx_pct, vix, "
                    "tsm_pct, nvda_pct, nq_f_pct, regime FROM us_overnight "
                    "ORDER BY as_of DESC LIMIT 1"
                ).fetchone()
        except sqlite3.Error:
            us_row = None
        if us_row:
            us_b = _pick(
                {
                    "as_of": us_row[0],
                    "ixic_pct": us_row[1],
                    "sox_pct": us_row[2],
                    "dji_pct": us_row[3],
                    "spx_pct": us_row[4],
                    "vix": us_row[5],
                    "tsm_pct": us_row[6],
                    "nvda_pct": us_row[7],
                    "nq_f_pct": us_row[8],
                    "regime": us_row[9],
                },
                _US_KEEP,
            )
            try:
                pay_row = None
                if day:
                    pay_row = conn.execute(
                        "SELECT payload FROM us_overnight WHERE as_of=?",
                        (day,),
                    ).fetchone()
                if not pay_row:
                    pay_row = conn.execute(
                        "SELECT payload FROM us_overnight ORDER BY as_of DESC LIMIT 1"
                    ).fetchone()
                extra = json.loads((pay_row[0] if pay_row else "") or "{}")
            except (sqlite3.Error, TypeError, json.JSONDecodeError):
                extra = {}
            if isinstance(extra, dict):
                for key in (
                    "brent_px",
                    "brent_pct",
                    "dx_f_px",
                    "dx_f_pct",
                    "usdtwd_px",
                    "usdtwd_pct",
                ):
                    if extra.get(key) is not None:
                        us_b[key] = extra.get(key)
            if us_b:
                out["us"] = us_b
    finally:
        conn.close()
    return out


def capture_review_context(
    db_path: str,
    as_of: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按 REVIEW_STEPS 把覆盤要的欄一次凍住。已有的數不重抓不覆蓋；缺的記在 holes。"""
    if not db_path:
        return {}
    day = _ymd(as_of)
    if not day:
        try:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(db_path))
        except Exception:
            day = ""
    if not day:
        return {}
    ensure_review_ctx(db_path)
    old = load_review_context(db_path, day)
    fresh = _read_live_context(db_path, day)
    extras = extra if isinstance(extra, dict) else {}
    for key in REVIEW_SLOTS:
        if extras.get(key) in (None, "", {}, []):
            continue
        fresh[key] = extras[key]
    merged = _fill_missing(old, fresh)
    if not merged.get("as_of"):
        merged["as_of"] = day
    core = {k: v for k, v in merged.items() if k not in {"holes", "steps"}}
    old_core = {k: v for k, v in old.items() if k not in {"holes", "steps"}}
    merged["holes"] = pack_holes(core)
    merged["steps"] = list(REVIEW_STEPS)
    if old and core == old_core:
        return {**old, "holes": merged["holes"], "steps": merged["steps"]}
    store = _store_path(db_path)
    conn = sqlite3.connect(store, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO silent_review_ctx(as_of, payload, created_at)
            VALUES (?,?,?)
            """,
            (day, json.dumps(merged, ensure_ascii=False, separators=(",", ":")), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return merged


def night_review(db_path: str, cap: str = "") -> Dict[str, Any]:
    """台北 01:00 按 REVIEW_STEPS 走完。缺欄跳過。不推話筒、不主動講。"""
    stats: Dict[str, Any] = {
        "twii": 0,
        "try": 0,
        "scored": 0,
        "dongzhu": 0,
        "screen": 0,
        "ai": 0,
        "ctx": 0,
        "holes": [],
        "speak": False,
        "step": "",
    }
    if not db_path:
        stats["step"] = "complete_as_of"
        return stats
    stats["step"] = "score_old"
    try:
        from biaoke_forecast import snapshot_and_score_twii

        stats["step"] = "record_forecast"
        got = snapshot_and_score_twii(db_path, cap) or {}
        stats["twii"] = int(got.get("twii") or 0)
        stats["try"] = int(got.get("try") or 0)
        stats["scored"] = int(got.get("scored") or 0)
        day = str(got.get("cap") or cap or "")
    except Exception:
        day = str(cap or "")
        got = {}
    stats["step"] = "write_pack"
    try:
        ctx = load_review_context(db_path, day) if day else {}
        if not ctx:
            ctx = capture_review_context(db_path, day or cap)
        stats["ctx"] = 1 if ctx else 0
        stats["holes"] = list(ctx.get("holes") or pack_holes(ctx))
    except Exception:
        pass
    stats["step"] = "never_speak"
    stats["speak"] = bool(
        speak_ready("twii", db_path)
        or speak_ready("dongzhu", db_path)
        or speak_ready("leave_zero", db_path)
    )
    return stats


def _forecast_n(db_path: str, kind: str) -> int:
    store = _store_path(db_path)
    if not store or not os.path.isfile(store):
        return 0
    qkind = "twii_try" if str(kind or "") == "twii" else str(kind or "")
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM biaoke_forecast WHERE kind=? AND check_n>=horizon AND horizon>0",
            (qkind,),
        ).fetchone()
        return int(row[0] if row else 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
