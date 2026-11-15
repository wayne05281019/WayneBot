# -*- coding: utf-8 -*-
"""低估名單掃描：推估防呆與硬濾／估值母體（與海選／黃金買點分開）。

A4：近 3 月 MoM 動能 g 夾在 [-5%, +10%]；不准拿單月極端 YoY 線性外推全年。
推估必標；無官方已公告月營收／季報／收盤就不進母體。不是進場買訊。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# 近 3 月平均月增動能安全區間（小數，非百分點）
G_MOM_FLOOR = -0.05
G_MOM_CEIL = 0.10
# 單月 YoY 超過此絕對值視為極端 → 外推仍只走夾限後的 g，不准用 YoY 當斜率
EXTREME_YOY_ABS_PCT = 80.0


def clamp_mom_g(moms: Sequence[Optional[float]]) -> Tuple[float, Dict[str, Any]]:
    """近 3 月 MoM 平均 → g，夾在 [G_MOM_FLOOR, G_MOM_CEIL]。

    moms 可為小數（0.03）或百分點（3.0）；絕對值 > 1.5 視為百分點並／100。
    缺樣 → g=0 並註記。回傳 (g, meta)。
    """
    vals: List[float] = []
    for raw in moms or ():
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if abs(v) > 1.5:
            v = v / 100.0
        vals.append(v)
    meta: Dict[str, Any] = {"n": len(vals), "raw_avg": None, "clamped": False}
    if not vals:
        meta["note"] = "缺近月MoM"
        return 0.0, meta
    avg = sum(vals) / float(len(vals))
    meta["raw_avg"] = avg
    g = max(G_MOM_FLOOR, min(G_MOM_CEIL, avg))
    meta["clamped"] = abs(g - avg) > 1e-12
    return g, meta


def is_extreme_yoy_pct(yoy_pct: Optional[float]) -> bool:
    """單月營收 YoY％是否極端（不准當全年線性斜率）。"""
    if yoy_pct is None:
        return False
    try:
        return abs(float(yoy_pct)) >= EXTREME_YOY_ABS_PCT
    except (TypeError, ValueError):
        return False


def project_remaining_month_revenues(
    last_rev: float,
    g: float,
    r_m: int,
    *,
    yoy_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """剩餘 R_m 個月營收遞推：Rev(m+1)=Rev(m)×(1+g×0.5)。

    即使 yoy 極端，也只用夾限後的 g；不准 YoY 線性外推全年。
    """
    try:
        rev0 = float(last_rev)
    except (TypeError, ValueError):
        rev0 = 0.0
    try:
        g_use = float(g)
    except (TypeError, ValueError):
        g_use = 0.0
    g_use = max(G_MOM_FLOOR, min(G_MOM_CEIL, g_use))
    n = max(0, int(r_m or 0))
    extreme = is_extreme_yoy_pct(yoy_pct)
    months: List[float] = []
    cur = rev0
    for _ in range(n):
        cur = cur * (1.0 + g_use * 0.5)
        months.append(cur)
    return {
        "months": months,
        "sum": float(sum(months)),
        "g_used": g_use,
        "extreme_yoy": extreme,
        "yoy_pct": yoy_pct,
        "note": "極端YoY不外推；走g夾限" if extreme else "",
    }


def estimate_year_revenue(
    ytd_rev: float,
    last_month_rev: float,
    moms: Sequence[Optional[float]],
    *,
    m_last: int,
    yoy_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """今年預估全年營收＝已公告累計＋剩餘月遞推合計。

    m_last＝今年最新已公告月（1～12）；R_m＝12−m_last。
    """
    try:
        ytd = float(ytd_rev or 0)
    except (TypeError, ValueError):
        ytd = 0.0
    ml = int(m_last or 0)
    if ml < 1 or ml > 12:
        return {
            "ok": False,
            "est_year_rev": None,
            "note": "m_last無效",
        }
    r_m = 12 - ml
    g, g_meta = clamp_mom_g(moms)
    proj = project_remaining_month_revenues(
        last_month_rev, g, r_m, yoy_pct=yoy_pct
    )
    est = ytd + float(proj["sum"])
    return {
        "ok": True,
        "est_year_rev": est,
        "ytd_rev": ytd,
        "r_m": r_m,
        "g": g,
        "g_meta": g_meta,
        "proj": proj,
        "label": "推估",
    }
