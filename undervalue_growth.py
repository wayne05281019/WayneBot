# -*- coding: utf-8 -*-
"""真成長低估：假低估鐵律＋產業 PE 封頂＋今明目標價（估值≠買訊）。

與海選／黃金買點分開；切入仍只認高低卡黃金買點。
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --- 鐵律 ---
GROSS_MARGIN_MIN = 20.0
GROSS_MARGIN_AI_SERVER_MIN = 12.0
AI_SERVER_YOY_MIN = 100.0
CORE_RATIO_MIN = 0.75  # 營業利益／稅前（缺稅前→／稅後淨利，本業>0）
PEER_PE_HARD_CAP = 35.0
PEER_PE_IP_CAP = 45.0
QTY60_EMERGING_MAX = 400.0  # 低於此→興櫃／量小觀察池

# 成熟晶圓代工／標準型記憶體（力積電、晶豪等）不准剔除——使用者 2026-11-16 補鎖
_CYCLICAL_RE = re.compile(
    r"石化|塑膠|化工|原物料|不鏽鋼|鋼鐵|鋼胚|電線|電纜|銅價|"
    r"航運|貨櫃|散裝|"
    r"營建|建設|資產開發|交屋|潤泰|興富發|南港|輪胎",
    re.I,
)
_AI_SERVER_RE = re.compile(r"AI\s*伺服器|伺服器整機|高成長板卡|技嘉|永擎|AMAX", re.I)
_IP_RE = re.compile(r"\bIP\b|矽智財|IC\s*設計|ASIC", re.I)

INDUSTRY_PE: Dict[str, Tuple[float, float]] = {
    "ic_ip": (40.0, 32.0),
    "adv_pack_mat": (35.0, 28.0),
    "ai_server_parts": (28.0, 23.0),
    "optical": (26.0, 21.0),
    "ai_pcb": (26.0, 21.0),
    "ai_server_oem": (16.0, 14.0),
    "default": (22.0, 18.0),
}


def _finite(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _blob(*parts: Any) -> str:
    return " ".join(str(p or "") for p in parts)


def industry_bucket(chain: str = "", tags: Sequence[str] = (), name: str = "") -> str:
    blob = _blob(chain, " ".join(tags), name)
    # 記憶體／成熟晶圓先走 default，不准被「IC設計」誤判成 IP/ASIC 40 倍
    if re.search(r"記憶體|DRAM|SRAM|NAND|Flash|晶豪|力積|標準型", blob, re.I):
        return "default"
    if _IP_RE.search(blob) or re.search(r"矽智財|(?<!記憶體)IC設計|IP/ASIC", blob):
        return "ic_ip"
    if re.search(r"先進封裝|特化材料|半導體材料|設備", blob):
        return "adv_pack_mat"
    if re.search(r"導軌|連接器|散熱|電源模組", blob):
        return "ai_server_parts"
    if re.search(r"光通訊|CPO|高速網通|智邦|光聖", blob):
        return "optical"
    if re.search(r"PCB|CCL|銅箔基板|台光電|台燿|金像", blob):
        return "ai_pcb"
    if _AI_SERVER_RE.search(blob):
        return "ai_server_oem"
    return "default"


def select_fair_pe_pair(
    peer_med_raw: Optional[float], bucket: str
) -> Tuple[float, float, float]:
    """同鏈中位未破硬頂→用中位算目標價；破頂才改產業表。

    回傳 (pe_year, pe_next, peer_for_display)。
    """
    ind_y, ind_n = fair_pe_pair(bucket)
    cap = peer_pe_cap(bucket)
    med = _finite(peer_med_raw)
    if med is None or med <= 0:
        return float(ind_y), float(ind_n), float(ind_y)
    if med > cap:
        return float(ind_y), float(ind_n), float(ind_y)
    # 中位可信：今年用中位；明年按產業表比例縮
    scale = float(ind_n) / float(ind_y) if ind_y else 1.0
    return float(med), float(med) * scale, float(med)


def fair_pe_pair(bucket: str) -> Tuple[float, float]:
    return INDUSTRY_PE.get(bucket) or INDUSTRY_PE["default"]


def peer_pe_cap(bucket: str) -> float:
    return PEER_PE_IP_CAP if bucket == "ic_ip" else PEER_PE_HARD_CAP


def capped_peer_median(raw_med: Optional[float], bucket: str) -> Optional[float]:
    med = _finite(raw_med)
    if med is None or med <= 0:
        return None
    cap = peer_pe_cap(bucket)
    year_pe, _ = fair_pe_pair(bucket)
    if med > cap:
        return float(year_pe)
    return float(med)


def is_cyclical_trap(chain: str = "", tags: Sequence[str] = (), name: str = "") -> bool:
    return bool(_CYCLICAL_RE.search(_blob(chain, " ".join(tags), name)))


def passes_gross_margin(
    gm: Optional[float],
    *,
    yoy_pct: Optional[float] = None,
    bucket: str = "default",
    gm_prev: Optional[float] = None,
) -> bool:
    g = _finite(gm)
    if g is None:
        return False
    if g >= GROSS_MARGIN_MIN:
        return True
    if bucket == "ai_server_oem" and g >= GROSS_MARGIN_AI_SERVER_MIN:
        yoy = _finite(yoy_pct)
        prev = _finite(gm_prev)
        if yoy is not None and yoy >= AI_SERVER_YOY_MIN and prev is not None and g > prev:
            return True
    return False


def passes_core_ratio(op_income: Optional[float], pretax_or_net: Optional[float]) -> bool:
    op = _finite(op_income)
    base = _finite(pretax_or_net)
    if op is None or base is None:
        return False
    if op <= 0 or base <= 0:
        return False
    return (op / base) >= CORE_RATIO_MIN


def load_quarter_fundamentals(
    conn: sqlite3.Connection, sid: str, *, year: int = 2026, season: int = 3
) -> Dict[str, Any]:
    """官方季報：毛利／營業利益／淨利／EPS（累計可能）。"""
    out: Dict[str, Any] = {}
    try:
        rows = conn.execute(
            """
            SELECT year, season, gross_margin_pct, operating_income, net_income, eps, revenue
            FROM quarterly_income
            WHERE stock_id=? AND year=?
            ORDER BY season ASC
            """,
            (sid, int(year)),
        ).fetchall()
    except sqlite3.Error:
        return out
    by_s: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        try:
            s = int(r[1] if not isinstance(r, sqlite3.Row) else r["season"])
        except (TypeError, ValueError):
            continue
        by_s[s] = {
            "gross_margin_pct": _finite(
                r[2] if not isinstance(r, sqlite3.Row) else r["gross_margin_pct"]
            ),
            "operating_income": _finite(
                r[3] if not isinstance(r, sqlite3.Row) else r["operating_income"]
            ),
            "net_income": _finite(
                r[4] if not isinstance(r, sqlite3.Row) else r["net_income"]
            ),
            "eps": _finite(r[5] if not isinstance(r, sqlite3.Row) else r["eps"]),
            "revenue": _finite(r[6] if not isinstance(r, sqlite3.Row) else r["revenue"]),
        }
    out["by_season"] = by_s
    q = by_s.get(int(season)) or {}
    out.update(q)
    prev = by_s.get(int(season) - 1) or {}
    out["gross_margin_prev"] = prev.get("gross_margin_pct")
    try:
        from fundamentals import expand_ytd_income_eps_to_single

        ytd_rows = [
            {
                "year": year,
                "season": s,
                "eps": by_s[s].get("eps"),
                "revenue": by_s[s].get("revenue") or 0.0,
            }
            for s in sorted(by_s)
        ]
        single = expand_ytd_income_eps_to_single(ytd_rows)
        out["eps_single"] = single.get((year, int(season)))
        out["eps_map"] = single
    except Exception:
        out["eps_single"] = None
        out["eps_map"] = {}
    return out


def load_chain_blob(conn: sqlite3.Connection, sid: str) -> Tuple[str, List[str]]:
    try:
        row = conn.execute(
            "SELECT chain, tags_json FROM stock_fine_industry WHERE stock_id=?",
            (sid,),
        ).fetchone()
    except sqlite3.Error:
        return "", []
    if not row:
        return "", []
    chain = str(row[0] or "")
    tags: List[str] = []
    try:
        tags = list(json.loads(row[1] or "[]"))
    except Exception:
        tags = [t for t in chain.split("-") if t]
    return chain, tags


def load_recent_moms(
    conn: sqlite3.Connection, sid: str, *, n: int = 3
) -> Tuple[List[Optional[float]], Optional[float], Optional[float], int]:
    """近 n 月 mom_pct、最新營收、YTD、最新月 m_last。"""
    try:
        rows = conn.execute(
            """
            SELECT yyyymm, revenue, mom_pct, ytd_revenue
            FROM monthly_revenue
            WHERE stock_id=? AND revenue IS NOT NULL AND revenue > 0
            ORDER BY yyyymm DESC LIMIT ?
            """,
            (sid, max(1, int(n))),
        ).fetchall()
    except sqlite3.Error:
        return [], None, None, 0
    if not rows:
        return [], None, None, 0
    moms = [
        _finite(r[2] if not isinstance(r, sqlite3.Row) else r["mom_pct"]) for r in rows
    ]
    last_rev = _finite(rows[0][1] if not isinstance(rows[0], sqlite3.Row) else rows[0]["revenue"])
    ytd = _finite(rows[0][3] if not isinstance(rows[0], sqlite3.Row) else rows[0]["ytd_revenue"])
    yyyymm = str(
        rows[0][0] if not isinstance(rows[0], sqlite3.Row) else rows[0]["yyyymm"] or ""
    )
    m_last = int(yyyymm[-2:]) if len(yyyymm) >= 6 and yyyymm[-2:].isdigit() else 0
    return moms, last_rev, ytd, m_last


def estimate_eps_year_next(
    *,
    eps_ytd_cum: Optional[float],
    eps_q3_single: Optional[float],
    ytd_rev: Optional[float],
    last_rev: Optional[float],
    moms: Sequence[Optional[float]],
    m_last: int,
    yoy_pct: Optional[float],
) -> Dict[str, Any]:
    """2026 全年／2027 預估 EPS（營收外推×動能）。缺官方數→ok False。"""
    from undervalue_scan import clamp_mom_g, estimate_year_revenue

    est_rev = estimate_year_revenue(
        float(ytd_rev or 0),
        float(last_rev or 0),
        moms,
        m_last=m_last,
        mom_unit="pct",
        yoy_pct=yoy_pct,
    )
    if not est_rev.get("ok"):
        return {"ok": False, "note": est_rev.get("note") or "缺營收"}
    year_rev = float(est_rev["est_year_rev"])
    q3 = _finite(eps_q3_single)
    if q3 is None or q3 <= 0:
        cum = _finite(eps_ytd_cum)
        if cum is None or cum <= 0:
            return {"ok": False, "note": "缺EPS"}
        q3 = cum / 3.0
    g, _ = clamp_mom_g(moms, unit="pct")
    q4 = float(q3) * (1.0 + g * 0.5)
    # 若 eps_q3_single 真單季：全年≈Q1+Q2+Q3+Q4；缺單季 map 時用 3×q3+q4
    eps_map_sum = None
    eps_2026 = float(q3) * 3.0 + float(q4)
    yoy = _finite(yoy_pct)
    growth = 0.10
    if yoy is not None:
        growth = max(-0.05, min(0.25, yoy / 100.0))
    eps_2027 = eps_2026 * (1.0 + growth)
    next_rev = year_rev * (1.0 + growth)
    thr_yi = next_rev / 12.0 / 100000.0  # 千元→億
    oct_yi = float(last_rev or 0) / 100000.0
    return {
        "ok": True,
        "eps_2026": eps_2026,
        "eps_2027": eps_2027,
        "year_rev": year_rev,
        "rev_threshold_yi": thr_yi,
        "rev_oct_yi": oct_yi,
        "g": g,
        "growth": growth,
        "est_rev": est_rev,
        "eps_map_sum": eps_map_sum,
    }


def price_targets(
    close: float,
    pe_now: float,
    eps_2026: float,
    eps_2027: float,
    pe_year: float,
    pe_next: float,
) -> Dict[str, Any]:
    fair = float(eps_2026) * float(pe_year)
    tgt = float(eps_2027) * float(pe_next)
    c = float(close)
    return {
        "fair_year": fair,
        "target_next": tgt,
        "ups_fair_pct": ((fair / c) - 1.0) * 100.0 if c > 0 else None,
        "ups_tgt_pct": ((tgt / c) - 1.0) * 100.0 if c > 0 else None,
        "pe_now": pe_now,
        "pe_year": pe_year,
        "pe_next": pe_next,
    }


def vol_support_note(
    conn: sqlite3.Connection, sid: str, as_of: str, close: float
) -> Dict[str, Any]:
    """近 60 日最大量那天的低＝大量區撐近似；破＝等止穩。"""
    day = str(as_of or "").replace("-", "")[:8]
    out: Dict[str, Any] = {"support": None, "status": "—", "broken": False}
    if len(day) != 8:
        return out
    try:
        rows = conn.execute(
            """
            SELECT date, high, low, close, volume FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
              AND volume IS NOT NULL AND volume > 0
            ORDER BY date DESC LIMIT 60
            """,
            (sid, day),
        ).fetchall()
    except sqlite3.Error:
        return out
    if not rows:
        return out
    best = max(rows, key=lambda r: float(r[4] or 0))
    lo = _finite(best[2])
    if lo is None:
        return out
    out["support"] = float(lo)
    if float(close) < float(lo) * 0.995:
        out["broken"] = True
        out["status"] = f"跌破大量區撐 {lo:.0f}，先看表等止穩"
    else:
        out["status"] = f"站回支撐區（大量區撐 {lo:.0f}）"
    return out


def trust_5d_note(conn: sqlite3.Connection, sid: str, as_of: str) -> str:
    day = str(as_of or "").replace("-", "")[:8]
    if len(day) != 8:
        return ""
    try:
        rows = conn.execute(
            """
            SELECT foreign_net, investment_net FROM daily_chips
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
            ORDER BY date DESC LIMIT 5
            """,
            (sid, day),
        ).fetchall()
    except sqlite3.Error:
        return ""
    if not rows:
        return ""
    inv = sum(float(_finite(r[1]) or 0) for r in rows)
    frn = sum(float(_finite(r[0]) or 0) for r in rows)
    bits = []
    if inv > 0:
        bits.append("投信近5日買超")
    elif inv < 0:
        bits.append("投信近5日賣超")
    if frn < 0:
        bits.append("外資近5日賣超")
    return "／".join(bits)


def growth_gate(
    *,
    chain: str,
    tags: Sequence[str],
    name: str,
    gm: Optional[float],
    gm_prev: Optional[float],
    op: Optional[float],
    net: Optional[float],
    yoy_pct: Optional[float],
    bucket: str,
) -> Tuple[bool, str]:
    if is_cyclical_trap(chain, tags, name):
        return False, "景氣循環／傳產／營建黑名單"
    if not passes_gross_margin(gm, yoy_pct=yoy_pct, bucket=bucket, gm_prev=gm_prev):
        return False, "毛利未達門檻"
    if not passes_core_ratio(op, net):
        return False, "本業占比不足或本業≤0"
    return True, ""


def enrich_growth_row(
    conn: sqlite3.Connection,
    *,
    sid: str,
    name: str,
    close: float,
    pe: float,
    peer_med_raw: float,
    as_of: str,
    yoy_pct: Optional[float],
    qty60: float,
    market_type: str = "",
) -> Optional[Dict[str, Any]]:
    """通過鐵律＋可推估目標價才回傳 detail；否則 None。"""
    chain, tags = load_chain_blob(conn, sid)
    bucket = industry_bucket(chain, tags, name)
    fund = load_quarter_fundamentals(conn, sid, year=2026, season=3)
    gm = fund.get("gross_margin_pct")
    gm_prev = fund.get("gross_margin_prev")
    op = fund.get("operating_income")
    net = fund.get("net_income")
    ok, why = growth_gate(
        chain=chain,
        tags=tags,
        name=name,
        gm=gm,
        gm_prev=gm_prev,
        op=op,
        net=net,
        yoy_pct=yoy_pct,
        bucket=bucket,
    )
    if not ok:
        return None
    med_cap = capped_peer_median(peer_med_raw, bucket)
    if med_cap is None:
        return None
    # 中位未破硬頂→用中位；破頂→產業表（不准再無視中位硬套 40 倍）
    use_pe_year, use_pe_next, _peer_disp = select_fair_pe_pair(peer_med_raw, bucket)

    moms, last_rev, ytd_rev, m_last = load_recent_moms(conn, sid, n=3)
    eps_est = estimate_eps_year_next(
        eps_ytd_cum=fund.get("eps"),
        eps_q3_single=fund.get("eps_single"),
        ytd_rev=ytd_rev,
        last_rev=last_rev,
        moms=moms,
        m_last=m_last or 10,
        yoy_pct=yoy_pct,
    )
    if not eps_est.get("ok"):
        return None
    tg = price_targets(
        float(close),
        float(pe),
        float(eps_est["eps_2026"]),
        float(eps_est["eps_2027"]),
        use_pe_year,
        use_pe_next,
    )
    supp = vol_support_note(conn, sid, as_of, float(close))
    chip = trust_5d_note(conn, sid, as_of)
    core_pct = None
    if _finite(op) and _finite(net) and float(net) > 0:
        core_pct = float(op) / float(net) * 100.0
    industry = ""
    if tags:
        industry = str(tags[-1])
    elif chain:
        industry = chain.split("-")[-1]
    emerging = (
        str(market_type or "").upper() in ("ROTC", "興櫃", "EMERGING")
        or float(qty60 or 0) < QTY60_EMERGING_MAX
    )
    broken = bool(supp.get("broken"))
    foreign_sell = "外資近5日賣超" in chip
    return {
        "chain": chain,
        "industry": industry or bucket,
        "bucket": bucket,
        "gross_margin": gm,
        "core_ratio_pct": core_pct,
        "yoy_pct": yoy_pct,
        "peer_pe_median_raw": float(peer_med_raw),
        "peer_pe_median": float(med_cap),
        "fair_year": tg["fair_year"],
        "target_next": tg["target_next"],
        "ups_fair_pct": tg["ups_fair_pct"],
        "ups_tgt_pct": tg["ups_tgt_pct"],
        "pe_year": use_pe_year,
        "pe_next": use_pe_next,
        "eps_2026": eps_est["eps_2026"],
        "eps_2027": eps_est["eps_2027"],
        "rev_threshold_yi": eps_est["rev_threshold_yi"],
        "rev_oct_yi": eps_est["rev_oct_yi"],
        "support": supp.get("support"),
        "tech_status": supp.get("status"),
        "tech_broken": broken,
        "chip_note": chip,
        "emerging": emerging,
        "prefer_watch": broken or foreign_sell,
        "gate_note": why,
    }
