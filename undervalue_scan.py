# -*- coding: utf-8 -*-
"""低估名單掃描：推估防呆與硬濾／估值母體（與海選／黃金買點分開）。

原意交叉：
- 卡欄＝官方本益、同鏈中位、距同鏈下緣％、流動張（話筒 PNG）。
- 同鏈＝industry_fine.chain_peer_ids／比價同源，不是證交所粗產業。
- 飆大 11/09 封印：龍頭「本益被低估」＝官方 PE 近自身近窗低緣（非買訊；切入仍黃金買點）。
- A4：近 3 月 MoM 動能 g 夾在 [-5%, +10%]；無官方月營收不推估（估 PE 軌另開）。

話筒現況碼 RULE_PHONE＝uv_growth_fair_v1（毛利／循環／本業鐵律＋產業PE封頂＋今明目標價）；
下一版靜默 RULE_NEXT＝uv_growth_fair_tight_v2。
§13：n≥20 且下一版贏現況才換話筒規則並再生；勝率不准混進海選／黃金買點。
不是進場買訊。估值≠買訊；切入仍只認高低卡黃金買點。
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# 近 3 月平均月增動能安全區間（小數，非百分點）
G_MOM_FLOOR = -0.05
G_MOM_CEIL = 0.10
# 單月 YoY 超過此絕對值視為極端 → 外推仍只走夾限後的 g，不准用 YoY 當斜率
EXTREME_YOY_ABS_PCT = 80.0
MOM_UNITS = ("pct", "frac")

# --- 滾動規則鍵（§13：換現況時必須同時再生下一版）---
RULE_PHONE = "uv_growth_fair_v1"
RULE_NEXT = "uv_growth_fair_tight_v2"
# 話筒名單上限（三段卡片：現在可買／等止穩／興櫃觀察）
PHONE_STAR_CAP = 8
PHONE_WATCH_CAP = 8
PHONE_EMERGING_CAP = 5
# 官方本益合理窗（排除極端／負值；無真數不上）
PE_MIN = 3.0
PE_MAX = 200.0
OWN_PE_LOOKBACK = 32
FLOW_DAYS = 20
FLOW_MIN_STAR = 1500.0
FLOW_MIN_WATCH = 1500.0
# 與 undervalue_growth.PEER_PE_FINE_MIN_N 對齊（n≥5）；不准 scan=3、滾動=5 雙軌
PEER_MIN_N = 5
# 硬濾（可量化；對齊鎖死規格能落地的部分）
YOY_MIN_PCT = 15.0
QTY60_A_MIN = 400.0  # A 穩當核心：近 60 日均量（張）
# 距下緣％＝(PE／同鏈中位−1)×100；≤−8%≈中位×0.92（比價 lag 帶）
STAR_DIST_MAX = -8.0
STAR_DIST_MAX_TIGHT = -12.0


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


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _median(vals: Sequence[float]) -> Optional[float]:
    xs = [float(v) for v in vals if _finite(v) is not None]
    if not xs:
        return None
    return float(statistics.median(xs))


def _load_latest_pe_map(conn: sqlite3.Connection, as_of: str) -> Dict[str, float]:
    """官方 daily_valuation.pe：每檔 as_of 當日或之前最新一筆；無真數不上。"""
    day = _ymd(as_of)
    out: Dict[str, float] = {}
    if not day:
        return out
    rows = conn.execute(
        """
        SELECT stock_id, pe FROM daily_valuation
        WHERE REPLACE(CAST(date AS TEXT),'-','')<=?
          AND pe IS NOT NULL AND pe > 0 AND pe < ?
        ORDER BY date DESC
        """,
        (day, PE_MAX),
    ).fetchall()
    for sid, pe in rows:
        code = str(sid or "").strip()
        if not code or code in out:
            continue
        v = _finite(pe)
        if v is None or v < PE_MIN:
            continue
        out[code] = float(v)
    return out


def _own_pe_series(
    conn: sqlite3.Connection, sid: str, as_of: str, *, cap: int = OWN_PE_LOOKBACK
) -> List[float]:
    day = _ymd(as_of)
    if not day or not sid:
        return []
    rows = conn.execute(
        """
        SELECT pe FROM daily_valuation
        WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
          AND pe IS NOT NULL AND pe > 0 AND pe < ?
        ORDER BY date DESC LIMIT ?
        """,
        (sid, day, PE_MAX, int(cap)),
    ).fetchall()
    out: List[float] = []
    for (pe,) in rows:
        v = _finite(pe)
        if v is not None and v >= PE_MIN:
            out.append(float(v))
    return out


def _quote_meta(
    conn: sqlite3.Connection, as_of: str, sids: Iterable[str]
) -> Dict[str, Dict[str, Any]]:
    """收盤＋名＋近窗均量（張）＋QTY60＋最新月 YoY。缺官方收就不進。"""
    day = _ymd(as_of)
    want = [str(s).strip() for s in sids if str(s or "").strip()]
    out: Dict[str, Dict[str, Any]] = {}
    if not day or not want:
        return out
    for sid in want:
        q = conn.execute(
            """
            SELECT stock_name, close FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
            ORDER BY date DESC LIMIT 1
            """,
            (sid, day),
        ).fetchone()
        if not q:
            continue
        close = _finite(q[1] if not isinstance(q, sqlite3.Row) else q["close"])
        if close is None or close <= 0:
            continue
        vols20 = conn.execute(
            """
            SELECT volume FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
              AND volume IS NOT NULL AND volume > 0
            ORDER BY date DESC LIMIT ?
            """,
            (sid, day, FLOW_DAYS),
        ).fetchall()
        flow_vals = [float(v) for v in (_finite(x[0]) for x in vols20) if v is not None]
        if len(flow_vals) < 5:
            continue
        vols60 = conn.execute(
            """
            SELECT volume FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
              AND volume IS NOT NULL AND volume > 0
            ORDER BY date DESC LIMIT 60
            """,
            (sid, day),
        ).fetchall()
        q60_vals = [float(v) for v in (_finite(x[0]) for x in vols60) if v is not None]
        qty60 = float(sum(q60_vals) / len(q60_vals)) if q60_vals else 0.0
        yoy = None
        try:
            mr = conn.execute(
                """
                SELECT yoy_pct FROM monthly_revenue
                WHERE stock_id=? AND yoy_pct IS NOT NULL
                ORDER BY yyyymm DESC LIMIT 1
                """,
                (sid,),
            ).fetchone()
            if mr is not None:
                yoy = _finite(mr[0] if not isinstance(mr, sqlite3.Row) else mr["yoy_pct"])
        except sqlite3.Error:
            yoy = None
        raw_name = str(
            (q[0] if not isinstance(q, sqlite3.Row) else q["stock_name"]) or ""
        ).strip()
        mkt = ""
        uni_name = ""
        try:
            ur = conn.execute(
                "SELECT market_type, stock_name FROM stock_universe WHERE stock_id=?",
                (sid,),
            ).fetchone()
            if ur is not None:
                mkt = str(
                    ur[0] if not isinstance(ur, sqlite3.Row) else ur["market_type"] or ""
                )
                uni_name = str(
                    ur[1] if not isinstance(ur, sqlite3.Row) else ur["stock_name"] or ""
                ).strip()
        except sqlite3.Error:
            mkt = ""
            uni_name = ""
        # 名缺／等於代號 → 用宇宙名；不准「2383 2383」
        name = raw_name
        if (not name or name == sid or name.isdigit()) and uni_name and uni_name != sid:
            name = uni_name
        if not name:
            name = sid
        out[sid] = {
            "name": name,
            "close": float(close),
            "flow_shares": float(sum(flow_vals) / len(flow_vals)),
            "qty60": qty60,
            "yoy_pct": yoy,
            "market_type": mkt,
        }
    return out


def _leader_ids(db_path: str, meta: Dict[str, Dict[str, Any]]) -> Set[str]:
    """話筒龍頭表＋長線抱；失敗＝空集合（不准假龍頭）。"""
    out: Set[str] = set()
    try:
        from biaoke_judge import _LONG_HOLD, leader_of

        out |= set(str(k) for k in (_LONG_HOLD or {}))
        for sid, m in meta.items():
            try:
                lid, _nm, _why = leader_of(db_path, sid, str(m.get("name") or ""))
            except Exception:
                continue
            if str(lid or "") == sid:
                out.add(sid)
    except Exception:
        return out
    return out


def _peer_index(db_path: str) -> Dict[str, List[str]]:
    """sid → 同鏈同業（含自己）。一次建索，避免每檔重掃表。"""
    try:
        from industry_fine import (
            CACHE_DAYS,
            _TAUGHT_CROSS,
            ensure_fine_industry_table,
            load_cached_fine_industry,
            membership_keys,
            split_chain,
        )
    except Exception:
        return {}
    ensure_fine_industry_table(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT f.stock_id, f.chain, f.tags_json
            FROM stock_fine_industry f
            JOIN stock_universe u ON u.stock_id = f.stock_id
            WHERE u.is_active=1 AND length(f.stock_id)=4
              AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    # sid → keys；key → sids
    sid_keys: Dict[str, set] = {}
    key_sids: Dict[Tuple[str, str], Set[str]] = {}
    all_sids: List[str] = []
    for sid_raw, chain, tags_json in rows:
        sid = str(sid_raw or "").strip()
        if not sid:
            continue
        all_sids.append(sid)
        try:
            tags = json.loads(tags_json) if tags_json else split_chain(chain)
        except Exception:
            tags = split_chain(chain)
        finest = str(tags[-1] if tags else "")
        keys = membership_keys(sid, finest)
        sid_keys[sid] = keys
        for k in keys:
            key_sids.setdefault(k, set()).add(sid)
    # taught cross members always see each other
    for _tag, members in _TAUGHT_CROSS:
        bucket = {str(x) for x in members}
        for sid in bucket:
            sid_keys.setdefault(sid, set())
            for other in bucket:
                # synthetic key so they link
                key_sids.setdefault(("x", _tag), set()).add(other)
            sid_keys[sid].add(("x", _tag))
    # warm cache for membership (used by membership_keys extras)
    try:
        load_cached_fine_industry(db_path, all_sids[:1], max_age_days=CACHE_DAYS)
    except Exception:
        pass
    out: Dict[str, List[str]] = {}
    for sid, keys in sid_keys.items():
        peers: Set[str] = set()
        for k in keys:
            peers |= key_sids.get(k, set())
        if sid not in peers:
            peers.add(sid)
        out[sid] = sorted(peers)
    return out


def _dist_to_peer_floor_pct(pe: float, med: float) -> float:
    """距下緣％＝相對同鏈中位（卡欄語意）；負＝便宜。"""
    if med <= 0:
        return 999.0
    return (float(pe) / float(med) - 1.0) * 100.0


def _classify_v1(
    *,
    pe: float,
    med: float,
    floor: float,
    flow: float,
    own_min: float,
    own_med: float,
    is_leader: bool,
    qty60: float = 0.0,
    yoy_pct: Optional[float] = None,
) -> Tuple[str, str, float]:
    """回傳 (mark|'' , reason, dist_to_floor_pct)。

    硬濾前置由呼叫端做；此處只分 ★／☆。
    ★：距中位≤−8%（≈中位×0.92）或自身近窗低緣；☆：距中位≤0 但未到 ★。
    """
    _ = floor
    dist = _dist_to_peer_floor_pct(pe, med)
    pool = "A穩當" if qty60 >= QTY60_A_MIN else "B量能薄"
    chain_cheap = (
        dist <= STAR_DIST_MAX
        and flow >= FLOW_MIN_STAR
        and pe >= 8.0
    )
    own_cheap = (
        pe <= own_min * 1.02
        and pe <= own_med * 0.85
        and flow >= FLOW_MIN_STAR
        and (is_leader or pe < med)
    )
    yoy_bit = ""
    if yoy_pct is not None:
        yoy_bit = f"；月YoY{yoy_pct:+.0f}%"
    if chain_cheap or own_cheap:
        bits: List[str] = [pool]
        if chain_cheap:
            bits.append(f"同鏈PE {pe:.1f} 距中位{dist:.1f}%")
        if own_cheap:
            bits.append(f"近窗本益近自身低緣{own_min:.1f}")
        return "star", "；".join(bits) + yoy_bit, dist
    if dist <= 0.0 and flow >= FLOW_MIN_WATCH:
        return "watch", f"{pool}；PE≤同鏈中位{med:.1f}，先觀察不當真低估{yoy_bit}", dist
    return "", "", dist


def _classify_v2(
    *,
    pe: float,
    med: float,
    floor: float,
    flow: float,
    own_min: float,
    own_med: float,
    is_leader: bool,
    qty60: float = 0.0,
    yoy_pct: Optional[float] = None,
) -> Tuple[str, str, float]:
    """下一版：更貼自身低緣＋距中位更緊（≤−12%）。"""
    _ = floor
    dist = _dist_to_peer_floor_pct(pe, med)
    pool = "A穩當" if qty60 >= QTY60_A_MIN else "B量能薄"
    yoy_bit = f"；月YoY{yoy_pct:+.0f}%" if yoy_pct is not None else ""
    tight = (
        pe <= own_min * 1.01
        and pe <= own_med * 0.82
        and dist <= STAR_DIST_MAX_TIGHT
        and flow >= 2000.0
        and (is_leader or pe <= med * 0.95)
    )
    if tight:
        return (
            "star",
            f"{pool}；自身低緣緊貼{own_min:.1f}且距中位{dist:.1f}%{yoy_bit}",
            dist,
        )
    near = pe <= own_min * 1.05 and dist <= 0.0 and flow >= FLOW_MIN_WATCH
    if near:
        return "watch", f"{pool}；近自身低緣、≤中位{med:.1f}{yoy_bit}", dist
    return "", "", dist


_CLASSIFIERS = {
    RULE_PHONE: _classify_v1,
    RULE_NEXT: _classify_v2,
    # 舊鍵仍可對質歷史落檔
    "uv_chain_own_v1": _classify_v1,
    "uv_own_floor_tight_v2": _classify_v2,
}


def run_undervalue_scan(
    db_path: str,
    as_of: str,
    *,
    rule_key: str = RULE_PHONE,
    star_cap: int = PHONE_STAR_CAP,
    watch_cap: int = PHONE_WATCH_CAP,
    emerging_cap: int = PHONE_EMERGING_CAP,
) -> Dict[str, Any]:
    """盤後低估掃描入口。只吃官方本益／收／量／同鏈／季報；不准假成本。不是買訊。"""
    path = str(db_path or "").strip()
    ymd = _ymd(as_of)
    rule = str(rule_key or RULE_PHONE).strip() or RULE_PHONE
    classify = _CLASSIFIERS.get(rule) or _classify_v1
    growth_mode = rule in (RULE_PHONE, RULE_NEXT) or rule.startswith("uv_growth_")
    empty = {
        "ok": True,
        "as_of": ymd,
        "rule_key": rule,
        "rows": [],
        "note": "",
    }
    if not path or not ymd:
        empty["ok"] = False
        empty["note"] = "缺 db 或 as_of"
        return empty
    try:
        conn = sqlite3.connect(path, timeout=60.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        empty["ok"] = False
        empty["note"] = type(exc).__name__
        return empty
    try:
        from undervalue_growth import enrich_growth_row

        pe_map = _load_latest_pe_map(conn, ymd)
        if not pe_map:
            empty["note"] = "無官方本益"
            return empty
        meta = _quote_meta(conn, ymd, pe_map.keys())
        leaders = _leader_ids(path, meta)
        peer_ix = _peer_index(path)
        stars: List[Dict[str, Any]] = []
        watches: List[Dict[str, Any]] = []
        emergings: List[Dict[str, Any]] = []
        from undervalue_growth import is_hard_excluded

        for sid, pe in pe_map.items():
            if sid not in meta:
                continue
            if is_hard_excluded(sid):
                continue
            # 硬濾：最新月營收 YoY ≥ +15%（無 YoY 不上；不准假成長）
            yoy = meta[sid].get("yoy_pct")
            if yoy is None or float(yoy) < YOY_MIN_PCT:
                continue
            peers = [p for p in peer_ix.get(sid, []) if p in pe_map]
            if sid not in peers:
                peers = [sid] + peers
            peer_pes = [pe_map[p] for p in peers if p in pe_map]
            if len(peer_pes) < PEER_MIN_N:
                continue
            med_raw = _median(peer_pes)
            floor = min(peer_pes) if peer_pes else None
            if med_raw is None or floor is None or floor <= 0:
                continue
            hist = _own_pe_series(conn, sid, ymd)
            if len(hist) < 12:
                continue
            own_min = min(hist)
            own_med = float(statistics.median(hist))
            flow = float(meta[sid]["flow_shares"])
            qty60 = float(meta[sid].get("qty60") or 0.0)
            detail = None
            med = float(med_raw)
            if growth_mode:
                detail = enrich_growth_row(
                    conn,
                    sid=sid,
                    name=str(meta[sid]["name"]),
                    close=float(meta[sid]["close"]),
                    pe=float(pe),
                    peer_med_raw=float(med_raw),
                    as_of=ymd,
                    yoy_pct=float(yoy),
                    qty60=qty60,
                    market_type=str(meta[sid].get("market_type") or ""),
                )
                if detail is None:
                    continue
                med = float(detail.get("peer_pe_median") or med_raw)
                if detail.get("name"):
                    meta[sid]["name"] = str(detail["name"])
            mark, reason, dist = classify(
                pe=float(pe),
                med=float(med),
                floor=float(floor),
                flow=flow,
                own_min=float(own_min),
                own_med=float(own_med),
                is_leader=sid in leaders,
                qty60=qty60,
                yoy_pct=float(yoy),
            )
            if not mark and not (growth_mode and detail):
                continue
            # 成長模式：通過鐵律且相對中位不貴（≤0）也可進觀察／興櫃池
            if not mark and growth_mode and detail:
                dist = _dist_to_peer_floor_pct(float(pe), float(med))
                if dist > 0:
                    continue
                mark = "watch"
                reason = f"成長體質過關；PE≤封頂中位{med:.1f}"
            # D3 分區：★＝明年≥+25%＋站穩撐＋非同賣＋非興櫃；破撐／同賣→☆；量小→⚠️
            if growth_mode and detail:
                ups = detail.get("ups_fair_pct")
                try:
                    ups_f = float(ups) if ups is not None else None
                except (TypeError, ValueError):
                    ups_f = None
                if ups_f is None or ups_f <= 0:
                    continue  # 高估／無空間＝不是低估名單
                if detail.get("emerging"):
                    mark = "emerging"
                elif detail.get("d3_star_ok"):
                    mark = "star"
                else:
                    mark = "watch"
                bits = [reason]
                if detail.get("tech_broken") and detail.get("support") is not None:
                    bits.append(f"⚠️破撐 {float(detail['support']):.0f}")
                elif detail.get("tech_status"):
                    bits.append(str(detail["tech_status"]))
                if detail.get("resistance") is not None:
                    bits.append(f"壓 {float(detail['resistance']):.0f}")
                if detail.get("chip_note"):
                    bits.append(str(detail["chip_note"]))
                reason = "；".join(x for x in bits if x)
            row: Dict[str, Any] = {
                "stock_id": sid,
                "name": meta[sid]["name"],
                "mark": mark,
                "close": meta[sid]["close"],
                "pe": float(pe),
                "pe_est": False,
                "peer_pe_median": float(med),
                "dist_to_floor_pct": float(dist),
                "flow_shares": flow,
                "reason": reason,
                "rule_key": rule,
                "qty60": qty60,
                "yoy_pct": float(yoy),
            }
            if detail:
                row.update(
                    {
                        "industry": detail.get("industry"),
                        "gross_margin": detail.get("gross_margin"),
                        "core_ratio_pct": detail.get("core_ratio_pct"),
                        "core_ratio_label": detail.get("core_ratio_label"),
                        "fair_year": detail.get("fair_year"),
                        "target_next": detail.get("target_next"),
                        "ups_fair_pct": detail.get("ups_fair_pct"),
                        "ups_tgt_pct": detail.get("ups_tgt_pct"),
                        "pe_year": detail.get("pe_year"),
                        "pe_next": detail.get("pe_next"),
                        "pe_fwd": detail.get("pe_fwd"),
                        "eps_earned": detail.get("eps_earned"),
                        "eps_2026": detail.get("eps_2026"),
                        "eps_2027": detail.get("eps_2027"),
                        "rev_threshold_yi": detail.get("rev_threshold_yi"),
                        "rev_oct_yi": detail.get("rev_oct_yi"),
                        "support": detail.get("support"),
                        "resistance": detail.get("resistance"),
                        "tech_status": detail.get("tech_status"),
                        "tech_broken": detail.get("tech_broken"),
                        "chip_note": detail.get("chip_note"),
                        "chip_kind": detail.get("chip_kind"),
                        "detail": detail,
                    }
                )
            if mark == "star":
                stars.append(row)
            elif mark == "emerging":
                emergings.append(row)
            else:
                watches.append(row)
    finally:
        conn.close()

    # 雙條件（同鏈＋自身）優先，再相對便宜（PE／中位），再距下緣
    def _rel(r: Dict[str, Any]) -> float:
        return float(r["pe"]) / max(float(r["peer_pe_median"]), 1e-9)

    def _star_key(r: Dict[str, Any]) -> Tuple[Any, ...]:
        reason = str(r.get("reason") or "")
        both = ("同鏈" in reason) and ("自身" in reason)
        ups = _finite(r.get("ups_tgt_pct"))
        # 成長卡：空間大的優先
        return (
            0 if both else 1,
            -(ups if ups is not None else 0.0),
            _rel(r),
            float(r["dist_to_floor_pct"]),
            float(r["pe"]),
        )

    stars.sort(key=_star_key)
    watches.sort(key=lambda r: (_rel(r), float(r["pe"])))
    emergings.sort(key=lambda r: (_rel(r), float(r["pe"])))
    rows = (
        stars[: max(0, int(star_cap))]
        + watches[: max(0, int(watch_cap))]
        + emergings[: max(0, int(emerging_cap))]
    )
    note = (
        f"{rule} star={min(len(stars), star_cap)}/{len(stars)} "
        f"watch={min(len(watches), watch_cap)}/{len(watches)} "
        f"emerging={min(len(emergings), emerging_cap)}/{len(emergings)}"
    )
    return {
        "ok": True,
        "as_of": ymd,
        "rule_key": rule,
        "rows": rows,
        "n_star_raw": len(stars),
        "n_watch_raw": len(watches),
        "n_emerging_raw": len(emergings),
        "note": note,
    }
