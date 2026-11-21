# -*- coding: utf-8 -*-
"""海選／綜合篩選：官方 YoY／毛利率顯示旁註（只出卡／組字，不准當選股閘）。

缺官方欄就整段省略，不准印假「—」。
"""
from __future__ import annotations

import math
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

# 話筒氣泡約 18 全形字；旁註走單位切開，不准從數字中間折。
FUND_SIDE_PHONE_MAX = 18


def _finite(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _sid_of(item: Mapping[str, Any]) -> str:
    for key in ("stock_id", "code", "sid"):
        s = str(item.get(key) or "").strip()
        if s:
            return s
    return ""


def _month_lab(yyyymm: Any) -> str:
    s = str(yyyymm or "").strip()
    if len(s) >= 6 and s[:6].isdigit():
        return f"{int(s[4:6])}月"
    return ""


def _season_lab(year: Any, season: Any) -> str:
    try:
        s = int(season)
    except (TypeError, ValueError):
        return ""
    if s not in (1, 2, 3, 4):
        return ""
    try:
        y = int(year)
    except (TypeError, ValueError):
        y = 0
    if y >= 2000:
        return f"{y % 100}Q{s}"
    return f"Q{s}"


def _fmt_yoy(yoy: float) -> str:
    # 整數％較短；非整數留一位，避免假精度。
    if abs(yoy - round(yoy)) < 1e-9:
        return f"{yoy:+.0f}%"
    return f"{yoy:+.1f}%"


def _fmt_gm(gm: float) -> str:
    if abs(gm - round(gm)) < 1e-9:
        return f"{gm:.0f}%"
    return f"{gm:.1f}%"


def batch_latest_fund_metrics(
    db_path: str,
    stock_ids: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    """小批讀各檔最新官方月營收 YoY（含 yyyymm）與季報毛利率。

    回傳鍵＝代號；值只放有官方數的欄（缺則該欄不出現）。
    """
    path = str(db_path or "").strip()
    codes = []
    seen = set()
    for raw in stock_ids or ():
        sid = str(raw or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        codes.append(sid)
    if not path or not codes:
        return {}
    out: Dict[str, Dict[str, Any]] = {sid: {} for sid in codes}
    try:
        conn = sqlite3.connect(path, timeout=15.0)
    except sqlite3.Error:
        return {}
    try:
        # 表不存在＝無官方源，整批空（不准造假）。
        tables = {
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        placeholders = ",".join("?" * len(codes))
        if "monthly_revenue" in tables:
            rows = conn.execute(
                f"""
                SELECT m.stock_id, m.yyyymm, m.yoy_pct
                FROM monthly_revenue m
                INNER JOIN (
                    SELECT stock_id, MAX(yyyymm) AS yyyymm
                    FROM monthly_revenue
                    WHERE stock_id IN ({placeholders})
                    GROUP BY stock_id
                ) t ON m.stock_id = t.stock_id AND m.yyyymm = t.yyyymm
                """,
                codes,
            ).fetchall()
            for sid, yyyymm, yoy in rows:
                s = str(sid or "").strip()
                if not s:
                    continue
                pack = out.setdefault(s, {})
                yoy_f = _finite(yoy)
                if yoy_f is not None:
                    pack["yoy_pct"] = yoy_f
                    ym = str(yyyymm or "").strip()
                    if ym:
                        pack["yyyymm"] = ym
        if "quarterly_income" in tables:
            rows = conn.execute(
                f"""
                SELECT q.stock_id, q.year, q.season, q.gross_margin_pct
                FROM quarterly_income q
                INNER JOIN (
                    SELECT stock_id, MAX(year * 10 + season) AS ys
                    FROM quarterly_income
                    WHERE stock_id IN ({placeholders})
                    GROUP BY stock_id
                ) t ON q.stock_id = t.stock_id
                   AND (q.year * 10 + q.season) = t.ys
                """,
                codes,
            ).fetchall()
            for sid, year, season, gm in rows:
                s = str(sid or "").strip()
                if not s:
                    continue
                pack = out.setdefault(s, {})
                gm_f = _finite(gm)
                if gm_f is not None:
                    pack["gross_margin_pct"] = gm_f
                    try:
                        pack["year"] = int(year)
                    except (TypeError, ValueError):
                        pass
                    try:
                        pack["season"] = int(season)
                    except (TypeError, ValueError):
                        pass
    except sqlite3.Error:
        return {k: v for k, v in out.items() if v}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {k: v for k, v in out.items() if v}


def format_fund_side_note(
    meta: Optional[Mapping[str, Any]],
    *,
    style: str = "card",
) -> str:
    """緊湊旁註。style=card 給海選卡／純文字；paren 給綜合篩選代號括註。

    缺數就省略該段；兩段都沒有回空字串（不准「—」）。
    """
    if not meta:
        return ""
    yoy = _finite(meta.get("yoy_pct"))
    gm = _finite(meta.get("gross_margin_pct"))
    month = _month_lab(meta.get("yyyymm"))
    season = _season_lab(meta.get("year"), meta.get("season"))

    bits: List[str] = []
    if yoy is not None:
        yoy_s = _fmt_yoy(yoy)
        if style == "paren":
            bits.append(f"YoY{yoy_s}")
        elif month:
            bits.append(f"{month}YoY{yoy_s}")
        else:
            bits.append(f"YoY{yoy_s}")
    if gm is not None:
        gm_s = _fmt_gm(gm)
        if style == "paren":
            bits.append(f"毛{gm_s}")
        elif season:
            bits.append(f"{season}毛{gm_s}")
        else:
            bits.append(f"毛{gm_s}")
    if not bits:
        return ""
    if style == "paren":
        return "(" + "｜".join(bits) + ")"
    return "　".join(bits)


def apply_fund_meta_to_item(
    item: MutableMapping[str, Any],
    meta: Optional[Mapping[str, Any]],
) -> None:
    """只寫顯示欄；不准動選股／閘門欄。"""
    if not isinstance(item, dict):
        return
    note = format_fund_side_note(meta, style="card")
    paren = format_fund_side_note(meta, style="paren")
    if note:
        item["fund_side_note"] = note
    else:
        item.pop("fund_side_note", None)
    if paren:
        item["fund_side_paren"] = paren
    else:
        item.pop("fund_side_paren", None)
    if not meta:
        for k in (
            "fund_yoy_pct",
            "fund_yoy_yyyymm",
            "fund_gross_margin_pct",
            "fund_gm_year",
            "fund_gm_season",
        ):
            item.pop(k, None)
        return
    if "yoy_pct" in meta:
        item["fund_yoy_pct"] = meta["yoy_pct"]
        if meta.get("yyyymm"):
            item["fund_yoy_yyyymm"] = meta["yyyymm"]
    if "gross_margin_pct" in meta:
        item["fund_gross_margin_pct"] = meta["gross_margin_pct"]
        if meta.get("year") is not None:
            item["fund_gm_year"] = meta["year"]
        if meta.get("season") is not None:
            item["fund_gm_season"] = meta["season"]


def hydrate_items_fund_side(
    items: Iterable[MutableMapping[str, Any]],
    db_path: str,
) -> None:
    """就地補 fund_side_note／paren；只格式用。"""
    path = str(db_path or "").strip()
    rows = [it for it in (items or ()) if isinstance(it, dict)]
    if not path or not rows:
        return
    codes = [_sid_of(it) for it in rows]
    by_id = batch_latest_fund_metrics(path, codes)
    for it in rows:
        apply_fund_meta_to_item(it, by_id.get(_sid_of(it)))


def hydrate_screen_results_fund_notes(
    results: Mapping[str, Any],
    db_path: str,
) -> Dict[str, Any]:
    """海選 results 各桶名單出卡前補基本面旁註（不改桶內容順序／選股）。"""
    path = str(db_path or "").strip()
    if not results or not path:
        return dict(results or {})
    codes: List[str] = []
    seen = set()
    for rows in results.values():
        if not isinstance(rows, list):
            continue
        for it in rows:
            if not isinstance(it, dict):
                continue
            sid = _sid_of(it)
            if sid and sid not in seen:
                seen.add(sid)
                codes.append(sid)
    by_id = batch_latest_fund_metrics(path, codes) if codes else {}
    for rows in results.values():
        if not isinstance(rows, list):
            continue
        for it in rows:
            if not isinstance(it, dict):
                continue
            apply_fund_meta_to_item(it, by_id.get(_sid_of(it)))
    return results  # type: ignore[return-value]


def fund_side_note_from_item(item: Optional[Mapping[str, Any]]) -> str:
    """讀已 hydrate 欄，或從 raw fund_* 組卡旁註。"""
    if not item:
        return ""
    ready = str(item.get("fund_side_note") or "").strip()
    if ready:
        return ready
    meta: Dict[str, Any] = {}
    yoy = _finite(item.get("fund_yoy_pct"))
    if yoy is not None:
        meta["yoy_pct"] = yoy
        ym = str(item.get("fund_yoy_yyyymm") or "").strip()
        if ym:
            meta["yyyymm"] = ym
    gm = _finite(item.get("fund_gross_margin_pct"))
    if gm is not None:
        meta["gross_margin_pct"] = gm
        if item.get("fund_gm_year") is not None:
            meta["year"] = item.get("fund_gm_year")
        if item.get("fund_gm_season") is not None:
            meta["season"] = item.get("fund_gm_season")
    return format_fund_side_note(meta, style="card")


def fund_side_paren_from_item(item: Optional[Mapping[str, Any]]) -> str:
    if not item:
        return ""
    ready = str(item.get("fund_side_paren") or "").strip()
    if ready:
        return ready
    meta: Dict[str, Any] = {}
    yoy = _finite(item.get("fund_yoy_pct"))
    if yoy is not None:
        meta["yoy_pct"] = yoy
    gm = _finite(item.get("fund_gross_margin_pct"))
    if gm is not None:
        meta["gross_margin_pct"] = gm
    return format_fund_side_note(meta, style="paren")
