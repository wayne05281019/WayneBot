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
PEER_PE_CYCLICAL_CAP = 18.0
PEER_PE_FINANCE_CAP = 18.0
PEER_PE_BIOTECH_CAP = 25.0
QTY60_EMERGING_MAX = 400.0  # 低於此→興櫃／量小觀察池
STAR_UPS_TGT_MIN = 25.0  # ★可買：明年空間 ≥ +25%
# 滾動同業本益：樣本與極端值閘（官方收／季 EPS；不准寫死 25）
PEER_PE_MEDIAN_MIN_N = 8
PEER_PE_MEDIAN_LO = 3.0
PEER_PE_MEDIAN_HI = 80.0

# D3 硬剔除（DRAM 週期／電子通路；不准再進低估名單）
HARD_EXCLUDE_SIDS = frozenset({"3006", "6265"})
# 產業標強制覆寫（8069 元太＝電子紙，不准 TFT 面板）
INDUSTRY_FORCE = {"8069": "電子紙"}

# 景氣循環／通路／DRAM 週期黑名單；成熟晶圓代工（力積電等）仍不進此網
_CYCLICAL_RE = re.compile(
    r"石化|塑膠|化工|原物料|不鏽鋼|鋼鐵|鋼胚|電線|電纜|銅價|"
    r"航運|貨櫃|散裝|"
    r"營建|建設|資產開發|交屋|潤泰|興富發|南港|輪胎|"
    r"通路|經銷|代理商|電子通路|"
    r"DRAM|標準型記憶體|記憶體週期|記憶體IC",
    re.I,
)
_FINANCE_RE = re.compile(r"金融|保險|銀行|證券|金控", re.I)
_BIOTECH_RE = re.compile(r"生技|醫療|製藥|醫材|診所", re.I)
_AI_SERVER_RE = re.compile(r"AI\s*伺服器|伺服器整機|高成長板卡|技嘉|永擎|AMAX", re.I)
_IP_RE = re.compile(r"\bIP\b|矽智財|IC\s*設計|ASIC", re.I)

