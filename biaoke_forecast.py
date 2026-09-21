# -*- coding: utf-8 -*-
"""演算延伸建檔：當下把未出現的走勢存下來，官方柱走完再對質。

個股＝量先價行壓撐＋連點延長。大盤＝他自己改口錨往原文水平延伸；
盤後另外內部試畫，不進話筒、不把練習段號寫進回覆。
不准把未出現的線當已經發生。不是買訊。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
KIND_TWII = "twii"
KIND_TWII_TRY = "twii_try"
TWII_TRY_HORIZON = 10
TWII_WORST = 43500.0

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_forecast (
    kind TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    key TEXT NOT NULL DEFAULT '',
    last_close REAL,
    target REAL,
    spike_high REAL,
    spike_low REAL,
    down_fut REAL,
    up_fut REAL,
    mark TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    path_json TEXT NOT NULL DEFAULT '[]',
    rays_json TEXT NOT NULL DEFAULT '[]',
    verdict TEXT NOT NULL DEFAULT '',
    check_n INTEGER NOT NULL DEFAULT 0,
    check_high REAL,
    check_low REAL,
    check_close REAL,
    checked_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, stock_id, as_of)
);
CREATE INDEX IF NOT EXISTS idx_biaoke_forecast_sid ON biaoke_forecast(stock_id, as_of);
"""


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return "—"
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _evolve_store(market_db: str) -> str:
    """內部試畫寫另一顆檔，不進問位階表、不跟洞燭／海選／AI倉混勝率。"""
    path = os.path.abspath(str(market_db or "data/wayne_market.db"))
    root = os.path.dirname(path) or "."
    name = os.path.basename(path)
    if name == "wayne_evolve.db":
        return path
    return os.path.join(root, "wayne_evolve.db")


_TRY_RATES_DDL = """
CREATE TABLE IF NOT EXISTS silent_twii_rates (
    kind TEXT PRIMARY KEY,
    n INTEGER NOT NULL DEFAULT 0,
    hit INTEGER NOT NULL DEFAULT 0,
    miss INTEGER NOT NULL DEFAULT 0,
    pending INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT ''
);
"""


