#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜加權落底前多因子共現（靜默統計）。

硬邊界：
- 只讀官方柱／breadth；缺就標缺，不准腦補 1.3 兆成交金額（本庫 TWII.volume 不是兆元口徑）。
- 不是買訊；不准寫回黃金買點／海選／洞燭／話筒預測。
- 落底＝多因子共現假設的觀測面：先定義可重跑的 trough，再算落底前窗共現率。
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

# trough：±look 窗最低低點，且之後 bounce_n 日內自低點反彈 ≥ bounce_pct
LOOK = 15
BOUNCE_N = 10
BOUNCE_PCT = 4.0
# 落底前窗（含 trough 當日）
PRE_N = 5
# 對照：非 trough 的隨機／所有開市日基線用「全體日」分布
VOL_SPIKE_MULT = 1.5  # 相對近 20 日均量
WICK_MIN = 0.45  # 下影佔全根 ≥
LIMIT_DOWN_PCTL = 80.0  # 在「有跌停」的日子裡取分位
LIMIT_DOWN_FLOOR = 20  # 絕對下限，避免 0 日把分位拉成永遠亮


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


def _load_twii(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume
        FROM index_daily
        WHERE (symbol='TWII' OR symbol='^TWII')
        ORDER BY 1
        """
    ).fetchall()
    out = []
    for d, o, h, l, c, v in rows:
        day = _ymd(d)
        if not day:
            continue
        oo, hh, ll, cc, vv = _f(o), _f(h), _f(l), _f(c), _f(v)
        if not cc or cc <= 0 or not hh or not ll:
            continue
        out.append(
            {
                "date": day,
                "open": oo or cc,
                "high": hh,
                "low": ll or cc,
                "close": cc,
                "volume": vv or 0.0,
            }
        )
    return out


def _load_2330(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume
        FROM daily_quotes WHERE stock_id='2330'
        ORDER BY 1
        """
    ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for d, o, h, l, c, v in rows:
        day = _ymd(d)
        if not day:
            continue
        oo, hh, ll, cc, vv = _f(o), _f(h), _f(l), _f(c), _f(v)
        if not cc or cc <= 0:
            continue
        out[day] = {
            "date": day,
            "open": oo or cc,
            "high": hh or cc,
            "low": ll or cc,
            "close": cc,
            "volume": vv or 0.0,
        }
    return out


def _load_breadth(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), limit_up, limit_down, up_count, down_count
            FROM index_breadth_daily
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for d, lu, ld, up, dn in rows:
        day = _ymd(d)
        if not day:
            continue
        out[day] = {
            "limit_up": int(lu or 0),
            "limit_down": int(ld or 0),
            "up_count": int(up or 0),
            "down_count": int(dn or 0),
        }
    return out


def _lower_wick_ratio(bar: Dict[str, Any]) -> Optional[float]:
    h, l = _f(bar.get("high")), _f(bar.get("low"))
    o, c = _f(bar.get("open")), _f(bar.get("close"))
    if not h or not l or h <= l or not c:
        return None
    body_low = min(o or c, c)
    wick = body_low - l
    span = h - l
    if span <= 0:
        return None
    return max(0.0, wick / span)


def _find_troughs(bars: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    n = len(bars)
    hits: List[Dict[str, Any]] = []
    for i in range(LOOK, n - 1):
        lo = float(bars[i]["low"])
        window = bars[i - LOOK : i + LOOK + 1]
        if lo > min(float(b["low"]) for b in window) + 1e-9:
            continue
        # bounce
        future = bars[i + 1 : i + 1 + BOUNCE_N]
        if not future:
            continue
        peak = max(float(b["high"]) for b in future)
        bounce = (peak / lo - 1.0) * 100.0 if lo > 0 else 0.0
        if bounce < BOUNCE_PCT:
            continue
        hits.append(
            {
                "i": i,
                "date": bars[i]["date"],
                "low": lo,
                "close": float(bars[i]["close"]),
                "bounce_pct": round(bounce, 2),
            }
        )
    # cluster：同 LOOK 內只留最低
    kept: List[Dict[str, Any]] = []
    for h in hits:
        if kept and h["i"] - kept[-1]["i"] <= LOOK:
            if h["low"] < kept[-1]["low"]:
                kept[-1] = h
            continue
        kept.append(h)
    return kept


def _ma(vals: Sequence[float], n: int) -> Optional[float]:
    if len(vals) < n:
        return None
    chunk = vals[-n:]
    if not chunk:
        return None
    return sum(chunk) / len(chunk)


def _percentile(sorted_vals: Sequence[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f))


def _pre_flags(
    bars: Sequence[Dict[str, Any]],
    i: int,
    *,
    tsm: Dict[str, Dict[str, Any]],
    breadth: Dict[str, Dict[str, Any]],
    ld_cut: Optional[float],
) -> Dict[str, Any]:
    start = max(0, i - PRE_N + 1)
    win = list(bars[start : i + 1])
    vols = [float(b["volume"] or 0) for b in bars[max(0, i - 20) : i]]
    ma20 = _ma(vols, min(20, len(vols))) if vols else None
    vol_spike = False
    max_vol = 0.0
    for b in win:
        max_vol = max(max_vol, float(b.get("volume") or 0))
        if ma20 and ma20 > 0 and float(b.get("volume") or 0) >= ma20 * VOL_SPIKE_MULT:
            vol_spike = True
    wick_hit = False
    for b in win:
        r = _lower_wick_ratio(b)
        if r is not None and r >= WICK_MIN:
            wick_hit = True
            break
    # 台積
    tsm_vol_spike = None
    tsm_wick = None
    tsm_missing = 0
    tsm_vols_hist: List[float] = []
    for j in range(max(0, i - 25), i + 1):
        day = bars[j]["date"]
        row = tsm.get(day)
        if not row:
            continue
        tsm_vols_hist.append(float(row.get("volume") or 0))
    tsm_ma = _ma(tsm_vols_hist[:-1], min(20, max(0, len(tsm_vols_hist) - 1))) if len(tsm_vols_hist) > 1 else None
    for b in win:
        row = tsm.get(b["date"])
        if not row:
            tsm_missing += 1
            continue
        if tsm_vol_spike is None:
            tsm_vol_spike = False
        if tsm_wick is None:
            tsm_wick = False
        if tsm_ma and tsm_ma > 0 and float(row.get("volume") or 0) >= tsm_ma * VOL_SPIKE_MULT:
            tsm_vol_spike = True
        wr = _lower_wick_ratio(row)
        if wr is not None and wr >= WICK_MIN:
            tsm_wick = True
    # 跌停家數
    ld_hit = None
    max_ld = None
    br_missing = 0
    for b in win:
        br = breadth.get(b["date"])
        if not br:
            br_missing += 1
            continue
        if ld_hit is None:
            ld_hit = False
        ld = int(br.get("limit_down") or 0)
        max_ld = ld if max_ld is None else max(max_ld, ld)
        if ld_cut is not None and ld >= ld_cut:
            ld_hit = True
    down_dom = None
    for b in win:
        br = breadth.get(b["date"])
        if not br:
            continue
        if down_dom is None:
            down_dom = False
        if int(br.get("down_count") or 0) > int(br.get("up_count") or 0) * 1.5:
            down_dom = True
    return {
        "vol_spike": bool(vol_spike),
        "twii_lower_wick": bool(wick_hit),
        "max_vol": max_vol,
        "vol_ma20": ma20,
        "tsm_vol_spike": tsm_vol_spike,
        "tsm_lower_wick": tsm_wick,
        "tsm_missing_days": tsm_missing,
        "limit_down_spike": ld_hit,
        "max_limit_down": max_ld,
        "limit_down_cut": ld_cut,
        "breadth_missing_days": br_missing,
        "down_dominate": down_dom,
    }


def _cooccur_count(flags: Dict[str, Any], keys: Sequence[str]) -> int:
    n = 0
    for k in keys:
        v = flags.get(k)
        if v is True:
            n += 1
    return n


def main() -> int:
    if not DB.is_file():
        print(json.dumps({"error": "missing_db", "path": str(DB)}, ensure_ascii=False))
        return 2
    conn = sqlite3.connect(str(DB), timeout=30.0)
    try:
        bars = _load_twii(conn)
        tsm = _load_2330(conn)
        breadth = _load_breadth(conn)
    finally:
        conn.close()
    troughs = _find_troughs(bars)
    ld_series = sorted(
        float(v["limit_down"])
        for v in breadth.values()
        if int(v.get("limit_down") or 0) > 0
    )
    ld_cut_raw = _percentile(ld_series, LIMIT_DOWN_PCTL)
    ld_cut = None
    if ld_cut_raw is not None:
        ld_cut = max(float(LIMIT_DOWN_FLOOR), float(ld_cut_raw))

    # 全體日基線（有 breadth 的日子）
    base_flags = []
    idx = {b["date"]: i for i, b in enumerate(bars)}
    for day, br in breadth.items():
        i = idx.get(day)
        if i is None or i < LOOK:
            continue
        base_flags.append(
            _pre_flags(bars, i, tsm=tsm, breadth=breadth, ld_cut=ld_cut)
        )

    rows_out: List[Dict[str, Any]] = []
    factor_keys = [
        "vol_spike",
        "twii_lower_wick",
        "tsm_vol_spike",
        "tsm_lower_wick",
        "limit_down_spike",
        "down_dominate",
    ]
    for t in troughs:
        i = int(t["i"])
        flags = _pre_flags(bars, i, tsm=tsm, breadth=breadth, ld_cut=ld_cut)
        k_hit = _cooccur_count(flags, factor_keys)
        rows_out.append(
            {
                "A": {
                    "event_date": t["date"],
                    "symbol": "TWII",
                    "level_hypothesis": f"swing_trough look={LOOK} bounce>={BOUNCE_PCT}%/{BOUNCE_N}d",
                    "seq": "bottom_cooccur",
                },
                "B": {
                    "alive_labels": [
                        {"label": "vol_spike", "hit": flags.get("vol_spike")},
                        {"label": "twii_lower_wick", "hit": flags.get("twii_lower_wick")},
                        {"label": "tsm_vol_spike", "hit": flags.get("tsm_vol_spike")},
                        {"label": "tsm_lower_wick", "hit": flags.get("tsm_lower_wick")},
                        {"label": "limit_down_spike", "hit": flags.get("limit_down_spike")},
                        {"label": "down_dominate", "hit": flags.get("down_dominate")},
                    ],
                    "cooccur_n": k_hit,
                    "cooccur_ge3": k_hit >= 3,
                    "cooccur_ge4": k_hit >= 4,
                },
                "C": {
                    "trough_low": t["low"],
                    "trough_close": t["close"],
                    "bounce_pct": t["bounce_pct"],
                    "pre_window_n": PRE_N,
                    "flags": flags,
                },
                "F": {"pot": "實驗室"},
                "G": {"note": "觀測共現，不是預測句；不是買訊"},
                "H": {"gaps": []},
            }
        )
        gaps = rows_out[-1]["H"]["gaps"]
        if flags.get("tsm_vol_spike") is None:
            gaps.append("缺：台積近窗（2330 庫短）")
        if flags.get("limit_down_spike") is None:
            gaps.append("缺：breadth／跌停家數")
        gaps.append("缺：成交金額兆元口徑（TWII.volume 非 1.3 兆定義）")
        gaps.append("缺：融資餘額長史（market_margin_daily 過短）")
        gaps.append("缺：主動式 ETF 投信買賣超序列")

    def rate(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
        vals = []
        for r in rows:
            v = r.get("C", {}).get("flags", {}).get(key)
            if v is True:
                vals.append(1)
            elif v is False:
                vals.append(0)
        if not vals:
            return None
        return sum(vals) / len(vals)

    def base_rate(key: str) -> Optional[float]:
        vals = []
        for f in base_flags:
            v = f.get(key)
            if v is True:
                vals.append(1)
            elif v is False:
                vals.append(0)
        if not vals:
            return None
        return sum(vals) / len(vals)

    co3 = sum(1 for r in rows_out if r["B"]["cooccur_ge3"])
    co4 = sum(1 for r in rows_out if r["B"]["cooccur_ge4"])
    summary = {
        "written_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "tz": "Asia/Taipei",
        "db": str(DB),
        "twii_n": len(bars),
        "twii_from": bars[0]["date"] if bars else "",
        "twii_to": bars[-1]["date"] if bars else "",
        "params": {
            "look": LOOK,
            "bounce_n": BOUNCE_N,
            "bounce_pct": BOUNCE_PCT,
            "pre_n": PRE_N,
            "vol_spike_mult": VOL_SPIKE_MULT,
            "wick_min": WICK_MIN,
            "limit_down_pctl": LIMIT_DOWN_PCTL,
            "limit_down_cut": ld_cut,
        },
        "n_trough": len(rows_out),
        "n_cooccur_ge3": co3,
        "n_cooccur_ge4": co4,
        "pct_cooccur_ge3": (co3 / len(rows_out)) if rows_out else None,
        "pct_cooccur_ge4": (co4 / len(rows_out)) if rows_out else None,
        "factor_hit_rate_at_trough": {k: rate(rows_out, k) for k in factor_keys},
        "factor_base_rate_all_breadth_days": {k: base_rate(k) for k in factor_keys},
        "lift_vs_base": {},
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "gaps": [
            "成交金額≥1.3兆×≥2日：本庫無兆元口徑官方序列",
            "融資餘額大減：market_margin_daily 過短",
            "主動式 ETF 投信轉賣：無專序列",
            "台積／跌停：僅 2023-12 起可對齊 breadth／2330",
        ],
    }
    for k in factor_keys:
        a = summary["factor_hit_rate_at_trough"].get(k)
        b = summary["factor_base_rate_all_breadth_days"].get(k)
        if a is None or b is None or b == 0:
            summary["lift_vs_base"][k] = None
        else:
            summary["lift_vs_base"][k] = round(a / b, 3)

    # 基線共現≥3
    base_co3 = 0
    base_n = 0
    for f in base_flags:
        base_n += 1
        if _cooccur_count(f, factor_keys) >= 3:
            base_co3 += 1
    summary["base_pct_cooccur_ge3"] = (base_co3 / base_n) if base_n else None
    summary["base_n_breadth_days"] = base_n

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TAIPEI).strftime("%Y%m%d")
    jsonl_path = OUT_DIR / f"bottom_cooccur_{stamp}.jsonl"
    latest_jsonl = OUT_DIR / "bottom_cooccur_latest.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows_out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    latest_jsonl.write_text(jsonl_path.read_text(encoding="utf-8"), encoding="utf-8")
    summary_path = OUT_DIR / "bottom_cooccur_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_lines = [
        "# 加權落底前多因子共現（實驗室）",
        "",
        f"寫入：`{summary['written_at']}`（Asia/Taipei）。",
        f"TWII 柱：{summary['twii_from']}→{summary['twii_to']} n={summary['twii_n']}。",
        f"trough 定義：±{LOOK}日最低低點，且之後 {BOUNCE_N} 日內反彈 ≥{BOUNCE_PCT}%。",
        f"前窗：含 trough 當日共 {PRE_N} 日。",
        "",
        f"- trough 數：**{summary['n_trough']}**",
        f"- 共現≥3 因子：{summary['n_cooccur_ge3']}（{summary['pct_cooccur_ge3']}）",
        f"- 共現≥4 因子：{summary['n_cooccur_ge4']}（{summary['pct_cooccur_ge4']}）",
        f"- 全體 breadth 日共現≥3 基線：{summary['base_pct_cooccur_ge3']}（n={summary['base_n_breadth_days']}）",
        "",
        "## 單因子命中率（trough 前窗 vs 基線）",
        "",
    ]
    for k in factor_keys:
        md_lines.append(
            f"- `{k}`：trough={summary['factor_hit_rate_at_trough'].get(k)} "
            f"base={summary['factor_base_rate_all_breadth_days'].get(k)} "
            f"lift={summary['lift_vs_base'].get(k)}"
        )
    md_lines += [
        "",
        "## 缺／不准硬編",
        "",
    ]
    for g in summary["gaps"]:
        md_lines.append(f"- {g}")
    md_lines += [
        "",
        "不是買訊。不准寫回黃金買點／海選／洞燭／話筒預測。",
        "",
        f"JSONL：`{latest_jsonl.relative_to(ROOT)}`",
        "",
    ]
    md_path = OUT_DIR / "bottom_cooccur_latest.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