# 產業表＝「同業滾動中位缺樣／爆表」時的備援與硬頂，不是日常合理倍數來源。
# 特殊成長桶僅留市場長期共識偏高者；循環／金融／生技／一般備援對齊庫內粗產業中位帶。
INDUSTRY_PE: Dict[str, Tuple[float, float]] = {
    # 特殊（有共識才留高倍）
    "ic_ip": (40.0, 32.0),  # 矽智財／ASIC
    "adv_pack_mat": (35.0, 28.0),  # 先進封裝材料
    "ai_server_parts": (28.0, 23.0),  # AI 伺服器零組件
    "optical": (26.0, 21.0),  # 光通訊／CPO
    "ai_pcb": (26.0, 21.0),  # AI PCB／CCL
    "ai_server_oem": (16.0, 14.0),  # 伺服器整機毛利薄
    # 一般／循環備援（庫內中位約：航運9、營建10、鋼鐵13、多數電子13–20）
    "cyclical": (12.0, 10.0),
    "finance": (12.0, 11.0),
    "biotech": (15.0, 12.0),
    "default": (16.0, 13.0),
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
    # 記憶體／成熟晶圓先走 cyclical／default，不准被「IC設計」誤判成 IP/ASIC 40 倍
    if re.search(r"記憶體|DRAM|SRAM|NAND|Flash|晶豪|力積|標準型", blob, re.I):
        return "cyclical" if _CYCLICAL_RE.search(blob) else "default"
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
    if _FINANCE_RE.search(blob):
        return "finance"
    if _BIOTECH_RE.search(blob):
        return "biotech"
    if _CYCLICAL_RE.search(blob):
        return "cyclical"
    return "default"


def select_fair_pe_pair(
    peer_med_raw: Optional[float], bucket: str
) -> Tuple[float, float, float]:
    """合理 PE：優先滾動同業中位；缺樣／爆表才退產業備援表。

    回傳 (pe_year, pe_next, peer_for_display)。
    不准寫死 25 當同業中位。
    """
    ind_y, ind_n = fair_pe_pair(bucket)
    cap = peer_pe_cap(bucket)
    med = _finite(peer_med_raw)
    if med is None or med <= 0:
        return float(ind_y), float(ind_n), float(ind_y)
    if med > cap:
        return float(ind_y), float(ind_n), float(ind_y)
    # 中位可信：今年用滾動中位；明年按備援表比例略縮
    scale = float(ind_n) / float(ind_y) if ind_y else 1.0
    return float(med), float(med) * scale, float(med)


def fair_pe_pair(bucket: str) -> Tuple[float, float]:
    return INDUSTRY_PE.get(bucket) or INDUSTRY_PE["default"]


def peer_pe_cap(bucket: str) -> float:
    b = str(bucket or "")
    if b == "ic_ip":
        return PEER_PE_IP_CAP
    if b == "cyclical":
        return PEER_PE_CYCLICAL_CAP
    if b == "finance":
        return PEER_PE_FINANCE_CAP
    if b == "biotech":
        return PEER_PE_BIOTECH_CAP
    return PEER_PE_HARD_CAP


def _median_sorted(vals: Sequence[float]) -> Optional[float]:
    xs = sorted(float(v) for v in vals if _finite(v) is not None)
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    if n % 2:
        return float(xs[mid])
    return float(xs[mid - 1] + xs[mid]) / 2.0


def _annualize_cum_eps(eps: float, season: int) -> Optional[float]:
    e = _finite(eps)
    if e is None or e <= 0:
        return None
    s = int(season or 0)
    if s >= 4:
        return float(e)
    if s == 3:
        return float(e) * 4.0 / 3.0
    if s == 2:
        return float(e) * 2.0
    if s == 1:
        return float(e) * 4.0
    return None


def twse_industry_peer_pe_median(
    conn: sqlite3.Connection,
    sid: str,
    *,
    as_of: str,
    min_n: int = PEER_PE_MEDIAN_MIN_N,
) -> Dict[str, Any]:
    """證交所粗產業同業本益滾動中位（官方收／季累計 EPS）。

    來源：stock_universe.industry ＋ daily_quotes.close ＋ quarterly_income.eps。
    年化：Q1×4、Q2×2、Q3×4/3、Q4 用全年。極端值剔除後取中位。
    樣本不足回 median=None（呼叫端改吃產業備援表）。
    """
    empty = {
        "median": None,
        "n": 0,
        "industry": "",
        "source": "twse_industry_peer_pe",
    }
    sid_s = str(sid or "").strip()
    day = str(as_of or "").replace("-", "")[:8]
    if len(sid_s) != 4 or len(day) != 8:
        return empty
    try:
        row = conn.execute(
            """
            SELECT COALESCE(industry, '') FROM stock_universe
            WHERE stock_id=? LIMIT 1
            """,
            (sid_s,),
        ).fetchone()
    except sqlite3.Error:
        return empty
    industry = str(row[0] if row else "").strip()
    if not industry:
        return empty
    try:
        peers = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT stock_id FROM stock_universe
                WHERE industry=? AND length(stock_id)=4
                  AND UPPER(COALESCE(market_type,'')) IN ('TW','TWO','TSE','OTC','')
                """,
                (industry,),
            ).fetchall()
            if r and r[0]
        ]
    except sqlite3.Error:
        return empty
    pes: List[float] = []
    for psid in peers:
        try:
            cq = conn.execute(
                """
                SELECT close FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                  AND close IS NOT NULL AND close>0
                ORDER BY date DESC LIMIT 1
                """,
                (psid, day),
            ).fetchone()
            eq = conn.execute(
                """
                SELECT eps, season FROM quarterly_income
                WHERE stock_id=? AND eps IS NOT NULL AND eps>0
                ORDER BY year DESC, season DESC LIMIT 1
                """,
                (psid,),
            ).fetchone()
        except sqlite3.Error:
            continue
        if not cq or not eq:
            continue
        close = _finite(cq[0])
        ann = _annualize_cum_eps(float(eq[0]), int(eq[1] or 0))
        if close is None or ann is None or ann <= 0:
            continue
        pe = float(close) / float(ann)
        if pe < PEER_PE_MEDIAN_LO or pe > PEER_PE_MEDIAN_HI:
            continue
        pes.append(pe)
    med = _median_sorted(pes)
    if med is None or len(pes) < int(min_n):
        return {
            "median": None,
            "n": len(pes),
            "industry": industry,
            "source": "twse_industry_peer_pe",
        }
    return {
        "median": float(med),
        "n": len(pes),
        "industry": industry,
        "source": "twse_industry_peer_pe",
    }


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


def is_hard_excluded(sid: str) -> bool:
    return str(sid or "").strip() in HARD_EXCLUDE_SIDS


def resolve_stock_name(
    conn: sqlite3.Connection, sid: str, raw_name: str = ""
) -> str:
    """股名缺／等於代號 → 查 stock_universe；不准印成「2383 2383」。"""
    sid_s = str(sid or "").strip()
    name = str(raw_name or "").strip()
    if name and name != sid_s and not name.isdigit():
        return name
    try:
        row = conn.execute(
            "SELECT stock_name FROM stock_universe WHERE stock_id=?",
            (sid_s,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row is not None:
        uni = str(
            row[0] if not isinstance(row, sqlite3.Row) else row["stock_name"] or ""
        ).strip()
        if uni and uni != sid_s:
            return uni
    return name if name and name != sid_s else sid_s


def format_core_ratio(core_pct: Optional[float]) -> str:
    """本業比 ≥100% →『純本業』；否則整數％。"""
    v = _finite(core_pct)
    if v is None:
        return "—"
    if v >= 100.0:
        return "純本業"
    return f"{v:.0f}%"


def resolve_industry_label(
    sid: str, tags: Sequence[str] = (), chain: str = ""
) -> str:
    force = INDUSTRY_FORCE.get(str(sid or "").strip())
    if force:
        return force
    if tags:
        return str(tags[-1])
    if chain:
        return str(chain).split("-")[-1]
    return ""


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


def _yoy_growth_frac(yoy_pct: Optional[float], *, default: float = 0.10) -> float:
    """營收 YoY％→成長小數；夾在 −5%～+25%。缺 YoY 用 default（不是假獲利）。"""
    yoy = _finite(yoy_pct)
    if yoy is None:
        return float(default)
    return max(-0.05, min(0.25, yoy / 100.0))


def estimate_eps_year_next(
    *,
    eps_ytd_cum: Optional[float],
    eps_q3_single: Optional[float] = None,
    eps_q_last_single: Optional[float] = None,
    last_season: int = 3,
    prior_year_eps: Optional[float] = None,
    ytd_rev: Optional[float],
    last_rev: Optional[float],
    moms: Sequence[Optional[float]],
    m_last: int,
    yoy_pct: Optional[float],
    rev_year_matches: bool = True,
    guidance_g: Optional[float] = None,
    guidance_eps_abs: Optional[float] = None,
    guidance_note: str = "",
) -> Dict[str, Any]:
    """今年／明年預估 EPS。未公布季＝末季單季×(1+g/2) 逐季遞推；不准 Q×3 冒充。

    路徑（有官方才走；缺→ok False）：
    1) 公司公告全年 EPS 絕對值（重大訊息可量化句）→ 直接用。
    2) 已公布累計季＋剩餘季遞推；步進 g 優先用公告 QoQ％，否則近三月 MoM 夾限。
    3) 尚無今年季報：去年全年 EPS×YoY 夾限（一月～Q1 公布前）。
    """
    from undervalue_scan import clamp_mom_g, estimate_year_revenue

    growth = _yoy_growth_frac(yoy_pct)
    g_mom, _ = clamp_mom_g(moms, unit="pct")
    g_guide = _finite(guidance_g)
    g = float(g_guide) if g_guide is not None else float(g_mom)
    g_source = "公告QoQ" if g_guide is not None else "MoM"
    last_q = _finite(eps_q_last_single)
    if last_q is None:
        last_q = _finite(eps_q3_single)
    cum = _finite(eps_ytd_cum)
    try:
        ls = int(last_season or 0)
    except (TypeError, ValueError):
        ls = 0

    est_rev: Dict[str, Any] = {"ok": False}
    year_rev = None
    if rev_year_matches:
        est_rev = estimate_year_revenue(
            float(ytd_rev or 0),
            float(last_rev or 0),
            moms,
            m_last=m_last,
            mom_unit="pct",
            yoy_pct=yoy_pct,
        )
        if est_rev.get("ok"):
            year_rev = float(est_rev["est_year_rev"])

    method = ""
    eps_this = None
    abs_eps = _finite(guidance_eps_abs)
    if abs_eps is not None and abs_eps > 0:
        eps_this = float(abs_eps)
        method = "公司公告全年EPS絕對值"
        if year_rev is None and rev_year_matches and est_rev.get("ok"):
            year_rev = float(est_rev["est_year_rev"])
        elif year_rev is None and _finite(ytd_rev) and float(ytd_rev or 0) > 0:
            year_rev = float(ytd_rev) * (1.0 + growth)
            est_rev = {"ok": True, "est_year_rev": year_rev, "label": "營收備援", "note": method}

    if eps_this is None and ls in (1, 2, 3, 4) and cum is not None and cum > 0:
        if last_q is None or last_q <= 0:
            last_q = float(cum) / float(ls)
        rem_n = max(0, 4 - ls)
        rem = 0.0
        cur = float(last_q)
        for _ in range(rem_n):
            cur = cur * (1.0 + g * 0.5)
            rem += cur
        eps_this = float(cum) + rem
        method = f"Q1–Q{ls}累計＋剩餘{rem_n}季(末季×(1+{g_source}/2))"
    elif eps_this is None:
        prior = _finite(prior_year_eps)
        if prior is None or prior <= 0:
            return {"ok": False, "note": "缺今年季報與去年全年EPS"}
        eps_this = float(prior) * (1.0 + growth)
        method = "尚無今年季報；去年全年×YoY夾限"
        if year_rev is None and _finite(ytd_rev) and float(ytd_rev or 0) > 0 and not rev_year_matches:
            # 月營收還停在去年：用去年 YTD（≈全年）×成長當今年營收推估
            year_rev = float(ytd_rev) * (1.0 + growth)
            est_rev = {"ok": True, "est_year_rev": year_rev, "label": "去年營收×YoY", "note": method}

    if year_rev is None or not est_rev.get("ok"):
        return {"ok": False, "note": est_rev.get("note") or "缺營收"}
    if eps_this is None or eps_this <= 0:
        return {"ok": False, "note": "缺EPS"}

    eps_next = float(eps_this) * (1.0 + growth)
    next_rev = float(year_rev) * (1.0 + growth)
    thr_yi = next_rev / 12.0 / 100000.0  # 千元→億
    oct_yi = float(last_rev or 0) / 100000.0
    return {
        "ok": True,
        "eps_2026": float(eps_this),
        "eps_2027": float(eps_next),
        "year_rev": float(year_rev),
        "rev_threshold_yi": thr_yi,
        "rev_oct_yi": oct_yi,
        "g": g,
        "growth": growth,
        "est_rev": est_rev,
        "eps_map_sum": None,
        "last_season": ls,
        "method": method,
        "g_source": g_source,
        "guidance_note": str(guidance_note or "")[:120],
    }


def price_targets(
    close: float,
    pe_now: float,
    eps_2026: float,
    eps_2027: float,
    pe_year: float,
    pe_next: float,
) -> Dict[str, Any]:
    """今年＝EPS今×合理PE今；明年＝EPS明×合理PE明。

    若兩目標幾乎相同（倍數縮與成長互消），不准靜默複製：
    改用明年EPS×今年倍數，仍相等再按成長率誠實上修明年目標。
    """
    e6 = float(eps_2026)
    e7 = float(eps_2027)
    py = float(pe_year)
    pn = float(pe_next)
    fair = e6 * py
    tgt = e7 * pn
    if fair > 0 and abs(tgt - fair) / fair < 0.01:
        tgt = e7 * py
    if fair > 0 and abs(tgt - fair) / fair < 0.01:
        g = (e7 / e6 - 1.0) if e6 > 0 else 0.0
        if g <= 0.001:
            g = 0.08
        tgt = fair * (1.0 + g)
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
    """大量區撐壓：優先 ``vol_zone_chart.find_volume_zone``（壓=高、撐=低）。

    缺柱退回近 60 日最大量日低點近似。破撐→等止穩。
    """
    day = str(as_of or "").replace("-", "")[:8]
    out: Dict[str, Any] = {
        "support": None,
        "resistance": None,
        "status": "—",
        "broken": False,
    }
    if len(day) != 8:
        return out
    zone = _find_vol_zone(conn, sid, day)
    if zone:
        lo = _finite(zone.get("low"))
        hi = _finite(zone.get("high"))
        if lo is not None:
            out["support"] = float(lo)
        if hi is not None:
            out["resistance"] = float(hi)
        if lo is not None and float(close) < float(lo) * 0.995:
            out["broken"] = True
            out["status"] = f"跌破大量區撐 {lo:.0f}，先看表等止穩"
        elif lo is not None:
            out["status"] = f"站回支撐區（大量區撐 {lo:.0f}）"
        return out
    # 退回：近 60 日最大量那天的低
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
    hi = _finite(best[1])
    if lo is None:
        return out
    out["support"] = float(lo)
    if hi is not None:
        out["resistance"] = float(hi)
    if float(close) < float(lo) * 0.995:
        out["broken"] = True
        out["status"] = f"跌破大量區撐 {lo:.0f}，先看表等止穩"
    else:
        out["status"] = f"站回支撐區（大量區撐 {lo:.0f}）"
    return out


def _find_vol_zone(
    conn: sqlite3.Connection, sid: str, day: str
) -> Optional[Dict[str, Any]]:
    try:
        import pandas as pd
        from vol_zone_chart import find_volume_zone
    except Exception:
        return None
    try:
        rows = conn.execute(
            """
            SELECT date, open, high, low, close, volume FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
              AND close IS NOT NULL AND close > 0
            ORDER BY date ASC
            """,
            (sid, day),
        ).fetchall()
    except sqlite3.Error:
        return None
    if len(rows) < 12:
        return None
    work = pd.DataFrame(
        [
            {
                "date": str(r[0]),
                "open": float(r[1] or 0),
                "high": float(r[2] or 0),
                "low": float(r[3] or 0),
                "close": float(r[4] or 0),
                "volume": float(r[5] or 0),
            }
            for r in rows
        ]
    )
    try:
        return find_volume_zone(work)
    except Exception:
        return None


def _streak_from_nets(
    nets: Sequence[Tuple[float, float]],
) -> Dict[str, Any]:
    """由新到舊的 (foreign_net, trust_net) 算連買／連賣膠囊。"""
    if not nets:
        return {
            "capsule": "",
            "chip_kind": "",
            "foreign_streak": 0,
            "trust_streak": 0,
            "both_buy": False,
            "both_sell": False,
            "foreign_sell": False,
        }
    f0, t0 = float(nets[0][0]), float(nets[0][1])
    both_buy = f0 > 0 and t0 > 0
    both_sell = f0 < 0 and t0 < 0
    foreign_sell = f0 < 0

    def _streak(pred) -> int:
        n = 0
        for f, t in nets:
            if not pred(float(f), float(t)):
                break
            n += 1
        return n

    f_buy = _streak(lambda f, t: f > 0)
    t_buy = _streak(lambda f, t: t > 0)
    both_buy_n = _streak(lambda f, t: f > 0 and t > 0)
    capsule = ""
    kind = ""
    if both_sell:
        capsule, kind = "外投同賣", "both_sell"
    elif both_buy or both_buy_n >= 1:
        capsule, kind = "外投同買", "both_buy"
    elif t_buy >= 2:
        capsule, kind = f"投信連買{t_buy}日", "trust_buy"
    elif f_buy >= 2:
        capsule, kind = f"外資連買{f_buy}日", "foreign_buy"
    elif t0 > 0 and f0 <= 0:
        capsule, kind = "投信買・外資調節", "trust_buy_foreign_adj"
    elif t_buy == 1:
        capsule, kind = "投信連買1日", "trust_buy"
    elif f_buy == 1:
        capsule, kind = "外資連買1日", "foreign_buy"
    return {
        "capsule": capsule,
        "chip_kind": kind,
        "foreign_streak": f_buy,
        "trust_streak": t_buy,
        "both_buy": both_buy,
        "both_sell": both_sell,
        "foreign_sell": foreign_sell,
    }


def chip_capsule_note(conn: sqlite3.Connection, sid: str, as_of: str) -> Dict[str, Any]:
    """籌碼膠囊：讀 ``daily_quotes.foreign_net``／``trust_net`` 連買日數。

    不准用壞掉的 ``daily_chips`` 表。興櫃無法人→空膠囊由呼叫端標。
    """
    day = str(as_of or "").replace("-", "")[:8]
    empty = {
        "capsule": "",
        "chip_kind": "",
        "foreign_streak": 0,
        "trust_streak": 0,
        "both_buy": False,
        "both_sell": False,
        "foreign_sell": False,
    }
    if len(day) != 8:
        return empty
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(foreign_net, 0), COALESCE(trust_net, 0)
            FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
            ORDER BY date DESC LIMIT 80
            """,
            (sid, day),
        ).fetchall()
    except sqlite3.Error:
        return empty
    nets = [
        (
            float(_finite(r[0]) or 0),
            float(_finite(r[1]) or 0),
        )
        for r in rows
    ]
    return _streak_from_nets(nets)


