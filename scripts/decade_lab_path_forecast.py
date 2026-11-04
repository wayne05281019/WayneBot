#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大盤走勢預測（靜默）｜從投資人要的結果反推。

目標（使用者鎖）：預判大盤漲勢（方向）及幅度。

投資人要的最終答案：
1. 這一段往哪（up／down／range）
2. 預估幅度 amp_pct（%）、目標價與失效價
3. 依據哪些因素（可覆盤歸因；幅度錯了也要能檢討）

因素與切法＝本模組責任（不准丟回使用者決定）。
缺就標缺；只落數字 json／gz；不准存圖；不是買訊；不准進話筒。
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
LAB_DB = Path(os.environ.get("DECADE_LAB_DB") or (ROOT / "data" / "decade_lab.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

# 投資人產出欄（責任切面）
INVESTOR_OUTPUT = (
    "bias",  # up|down|range
    "amp_pct",  # 預估幅度％（漲勢為正、跌勢為負）
    "amp_class",  # micro|small|mid|large
    "horizon",  # session(1d)|segment(3d)
    "last_close",
    "target",
    "invalidate",
    "factors",  # 當下鎖進的因素快照
    "missing",  # 缺什麼 → 覆盤時知道資訊不完整
    "why_codes",  # 點亮的可沿用旗標／結構碼
)

# 我負責納入的因素包（正反：預測要準＋錯了能歸因）
FACTOR_PACK = (
    # A 結構
    "twii_ret",
    "twii_wick",
    "twii_vol_spike",
    "twii_prev_ret",
    # B 美股領導
    "ixic_prior_ret",
    "sox_prior_ret",
    "vix_prior_ret",
    # C 權值／半導體代理
    "tsm_prior_ret",
    "nvda_prior_ret",
    # D 外圍風險
    "dxy_prior_ret",
    "usdtwd_prior_ret",
    "brent_prior_ret",
    # E 期貨夜盤（有才納；缺標缺）
    "tx_night_ret",
)

# 可沿用旗標權重：用 reusable_quant 的 edge 符號當票（正 edge→偏多票）
# 這裡內建已量化過關的碼；檔案更新時可覆寫
DEFAULT_EDGE_VOTES: Dict[str, float] = {
    "us_up_tw_down": 0.57,
    "us_risk_off_tw_green": 0.45,
    "us_down_tw_hold": 0.36,
    "tw_vol_spike": 0.41,
    "after_tw_down2_with_wick": 0.90,
    "after_tw_down2_us_up": 0.56,
    "after_tw_down2_vol_spike": 0.49,
    "tw_crash_3pct": 0.31,
    "dxy_up_tw_down": -0.64,
    "brent_up_tw_down": -0.40,
    "fx_up_tw_down": -0.77,
}

DDL = """
CREATE TABLE IF NOT EXISTS path_forecast (
    as_of TEXT NOT NULL,
    horizon TEXT NOT NULL,
    bias TEXT NOT NULL,
    last_close REAL,
    target REAL,
    invalidate REAL,
    factors_json TEXT NOT NULL DEFAULT '{}',
    missing_json TEXT NOT NULL DEFAULT '[]',
    why_json TEXT NOT NULL DEFAULT '[]',
    score REAL,
    verdict TEXT NOT NULL DEFAULT '',
    check_close REAL,
    checked_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    amp_pct REAL,
    amp_class TEXT NOT NULL DEFAULT '',
    amp_verdict TEXT NOT NULL DEFAULT '',
    actual_ret_pct REAL,
    PRIMARY KEY (as_of, horizon)
);
"""


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


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _load_sym(conn: sqlite3.Connection, symbol: str) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume, pct_change
        FROM index_daily WHERE symbol=? ORDER BY 1
        """,
        (symbol,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev = None
    for d, o, h, l, c, vol, pct in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = _f(pct)
        if ret is None and prev and prev > 0:
            ret = (cc / prev - 1.0) * 100.0
        out[day] = {
            "open": _f(o) or cc,
            "high": _f(h) or cc,
            "low": _f(l) or cc,
            "close": cc,
            "volume": _f(vol) or 0.0,
            "ret": ret if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _load_tx_night(conn: sqlite3.Connection) -> Dict[str, float]:
    out: Dict[str, float] = {}
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), pct_change, close
            FROM futures_daily WHERE symbol='TX' AND session='night' ORDER BY 1
            """
        ).fetchall()
    except sqlite3.Error:
        return out
    prev = None
    for d, pct, c in rows:
        day = _ymd(d)
        if not day:
            continue
        r = _f(pct)
        if r is None and prev and _f(c) and prev > 0:
            r = (float(c) / prev - 1.0) * 100.0
        if r is not None:
            out[day] = r
        if _f(c):
            prev = float(c)
    return out


def _prior(us_days: Sequence[str], tw: str) -> Optional[str]:
    prev = None
    for d in us_days:
        if d < tw:
            prev = d
        else:
            break
    return prev


def _wick(bar: Dict[str, float]) -> float:
    span = bar["high"] - bar["low"]
    if span <= 0:
        return 0.0
    return (min(bar["open"], bar["close"]) - bar["low"]) / span


def _load_edge_votes() -> Dict[str, float]:
    path = OUT_DIR / "reusable_quant_latest.json"
    votes = dict(DEFAULT_EDGE_VOTES)
    if not path.is_file():
        return votes
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return votes
    for r in blob.get("reusable") or []:
        flag = str(r.get("flag") or "")
        edge = _f(r.get("edge3"))
        n = int(r.get("n") or 0)
        if flag and edge is not None and n >= 20:
            votes[flag] = float(edge)
    return votes


def snapshot_factors(
    *,
    twii: Dict[str, Dict[str, float]],
    ixic: Dict[str, Dict[str, float]],
    sox: Dict[str, Dict[str, float]],
    vix: Dict[str, Dict[str, float]],
    tsm: Dict[str, Dict[str, float]],
    nvda: Dict[str, Dict[str, float]],
    dxy: Dict[str, Dict[str, float]],
    usdtwd: Dict[str, Dict[str, float]],
    brent: Dict[str, Dict[str, float]],
    tx_night: Dict[str, float],
    tw_days: Sequence[str],
    as_of: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """只准用 as_of 當日（含）以前的資訊。"""
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    if day not in twii or not twii[day].get("ret_ok"):
        return {}, ["twii_bar"]
    i = list(tw_days).index(day)
    bar = twii[day]
    factors["twii_ret"] = bar["ret"]
    factors["twii_wick"] = _wick(bar)
    # vol spike vs prior 20
    vols = [twii[tw_days[j]]["volume"] for j in range(max(0, i - 20), i) if twii[tw_days[j]]["volume"] > 0]
    ma = (sum(vols) / len(vols)) if vols else 0.0
    factors["twii_vol_spike"] = bool(ma > 0 and bar["volume"] >= 1.5 * ma)
    if i >= 1 and twii[tw_days[i - 1]].get("ret_ok"):
        factors["twii_prev_ret"] = twii[tw_days[i - 1]]["ret"]
    else:
        missing.append("twii_prev_ret")

    us_days = sorted(ixic.keys())
    u = _prior(us_days, day)
    if not u:
        missing.extend(
            [
                "ixic_prior_ret",
                "sox_prior_ret",
                "vix_prior_ret",
                "tsm_prior_ret",
                "nvda_prior_ret",
                "dxy_prior_ret",
                "usdtwd_prior_ret",
                "brent_prior_ret",
            ]
        )
    else:
        factors["us_as_of"] = u

        def take(name: str, m: Dict[str, Dict[str, float]]) -> None:
            b = m.get(u)
            if b and b.get("ret_ok"):
                factors[name] = b["ret"]
            else:
                missing.append(name)

        take("ixic_prior_ret", ixic)
        take("sox_prior_ret", sox)
        take("vix_prior_ret", vix)
        take("tsm_prior_ret", tsm)
        take("nvda_prior_ret", nvda)
        take("dxy_prior_ret", dxy)
        take("usdtwd_prior_ret", usdtwd)
        take("brent_prior_ret", brent)

    # TX night：同日或前一日
    if day in tx_night:
        factors["tx_night_ret"] = tx_night[day]
    elif u and u in tx_night:
        factors["tx_night_ret"] = tx_night[u]
    else:
        missing.append("tx_night_ret")

    return factors, missing


def _lit_why(factors: Dict[str, Any], votes: Dict[str, float]) -> List[Dict[str, Any]]:
    tw = _f(factors.get("twii_ret")) or 0.0
    ix = _f(factors.get("ixic_prior_ret"))
    dx = _f(factors.get("dxy_prior_ret"))
    br = _f(factors.get("brent_prior_ret"))
    fx = _f(factors.get("usdtwd_prior_ret"))
    wick = _f(factors.get("twii_wick")) or 0.0
    vol_spike = bool(factors.get("twii_vol_spike"))
    lit = []

    def add(code: str, ok: bool) -> None:
        if not ok or code not in votes:
            return
        lit.append({"code": code, "edge": votes[code]})

    if ix is not None:
        add("us_up_tw_down", ix >= 1.0 and tw <= -0.8)
        add("us_down_tw_hold", ix <= -1.5 and tw >= -0.55)
        add("us_risk_off_tw_green", ix <= -1.5 and tw > 0.2)
        add("after_tw_down2_us_up", tw <= -2.0 and ix >= 0.5)
    add("tw_vol_spike", vol_spike)
    add("after_tw_down2_with_wick", tw <= -2.0 and wick >= 0.45)
    add("after_tw_down2_vol_spike", tw <= -2.0 and vol_spike)
    add("tw_crash_3pct", tw <= -3.0)
    if dx is not None:
        add("dxy_up_tw_down", dx >= 0.6 and tw <= -0.8)
    if br is not None:
        add("brent_up_tw_down", br >= 2.0 and tw <= -0.8)
    if fx is not None:
        add("fx_up_tw_down", fx >= 0.4 and tw <= -0.8)
    return lit


def decide_path(factors: Dict[str, Any], missing: Sequence[str], votes: Dict[str, float]) -> Dict[str, Any]:
    """產出投資人要的預測列。因素不夠仍給 bias，但標 reviewable=false。"""
    last = None
    # last_close must be passed via factors helper — caller fills
    lit = _lit_why(factors, votes)
    score = sum(float(x["edge"]) for x in lit)
    # 結構微調：大跌＋下影偏多；美元／油漲＋台跌偏空已在票裡
    if score > 0.35:
        bias = "up"
    elif score < -0.35:
        bias = "down"
    else:
        bias = "range"
    # 必要因素：至少有 twii＋ixic，否則不可完整覆盤歸因
    need = {"twii_ret", "ixic_prior_ret"}
    have = set(factors.keys())
    reviewable = need.issubset(have) and len(missing) <= 4
    return {
        "bias": bias,
        "score": round(score, 4),
        "why": lit,
        "reviewable": reviewable,
        "missing": list(missing),
    }


def _amp_class(amp_abs: float) -> str:
    a = abs(float(amp_abs))
    if a < 0.6:
        return "micro"
    if a < 1.5:
        return "small"
    if a < 3.0:
        return "mid"
    return "large"


def estimate_amplitude(
    bias: str,
    score: float,
    factors: Dict[str, Any],
    *,
    realized_abs_ret: Optional[float] = None,
) -> Dict[str, Any]:
    """估幅度％。漲勢為正、跌勢為負；range＝0。

    自修：純票強度 MAE 大；近窗實現波動（日均 |ret| ×√3）準度較高，改為主幹，
    票強度／量能／VIX／夜盤只做微調。
    """
    if bias not in {"up", "down"}:
        return {"amp_pct": 0.0, "amp_class": "micro", "amp_basis": "range_no_amp"}
    strength = abs(float(score or 0.0))
    score_leg = 0.45 + min(2.4, strength * 0.85)
    if realized_abs_ret is not None and realized_abs_ret > 0:
        # 3 日窗 ≈ 日波動 × √3
        rv_leg = float(realized_abs_ret) * (3.0 ** 0.5) * 1.10
        base = 0.75 * rv_leg + 0.25 * score_leg
        basis = "rv20_sqrt3_primary"
    else:
        base = score_leg
        basis = "score_fallback"
    if bool(factors.get("twii_vol_spike")):
        base += 0.20
    vix = _f(factors.get("vix_prior_ret"))
    if vix is not None and abs(vix) >= 8.0:
        base += 0.15
    tw = abs(_f(factors.get("twii_ret")) or 0.0)
    if tw >= 2.0:
        base += 0.10
    tx = _f(factors.get("tx_night_ret"))
    if tx is not None:
        if bias == "up" and tx > 0.3:
            base += 0.10
        elif bias == "down" and tx < -0.3:
            base += 0.10
        elif bias == "up" and tx < -0.5:
            base -= 0.10
        elif bias == "down" and tx > 0.5:
            base -= 0.10
    amp_abs = max(0.40, min(4.0, base))
    amp = amp_abs if bias == "up" else -amp_abs
    return {
        "amp_pct": round(amp, 3),
        "amp_class": _amp_class(amp_abs),
        "amp_basis": basis,
    }


def _targets(bias: str, last_close: float, amp_pct: float = 0.8) -> Tuple[float, float]:
    """目標＝預估幅度；失效＝反向約一半幅度（破了＝方向判斷作廢）。"""
    if last_close <= 0:
        return last_close, last_close
    if bias == "up":
        a = abs(float(amp_pct) or 0.8) / 100.0
        return last_close * (1.0 + a), last_close * (1.0 - a * 0.5)
    if bias == "down":
        a = abs(float(amp_pct) or 0.8) / 100.0
        return last_close * (1.0 - a), last_close * (1.0 + a * 0.5)
    return last_close, last_close * 0.985


def ensure_lab(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(path_forecast)")}
    for name, typ in (
        ("amp_pct", "REAL"),
        ("amp_class", "TEXT"),
        ("amp_verdict", "TEXT"),
        ("actual_ret_pct", "REAL"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE path_forecast ADD COLUMN {name} {typ}")


def upsert_forecast(conn: sqlite3.Connection, rec: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO path_forecast(
            as_of, horizon, bias, last_close, target, invalidate,
            factors_json, missing_json, why_json, score, verdict,
            check_close, checked_at, created_at,
            amp_pct, amp_class, amp_verdict, actual_ret_pct
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of, horizon) DO UPDATE SET
            bias=excluded.bias, last_close=excluded.last_close,
            target=excluded.target, invalidate=excluded.invalidate,
            factors_json=excluded.factors_json, missing_json=excluded.missing_json,
            why_json=excluded.why_json, score=excluded.score,
            verdict=excluded.verdict, check_close=excluded.check_close,
            checked_at=excluded.checked_at, created_at=excluded.created_at,
            amp_pct=excluded.amp_pct, amp_class=excluded.amp_class,
            amp_verdict=excluded.amp_verdict, actual_ret_pct=excluded.actual_ret_pct
        """,
        (
            rec["as_of"],
            rec["horizon"],
            rec["bias"],
            rec.get("last_close"),
            rec.get("target"),
            rec.get("invalidate"),
            json.dumps(rec.get("factors") or {}, ensure_ascii=False),
            json.dumps(rec.get("missing") or [], ensure_ascii=False),
            json.dumps(rec.get("why") or [], ensure_ascii=False),
            rec.get("score"),
            rec.get("verdict") or "",
            rec.get("check_close"),
            rec.get("checked_at") or "",
            rec.get("created_at") or _now(),
            rec.get("amp_pct"),
            rec.get("amp_class") or "",
            rec.get("amp_verdict") or "",
            rec.get("actual_ret_pct"),
        ),
    )


def _judge(bias: str, last: float, close: float, invalidate: float) -> str:
    """方向對錯。range＝無明確方向，不計勝率（觀望）。"""
    if close <= 0 or last <= 0:
        return "還沒走完"
    ret = (close / last - 1.0) * 100.0
    if bias == "up":
        if close > last:
            return f"對得上往上：收{close:.0f}"
        if close < invalidate:
            return f"偏了破失效：收{close:.0f}"
        return f"偏了沒往上：收{close:.0f}（{ret:+.2f}%）"
    if bias == "down":
        if close < last:
            return f"對得上往下：收{close:.0f}"
        if close > invalidate:
            return f"偏了破失效：收{close:.0f}"
        return f"偏了沒往下：收{close:.0f}（{ret:+.2f}%）"
    return f"觀望不計分：收{close:.0f}（{ret:+.2f}%）"


def _judge_amp(bias: str, amp_pct: float, actual_ret: float) -> str:
    """幅度對質：僅在方向對時計；落在預估帶＝幅度對得上。

    帶寬：預估 |amp| 的 50%～150%，且至少 ±0.35pt 容差。
    """
    if bias not in {"up", "down"}:
        return "觀望不計幅度"
    if bias == "up" and actual_ret <= 0:
        return "方向偏了不計幅度"
    if bias == "down" and actual_ret >= 0:
        return "方向偏了不計幅度"
    pred = abs(float(amp_pct) or 0.0)
    act = abs(float(actual_ret) or 0.0)
    if pred <= 0:
        return "無幅度預測"
    lo = max(0.0, pred * 0.5 - 0.15)
    hi = pred * 1.5 + 0.35
    if lo <= act <= hi:
        return f"幅度對得上：估{amp_pct:+.2f}% 實{actual_ret:+.2f}%"
    return f"幅度偏了：估{amp_pct:+.2f}% 實{actual_ret:+.2f}%"


def run_backtest(*, max_days: int = 0) -> Dict[str, Any]:
    votes = _load_edge_votes()
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        twii = _load_sym(conn, "TWII")
        ixic = _load_sym(conn, "IXIC")
        sox = _load_sym(conn, "SOX")
        vix = _load_sym(conn, "VIX")
        tsm = _load_sym(conn, "TSM")
        nvda = _load_sym(conn, "NVDA")
        dxy = _load_sym(conn, "DXY")
        usdtwd = _load_sym(conn, "USDTWD")
        brent = _load_sym(conn, "BRENT")
        tx_night = _load_tx_night(conn)
    finally:
        conn.close()

    tw_days = sorted(twii.keys())
    # segment horizon＝後 3 根；預測日用「當日收盤後」視角對下一窗（用當日因素預測未來，對質用後3日收）
    # 為免偷看：factors 用 as_of 當日已知（收盤後建檔）
    lab = sqlite3.connect(str(LAB_DB), timeout=60.0)
    ensure_lab(lab)
    wrote = 0
    scored = []
    days = tw_days[:-3]  # need forward
    if max_days > 0:
        days = days[-max_days:]
    for day in days:
        if day not in twii or not twii[day].get("ret_ok"):
            continue
        factors, missing = snapshot_factors(
            twii=twii,
            ixic=ixic,
            sox=sox,
            vix=vix,
            tsm=tsm,
            nvda=nvda,
            dxy=dxy,
            usdtwd=usdtwd,
            brent=brent,
            tx_night=tx_night,
            tw_days=tw_days,
            as_of=day,
        )
        if not factors:
            continue
        decision = decide_path(factors, missing, votes)
        last = twii[day]["close"]
        # 近 20 日 |ret| 均（as-of 前，不含未來）
        i0 = tw_days.index(day)
        prior_abs = [
            abs(float(twii[tw_days[j]]["ret"]))
            for j in range(max(0, i0 - 20), i0)
            if twii[tw_days[j]].get("ret_ok")
        ]
        rv = (sum(prior_abs) / len(prior_abs)) if len(prior_abs) >= 5 else None
        amp_info = estimate_amplitude(
            decision["bias"],
            float(decision["score"] or 0.0),
            factors,
            realized_abs_ret=rv,
        )
        amp_pct = float(amp_info["amp_pct"])
        tgt, inv = _targets(decision["bias"], last, amp_pct)
        # forward close
        i = tw_days.index(day)
        fut = twii[tw_days[i + 3]]["close"]
        actual_ret = ((fut / last - 1.0) * 100.0) if last > 0 else 0.0
        verd = _judge(decision["bias"], last, fut, inv) if decision["reviewable"] else "因素不足不計分"
        amp_verd = (
            _judge_amp(decision["bias"], amp_pct, actual_ret)
            if decision["reviewable"]
            else "因素不足不計幅度"
        )
        rec = {
            "as_of": day,
            "horizon": "segment3",
            "bias": decision["bias"],
            "amp_pct": amp_pct,
            "amp_class": amp_info.get("amp_class"),
            "last_close": last,
            "target": tgt,
            "invalidate": inv,
            "factors": factors,
            "missing": decision["missing"],
            "why": decision["why"],
            "score": decision["score"],
            "verdict": verd,
            "amp_verdict": amp_verd,
            "actual_ret_pct": round(actual_ret, 4),
            "check_close": fut,
            "checked_at": _now(),
            "created_at": _now(),
            "reviewable": decision["reviewable"],
        }
        upsert_forecast(lab, rec)
        wrote += 1
        if decision["reviewable"] and ("對得上" in verd or "偏了" in verd):
            scored.append(
                {
                    "as_of": day,
                    "bias": decision["bias"],
                    "amp_pct": amp_pct,
                    "amp_class": amp_info.get("amp_class"),
                    "actual_ret_pct": round(actual_ret, 4),
                    "verdict": verd,
                    "amp_verdict": amp_verd,
                    "score": decision["score"],
                    "why": decision["why"],
                }
            )
    lab.commit()

    # 投資人可用：只計有方向（up/down）的對質
    dir_rows = [r for r in scored if r.get("bias") in {"up", "down"}]
    hit = sum(1 for r in dir_rows if "對得上" in r["verdict"])
    miss = sum(1 for r in dir_rows if "偏了" in r["verdict"])
    amp_rows = [r for r in dir_rows if "對得上" in (r.get("verdict") or "")]
    amp_hit = sum(1 for r in amp_rows if "幅度對得上" in (r.get("amp_verdict") or ""))
    amp_miss = sum(1 for r in amp_rows if "幅度偏了" in (r.get("amp_verdict") or ""))
    # 幅度誤差（方向對的樣本）
    abs_err = [
        abs(abs(float(r.get("amp_pct") or 0)) - abs(float(r.get("actual_ret_pct") or 0)))
        for r in amp_rows
    ]
    mae = (sum(abs_err) / len(abs_err)) if abs_err else None
    by_bias = {}
    for b in ("up", "down"):
        sub = [r for r in dir_rows if r.get("bias") == b]
        h = sum(1 for r in sub if "對得上" in r["verdict"])
        m = sum(1 for r in sub if "偏了" in r["verdict"])
        by_bias[b] = {
            "n": h + m,
            "hit": h,
            "miss": m,
            "hit_rate": (h / (h + m)) if (h + m) else None,
        }
    by_amp_class: Dict[str, Any] = {}
    for cls in ("micro", "small", "mid", "large"):
        sub = [r for r in amp_rows if r.get("amp_class") == cls]
        ah = sum(1 for r in sub if "幅度對得上" in (r.get("amp_verdict") or ""))
        am = sum(1 for r in sub if "幅度偏了" in (r.get("amp_verdict") or ""))
        by_amp_class[cls] = {
            "n": ah + am,
            "hit": ah,
            "miss": am,
            "hit_rate": (ah / (ah + am)) if (ah + am) else None,
        }
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "goal_zh": "預判大盤漲勢（方向）及幅度",
        "investor_output": list(INVESTOR_OUTPUT),
        "factor_pack": list(FACTOR_PACK),
        "my_responsibility_zh": (
            "最終答案＝漲勢方向＋預估幅度％＋目標／失效＋依據。"
            "要納入哪些因素、怎麼切、怎麼估幅度＝程式責任；使用者只收結果與覆盤。"
        ),
        "wrote": wrote,
        "scored_n": len(scored),
        "directional_n": hit + miss,
        "hit": hit,
        "miss": miss,
        "hit_rate_directional": (hit / (hit + miss)) if (hit + miss) else None,
        "amp_n": amp_hit + amp_miss,
        "amp_hit": amp_hit,
        "amp_miss": amp_miss,
        "hit_rate_amplitude": (amp_hit / (amp_hit + amp_miss)) if (amp_hit + amp_miss) else None,
        "amp_mae_pct": round(mae, 4) if mae is not None else None,
        "by_bias": by_bias,
        "by_amp_class": by_amp_class,
        "gate_n20": (hit + miss) >= 20,
        "reverse_think_zh": (
            "目標是漲勢＋幅度。只對方向不夠；幅度偏了要回查波動／夜盤／外圍強度是否估錯。"
            "range＝觀望不計分。因素不足→factor_gap_queue。"
        ),
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "storage": "decade_lab.path_forecast + json/gz；不准 PNG",
    }
    lab.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "path_forecast_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "path_forecast_scored_latest.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in scored[-5000:]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # 因素不足／準度偏弱 → 記錄發想＋排程補抓重測（不准吞掉）
    try:
        from scripts.decade_lab_factor_gap_queue import record_gap

        gap = record_gap(source="path_forecast", path_summary=summary)
        summary["factor_gap"] = {
            "id": gap.get("id"),
            "fruitless": gap.get("fruitless"),
            "ideas_n": len(gap.get("ideas") or []),
            "schedule_n": len(gap.get("schedule") or []),
            "reason_zh": (gap.get("reason_zh") or "")[:300],
        }
    except Exception as exc:  # noqa: BLE001 — 缺口佇列失敗不准擋主回測落檔
        summary["factor_gap_error"] = str(exc)[:200]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-days", type=int, default=0, help="0=全長史；否則只跑最近 N 日")
    args = ap.parse_args()
    summary = run_backtest(max_days=args.max_days)
    return 0 if summary.get("wrote", 0) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
