# -*- coding: utf-8 -*-
"""低估名單靜默對質閘（§13）。不是買訊；不准改黃金買點／leave_zero。

現況 tag＝RULE_PHONE；下一版＝RULE_NEXT（與 undervalue_scan 同源）。
吃 judge_tape live_judge／score；night_tick＝再凍＋計分＋閘狀態。
"""
from __future__ import annotations

from typing import Any, Dict

from undervalue_confront import (
    KIND_NEXT,
    KIND_PHONE,
    OPTIMIZE_MIN_N,
    confront_status,
    remember_scan_rows,
    run_next_variant_silent,
)
from undervalue_scan import RULE_NEXT, RULE_PHONE
from undervalue_sync import load_picks, load_run

KIND = "undervalue"
TAG_CURRENT = RULE_PHONE
TAG_NEXT = RULE_NEXT
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
BUY_SIGNAL = False


def gate_status(db_path: str) -> Dict[str, Any]:
    """n≥20 且下一版贏現況才可換話筒硬濾；永遠不准 promote 成買訊。"""
    st = confront_status(db_path)
    cur = st.get("current") or {}
    nxt = st.get("next") or {}
    promote = bool(st.get("promote_ready"))
    return {
        "kind": KIND,
        "buy_signal": False,
        "promote_golden_buy": False,
        "promote_paint": False,
        "promote_rule": promote,
        "tag_current": TAG_CURRENT,
        "tag_next": TAG_NEXT,
        "current": cur,
        "next": nxt,
        "min_n": MIN_UNIQUE_DAYS,
        "note": (
            f"低估名單：{TAG_NEXT} n≥{MIN_UNIQUE_DAYS} 且贏 {TAG_CURRENT} → 可換硬濾並再生；"
            "永遠不是買訊"
            if promote
            else (
                f"低估名單靜默：{TAG_CURRENT} n={int(cur.get('n_days') or 0)}/{MIN_UNIQUE_DAYS}；"
                f"{TAG_NEXT} 續收／不改買訊"
            )
        ),
    }


def optimize_status_one_liner(db_path: str) -> str:
    g = gate_status(db_path)
    return str(g.get("note") or "")


def night_tick(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """盤後／壓力軌掛點：再凍現況名單＋下一版靜默＋閘狀態。失敗吞掉。"""
    out: Dict[str, Any] = {
        "wrote": 0,
        "next": {},
        "gate": {},
        "buy_signal": False,
        "tag_current": TAG_CURRENT,
        "tag_next": TAG_NEXT,
    }
    day = str(as_of or "").replace("-", "")[:8]
    if not db_path:
        return out
    if len(day) != 8:
        try:
            from import_health import latest_complete_quote_date

            day = str(latest_complete_quote_date(db_path) or "")
        except Exception:
            day = ""
    if len(day) != 8:
        return out
    try:
        run = load_run(db_path, day) or {}
        rows = load_picks(db_path, day) or []
        if str(run.get("status") or "") == "success" and rows:
            out["wrote"] = int(
                remember_scan_rows(db_path, day, rows, rule_key=TAG_CURRENT) or 0
            )
        out["next"] = run_next_variant_silent(db_path, day)
        # 官方柱走完才填分（與全系統同輪 score_live_judges；此處只觸發可重入）
        try:
            from judge_tape import score_live_judges

            out["scored"] = int(score_live_judges(db_path, cap=day) or 0)
        except Exception:
            out["scored"] = 0
        out["gate"] = gate_status(db_path)
        out["kinds"] = (KIND_PHONE, KIND_NEXT)
    except Exception:
        return out
    return out
