# -*- coding: utf-8 -*-
"""默默畫、覆盤、檢討。不到能講的那天不准開口。

大盤／洞燭／黃金買點各做各的。不推話筒、不改黃金買點、現在不在話筒發明 5／9。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

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


def night_review(db_path: str, cap: str = "") -> Dict[str, Any]:
    """台北 02:00：覆盤官方柱、對他的畫、再試畫明天。不推話筒、不主動講。"""
    stats: Dict[str, Any] = {
        "twii": 0,
        "try": 0,
        "scored": 0,
        "dongzhu": 0,
        "speak": False,
    }
    if not db_path:
        return stats
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
    if not db_path:
        return 0
    import os
    import sqlite3

    if not os.path.isfile(db_path):
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
