#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路徑預測加測包（靜默）｜服務「方向＋幅度」，波浪主判之外的確認／否決。

納入（能量化才進票）：
- 美債10Y／日圓／金／銅／VIX 極端（恐懼代理）
- 台積 ADR 溢價（2330 vs TSM）
- 那指／費半持續背離
- 連漲連跌天數、開盤跳空（用當日 open vs 昨收）
- 現貨－夜盤基差（TWII vs TX night）
- 分市況標籤（bull／bear／chop by MA60）

缺官方長史就標缺（OTC／VVIX／夜盤OI=0 不硬填）。
不是買訊；不上話筒。
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
MIN_SIDE_HIT = 0.55


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


def _load_sym(conn: sqlite3.Connection, symbol: str) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    prev = None
    for d, o, h, lo, c in conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol=? ORDER BY 1
        """,
        (symbol,),
    ):
        day = _ymd(d)
        cc = _f(c)
        if not day or cc is None or cc <= 0:
            continue
        ret = ((cc / prev - 1.0) * 100.0) if prev else None
        out[day] = {
            "open": _f(o) or cc,
            "high": _f(h) or cc,
            "low": _f(lo) or cc,
            "close": cc,
            "ret": ret if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _load_tx_night_close(conn: sqlite3.Connection) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for d, c in conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), close
        FROM futures_daily WHERE symbol='TX' AND session='night' ORDER BY 1
        """
    ):
        day = _ymd(d)
        cc = _f(c)
        if day and cc:
            out[day] = cc
    return out


def _z(series: Dict[str, float], day: str, look: int = 60) -> Optional[float]:
    keys = sorted(series)
    if day not in series:
        return None
    i = keys.index(day)
    window = [series[keys[j]] for j in range(max(0, i - look), i)]
    if len(window) < 20:
        return None
    mu = sum(window) / len(window)
    var = sum((x - mu) ** 2 for x in window) / len(window)
    sd = var ** 0.5
    if sd <= 1e-9:
        return None
    return (series[day] - mu) / sd


