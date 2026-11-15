# -*- coding: utf-8 -*-
"""低估名單靜默對質／下一版再生（§13）。

與海選／黃金買點／AI倉勝率分開記、分開比、分開換。
空名單不算。未收不當收。過程／％不准進對話。
過閘才換話筒 RULE_PHONE，且同件必須再生下一版鍵。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from undervalue_scan import RULE_NEXT, RULE_PHONE

logger = logging.getLogger("wayne.undervalue.confront")

KIND_PHONE = "undervalue"
KIND_NEXT = "undervalue_next"
OPTIMIZE_MIN_N = 20


def remember_scan_rows(
    db_path: str,
    as_of: str,
    rows: Sequence[Dict[str, Any]],
    *,
    rule_key: str = RULE_PHONE,
) -> int:
    """把當日真代號＋規則鍵凍進 live_judge。失敗吞掉。"""
    day = str(as_of or "").replace("-", "")[:8]
    path = str(db_path or "").strip()
    items: List[Dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("stock_id") or "").strip()
        if not sid:
            continue
        mark = str(raw.get("mark") or "watch")
        items.append(
            {
                "stock_id": sid,
                "stock_name": str(raw.get("name") or ""),
                "close": raw.get("close"),
                "px": raw.get("close"),
                "bucket_key": mark,
                "why": str(raw.get("reason") or "")[:120],
                "rule_key": str(raw.get("rule_key") or rule_key),
                "pe": raw.get("pe"),
            }
        )
    if not path or len(day) != 8 or not items:
        return 0
    kind = KIND_PHONE if str(rule_key) == RULE_PHONE else KIND_NEXT
    try:
        from judge_tape import remember_rows

        return int(
            remember_rows(
                path,
                kind,
                items,
                as_of=day,
                pick=str(rule_key or "")[:40],
                src="undervalue",
            )
            or 0
        )
    except Exception:
        logger.exception("低估靜默落檔失敗")
        return 0


def run_next_variant_silent(db_path: str, as_of: str) -> Dict[str, Any]:
    """盤後順便跑下一版硬濾，只靜默落檔，不上話筒。"""
    from undervalue_scan import run_undervalue_scan

    scanned = run_undervalue_scan(db_path, as_of, rule_key=RULE_NEXT) or {}
    rows = list(scanned.get("rows") or [])
    n = remember_scan_rows(db_path, as_of, rows, rule_key=RULE_NEXT)
    return {
        "ok": bool(scanned.get("ok")),
        "as_of": str(scanned.get("as_of") or as_of),
        "n": len(rows),
        "remembered": n,
        "note": str(scanned.get("note") or ""),
        "rule_key": RULE_NEXT,
    }


def _score_summary(db_path: str, kind: str) -> Dict[str, Any]:
    """讀 live_judge_score：獨立交易日數＋前瞻 5 日報酬均。缺＝n0。"""
    out = {"n_days": 0, "n_rows": 0, "avg_h5": None, "kind": kind}
    try:
        from judge_tape import store_path

        store = store_path(db_path)
    except Exception:
        return out
    try:
        conn = sqlite3.connect(store, timeout=15.0)
    except sqlite3.Error:
        return out
    try:
        rows = conn.execute(
            """
            SELECT as_of, AVG(ret) AS avg_ret, COUNT(*) AS n
            FROM live_judge_score
            WHERE kind=? AND horizon=5 AND ret IS NOT NULL
            GROUP BY as_of
            """,
            (kind,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    if not rows:
        return out
    days = []
    total_n = 0
    wsum = 0.0
    for as_of, avg_ret, n in rows:
        if not as_of or avg_ret is None:
            continue
        days.append(str(as_of))
        nn = int(n or 0)
        total_n += nn
        wsum += float(avg_ret) * nn
    out["n_days"] = len(days)
    out["n_rows"] = total_n
    if total_n > 0:
        out["avg_h5"] = wsum / float(total_n)
    return out


def confront_status(db_path: str) -> Dict[str, Any]:
    """明確優化狀態一句可用：n 夠不夠、有沒有贏現況。過程％不進對話。"""
    cur = _score_summary(db_path, KIND_PHONE)
    nxt = _score_summary(db_path, KIND_NEXT)
    n_ok = int(nxt.get("n_days") or 0) >= OPTIMIZE_MIN_N and int(
        cur.get("n_days") or 0
    ) >= OPTIMIZE_MIN_N
    cur_avg = cur.get("avg_h5")
    nxt_avg = nxt.get("avg_h5")
    wins = (
        n_ok
        and cur_avg is not None
        and nxt_avg is not None
        and float(nxt_avg) > float(cur_avg)
    )
    return {
        "phone_rule": RULE_PHONE,
        "next_rule": RULE_NEXT,
        "current": cur,
        "next": nxt,
        "n_gate": OPTIMIZE_MIN_N,
        "n_ok": n_ok,
        "next_wins": bool(wins),
        "promote_ready": bool(wins),
    }


def maybe_promote_phone_rule(db_path: str) -> Dict[str, Any]:
    """過閘才回傳建議換碼；本模組不直接改檔。換碼時呼叫端必須再生下一版鍵。"""
    st = confront_status(db_path)
    if not st.get("promote_ready"):
        st["promoted"] = False
        st["note"] = "未過閘或不贏現況"
        return st
    st["promoted"] = False
    st["note"] = (
        f"建議話筒 {RULE_PHONE}→{RULE_NEXT}；換碼同件必須再生下一版"
    )
    st["suggest_phone"] = RULE_NEXT
    return st