def ensure_forecast_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _later_bars(db_path: str, sid: str, as_of: str, n: int) -> List[Dict[str, Any]]:
    day = _ymd(as_of)
    if not db_path or not os.path.isfile(db_path) or not sid or not day or n <= 0:
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        if sid == "TWII":
            rows = conn.execute(
                "SELECT date, open, high, low, close FROM index_daily "
                "WHERE (symbol='TWII' OR symbol='^TWII') "
                "AND REPLACE(CAST(date AS TEXT),'-','')>? "
                "ORDER BY REPLACE(CAST(date AS TEXT),'-','') ASC LIMIT ?",
                (day, int(n)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, open, high, low, close FROM daily_quotes "
                "WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')>? "
                "ORDER BY REPLACE(CAST(date AS TEXT),'-','') ASC LIMIT ?",
                (sid, day, int(n)),
            ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            out.append(
                {
                    "date": r[0],
                    "open": float(r[1] or 0),
                    "high": float(r[2] or 0),
                    "low": float(r[3] or 0),
                    "close": float(r[4] or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return out


def _upsert(db_path: str, row: Dict[str, Any]) -> None:
    ensure_forecast_table(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO biaoke_forecast
            (kind, stock_id, as_of, horizon, key, last_close, target,
             spike_high, spike_low, down_fut, up_fut, mark, label,
             path_json, rays_json, verdict, check_n, check_high, check_low,
             check_close, checked_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row.get("kind") or "stock",
                row.get("stock_id") or "",
                row.get("as_of") or "",
                int(row.get("horizon") or 0),
                row.get("key") or "",
                row.get("last_close"),
                row.get("target"),
                row.get("spike_high"),
                row.get("spike_low"),
                row.get("down_fut"),
                row.get("up_fut"),
                row.get("mark") or "",
                row.get("label") or "",
                row.get("path_json") or "[]",
                row.get("rays_json") or "[]",
                row.get("verdict") or "",
                int(row.get("check_n") or 0),
                row.get("check_high"),
                row.get("check_low"),
                row.get("check_close"),
                row.get("checked_at") or "",
                row.get("created_at") or _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_stock(db_path: str, sid: str, bars: Sequence[Dict[str, Any]], *, name: str = "") -> Dict[str, Any]:
    """把這一檔當下的演算路徑存下來。as_of＝最後一根完整官方柱。"""
    from biaoke_chart import _BARS, analyze_structure

    sid = str(sid or "").strip()
    rows = list(bars or [])
    if not db_path or not sid or len(rows) < 8:
        return {}
    info = analyze_structure(rows[-_BARS:])
    proj = info.get("project") or {}
    last = info.get("last_bar") or rows[-1]
    as_of = _ymd(last.get("date"))
    if not as_of or not proj:
        return {}
    st = info.get("struct") or {}
    path = []
    for i, pt in enumerate(proj.get("path") or []):
        try:
            path.append({"off": i, "y": float(pt[1])})
        except (TypeError, ValueError, IndexError):
            continue
    rec = {
        "kind": "stock",
        "stock_id": sid,
        "as_of": as_of,
        "horizon": int(proj.get("horizon") or 0),
        "key": str(proj.get("key") or ""),
        "last_close": float(last.get("close") or 0) or None,
        "target": proj.get("target"),
        "spike_high": st.get("spike_high"),
        "spike_low": st.get("spike_low"),
        "down_fut": proj.get("down_fut"),
        "up_fut": proj.get("up_fut"),
        "mark": str(proj.get("mark") or ""),
        "label": str(proj.get("label") or ""),
        "path_json": json.dumps(path, ensure_ascii=False),
        "rays_json": "[]",
        "verdict": "",
        "created_at": _now(),
    }
    _upsert(db_path, rec)
    return rec


def record_twii(
    db_path: str,
    bars: Sequence[Dict[str, Any]],
    *,
    rays: Optional[Sequence[Dict[str, Any]]] = None,
    last_tag: str = "",
) -> Dict[str, Any]:
    """大盤延伸只沿他自己點過的水平，不數 5／9。"""
    rows = list(bars or [])
    if not db_path or len(rows) < 8:
        return {}
    last = rows[-1]
    as_of = _ymd(last.get("date"))
    if not as_of:
        return {}
    try:
        last_c = float(last.get("close") or 0)
    except (TypeError, ValueError):
        last_c = 0.0
    ray_rows = [dict(r) for r in (rays or []) if r.get("y")]
    target = None
    for r in ray_rows:
        if r.get("kind") == "worst":
            try:
                target = float(r.get("y"))
            except (TypeError, ValueError):
                target = None
            break
    rec = {
        "kind": KIND_TWII,
        "stock_id": "TWII",
        "as_of": as_of,
        "horizon": 10,
        "key": last_tag or "twii",
        "last_close": last_c or None,
        "target": target,
        "spike_high": None,
        "spike_low": None,
        "down_fut": None,
        "up_fut": None,
        "mark": "未確認延伸" + (f" {last_tag}" if last_tag else ""),
        "label": "轉折線往他自己點過的水平延伸，不數 5／9 段。不是保證。",
        "path_json": json.dumps(
            [{"y": r.get("y"), "lab": r.get("label") or r.get("kind") or ""} for r in ray_rows],
            ensure_ascii=False,
        ),
        "rays_json": json.dumps(ray_rows, ensure_ascii=False),
        "verdict": "",
        "created_at": _now(),
    }
    _upsert(db_path, rec)
    return rec


def _try_impulse(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """內部試畫：官方柱夠才推。推不出來就空，不准亂數。不進話筒。"""
    bars = list(rows or [])
    n = len(bars)
    if n < 20:
        return {}
    try:
        highs = [float(r.get("high") or 0) for r in bars]
    except (TypeError, ValueError):
        return {}
    end = n - 3
    if end < 12:
        return {}
    peak_i = max(range(10, end), key=lambda i: highs[i] if highs[i] > 0 else -1e18)
    if highs[peak_i] <= 0:
        return {}
    try:
        from biaoke_chart import infer_impulse_five

        return infer_impulse_five(bars, peak_i=peak_i) or {}
    except Exception:
        return {}


def record_twii_try(
    db_path: str,
    bars: Sequence[Dict[str, Any]],
    *,
    last_tag: str = "",
    direc: str = "",
) -> Dict[str, Any]:
    """大盤內部試畫。寫另一顆檔。不進話筒、不把段號寫進回覆。不是買訊。"""
    rows = list(bars or [])
    if not db_path or len(rows) < 8:
        return {}
    last = rows[-1]
    as_of = _ymd(last.get("date"))
    if not as_of:
        return {}
    try:
        last_c = float(last.get("close") or 0)
    except (TypeError, ValueError):
        last_c = 0.0
    if last_c <= 0:
        return {}
    five = _try_impulse(rows)
    path: List[Dict[str, Any]] = []
    target = None
    start = (five or {}).get("start") or {}
    pts = list((five or {}).get("pts") or [])
    if start and start.get("y"):
        try:
            path.append({"off": int(start.get("i") or 0), "y": float(start.get("y") or 0)})
        except (TypeError, ValueError):
            pass
    p4 = p5 = None
    for p in pts:
        try:
            path.append({"off": int(p.get("i") or 0), "y": float(p.get("y") or 0)})
        except (TypeError, ValueError):
            continue
        if str(p.get("n") or "") == "4":
            p4 = p
        elif str(p.get("n") or "") == "5":
            p5 = p
    last_i = len(rows) - 1
    if p5 and p4 and int(p5.get("i") or 0) < last_i - 1:
        try:
            target = float(p4.get("y") or 0) or None
        except (TypeError, ValueError):
            target = None
    d = str(direc or "").strip().lower()
    if target is None and d in {"down", "retest"} and last_c > TWII_WORST:
        target = TWII_WORST
    rec = {
        "kind": KIND_TWII_TRY,
        "stock_id": "TWII",
        "as_of": as_of,
        "horizon": TWII_TRY_HORIZON,
        "key": d or (last_tag or "try"),
        "last_close": last_c,
        "target": target,
        "spike_high": None,
        "spike_low": None,
        "down_fut": None,
        "up_fut": None,
        "mark": "內部試畫",
        "label": "不進話筒。不是保證。",
        "path_json": json.dumps(path, ensure_ascii=False),
        "rays_json": "[]",
        "verdict": "",
        "created_at": _now(),
    }
    store = _evolve_store(db_path)
    _upsert(store, rec)
    _refresh_twii_try_rates(store)
    return rec


def _judge_stock(row: Dict[str, Any], later: Sequence[Dict[str, Any]]) -> str:
    need = int(row.get("horizon") or 0)
    if not later:
        return "還沒走完（之後還沒官方柱）"
    hi = max(float(b.get("high") or 0) for b in later)
    lo = min(float(b.get("low") or 0) for b in later)
    close = float(later[-1].get("close") or 0)
    key = str(row.get("key") or "")
    target = row.get("target")
    last0 = row.get("last_close")
    shi = row.get("spike_high")
    slo = row.get("spike_low")
    done = len(later) >= max(1, need)
    head = "" if done else f"已走{len(later)}/{need}根，"

    def hit_tgt() -> bool:
        try:
            t = float(target)
            a = float(last0 or 0)
        except (TypeError, ValueError):
            return False
        if t >= a:
            return hi >= t * 0.997
        return lo <= t * 1.003

    if key in {"wash", "toward_press", "rail"}:
        if hit_tgt():
            bit = f"對得上：後來高{_px(hi)}低{_px(lo)}碰到目標{_px(target)}"
        else:
            bit = f"還沒碰到目標{_px(target)}：後來高{_px(hi)}低{_px(lo)}收{_px(close)}"
    elif key == "abandon":
        try:
            s = float(slo or 0)
        except (TypeError, ValueError):
            s = 0.0
        if s and close < s:
            bit = f"對得上：還在撐{_px(s)}下，收{_px(close)}"
        elif s:
            bit = f"偏了：已站上撐{_px(s)}，收{_px(close)}"
        else:
            bit = f"後來收{_px(close)}"
    elif key == "wait":
        try:
            s_hi = float(shi or 0)
            s_lo = float(slo or 0)
        except (TypeError, ValueError):
            s_hi, s_lo = 0.0, 0.0
        if s_lo and close < s_lo:
            bit = f"偏了：整理中跌破撐{_px(s_lo)}，收{_px(close)}"
        elif s_hi and hi > s_hi * 1.05:
            bit = f"偏了：整理中過壓{_px(s_hi)}，高{_px(hi)}"
        else:
            bit = f"對得上：先整理，後來高{_px(hi)}低{_px(lo)}收{_px(close)}"
    elif key == "distribution":
        try:
            s = float(slo or 0)
        except (TypeError, ValueError):
            s = 0.0
        if s and lo <= s * 1.003:
            bit = f"對得上：後來低{_px(lo)}碰到撐{_px(s)}"
        else:
            bit = f"還沒到撐{_px(slo)}：後來低{_px(lo)}"
    elif key == "press_hold":
        try:
            s = float(shi or 0)
        except (TypeError, ValueError):
            s = 0.0
        if s and lo >= s * 0.995:
            bit = f"對得上：壓轉撐{_px(s)}有守，後來低{_px(lo)}"
        elif s:
            bit = f"偏了：壓轉撐{_px(s)}被跌破，後來低{_px(lo)}"
        else:
            bit = f"後來收{_px(close)}"
    elif key == "rail_cap":
        df = row.get("down_fut")
        try:
            d = float(df or 0)
        except (TypeError, ValueError):
            d = 0.0
        if d and hi < d * 1.002:
            bit = f"對得上：還在下降連點{_px(d)}下，高{_px(hi)}"
        elif d:
            bit = f"偏了：過了連點延長{_px(d)}，高{_px(hi)}"
        else:
            bit = f"後來收{_px(close)}"
    else:
        bit = f"後來高{_px(hi)}低{_px(lo)}收{_px(close)}"
    if not done:
        bit = head + bit + "。還沒走完"
    return bit


def _judge_twii(row: Dict[str, Any], later: Sequence[Dict[str, Any]]) -> str:
    if not later:
        return "還沒走完（之後還沒官方加權柱）"
    hi = max(float(b.get("high") or 0) for b in later)
    lo = min(float(b.get("low") or 0) for b in later)
    close = float(later[-1].get("close") or 0)
    need = int(row.get("horizon") or 10)
    done = len(later) >= max(1, need)
    head = "" if done else f"已走{len(later)}/{need}根，"
    tgt = row.get("target")
    bits = []
    try:
        t = float(tgt) if tgt is not None else 0.0
    except (TypeError, ValueError):
        t = 0.0
    if t and lo <= t * 1.001:
        bits.append(f"對得上碰到原文最差{_px(t)}：後來低{_px(lo)}")
    elif t:
        bits.append(f"還沒碰到原文最差{_px(t)}：後來低{_px(lo)}收{_px(close)}")
    if close >= 45839:
        bits.append(f"收{_px(close)}還在 45839 之上")
    else:
        bits.append(f"收{_px(close)}已低於 45839")
    bit = "；".join(bits) if bits else f"後來高{_px(hi)}低{_px(lo)}收{_px(close)}"
    if not done:
        bit = head + bit + "。還沒走完"
    return bit


def _judge_twii_try(row: Dict[str, Any], later: Sequence[Dict[str, Any]]) -> str:
    if not later:
        return "還沒走完（之後還沒官方加權柱）"
    hi = max(float(b.get("high") or 0) for b in later)
    lo = min(float(b.get("low") or 0) for b in later)
    close = float(later[-1].get("close") or 0)
    need = int(row.get("horizon") or TWII_TRY_HORIZON)
    done = len(later) >= max(1, need)
    head = "" if done else f"已走{len(later)}/{need}根，"
    tgt = row.get("target")
    last0 = row.get("last_close")
    key = str(row.get("key") or "")
    bits: List[str] = []
    try:
        t = float(tgt) if tgt is not None else 0.0
        a = float(last0 or 0)
    except (TypeError, ValueError):
        t, a = 0.0, 0.0
    if t and a:
        if t < a:
            if lo <= t * 1.001:
                bits.append(f"對得上碰到目標{_px(t)}：後來低{_px(lo)}")
            else:
                bits.append(f"還沒碰到目標{_px(t)}：後來低{_px(lo)}收{_px(close)}")
        else:
            if hi >= t * 0.999:
                bits.append(f"對得上碰到目標{_px(t)}：後來高{_px(hi)}")
            else:
                bits.append(f"還沒碰到目標{_px(t)}：後來高{_px(hi)}收{_px(close)}")
    elif a:
        going_down = key in {"down", "retest"} or "C-" in key or "逃命" in key
        going_up = key in {"up"} or "大B" in key or "末升" in key
        if going_down:
            if close < a:
                bits.append(f"對得上往下：收{_px(close)}")
            elif close > a * 1.01:
                bits.append(f"偏了沒往下：收{_px(close)}")
            else:
                bits.append(f"後來收{_px(close)}")
        elif going_up:
            if close > a:
                bits.append(f"對得上往上：收{_px(close)}")
            elif close < a * 0.99:
                bits.append(f"偏了沒往上：收{_px(close)}")
            else:
                bits.append(f"後來收{_px(close)}")
        else:
            bits.append(f"後來高{_px(hi)}低{_px(lo)}收{_px(close)}")
    bit = "；".join(bits) if bits else f"後來高{_px(hi)}低{_px(lo)}收{_px(close)}"
    if not done:
        bit = head + bit + "。還沒走完"
    return bit


def verify_due(db_path: str, sid: str = "") -> int:
    """官方柱夠了就對質當初建檔的演算。盤中未收不當官方收。"""
    if not db_path or not os.path.isfile(db_path):
        return 0
    ensure_forecast_table(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        if sid:
            rows = conn.execute(
                "SELECT * FROM biaoke_forecast WHERE stock_id=?", (sid,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM biaoke_forecast").fetchall()
    except sqlite3.Error:
        rows = []
        conn.close()
        return 0
    n = 0
    stamp = _now()
    for raw in rows:
        row = dict(raw)
        if "對得上" in (row.get("verdict") or "") and "還沒走完" not in (row.get("verdict") or ""):
            if "偏了" in (row.get("verdict") or ""):
                pass
            elif int(row.get("check_n") or 0) >= int(row.get("horizon") or 0):
                continue
        later = _later_bars(
            db_path, str(row.get("stock_id") or ""), str(row.get("as_of") or ""), int(row.get("horizon") or 0)
        )
        kind = str(row.get("kind") or "")
        if kind == KIND_TWII_TRY:
            continue
        if kind == KIND_TWII:
            verdict = _judge_twii(row, later)
        else:
            verdict = _judge_stock(row, later)
        hi = lo = cl = None
        if later:
            hi = max(float(b.get("high") or 0) for b in later)
            lo = min(float(b.get("low") or 0) for b in later)
            cl = float(later[-1].get("close") or 0)
        conn.execute(
            """
            UPDATE biaoke_forecast
            SET verdict=?, check_n=?, check_high=?, check_low=?, check_close=?, checked_at=?
            WHERE kind=? AND stock_id=? AND as_of=?
            """,
            (
                verdict,
                len(later),
                hi,
                lo,
                cl,
                stamp,
                row.get("kind"),
                row.get("stock_id"),
                row.get("as_of"),
            ),
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def verify_twii_try(db_path: str) -> int:
    """只對質內部試畫。寫另一顆檔，不碰問位階、洞燭、海選、AI倉。"""
    store = _evolve_store(db_path)
    if not store or not os.path.isfile(store):
        return 0
    ensure_forecast_table(store)
    conn = sqlite3.connect(store, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM biaoke_forecast WHERE kind=?",
            (KIND_TWII_TRY,),
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return 0
    n = 0
    stamp = _now()
    for raw in rows:
        row = dict(raw)
        if "對得上" in (row.get("verdict") or "") and "還沒走完" not in (row.get("verdict") or ""):
            if "偏了" in (row.get("verdict") or ""):
                pass
            elif int(row.get("check_n") or 0) >= int(row.get("horizon") or 0):
                continue
        later = _later_bars(
            db_path,
            str(row.get("stock_id") or ""),
            str(row.get("as_of") or ""),
            int(row.get("horizon") or 0),
        )
        verdict = _judge_twii_try(row, later)
        hi = lo = cl = None
        if later:
            hi = max(float(b.get("high") or 0) for b in later)
            lo = min(float(b.get("low") or 0) for b in later)
            cl = float(later[-1].get("close") or 0)
        conn.execute(
            """
            UPDATE biaoke_forecast
            SET verdict=?, check_n=?, check_high=?, check_low=?, check_close=?, checked_at=?
            WHERE kind=? AND stock_id=? AND as_of=?
            """,
            (
                verdict,
                len(later),
                hi,
                lo,
                cl,
                stamp,
                row.get("kind"),
                row.get("stock_id"),
                row.get("as_of"),
            ),
        )
        n += 1
    conn.commit()
    conn.close()
    _refresh_twii_try_rates(store)
    return n


def _refresh_twii_try_rates(store: str) -> None:
    if not store:
        return
    parent = os.path.dirname(os.path.abspath(store))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(_TRY_RATES_DDL)
        rows = conn.execute(
            "SELECT verdict FROM biaoke_forecast WHERE kind=?",
            (KIND_TWII_TRY,),
        ).fetchall()
        hit = miss = pending = 0
        for (verdict,) in rows:
            t = str(verdict or "")
            if "還沒走完" in t or not t:
                pending += 1
            elif "偏了" in t:
                miss += 1
            elif "對得上" in t:
                hit += 1
            else:
                pending += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO silent_twii_rates(
                kind, n, hit, miss, pending, updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (KIND_TWII_TRY, hit + miss + pending, hit, miss, pending, _now()),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def glance_forecast(db_path: str, sid: str) -> str:
    """第④顆讀最近一次演算建檔＋對質。內部試畫不讀出來。"""
    if not db_path or not os.path.isfile(db_path) or not sid:
        return ""
    ensure_forecast_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT as_of, mark, verdict FROM biaoke_forecast "
            "WHERE stock_id=? AND kind!=? ORDER BY as_of DESC LIMIT 1",
            (sid, KIND_TWII_TRY),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row:
        return ""
    as_of, mark, verdict = row
    bit = f"演算建檔 {as_of} {mark or ''}".strip()
    if verdict:
        bit += "；對質 " + verdict
    else:
        bit += "；之後官方柱走完再對質"
    return bit


def record_from_events(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """新文點到的檔／大盤，立刻演算建檔並對質舊檔。"""
    if not db_path or not events:
        return 0
    from biaoke_brain import load_bars, load_index_bars
    from biaoke_tape import named_pairs

    sids = []
    seen = set()
    want_twii = False
    for ev in events:
        text = str(ev.get("text") or "")
        for sid, _name in named_pairs(text, ev.get("tags")):
            if sid == "TWII":
                want_twii = True
                continue
            if sid not in seen:
                seen.add(sid)
                sids.append(sid)
        if "大盤" in text or "加權" in text or "台指" in text:
            want_twii = True
    n = 0
    for sid in sids:
        bars = load_bars(db_path, sid, n=120)
        if record_stock(db_path, sid, bars):
            n += 1
    if want_twii:
        try:
            from biaoke_wave import _load_twii_bars, last_two, wave_extend_rays, wave_path_points

            bars = _load_twii_bars(db_path, n=90)
            pts = wave_path_points(db_path, bars)
            last, _prev = last_two(db_path)
            tag = str((last or {}).get("tag") or "")
            rays = wave_extend_rays(pts, len(bars), tag)
            if record_twii(db_path, bars, rays=rays, last_tag=tag):
                n += 1
        except Exception:
            try:
                bars = load_index_bars(db_path, n=90)
                if record_twii(db_path, bars, last_tag="TWII"):
                    n += 1
            except Exception:
                pass
    try:
        verify_due(db_path)
    except Exception:
        pass
    return n


def ensure_wave_inputs(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """波浪圖要的料：缺完整官方收才去同步，寫進程情庫。pytest 不打外網。未收不當收。"""
    stats: Dict[str, Any] = {"twii": 0, "fut": 0, "us": 0}
    if not db_path:
        return stats
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_ALLOW_WAVE_SYNC") != "1":
        return {**stats, "skipped": "pytest"}
    day = _ymd(as_of)
    holes: List[str] = []
    try:
        from silent_progress import _read_live_context, pack_holes

        holes = pack_holes(_read_live_context(db_path, day))
    except Exception:
        holes = ["twii", "tx_day", "tx_night", "te_day", "te_night", "us"]
    if "twii" in holes:
        try:
            from taiwan_market import sync_index_daily

            sync_index_daily(db_path)
            stats["twii"] = 1
        except Exception:
            pass
    if any(k in holes for k in ("tx_day", "tx_night", "te_day", "te_night")):
        try:
            from taiwan_market import sync_futures_daily

            sync_futures_daily(db_path, dates=[day] if day else None)
            stats["fut"] = 1
        except Exception:
            pass
    if "us" in holes:
        try:
            from us_overnight import refresh_us_overnight, us_tape_phase

            if us_tape_phase() != "regular":
                refresh_us_overnight(db_path, day or as_of)
                stats["us"] = 1
        except Exception:
            pass
    return stats


def snapshot_and_score_twii(db_path: str, cap: str = "") -> Dict[str, Any]:
    """盤後齊了：內部試畫＋覆盤包。不寫問位階、不改洞燭名單／海選／AI倉／黃金買點、不推話筒。"""
    cap_ymd = _ymd(cap)
    if not db_path:
        return {"twii": 0, "try": 0, "scored": 0, "cap": cap_ymd}
    try:
        ensure_wave_inputs(db_path, cap_ymd)
    except Exception:
        pass
    scored = 0
    try:
        scored = int(verify_twii_try(db_path) or 0)
    except Exception:
        scored = 0
    rec: Dict[str, Any] = {}
    try_rec: Dict[str, Any] = {}
    try:
        from biaoke_wave import _complete_bar_ymd, _load_twii_bars, last_two, wave_extend_rays, wave_path_points

        complete = _complete_bar_ymd(db_path) or cap_ymd
        bars = _load_twii_bars(db_path, n=220)
        if complete:
            bars = [b for b in bars if _ymd(b.get("date")) <= complete]
        if cap_ymd:
            bars = [b for b in bars if _ymd(b.get("date")) <= cap_ymd]
        if not bars:
            return {
                "twii": 0,
                "try": 0,
                "scored": scored,
                "cap": cap_ymd or complete,
                "skipped": "no_bars",
            }
        last = bars[-1]
        try:
            last_c = float(last.get("close") or 0)
        except (TypeError, ValueError):
            last_c = 0.0
        if last_c <= 0:
            return {
                "twii": 0,
                "try": 0,
                "scored": scored,
                "cap": cap_ymd or complete,
                "skipped": "zero_close",
            }
        last_turn, _prev = last_two(db_path)
        tag = str((last_turn or {}).get("tag") or "")
        direc = str((last_turn or {}).get("direc") or "")
        pts = wave_path_points(db_path, bars)
        rays = wave_extend_rays(pts, len(bars), tag)
        from silent_progress import capture_review_context, simulate_next_legs

        legs = simulate_next_legs(tag, last_c, rays)
        extra = {
            "twii": {
                k: last.get(k)
                for k in ("date", "open", "high", "low", "close", "volume")
                if last.get(k) not in (None, "")
            },
            "biaoke": {
                k: (last_turn or {}).get(k)
                for k in ("tag", "direc", "date")
                if (last_turn or {}).get(k)
            },
            "legs": legs,
        }
        try:
            capture_review_context(db_path, as_of=_ymd(last.get("date")) or cap_ymd, extra=extra)
        except Exception:
            pass
        try_rec = record_twii_try(db_path, bars, last_tag=tag, direc=direc) or {}
    except Exception:
        try:
            from biaoke_brain import load_index_bars

            bars = load_index_bars(db_path, n=220)
            if cap_ymd:
                bars = [b for b in bars if _ymd(b.get("date")) <= cap_ymd]
            try_rec = record_twii_try(db_path, bars) or {}
        except Exception:
            rec, try_rec = {}, {}
    return {
        "twii": 0,
        "try": 1 if try_rec else 0,
        "scored": scored,
        "cap": cap_ymd or _ymd((try_rec or {}).get("as_of")),
    }
