#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多週期量價因素（靜默）｜自飆大季／年線＋爆巨量說法提煉。

可沿用判斷因素（數字，不准 PNG）：
1. 季線／年線 OHLC＋成交值（由日柱／market_tape 合成）
2. 爆巨量：成交值相對近窗分位／倍數
3. 巨量後創高耗時（交易日／季）：對質他說 2021→約3年、2024→約1年
4. 距歷史高％、季振幅％
5. 他點名關鍵低（如 7/29）是否有效跌破 → 橫整假設失效碼

不是買訊。不上話筒。不准發明 5／9。
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
MIN_EDGE = 0.25


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _load_daily(conn: sqlite3.Connection) -> List[Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume
        FROM index_daily WHERE symbol='TWII' ORDER BY 1
        """
    ).fetchall()
    out: List[Dict[str, float]] = []
    for d, o, h, l, c, v in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        out.append(
            {
                "date": day,
                "open": _f(o) or cc,
                "high": _f(h) or cc,
                "low": _f(l) or cc,
                "close": cc,
                "volume": _f(v) or 0.0,
            }
        )
    return out


def _load_tape_amount(conn: sqlite3.Connection) -> Dict[str, float]:
    """市場成交金額（兆可從 amount_trillion；否則 amount_ntd）。"""
    out: Dict[str, float] = {}
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), amount_trillion, amount_ntd
            FROM market_tape_daily ORDER BY 1
            """
        ).fetchall()
    except sqlite3.Error:
        return out
    for d, tr, ntd in rows:
        day = _ymd(d)
        if not day:
            continue
        a = _f(tr)
        if a is None or a <= 0:
            n = _f(ntd)
            a = (n / 1e12) if n and n > 0 else None  # 元→兆
        if a and a > 0:
            out[day] = float(a)
    return out


def _period_key(day: str, how: str) -> str:
    y, m = int(day[:4]), int(day[4:6])
    if how == "Y":
        return f"{y}"
    q = (m - 1) // 3 + 1
    return f"{y}Q{q}"


def aggregate_mtf(
    bars: Sequence[Dict[str, float]], tape: Dict[str, float], how: str
) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for b in bars:
        key = _period_key(b["date"], how)
        if key not in buckets:
            buckets[key] = {
                "key": key,
                "how": how,
                "start": b["date"],
                "end": b["date"],
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": 0.0,
                "amount_trillion": 0.0,
                "n_days": 0,
            }
            order.append(key)
        u = buckets[key]
        u["end"] = b["date"]
        u["high"] = max(u["high"], b["high"])
        u["low"] = min(u["low"], b["low"])
        u["close"] = b["close"]
        u["volume"] += float(b.get("volume") or 0)
        u["amount_trillion"] += float(tape.get(b["date"]) or 0)
        u["n_days"] += 1
    out = []
    for k in order:
        u = buckets[k]
        span = u["high"] - u["low"]
        u["range_pct"] = round((span / u["close"] * 100.0) if u["close"] else 0.0, 4)
        u["ret_pct"] = (
            round((u["close"] / u["open"] - 1.0) * 100.0, 4) if u["open"] else None
        )
        out.append(u)
    return out


def _ath_series(bars: Sequence[Dict[str, float]]) -> Dict[str, float]:
    ath = None
    out: Dict[str, float] = {}
    for b in bars:
        ath = b["high"] if ath is None else max(ath, b["high"])
        out[b["date"]] = ath
    return out


