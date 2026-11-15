# -*- coding: utf-8 -*-
"""低估名單掃描：推估防呆與硬濾／估值母體（與海選／黃金買點分開）。

A4：近 3 月 MoM 動能 g 夾在 [-5%, +10%]；不准拿單月極端 YoY 線性外推全年。
推估必標；無官方已公告月營收／季報／收盤就不進母體。不是進場買訊。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 近 3 月平均月增動能安全區間（小數，非百分點）
G_MOM_FLOOR = -0.05
G_MOM_CEIL = 0.10
# 單月 YoY 超過此絕對值視為極端 → 外推仍只走夾限後的 g，不准用 YoY 當斜率
EXTREME_YOY_ABS_PCT = 80.0
MOM_UNITS = ("pct", "frac")


def _finite(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def clamp_mom_g(
    moms: Sequence[Optional[float]], *, unit: str
) -> Tuple[float, Dict[str, Any]]:
    """近 3 月 MoM 平均 → g（小數），夾在 [G_MOM_FLOOR, G_MOM_CEIL]。

    unit 必須講清楚："pct"＝百分點（庫內 monthly_revenue.mom_pct，1.2＝+1.2%）；
    "frac"＝小數（0.012）。不准逐筆猜單位：+1.2% 會被當成 +120% 直接頂到上限。
    NaN／inf／None 不收；缺樣 → g=0 並註記。回傳 (g, meta)。
    """
    if unit not in MOM_UNITS:
        raise ValueError(f"unit 必須是 {MOM_UNITS}，收到 {unit!r}")
    scale = 0.01 if unit == "pct" else 1.0
    vals = [v * scale for v in (_finite(x) for x in (moms or ())) if v is not None]
    meta: Dict[str, Any] = {"n": len(vals), "raw_avg": None, "clamped": False, "unit": unit}
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
    v = _finite(yoy_pct)
    return v is not None and abs(v) >= EXTREME_YOY_ABS_PCT


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
    rev0 = _finite(last_rev) or 0.0
    g_use = _finite(g) or 0.0
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
    mom_unit: str,
    yoy_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """今年預估全年營收＝已公告累計＋剩餘月遞推合計。

    m_last＝今年最新已公告月（1～12）；R_m＝12−m_last。
    沒有官方已公告累計／最新月營收（≤0 或缺）就不推估、不進母體。
    """
    ytd = _finite(ytd_rev)
    last = _finite(last_month_rev)
    try:
        ml = int(m_last or 0)
    except (TypeError, ValueError):
        ml = 0
    if ml < 1 or ml > 12:
        return {"ok": False, "est_year_rev": None, "note": "m_last無效"}
    if ytd is None or ytd <= 0 or last is None or last <= 0:
        return {"ok": False, "est_year_rev": None, "note": "缺官方月營收"}
    r_m = 12 - ml
    g, g_meta = clamp_mom_g(moms, unit=mom_unit)
    proj = project_remaining_month_revenues(last, g, r_m, yoy_pct=yoy_pct)
    est = ytd + float(proj["sum"])
    # 推估必標；12 月已齊＝已公告，不准再掛「推估」
    return {
        "ok": True,
        "est_year_rev": est,
        "ytd_rev": ytd,
        "r_m": r_m,
        "g": g,
        "g_meta": g_meta,
        "proj": proj,
        "label": "推估" if r_m > 0 else "已公告",
    }
