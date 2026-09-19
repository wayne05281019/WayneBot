# -*- coding: utf-8 -*-
"""默默畫、覆盤、檢討。不到能講的那天不准開口。

大盤／洞燭／黃金買點各做各的。不推話筒、不改黃金買點、現在不在話筒發明 5／9。
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
)
_FUT_KEEP = ("date", "symbol", "session", "close", "high", "low", "pct_change")

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
        if k.endswith("_pct") or k in {"close", "high", "low", "vix"}:
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


def ensure_review_ctx(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_CTX_DDL)
        conn.commit()
    finally:
        conn.close()


def load_review_context(db_path: str, as_of: str) -> Dict[str, Any]:
    day = _ymd(as_of)
    if not db_path or not os.path.isfile(db_path) or not day:
        return {}
    conn = sqlite3.connect(db_path, timeout=8.0)
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


def _read_live_context(db_path: str, as_of: str) -> Dict[str, Any]:
    """只讀已經進庫的官方欄。沒有就不寫。不准現場打外網。"""
    day = _ymd(as_of)
    out: Dict[str, Any] = {"as_of": day} if day else {}
    if not db_path or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        for sym, key in (("TX", "tx_night"), ("TE", "te_night")):
            try:
                if day:
                    row = conn.execute(
                        """
                        SELECT date, symbol, session, close, high, low, pct_change
                        FROM futures_daily
                        WHERE symbol=? AND session='night' AND REPLACE(CAST(date AS TEXT),'-','')<=?
                        ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1
                        """,
                        (sym, day),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        SELECT date, symbol, session, close, high, low, pct_change
                        FROM futures_daily
                        WHERE symbol=? AND session='night'
                        ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1
                        """,
                        (sym,),
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
                    "close": row[3],
                    "high": row[4],
                    "low": row[5],
                    "pct_change": row[6],
                },
                _FUT_KEEP,
            )
            if bit.get("close"):
                out[key] = bit
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
            if us_b:
                out["us"] = us_b
    finally:
        conn.close()
    return out


def capture_review_context(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """當下把夜盤／美指／美股已進庫的數凍住，給之後覆盤。已有的數不重抓不覆蓋。"""
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
    merged = _fill_missing(old, fresh)
    if not merged.get("as_of"):
        merged["as_of"] = day
    if merged == old:
        return old
    conn = sqlite3.connect(db_path, timeout=30.0)
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
    """台北 02:00：覆盤官方柱、對他的畫、再試畫明天。不推話筒、不主動講。"""
    stats: Dict[str, Any] = {
        "twii": 0,
        "try": 0,
        "scored": 0,
        "dongzhu": 0,
        "ctx": 0,
        "speak": False,
    }
    if not db_path:
        return stats
    try:
        ctx = capture_review_context(db_path, cap)
        stats["ctx"] = 1 if ctx else 0
    except Exception:
        pass
    try:
        from biaoke_forecast import snapshot_and_score_twii, verify_due

        try:
            verify_due(db_path)
        except Exception:
            pass
        got = snapshot_and_score_twii(db_path, cap) or {}
        stats["twii"] = int(got.get("twii") or 0)
        stats["try"] = int(got.get("try") or 0)
        stats["scored"] = int(got.get("scored") or 0)
    except Exception:
        pass
    try:
        from dongzhu_tape import snapshot_and_score_dongzhu
        from import_health import latest_complete_quote_date

        day = str(cap or latest_complete_quote_date(db_path) or "").replace("-", "")[:8]
        if day:
            dz = snapshot_and_score_dongzhu(db_path, day) or {}
            stats["dongzhu"] = int(dz.get("snap") or 0) + int(dz.get("scored") or 0)
    except Exception:
        pass
    stats["speak"] = bool(
        speak_ready("twii", db_path)
        or speak_ready("dongzhu", db_path)
        or speak_ready("leave_zero", db_path)
    )
    return stats


def _forecast_n(db_path: str, kind: str) -> int:
    if not db_path or not os.path.isfile(db_path):
        return 0
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM biaoke_forecast WHERE kind=? AND check_n>=horizon AND horizon>0",
            (kind,),
        ).fetchone()
        return int(row[0] if row else 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