def trust_5d_note(conn: sqlite3.Connection, sid: str, as_of: str) -> str:
    """相容舊欄：回傳膠囊字串（來源改 daily_quotes 連買）。"""
    return str(chip_capsule_note(conn, sid, as_of).get("capsule") or "")


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
    sid_s = str(sid or "").strip()
    if is_hard_excluded(sid_s):
        return None
    name_s = resolve_stock_name(conn, sid_s, name)
    chain, tags = load_chain_blob(conn, sid_s)
    bucket = industry_bucket(chain, tags, name_s)
    try:
        fy = int(str(as_of or "").replace("-", "")[:4])
    except ValueError:
        fy = 2026
    # 先讀全年季次，取最新已公布季（不准寫死 season=3）
    fund_probe = load_quarter_fundamentals(conn, sid_s, year=fy, season=3)
    by_s = fund_probe.get("by_season") or {}
    last_s = max(int(k) for k in by_s) if by_s else 0
    fund = (
        load_quarter_fundamentals(conn, sid_s, year=fy, season=last_s)
        if last_s
        else fund_probe
    )
    prior_fund = load_quarter_fundamentals(conn, sid_s, year=fy - 1, season=4)
    prior_eps = _finite(prior_fund.get("eps"))
    gm = fund.get("gross_margin_pct")
    gm_prev = fund.get("gross_margin_prev")
    op = fund.get("operating_income")
    net = fund.get("net_income")
    # 尚無今年季報：毛利鐵律改看去年 Q4（有官方才過閘；不准空白過）
    if last_s <= 0:
        gm = prior_fund.get("gross_margin_pct")
        gm_prev = prior_fund.get("gross_margin_prev")
        op = prior_fund.get("operating_income")
        net = prior_fund.get("net_income")
    ok, why = growth_gate(
        chain=chain,
        tags=tags,
        name=name_s,
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

    moms, last_rev, ytd_rev, m_last = load_recent_moms(conn, sid_s, n=3)
    # 月營收 yyyymm 年份須對得上估的會計年；一月常還停在去年 12 月
    rev_year_matches = True
    try:
        # load_recent_moms 只回 m_last；用 last 列的 ytd 年份需再查
        row_ym = conn.execute(
            "SELECT yyyymm FROM monthly_revenue WHERE stock_id=? "
            "AND revenue IS NOT NULL AND revenue>0 ORDER BY yyyymm DESC LIMIT 1",
            (sid_s,),
        ).fetchone()
        ym = str(row_ym[0] if row_ym else "")
        if len(ym) >= 6 and int(ym[:4]) != fy:
            rev_year_matches = False
    except Exception:
        rev_year_matches = True
    guide: Dict[str, Any] = {}
    g_note = ""
    g_step = None
    g_abs = None
    try:
        from company_guidance import (
            format_guidance_note,
            guidance_step_g,
            load_latest_guidance,
        )

        db_path = ""
        for _row in conn.execute("PRAGMA database_list"):
            if str(_row[1]) == "main":
                db_path = str(_row[2] or "")
                break
        if db_path:
            guide = load_latest_guidance(db_path, sid_s)
            g_note = format_guidance_note(guide)
            g_step = guidance_step_g(guide)
            if str(guide.get("kind") or "") == "eps_year_abs":
                g_abs = _finite(guide.get("value"))
    except Exception:
        guide = {}
    eps_est = estimate_eps_year_next(
        eps_ytd_cum=fund.get("eps") if last_s else None,
        eps_q_last_single=fund.get("eps_single") if last_s else None,
        last_season=last_s,
        prior_year_eps=prior_eps,
        ytd_rev=ytd_rev,
        last_rev=last_rev,
        moms=moms,
        m_last=m_last or 10,
        yoy_pct=yoy_pct,
        rev_year_matches=rev_year_matches,
        guidance_g=g_step,
        guidance_eps_abs=g_abs,
        guidance_note=g_note,
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
    supp = vol_support_note(conn, sid_s, as_of, float(close))
    chip_info = chip_capsule_note(conn, sid_s, as_of)
    chip = str(chip_info.get("capsule") or "")
    core_pct = None
    if _finite(op) and _finite(net) and float(net) > 0:
        core_pct = float(op) / float(net) * 100.0
    industry = resolve_industry_label(sid_s, tags, chain) or bucket
    emerging = (
        str(market_type or "").upper() in ("ROTC", "興櫃", "EMERGING")
        or float(qty60 or 0) < QTY60_EMERGING_MAX
    )
    if emerging and not chip:
        chip = "興櫃無法人"
        chip_info = dict(chip_info)
        chip_info["capsule"] = chip
        chip_info["chip_kind"] = "emerging"
    broken = bool(supp.get("broken"))
    both_sell = bool(chip_info.get("both_sell"))
    foreign_sell = bool(chip_info.get("foreign_sell")) or both_sell
    ups_tgt = _finite(tg.get("ups_tgt_pct"))
    d3_star = (
        ups_tgt is not None
        and ups_tgt >= STAR_UPS_TGT_MIN
        and not broken
        and not both_sell
        and not emerging
    )
    # 前瞻本益＝現價／明年EPS
    pe_fwd = None
    if float(eps_est["eps_2027"]) > 0 and float(close) > 0:
        pe_fwd = float(close) / float(eps_est["eps_2027"])
    eps_earned = _finite(fund.get("eps"))
    if eps_earned is None:
        eps_earned = _finite(fund.get("eps_single"))
    return {
        "stock_id": sid_s,
        "name": name_s,
        "chain": chain,
        "industry": industry,
        "bucket": bucket,
        "gross_margin": gm,
        "core_ratio_pct": core_pct,
        "core_ratio_label": format_core_ratio(core_pct),
        "yoy_pct": yoy_pct,
        "peer_pe_median_raw": _finite(peer_med_raw),
        "peer_pe_median": float(med_cap),
        "fair_year": tg["fair_year"],
        "target_next": tg["target_next"],
        "ups_fair_pct": tg["ups_fair_pct"],
        "ups_tgt_pct": tg["ups_tgt_pct"],
        "pe_year": use_pe_year,
        "pe_next": use_pe_next,
        "pe_fwd": pe_fwd,
        "eps_earned": eps_earned,
        "eps_2026": eps_est["eps_2026"],
        "eps_2027": eps_est["eps_2027"],
        "rev_threshold_yi": eps_est["rev_threshold_yi"],
        "rev_oct_yi": eps_est["rev_oct_yi"],
        "support": supp.get("support"),
        "resistance": supp.get("resistance"),
        "tech_status": supp.get("status"),
        "tech_broken": broken,
        "chip_note": chip,
        "chip_kind": chip_info.get("chip_kind") or "",
        "guidance_note": str(eps_est.get("guidance_note") or g_note or "")[:120],
        "eps_method": str(eps_est.get("method") or "")[:80],
        "emerging": emerging,
        "prefer_watch": broken or both_sell or foreign_sell or not d3_star,
        "d3_star_ok": d3_star,
        "gate_note": why,
    }
