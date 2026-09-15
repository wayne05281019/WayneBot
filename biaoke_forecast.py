# -*- coding: utf-8 -*-
"""演算延伸建檔：當下把未出現的走勢存下來，官方柱走完再對質。

個股＝量先價行壓撐＋連點延長。大盤＝他自己改口錨往原文水平延伸。
不數 5／9 段、不准把未出現的線當已經發生。不是買訊。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

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
        "kind": "twii",
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
        "path_json": "[]",
        "rays_json": json.dumps(ray_rows, ensure_ascii=False),
        "verdict": "",
        "created_at": _now(),
    }
    _upsert(db_path, rec)
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
        if str(row.get("kind") or "") == "twii":
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


def glance_forecast(db_path: str, sid: str) -> str:
    """第④顆讀最近一次演算建檔＋對質。"""
    if not db_path or not os.path.isfile(db_path) or not sid:
        return ""
    ensure_forecast_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT as_of, mark, verdict FROM biaoke_forecast "
            "WHERE stock_id=? ORDER BY as_of DESC LIMIT 1",
            (sid,),
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
