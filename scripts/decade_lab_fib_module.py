#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""黃金切割率模組（靜默）｜完整 Fib 回撤／延伸進路徑預測驗證。

已有：波浪鐵律擴延≥1.618、ABC B 回撤 0.382–0.786（wave8_dual）。
本模組補齊投資人路徑用的切割位：
- 回撤／反彈：0.382／0.5／0.618／0.75／0.786
- 延伸目標：1.0／1.272／1.618／2.618
- 近位旗標→方向票；切割跨度→幅度候選（對質贏才可換 RV）

規則：只用已收官方柱；不准假數；不是買訊；不上話筒。
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

from mine_wave_rules import (  # noqa: E402
    DEFAULT_EXT_RATIOS,
    DEFAULT_RETRACE_RATIOS,
    fib_extension_targets,
    fib_retracement_levels,
)

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
MIN_EDGE = 0.25
MIN_SIDE_HIT = 0.55
NEAR_PCT = 1.0  # 收盤距切割位 ≤1.0% 算「貼近」（0.35% 過緊幾乎點不亮）
ZONE_PCT = 1.5  # 稍寬帶：≤1.5%
POS_BAND = 0.05  # 在 swing 比例座標上距切割比 ≤0.05 也算貼近
SWING_LOOK = 60


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


def load_twii(conn: sqlite3.Connection) -> List[Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), high, low, close
        FROM index_daily WHERE symbol='TWII'
        ORDER BY 1
        """
    ).fetchall()
    out: List[Dict[str, float]] = []
    for d, h, lo, c in rows:
        day = _ymd(d)
        hh, ll, cc = _f(h), _f(lo), _f(c)
        if not day or hh is None or ll is None or cc is None or cc <= 0:
            continue
        out.append({"date": day, "high": hh, "low": ll, "close": cc})
    return out


def _swing(bars: Sequence[Dict[str, float]], i: int, look: int = SWING_LOOK) -> Optional[Dict[str, float]]:
    """as-of 前 look 根（含當日）高低窗。"""
    if i < 0 or i >= len(bars):
        return None
    start = max(0, i - look + 1)
    window = bars[start : i + 1]
    if len(window) < 20:
        return None
    hi = max(float(b["high"]) for b in window)
    lo = min(float(b["low"]) for b in window)
    if hi <= lo:
        return None
    return {"high": hi, "low": lo, "span": hi - lo, "n": float(len(window))}


def _near(px: float, level: float, tol_pct: float = NEAR_PCT) -> bool:
    if px <= 0 or level <= 0:
        return False
    return abs(px - level) / px * 100.0 <= tol_pct


def snapshot_fib_factors(
    bars: Sequence[Dict[str, float]],
    as_of: str,
    *,
    look: int = SWING_LOOK,
) -> Tuple[Dict[str, Any], List[str]]:
    """as-of 當日黃金切割因素（只准用當日與以前）。"""
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    idx = {b["date"]: i for i, b in enumerate(bars)}
    i = idx.get(day)
    if i is None:
        return factors, ["fib_as_of"]
    sw = _swing(bars, i, look=look)
    if not sw:
        return factors, ["fib_swing"]
    px = float(bars[i]["close"])
    hi, lo, span = float(sw["high"]), float(sw["low"]), float(sw["span"])
    factors["fib_swing_high"] = hi
    factors["fib_swing_low"] = lo
    factors["fib_swing_span"] = round(span, 4)
    factors["fib_swing_span_pct"] = round(span / px * 100.0, 4)

    pull = fib_retracement_levels(hi, lo, ratios=DEFAULT_RETRACE_RATIOS, direction="pullback_from_high")
    bounce = fib_retracement_levels(hi, lo, ratios=DEFAULT_RETRACE_RATIOS, direction="bounce_from_low")
    ext_up = fib_extension_targets(lo, hi, ratios=DEFAULT_EXT_RATIOS, from_price=hi)
    ext_dn = fib_extension_targets(hi, lo, ratios=DEFAULT_EXT_RATIOS, from_price=lo)

    factors["fib_pull_ok"] = bool(pull.get("ok"))
    factors["fib_bounce_ok"] = bool(bounce.get("ok"))
    # 距高／低位置：0=在低、1=在高
    pos = (px - lo) / span if span > 0 else 0.5
    factors["fib_pos_in_swing"] = round(pos, 4)

    nearest_pull = None
    nearest_pull_dist = 1e18
    for r in DEFAULT_RETRACE_RATIOS:
        key = f"{float(r):g}"
        pl = (pull.get("levels") or {}).get(key)
        bl = (bounce.get("levels") or {}).get(key)
        if pl is not None:
            factors[f"fib_pull_{key}"] = round(float(pl), 4)
            factors[f"fib_near_pull_{key}"] = _near(px, float(pl), NEAR_PCT)
            factors[f"fib_zone_pull_{key}"] = _near(px, float(pl), ZONE_PCT)
            # swing 比例座標：回檔深度 ≈ (hi-px)/span
            pull_depth = (hi - px) / span if span > 0 else 0.0
            factors[f"fib_pos_near_pull_{key}"] = abs(pull_depth - float(r)) <= POS_BAND
            dlt = abs(px - float(pl))
            if dlt < nearest_pull_dist:
                nearest_pull_dist = dlt
                nearest_pull = key
        if bl is not None:
            factors[f"fib_bounce_{key}"] = round(float(bl), 4)
            factors[f"fib_near_bounce_{key}"] = _near(px, float(bl), NEAR_PCT)
            factors[f"fib_zone_bounce_{key}"] = _near(px, float(bl), ZONE_PCT)
            bounce_h = (px - lo) / span if span > 0 else 0.0
            factors[f"fib_pos_near_bounce_{key}"] = abs(bounce_h - float(r)) <= POS_BAND

    if nearest_pull:
        factors["fib_nearest_pull"] = nearest_pull
        for r in DEFAULT_RETRACE_RATIOS:
            key = f"{float(r):g}"
            factors[f"fib_nearest_is_{key}"] = nearest_pull == key

    # 破位：收盤低於回檔 0.786＝深修；高於反彈 0.786＝深彈
    p786 = (pull.get("levels") or {}).get("0.786")
    b786 = (bounce.get("levels") or {}).get("0.786")
    if p786 is not None:
        factors["fib_broke_pull_0786"] = bool(px < float(p786))
    if b786 is not None:
        factors["fib_broke_bounce_0786"] = bool(px > float(b786))

    # 延伸目標（幅度候選％）
    for r in (1.0, 1.272, 1.618):
        key = f"{float(r):g}"
        tu = (ext_up.get("targets") or {}).get(key)
        td = (ext_dn.get("targets") or {}).get(key)
        if tu is not None:
            factors[f"fib_ext_up_{key}_pct"] = round((float(tu) / px - 1.0) * 100.0, 4)
        if td is not None:
            factors[f"fib_ext_dn_{key}_pct"] = round((float(td) / px - 1.0) * 100.0, 4)
    # 常用幅度代理：切割跨度 ×0.382／0.618
    factors["fib_amp_0382_pct"] = round(0.382 * span / px * 100.0, 4)
    factors["fib_amp_0618_pct"] = round(0.618 * span / px * 100.0, 4)
    # 自高回檔幅度本身（切割語意）
    factors["fib_pull_depth_pct"] = round((hi - px) / px * 100.0, 4)

    # 結構語意旗（價近 or 比例近）
    def _sup(rkey: str) -> bool:
        return bool(
            factors.get(f"fib_near_pull_{rkey}")
            or factors.get(f"fib_zone_pull_{rkey}")
            or factors.get(f"fib_pos_near_pull_{rkey}")
        )

    def _res(rkey: str) -> bool:
        return bool(
            factors.get(f"fib_near_bounce_{rkey}")
            or factors.get(f"fib_zone_bounce_{rkey}")
            or factors.get(f"fib_pos_near_bounce_{rkey}")
        )

    factors["fib_near_0618_support"] = _sup("0.618")
    factors["fib_near_0382_support"] = _sup("0.382")
    factors["fib_near_0500_support"] = _sup("0.5")
    factors["fib_near_0750_support"] = _sup("0.75")
    factors["fib_near_0786_support"] = _sup("0.786")
    factors["fib_near_0618_resist"] = _res("0.618")
    factors["fib_near_0382_resist"] = _res("0.382")
    factors["fib_near_0750_resist"] = _res("0.75")
    factors["fib_deep_pull"] = bool(factors.get("fib_broke_pull_0786") or pos <= 0.22)
    factors["fib_upper_third"] = bool(pos >= 0.66)
    factors["fib_lower_third"] = bool(pos <= 0.34)
    factors["fib_mid_band"] = bool(0.45 <= pos <= 0.55)
    return factors, missing


def quantify(conn: sqlite3.Connection) -> Dict[str, Any]:
    bars = load_twii(conn)
    idx = {b["date"]: i for i, b in enumerate(bars)}
    keys = [b["date"] for b in bars]

    def fwd3(d: str) -> Optional[float]:
        i = idx.get(d)
        if i is None or i + 3 >= len(keys):
            return None
        return (bars[i + 3]["close"] / bars[i]["close"] - 1.0) * 100.0

    # 預先算每日因素（重用）
    day_f: Dict[str, Dict[str, Any]] = {}
    for i, b in enumerate(bars):
        if i + 3 >= len(bars):
            break
        f, _m = snapshot_fib_factors(bars, b["date"])
        if f:
            day_f[b["date"]] = f

    days = [d for d in sorted(day_f) if fwd3(d) is not None]
    base = [fwd3(d) for d in days]
    base = [x for x in base if x is not None]
    base_m = (sum(base) / len(base)) if base else 0.0
    flags: List[Dict[str, Any]] = []
    soft: List[Dict[str, Any]] = []

    def add(code: str, mask_key: str) -> None:
        xs = [fwd3(d) for d in days if day_f[d].get(mask_key)]
        xs = [x for x in xs if x is not None]
        if len(xs) < MIN_N:
            return
        m = sum(xs) / len(xs)
        edge = m - base_m
        if edge > 0:
            hit = sum(1 for x in xs if x > 0.6) / len(xs)
            bias = "up"
        else:
            hit = sum(1 for x in xs if x < -0.6) / len(xs)
            bias = "down"
        row = {
            "code": code,
            "n": len(xs),
            "mean3": round(m, 4),
            "edge3": round(edge, 4),
            "bias": bias,
            "hit_rate_side": round(hit, 4),
            "vote": round(edge, 4),
        }
        if abs(edge) >= MIN_EDGE and hit >= MIN_SIDE_HIT:
            flags.append(row)
        elif abs(edge) >= 0.10:
            soft.append(row)

    for code in (
        "fib_near_0618_support",
        "fib_near_0382_support",
        "fib_near_0500_support",
        "fib_near_0750_support",
        "fib_near_0786_support",
        "fib_near_0618_resist",
        "fib_near_0382_resist",
        "fib_near_0750_resist",
        "fib_deep_pull",
        "fib_upper_third",
        "fib_lower_third",
        "fib_mid_band",
        "fib_nearest_is_0.382",
        "fib_nearest_is_0.5",
        "fib_nearest_is_0.618",
        "fib_nearest_is_0.75",
        "fib_nearest_is_0.786",
    ):
        add(code, code)

    # 與籌碼／法人共現（單一切割方向票不夠時的下一刀）
    try:
        from scripts.decade_lab_chips_module import snapshot_chips_factors
        from scripts.decade_lab_inst_module import snapshot_inst_factors

        for d in days:
            cf, _ = snapshot_chips_factors(conn, d)
            inf, _ = snapshot_inst_factors(conn, d)
            day_f[d]["fib_lower_x_margin_kill"] = bool(
                day_f[d].get("fib_lower_third") and cf.get("chips_margin_kill_2d")
            )
            day_f[d]["fib_0618sup_x_foreign_pos"] = bool(
                day_f[d].get("fib_near_0618_support")
                and (inf.get("inst_foreign_pos_2d") or (_f(inf.get("inst_foreign_z")) or 0) >= 0.5)
            )
            day_f[d]["fib_deep_x_margin_z"] = bool(
                day_f[d].get("fib_deep_pull") and cf.get("chips_margin_z_le_m1")
            )
            day_f[d]["fib_upper_x_limit_up"] = bool(
                day_f[d].get("fib_upper_third") and cf.get("chips_limit_up_ge_20")
            )
        add("fib_lower_x_margin_kill", "fib_lower_x_margin_kill")
        add("fib_0618sup_x_foreign_pos", "fib_0618sup_x_foreign_pos")
        add("fib_deep_x_margin_z", "fib_deep_x_margin_z")
        add("fib_upper_x_limit_up", "fib_upper_x_limit_up")
    except Exception:
        pass

    # 幅度候選：切割跨度×0.382／0.618／pull_depth vs 實現 |ret3|
    def _amp_score(pred_key: str) -> Dict[str, Any]:
        rows = []
        for d in days:
            f = day_f[d]
            act = fwd3(d)
            if act is None:
                continue
            pred = abs(float(f.get(pred_key) or 0))
            if pred <= 0:
                continue
            act_a = abs(act)
            lo = max(0.0, pred * 0.5 - 0.15)
            hi = pred * 1.5 + 0.35
            rows.append(lo <= act_a <= hi)
        hit = sum(1 for x in rows if x)
        n = len(rows)
        return {"n": n, "hit": hit, "hit_rate": round(hit / n, 4) if n else None}

    amp_0382 = _amp_score("fib_amp_0382_pct")
    amp_0618 = _amp_score("fib_amp_0618_pct")
    amp_depth = _amp_score("fib_pull_depth_pct")

    flags.sort(key=lambda x: -abs(float(x["edge3"])))
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "scored_days": len(days),
        "base_mean3": round(base_m, 4),
        "flags": flags,
        "n_flags": len(flags),
        "soft_flags": soft[:20],
        "n_soft": len(soft),
        "ratios": list(DEFAULT_RETRACE_RATIOS),
        "ext_ratios": list(DEFAULT_EXT_RATIOS),
        "near_pct": NEAR_PCT,
        "zone_pct": ZONE_PCT,
        "pos_band": POS_BAND,
        "swing_look": SWING_LOOK,
        "amp_candidates": {
            "span_x_0382": amp_0382,
            "span_x_0618": amp_0618,
            "pull_depth": amp_depth,
            "note_zh": "切割幅度候選；未贏 RV 主幹前不換",
        },
        "gate": "n>=20 & |edge3|>=0.25 & side_hit>=0.55",
        "also_in_wave8_zh": "擴延≥1.618；ABC B回撤0.382–0.786 已在 wave8_dual",
        "goal_zh": "黃金切割完整進路徑方向＋幅度驗證",
        "not_buy_signal": True,
        "phone_sync": "blocked",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "fib_quant_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "fib_quant_flags.jsonl.gz", "wt", encoding="utf-8") as f:
        for row in flags:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return summary


def load_fib_votes(path: Optional[Path] = None) -> Dict[str, float]:
    p = path or (OUT_DIR / "fib_quant_latest.json")
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: Dict[str, float] = {}
    for row in d.get("flags") or []:
        code = str(row.get("code") or "")
        if not code:
            continue
        out[code] = float(row.get("vote") or row.get("edge3") or 0.0)
    return out


def main() -> int:
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        summary = quantify(conn)
    finally:
        conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