def snapshot_extras(
    *,
    twii: Dict[str, Dict[str, float]],
    ixic: Dict[str, Dict[str, float]],
    sox: Dict[str, Dict[str, float]],
    vix: Dict[str, Dict[str, float]],
    us10y: Dict[str, Dict[str, float]],
    usdjpy: Dict[str, Dict[str, float]],
    gold: Dict[str, Dict[str, float]],
    copper: Dict[str, Dict[str, float]],
    tsm: Dict[str, Dict[str, float]],
    tw2330: Dict[str, Dict[str, float]],
    tx_night_px: Dict[str, float],
    tw_days: Sequence[str],
    as_of: str,
    otc: Optional[Dict[str, Dict[str, float]]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    if day not in twii:
        return factors, ["extras_twii"]
    i = list(tw_days).index(day)
    bar = twii[day]

    # 市況：收 vs MA60
    if i >= 60:
        ma = sum(twii[tw_days[j]]["close"] for j in range(i - 60, i)) / 60.0
        factors["regime_ma60"] = round(ma, 2)
        px = bar["close"]
        if px >= ma * 1.03:
            factors["regime"] = "bull"
        elif px <= ma * 0.97:
            factors["regime"] = "bear"
        else:
            factors["regime"] = "chop"
    else:
        missing.append("regime_ma60")

    # 連漲連跌
    streak = 0
    sign0 = 0
    for j in range(i, max(-1, i - 8), -1):
        r = twii[tw_days[j]].get("ret") if twii[tw_days[j]].get("ret_ok") else None
        if r is None:
            break
        s = 1 if r > 0.15 else (-1 if r < -0.15 else 0)
        if s == 0:
            break
        if sign0 == 0:
            sign0 = s
        if s != sign0:
            break
        streak += 1
    factors["tw_streak"] = streak * sign0
    factors["tw_down_streak_ge3"] = bool(sign0 < 0 and streak >= 3)
    factors["tw_up_streak_ge3"] = bool(sign0 > 0 and streak >= 3)

    # 跳空：今開 vs 昨收
    if i >= 1:
        prev_c = twii[tw_days[i - 1]]["close"]
        gap = (bar["open"] / prev_c - 1.0) * 100.0 if prev_c > 0 else 0.0
        factors["tw_gap_pct"] = round(gap, 4)
        factors["tw_gap_up_ge_0_8"] = gap >= 0.8
        factors["tw_gap_dn_le_m0_8"] = gap <= -0.8

    # 宏觀 prior（美盤日）
    us_days = sorted(ixic.keys())
    u = None
    for d in us_days:
        if d < day:
            u = d
        else:
            break

    def take(name: str, m: Dict[str, Dict[str, float]]) -> Optional[float]:
        if not u or u not in m or not m[u].get("ret_ok"):
            missing.append(name)
            return None
        factors[name] = m[u]["ret"]
        return float(m[u]["ret"])

    r10 = take("us10y_prior_ret", us10y)
    rj = take("usdjpy_prior_ret", usdjpy)
    rg = take("gold_prior_ret", gold)
    rc = take("copper_prior_ret", copper)
    rv = take("vix_prior_ret", vix)
    factors["us10y_up_tw_down"] = bool(r10 is not None and r10 >= 0.05 and bar["ret"] <= -0.8)
    factors["yen_up_tw_down"] = bool(rj is not None and rj <= -0.6 and bar["ret"] <= -0.8)  # USDJPY跌＝日圓升
    factors["gold_up_risk_off"] = bool(rg is not None and rg >= 1.0 and bar["ret"] <= -0.5)
    factors["copper_down_risk_off"] = bool(rc is not None and rc <= -1.5 and bar["ret"] <= -0.5)
    # VIX 極端：用過去 z
    if u and u in vix:
        vz = _z({d: vix[d]["close"] for d in vix}, u)
        if vz is not None:
            factors["vix_z"] = round(vz, 4)
            factors["vix_z_ge_p1"] = vz >= 1.0
            factors["vix_z_le_m1"] = vz <= -1.0
        else:
            missing.append("vix_z")

    # 美強台弱持續 2 日
    if i >= 1 and u:
        prev_u = None
        for d in us_days:
            if d < tw_days[i - 1]:
                prev_u = d
            else:
                break
        if prev_u and prev_u in ixic and u in ixic:
            factors["us_tw_diverge_2d"] = bool(
                ixic[u]["ret"] >= 0.6
                and bar["ret"] <= -0.5
                and ixic[prev_u]["ret"] >= 0.4
                and twii[tw_days[i - 1]]["ret"] <= -0.4
            )

    # 2330 vs TSM ADR 溢價（同日或美先）
    if day in tw2330 and u and u in tsm and tw2330[day]["close"] > 0 and tsm[u]["close"] > 0:
        # 粗溢價代理：兩日報酬差（非精確匯率溢價；標清楚）
        prem = tw2330[day]["ret"] - tsm[u]["ret"]
        factors["adr_ret_gap"] = round(prem, 4)
        factors["adr_tw_lag"] = prem <= -1.0  # 台積日弱於 ADR
        factors["adr_tw_lead"] = prem >= 1.0
    else:
        missing.append("adr_premium")

    # 台積量價→大盤確認（飆大：用台積量價看整體台股；只當確認不是主判）
    if day in tw2330:
        bar2330 = tw2330[day]
        vols = [
            float(tw2330[tw_days[j]].get("volume") or 0.0)
            for j in range(max(0, i - 20), i)
            if tw_days[j] in tw2330 and (tw2330[tw_days[j]].get("volume") or 0) > 0
        ]
        # tw_days 是 TWII 日；2330 可能缺日 → 改用 2330 自己的日前窗
        if len(vols) < 8:
            keys2330 = sorted(tw2330)
            if day in keys2330:
                ii = keys2330.index(day)
                vols = [
                    float(tw2330[keys2330[j]].get("volume") or 0.0)
                    for j in range(max(0, ii - 20), ii)
                    if (tw2330[keys2330[j]].get("volume") or 0) > 0
                ]
        v0 = float(bar2330.get("volume") or 0.0)
        if len(vols) >= 8 and v0 > 0:
            med = sorted(vols)[len(vols) // 2]
            spike = bool(med > 0 and v0 >= med * 1.8)
            factors["tsmc_vol_spike"] = spike
            ret2330 = float(bar2330.get("ret") or 0.0)
            # 爆量收紅＝偏多確認；爆量收黑＝偏空確認（量價結構代理）
            factors["tsmc_vol_confirm_up"] = bool(spike and ret2330 >= 0.8)
            factors["tsmc_vol_confirm_down"] = bool(spike and ret2330 <= -0.8)
        else:
            missing.append("tsmc_vol")
    else:
        missing.append("tsmc_vol")

    # 櫃買 OTC：有長史才比廣度（加權被權值綁架時對質）；缺就不硬填
    if otc and day in otc and otc[day].get("ret_ok"):
        otc_r = float(otc[day]["ret"])
        tw_r = float(bar.get("ret") or 0.0)
        factors["otc_ret"] = otc_r
        factors["otc_lag_tw"] = bool(otc_r <= -0.8 and tw_r >= 0.3)
        factors["otc_lead_tw"] = bool(otc_r >= 0.8 and tw_r <= -0.3)
    elif otc is not None:
        missing.append("otc_ret")

    # 現貨－夜盤基差
    if day in tx_night_px and bar["close"] > 0:
        basis = (tx_night_px[day] / bar["close"] - 1.0) * 100.0
        factors["tx_basis_pct"] = round(basis, 4)
        factors["tx_contango_ge_0_4"] = basis >= 0.4
        factors["tx_backward_le_m0_4"] = basis <= -0.4
    else:
        missing.append("tx_basis")

    return factors, missing


def quantify_extras(conn: sqlite3.Connection) -> Dict[str, Any]:
    twii = _load_sym(conn, "TWII")
    ixic = _load_sym(conn, "IXIC")
    sox = _load_sym(conn, "SOX")
    vix = _load_sym(conn, "VIX")
    us10y = _load_sym(conn, "US10Y")
    usdjpy = _load_sym(conn, "USDJPY")
    gold = _load_sym(conn, "GOLD")
    copper = _load_sym(conn, "COPPER")
    tsm = _load_sym(conn, "TSM")
    # 2330 from daily_quotes（含量，供量價確認）
    tw2330: Dict[str, Dict[str, float]] = {}
    prev = None
    for d, c, vol in conn.execute(
        "SELECT REPLACE(CAST(date AS TEXT),'-',''), close, volume FROM daily_quotes WHERE stock_id='2330' ORDER BY 1"
    ):
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc:
            continue
        ret = ((cc / prev - 1.0) * 100.0) if prev else None
        tw2330[day] = {
            "close": cc,
            "ret": ret or 0.0,
            "ret_ok": ret is not None,
            "volume": _f(vol) or 0.0,
        }
        prev = cc
    otc = _load_sym(conn, "OTC")
    tx_night = _load_tx_night_close(conn)
    tw_days = sorted(twii.keys())
    idx = {d: i for i, d in enumerate(tw_days)}

    def fwd3(d: str) -> Optional[float]:
        i = idx.get(d)
        if i is None or i + 3 >= len(tw_days):
            return None
        return (twii[tw_days[i + 3]]["close"] / twii[d]["close"] - 1.0) * 100.0

    day_f: Dict[str, Dict[str, Any]] = {}
    for d in tw_days[:-3]:
        f, _m = snapshot_extras(
            twii=twii,
            ixic=ixic,
            sox=sox,
            vix=vix,
            us10y=us10y,
            usdjpy=usdjpy,
            gold=gold,
            copper=copper,
            tsm=tsm,
            tw2330=tw2330,
            tx_night_px=tx_night,
            tw_days=tw_days,
            as_of=d,
            otc=otc or None,
        )
        if f:
            day_f[d] = f
    days = [d for d in sorted(day_f) if fwd3(d) is not None]
    base = [fwd3(d) for d in days]
    base = [x for x in base if x is not None]
    base_m = (sum(base) / len(base)) if base else 0.0
    flags: List[Dict[str, Any]] = []

    codes = [
        "tw_down_streak_ge3",
        "tw_up_streak_ge3",
        "tw_gap_up_ge_0_8",
        "tw_gap_dn_le_m0_8",
        "us10y_up_tw_down",
        "yen_up_tw_down",
        "gold_up_risk_off",
        "copper_down_risk_off",
        "vix_z_ge_p1",
        "vix_z_le_m1",
        "us_tw_diverge_2d",
        "adr_tw_lag",
        "adr_tw_lead",
        "tx_contango_ge_0_4",
        "tx_backward_le_m0_4",
        "tsmc_vol_confirm_up",
        "tsmc_vol_confirm_down",
        "otc_lag_tw",
        "otc_lead_tw",
    ]

    def add(code: str) -> None:
        xs = [fwd3(d) for d in days if day_f[d].get(code)]
        xs = [x for x in xs if x is not None]
        if len(xs) < MIN_N:
            return
        m = sum(xs) / len(xs)
        edge = m - base_m
        if abs(edge) < MIN_EDGE:
            return
        if edge > 0:
            hit = sum(1 for x in xs if x > 0.6) / len(xs)
            bias = "up"
        else:
            hit = sum(1 for x in xs if x < -0.6) / len(xs)
            bias = "down"
        if hit < MIN_SIDE_HIT:
            return
        flags.append(
            {
                "code": code,
                "n": len(xs),
                "mean3": round(m, 4),
                "edge3": round(edge, 4),
                "bias": bias,
                "hit_rate_side": round(hit, 4),
                "vote": round(edge, 4),
            }
        )

    for c in codes:
        add(c)
    flags.sort(key=lambda x: -abs(float(x["edge3"])))

    # 分市況基線（無模型，只記母體）
    by_reg: Dict[str, Any] = {}
    for reg in ("bull", "bear", "chop"):
        sub = [fwd3(d) for d in days if day_f[d].get("regime") == reg]
        sub = [x for x in sub if x is not None]
        by_reg[reg] = {
            "n": len(sub),
            "mean3": round(sum(sub) / len(sub), 4) if sub else None,
        }

    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "scored_days": len(days),
        "base_mean3": round(base_m, 4),
        "flags": flags,
        "n_flags": len(flags),
        "regime_baseline": by_reg,
        "ideas_zh": [
            "美債／日圓／金銅／VIX",
            "ADR溢價代理",
            "美台背離2日",
            "連漲跌／跳空",
            "夜盤基差",
            "分市況母體",
        ],
        "missing_hard_zh": ["OTC長史", "VVIX", "TX夜盤OI常為0"],
        "gate": "n>=20 & |edge|>=0.25 & side_hit>=0.55",
        "goal_zh": "提高大盤方向＋幅度判斷；波浪主判外確認／否決",
        "not_buy_signal": True,
        "phone_sync": "blocked",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "path_extras_quant_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "path_extras_flags.jsonl.gz", "wt", encoding="utf-8") as f:
        for row in flags:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return summary


def load_extras_votes(path: Optional[Path] = None) -> Dict[str, float]:
    p = path or (OUT_DIR / "path_extras_quant_latest.json")
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: Dict[str, float] = {}
    for row in d.get("flags") or []:
        code = str(row.get("code") or "")
        if code:
            out[code] = float(row.get("vote") or row.get("edge3") or 0.0)
    return out


def main() -> int:
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        summary = quantify_extras(conn)
    finally:
        conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