def detect_volume_climaxes(
    bars: Sequence[Dict[str, float]],
    tape: Dict[str, float],
    *,
    look: int = 252,
    pct: float = 98.0,
    min_mult: float = 2.0,
) -> List[Dict[str, Any]]:
    """日成交值爆巨量：相對過去 look 日 ≥pct 分位且 ≥中位數×min_mult。"""
    days = [b["date"] for b in bars]
    amts = []
    for b in bars:
        a = tape.get(b["date"])
        if a and a > 0:
            amts.append(a)
        else:
            # fallback：用 volume 當代理（不同單位，只比相對）
            amts.append(float(b.get("volume") or 0) / 1e6)
    hits: List[Dict[str, Any]] = []
    for i in range(look, len(bars)):
        window = [x for x in amts[i - look : i] if x > 0]
        if len(window) < look // 2:
            continue
        cur = amts[i]
        if cur <= 0:
            continue
        ws = sorted(window)
        cut = ws[int((pct / 100.0) * (len(ws) - 1))]
        med = ws[len(ws) // 2]
        if cur >= cut and med > 0 and cur >= med * min_mult:
            hits.append(
                {
                    "date": days[i],
                    "amount": round(cur, 4),
                    "cut": round(cut, 4),
                    "mult_vs_med": round(cur / med, 3),
                    "close": bars[i]["close"],
                    "high": bars[i]["high"],
                }
            )
    return hits


def time_to_new_high(
    bars: Sequence[Dict[str, float]], climaxes: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """巨量日之後，收盤創「巨量當日以前 ATH」新高要幾根交易日。"""
    day_i = {b["date"]: i for i, b in enumerate(bars)}
    ath = _ath_series(bars)
    rows: List[Dict[str, Any]] = []
    for c in climaxes:
        d = c["date"]
        i = day_i.get(d)
        if i is None:
            continue
        # 巨量當日之前的 ATH（不含當日）
        prior_ath = ath[bars[i - 1]["date"]] if i > 0 else bars[i]["high"]
        days_needed = None
        hit_date = None
        for j in range(i + 1, len(bars)):
            if bars[j]["close"] > prior_ath and bars[j]["high"] > prior_ath:
                days_needed = j - i
                hit_date = bars[j]["date"]
                break
        rows.append(
            {
                "climax_date": d,
                "prior_ath": round(prior_ath, 2),
                "days_to_new_high": days_needed,
                "new_high_date": hit_date,
                "years_approx": round(days_needed / 252.0, 2) if days_needed else None,
                "quarters_approx": round(days_needed / 63.0, 2) if days_needed else None,
                "still_waiting": days_needed is None,
            }
        )
    return rows


def _calibrated_quarter_amount(qbars: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """統一季成交值：有 tape 用 tape；缺洞用 TWII 量×重疊期中位換算。"""
    ratios: List[float] = []
    for q in qbars:
        amt = float(q.get("amount_trillion") or 0)
        vol = float(q.get("volume") or 0)
        if amt > 0 and vol > 0:
            ratios.append(amt / (vol / 1e9))
    k = sorted(ratios)[len(ratios) // 2] if ratios else 40.0
    out: List[Dict[str, Any]] = []
    for q in qbars:
        amt = float(q.get("amount_trillion") or 0)
        vol = float(q.get("volume") or 0)
        if amt > 0:
            u, src = amt, "tape_trillion"
        elif vol > 0:
            u, src = (vol / 1e9) * k, "vol_calibrated"
        else:
            u, src = 0.0, "empty"
        row = dict(q)
        row["u_trillion"] = u
        row["u_source"] = src
        out.append(row)
    return out


def quarterly_volume_climaxes(
    qbars: Sequence[Dict[str, Any]], *, look: int = 16, pct: float = 88.0
) -> List[Dict[str, Any]]:
    """季成交爆巨量（對齊他文季線圖；tape 缺年用加權量校正）。"""
    uni = _calibrated_quarter_amount(qbars)
    hits: List[Dict[str, Any]] = []
    for i in range(look, len(uni)):
        window = [uni[j]["u_trillion"] for j in range(i - look, i) if uni[j]["u_trillion"] > 0]
        cur = float(uni[i]["u_trillion"])
        if cur <= 0 or len(window) < max(6, look // 2):
            continue
        ws = sorted(window)
        cut = ws[int((pct / 100.0) * (len(ws) - 1))]
        med = ws[len(ws) // 2]
        prev4 = max(uni[j]["u_trillion"] for j in range(i - 4, i))
        is_local_max = cur >= prev4 * 0.98
        if (cur >= cut and med > 0 and cur >= med * 1.35) or (
            is_local_max and med > 0 and cur >= med * 1.45
        ):
            hits.append(
                {
                    "key": uni[i]["key"],
                    "end": uni[i]["end"],
                    "high": uni[i]["high"],
                    "metric": round(cur, 4),
                    "source": uni[i]["u_source"],
                    "amount_trillion": round(float(uni[i].get("amount_trillion") or 0), 4),
                    "mult_vs_med": round(cur / med, 3) if med else None,
                    "local_max": bool(is_local_max),
                }
            )
    return hits


def quarters_to_new_high(
    qbars: Sequence[Dict[str, Any]],
    climaxes: Sequence[Dict[str, Any]],
    *,
    require_drawdown_pct: float = 12.0,
) -> List[Dict[str, Any]]:
    """季爆量後「有效越過前高」耗時。

    他文語意不是下一季虛破，而是巨量高峰後先回撤，再花時間越過該季高。
    規則：自巨量季高算起，先出現 ≥require_drawdown_pct 回撤，之後收盤才計越前高。
    """
    key_i = {q["key"]: i for i, q in enumerate(qbars)}
    rows: List[Dict[str, Any]] = []
    for c in climaxes:
        i = key_i.get(c["key"])
        if i is None:
            continue
        barrier = float(c["high"])
        need = None
        hit_key = None
        drew = False
        min_after = barrier
        for j in range(i + 1, len(qbars)):
            min_after = min(min_after, float(qbars[j]["low"]))
            dd = (barrier - min_after) / barrier * 100.0 if barrier else 0.0
            if dd >= require_drawdown_pct:
                drew = True
            if drew and float(qbars[j]["close"]) > barrier:
                need = j - i
                hit_key = qbars[j]["key"]
                break
        rows.append(
            {
                "climax_key": c["key"],
                "barrier_high": round(barrier, 2),
                "quarters_to_new_high": need,
                "years_approx": round(need / 4.0, 2) if need is not None else None,
                "new_high_key": hit_key,
                "required_drawdown_pct": require_drawdown_pct,
                "saw_drawdown": drew,
                "still_waiting": need is None,
            }
        )
    return rows


def verify_teacher_claims_quarterly(
    q_ttnh: Sequence[Dict[str, Any]],
    climaxes: Sequence[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """對質他說：2021 巨量後約3年、2024 約1年（回撤後再越前高）。"""
    # 每年取 metric 最大的巨量季當代表（對齊圖上年度爆量標記）
    year_best: Dict[str, str] = {}
    if climaxes:
        by_m: Dict[str, Dict[str, Any]] = {}
        for c in climaxes:
            y = str(c.get("key") or "")[:4]
            if not y:
                continue
            if y not in by_m or float(c.get("metric") or 0) >= float(by_m[y].get("metric") or 0):
                by_m[y] = c
        year_best = {y: str(v.get("key")) for y, v in by_m.items()}
    by_key = {str(r.get("climax_key")): r for r in q_ttnh}
    claims = {}
    for y, expect_y in (("2021", 3.0), ("2024", 1.0)):
        key = year_best.get(y)
        row = by_key.get(key or "") if key else None
        if not row:
            # fallback：該年任一完成樣本中位
            rows = [r for r in q_ttnh if str(r.get("climax_key") or "").startswith(y)]
            done = [r for r in rows if r.get("years_approx") is not None]
            if not done:
                claims[y] = {"ok": False, "note": "無完成樣本", "expect_years": expect_y}
                continue
            years = [float(r["years_approx"]) for r in done]
            med = sorted(years)[len(years) // 2]
            row = done[0]
            yrs = med
        else:
            yrs = float(row.get("years_approx") or 0) if row.get("years_approx") is not None else None
        if yrs is None:
            claims[y] = {
                "ok": False,
                "note": "尚未越前高（可能仍在整理）",
                "expect_years": expect_y,
                "sample": row,
            }
            continue
        claims[y] = {
            "ok": abs(yrs - expect_y) <= 1.25,
            "years": yrs,
            "expect_years": expect_y,
            "climax_key": row.get("climax_key"),
            "sample": row,
        }
    return claims


# 飆大點名低點（例 7/29 A波低）：只准 as_of ≥ 該日才當 named_support（不准回灌到更早日）
BIAOKE_NAMED_SUPPORT_YMD = "20260729"


def named_support_asof(
    bars: Sequence[Dict[str, float]],
    as_of: str,
    *,
    named_day: str = BIAOKE_NAMED_SUPPORT_YMD,
) -> Optional[float]:
    """回傳點名支撐價；as_of 早於點名日 → None（防 look-ahead）。"""
    day = _ymd(as_of)
    nd = _ymd(named_day)
    if not day or not nd or day < nd:
        return None
    for b in bars:
        if b.get("date") == nd:
            px = float(b.get("low") or 0.0)
            return px if px > 0 else None
    return None


def snapshot_mtf_factors(
    bars: Sequence[Dict[str, float]],
    tape: Dict[str, float],
    as_of: str,
    *,
    named_support: Optional[float] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """as-of 當日可見的多週期／量能因素。"""
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    day_i = {b["date"]: i for i, b in enumerate(bars)}
    if day not in day_i:
        return {}, ["twii_bar"]
    i = day_i[day]
    hist = list(bars[: i + 1])
    ath = max(b["high"] for b in hist)
    last = bars[i]["close"]
    factors["mtf_dist_ath_pct"] = round((last / ath - 1.0) * 100.0, 4)
    # 近 60 日量能分位
    amts = []
    for b in hist[-60:]:
        a = tape.get(b["date"])
        amts.append(a if a and a > 0 else float(b.get("volume") or 0) / 1e6)
    cur_a = amts[-1] if amts else 0
    if len(amts) >= 20 and cur_a > 0:
        ws = sorted(amts[:-1])
        # rank
        rank = sum(1 for x in ws if x <= cur_a) / max(1, len(ws))
        factors["mtf_amount_pctile_60"] = round(rank * 100.0, 2)
        med = ws[len(ws) // 2]
        factors["mtf_amount_mult_med60"] = round(cur_a / med, 3) if med > 0 else None
        factors["mtf_volume_climax"] = bool(rank >= 0.98 and med > 0 and cur_a >= med * 2)
    else:
        missing.append("mtf_amount_window")
    # 當季至今振幅
    qkey = _period_key(day, "Q")
    qbars = [b for b in hist if _period_key(b["date"], "Q") == qkey]
    if qbars:
        qh = max(b["high"] for b in qbars)
        ql = min(b["low"] for b in qbars)
        factors["mtf_qtd_range_pct"] = round((qh - ql) / last * 100.0, 4)
        factors["mtf_qtd_ret_pct"] = round((last / qbars[0]["open"] - 1.0) * 100.0, 4)
    ykey = _period_key(day, "Y")
    ybars = [b for b in hist if _period_key(b["date"], "Y") == ykey]
    if ybars:
        factors["mtf_ytd_ret_pct"] = round((last / ybars[0]["open"] - 1.0) * 100.0, 4)
    if named_support is not None and named_support > 0:
        factors["mtf_named_support"] = float(named_support)
        factors["mtf_below_named_support"] = bool(last < named_support * 0.995)
        # 有效跌破：收盤低於支撐且當日低更破
        factors["mtf_named_support_broken"] = bool(
            last < named_support * 0.99 and bars[i]["low"] < named_support * 0.99
        )
    return factors, missing


def quantify_mtf_edges(conn: sqlite3.Connection) -> Dict[str, Any]:
    bars = _load_daily(conn)
    tape = _load_tape_amount(conn)
    if len(bars) < 300:
        return {"error": "twii_too_short", "n": len(bars)}
    climaxes = detect_volume_climaxes(bars, tape)
    ttnh = time_to_new_high(bars, climaxes)
    qbars = aggregate_mtf(bars, tape, "Q")
    ybars = aggregate_mtf(bars, tape, "Y")
    q_climaxes = quarterly_volume_climaxes(qbars)
    q_ttnh = quarters_to_new_high(qbars, q_climaxes)
    claims = verify_teacher_claims_quarterly(q_ttnh, q_climaxes)

    # 日級：爆巨量後 3／60 日方向
    day_i = {b["date"]: i for i, b in enumerate(bars)}
    climax_set = {c["date"] for c in climaxes}

    def fwd(d: str, n: int) -> Optional[float]:
        i = day_i.get(d)
        if i is None or i + n >= len(bars):
            return None
        return (bars[i + n]["close"] / bars[i]["close"] - 1.0) * 100.0

    flags: List[Dict[str, Any]] = []
    base_days = [b["date"] for b in bars[252:-5]]
    base3 = [fwd(d, 3) for d in base_days]
    base3 = [x for x in base3 if x is not None]
    bm3 = sum(base3) / len(base3) if base3 else 0.0

    def add(code: str, days: Sequence[str], n_fwd: int = 3) -> None:
        xs = [fwd(d, n_fwd) for d in days]
        xs = [x for x in xs if x is not None]
        if len(xs) < MIN_N:
            return
        m = sum(xs) / len(xs)
        edge = m - (bm3 if n_fwd == 3 else 0.0)
        if n_fwd != 3:
            # rebuild base for other horizon lightly
            base = [fwd(d, n_fwd) for d in base_days]
            base = [x for x in base if x is not None]
            bm = sum(base) / len(base) if base else 0.0
            edge = m - bm
        if abs(edge) < MIN_EDGE:
            return
        if edge > 0:
            hit = sum(1 for x in xs if x > 0.6) / len(xs)
            bias = "up"
        else:
            hit = sum(1 for x in xs if x < -0.6) / len(xs)
            bias = "down"
        if hit < 0.50:
            return
        flags.append(
            {
                "code": code,
                "n": len(xs),
                "mean": round(m, 4),
                "edge": round(edge, 4),
                "hit_rate_side": round(hit, 4),
                "bias": bias,
                "vote": round(edge, 4),
                "horizon_days": n_fwd,
            }
        )

    add("mtf_volume_climax_d3", sorted(climax_set), 3)
    add("mtf_volume_climax_d60", sorted(climax_set), 60)

    # 近歷史高且爆量 → 常震盪／偏弱（對質）
    ath = _ath_series(bars)
    near_ath_climax = [
        d
        for d in climax_set
        if d in day_i and bars[day_i[d]]["close"] >= ath[d] * 0.97
    ]
    add("mtf_climax_near_ath_d3", near_ath_climax, 3)
    add("mtf_climax_near_ath_d60", near_ath_climax, 60)

    # 遠低於 ATH（>15%）爆量 → 可能止跌
    deep_climax = [
        d
        for d in climax_set
        if d in day_i and bars[day_i[d]]["close"] < ath[d] * 0.85
    ]
    add("mtf_climax_deep_discount_d3", deep_climax, 3)

    flags.sort(key=lambda x: -abs(float(x["edge"])))

    # 7/29 支撐：找 20260729 低點
    support = None
    for b in bars:
        if b["date"] == "20260729":
            support = b["low"]
            break
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "source_zh": "飆大季／年線圖＋爆巨量文；官方日柱／tape 量化",
        "twii_n": len(bars),
        "q_bars": len(qbars),
        "y_bars": len(ybars),
        "climax_n": len(climaxes),
        "q_climax_n": len(q_climaxes),
        "q_climaxes": q_climaxes[-8:],
        "teacher_claims_check_quarterly": claims,
        "support_20260729_low": support,
        "ttnh_sample": [r for r in ttnh if r.get("years_approx") is not None][:8],
        "q_ttnh_sample": q_ttnh[-8:],
        "ttnh_waiting_n": sum(1 for r in ttnh if r.get("still_waiting")),
        "flags": flags,
        "n_flags": len(flags),
        "factor_ideas_zh": [
            "爆巨量（日成交值高分位＋倍數）",
            "季線爆巨量＋創高耗時（對質他說 2021≈3年／2024≈1年）",
            "距 ATH％、季振幅、YTD",
            "他點名低點（如 7/29）有效跌破＝橫整假設失效",
            "高檔巨量 vs 深跌巨量分開對質",
            "巨量後中期偏整理（range），不是自動空單",
        ],
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "wave_note_zh": "不准發明 5／9；此模組只做量價／位階失效數字",
    }
    with gzip.open(OUT_DIR / "mtf_q_climaxes.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in q_climaxes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with gzip.open(OUT_DIR / "mtf_q_ttnh.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in q_ttnh:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "mtf_volume_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "mtf_volume_climaxes.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in climaxes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with gzip.open(OUT_DIR / "mtf_volume_ttnh.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in ttnh:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with gzip.open(OUT_DIR / "mtf_q_bars.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in qbars:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with gzip.open(OUT_DIR / "mtf_y_bars.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in ybars:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return summary


def load_mtf_votes() -> Dict[str, float]:
    p = OUT_DIR / "mtf_volume_latest.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: Dict[str, float] = {}
    for row in d.get("flags") or []:
        # 預測票只用短窗（3日）；60日另軌
        if int(row.get("horizon_days") or 3) != 3:
            continue
        code = str(row.get("code") or "")
        if code:
            out[code] = float(row.get("vote") or row.get("edge") or 0)
    return out


def main() -> int:
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        s = quantify_mtf_edges(conn)
    finally:
        conn.close()
    print(json.dumps(s, ensure_ascii=False, indent=2)[:6000])
    return 0 if not s.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
