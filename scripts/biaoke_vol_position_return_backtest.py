#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量相 × 相對股價位置 × 後續漲幅：產業龍頭分軌回測（觀察／非買訊）。

硬邊界：Asia/Taipei；官方柱；未收不當收；phone_sync blocked；
勝率分產業／分角色，不准混；禁稱「一年級」。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from scripts.biaoke_bottom_vol_observe_screen import YEAR_LOOKBACK, load_bars
from scripts.biaoke_leader_vol_tracks import (
    LOW_ZONE_PCT,
    HIGH_ZONE_PCT,
    classify_phase,
    industry_vane,
    load_twii,
    PhaseSnap,
)

TAIPEI = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
DB_DEFAULT = ROOT / "data" / "wayne_market.db"
HORIZONS = (5, 10, 20)

# 回測面板（對齊 playbook；provisional 分軌）
BACKTEST_PANELS: List[Dict[str, Any]] = [
    {"industry": "台積錨", "role": "market_anchor", "leaders": ["2330"]},
    {"industry": "PCB", "role": "taught_oral", "leaders": ["2383", "2368", "6274"]},
    {"industry": "ABF", "role": "contrast", "leaders": ["3037", "8046", "3189"]},
    {"industry": "CPo光通訊", "role": "taught_oral", "leaders": ["6442", "2345", "3081"]},
    {"industry": "ASIC", "role": "taught_oral", "leaders": ["3443", "3661", "3035"]},
    {"industry": "散熱", "role": "taught_oral", "leaders": ["3017", "2059", "3653"]},
    {"industry": "低軌衛星", "role": "taught", "leaders": ["3491", "3105", "6285"]},
    {"industry": "被動元件", "role": "rebound_contrast", "leaders": ["2327"]},
    {"industry": "封測", "role": "taught_mix", "leaders": ["3711", "6239", "8150"]},
    {"industry": "GPU供應鏈", "role": "provisional", "leaders": ["6669", "2382", "3231"]},
    {"industry": "CPU暫定", "role": "provisional", "leaders": ["2454", "2379"]},
    {"industry": "功率暫定", "role": "provisional", "leaders": ["2308", "2455", "3105"]},
    {"industry": "IC設計廣義", "role": "provisional", "leaders": ["2454", "2379", "3034"]},
]


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def position_zone(dist_lo: float, dist_hi: float) -> str:
    """相對股價位置：低位／高位／中段。"""
    if dist_lo <= LOW_ZONE_PCT:
        return "low"
    if dist_hi <= HIGH_ZONE_PCT:
        return "high"
    return "mid"


def trading_days(con: sqlite3.Connection) -> List[str]:
    rows = con.execute(
        """
        SELECT date FROM daily_quotes
        GROUP BY date HAVING COUNT(*) >= 1500
        ORDER BY date
        """
    ).fetchall()
    return [_ymd(r[0]) for r in rows if _ymd(r[0])]


def fwd_and_rs(
    closes: Sequence[float],
    dates: Sequence[str],
    idx: int,
    twii: Dict[str, float],
    horizons: Sequence[int] = HORIZONS,
) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    c0 = closes[idx]
    d0 = dates[idx]
    t0 = twii.get(d0)
    for h in horizons:
        j = idx + int(h)
        if j >= len(closes) or c0 <= 0:
            out[f"fwd_{h}"] = None
            out[f"rs_{h}"] = None
            continue
        ret = (closes[j] / c0 - 1.0) * 100.0
        out[f"fwd_{h}"] = round(ret, 3)
        d1 = dates[j]
        t1 = twii.get(d1)
        if t0 and t1 and t0 > 0:
            out[f"rs_{h}"] = round(ret - (t1 / t0 - 1.0) * 100.0, 3)
        else:
            out[f"rs_{h}"] = None
    # 窗內最大回撤（相對事件收）
    j20 = min(len(closes) - 1, idx + 20)
    if j20 > idx and c0 > 0:
        path = closes[idx : j20 + 1]
        peak = path[0]
        mdd = 0.0
        for x in path:
            peak = max(peak, x)
            if peak > 0:
                mdd = min(mdd, (x / peak - 1.0) * 100.0)
        out["mdd_20"] = round(mdd, 3)
    else:
        out["mdd_20"] = None
    return out


def _mean(xs: List[float]) -> Optional[float]:
    return round(statistics.mean(xs), 3) if xs else None


def _med(xs: List[float]) -> Optional[float]:
    return round(statistics.median(xs), 3) if xs else None


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    out: Dict[str, Any] = {"n": n}
    if n == 0:
        return out
    for h in HORIZONS:
        fw = [float(r[f"fwd_{h}"]) for r in rows if r.get(f"fwd_{h}") is not None]
        rs = [float(r[f"rs_{h}"]) for r in rows if r.get(f"rs_{h}") is not None]
        out[f"fwd_{h}_mean"] = _mean(fw)
        out[f"fwd_{h}_med"] = _med(fw)
        out[f"fwd_{h}_pos_pct"] = round(100.0 * sum(1 for x in fw if x > 0) / len(fw), 1) if fw else None
        out[f"rs_{h}_mean"] = _mean(rs)
        out[f"rs_{h}_med"] = _med(rs)
    mdd = [float(r["mdd_20"]) for r in rows if r.get("mdd_20") is not None]
    out["mdd_20_med"] = _med(mdd)
    return out


def run_backtest(
    db_path: str,
    *,
    step: int = 1,
    min_history: int = 120,
) -> Dict[str, Any]:
    con = sqlite3.connect(db_path)
    try:
        days = trading_days(con)
        twii = load_twii(con)
        # preload bars
        all_sids = sorted({s for p in BACKTEST_PANELS for s in p["leaders"]})
        series: Dict[str, Dict[str, Any]] = {}
        for sid in all_sids:
            bars = load_bars(con, sid, lookback=800)
            if len(bars) < min_history + max(HORIZONS) + 5:
                continue
            series[sid] = {
                "dates": [b["date"] for b in bars],
                "closes": [b["close"] for b in bars],
                "bars": bars,
                "index": {b["date"]: i for i, b in enumerate(bars)},
            }

        # events: stock-day
        events: List[Dict[str, Any]] = []
        # vane events per industry-day
        vane_events: List[Dict[str, Any]] = []

        day_set = set(days)
        # walk days with step; keep last max(H) for fwd
        usable = days[: -max(HORIZONS)] if len(days) > max(HORIZONS) else []
        usable = usable[:: max(1, int(step))]

        for panel in BACKTEST_PANELS:
            ind = str(panel["industry"])
            role = str(panel["role"])
            leaders = [str(x) for x in panel["leaders"]]

            for d in usable:
                day_snaps: List[PhaseSnap] = []
                day_phase_rows: List[Dict[str, Any]] = []
                for sid in leaders:
                    ser = series.get(sid)
                    if not ser:
                        continue
                    idx = ser["index"].get(d)
                    if idx is None or idx < min_history:
                        continue
                    bars_i = ser["bars"][: idx + 1]
                    phase, flags, m = classify_phase(bars_i)
                    zone = position_zone(float(m["dist_lo"]), float(m["dist_hi"]))
                    fwd = fwd_and_rs(ser["closes"], ser["dates"], idx, twii)
                    row = {
                        "date": d,
                        "stock_id": sid,
                        "industry": ind,
                        "role": role,
                        "phase": phase,
                        "zone": zone,
                        "dist_lo": round(float(m["dist_lo"]), 2),
                        "dist_hi": round(float(m["dist_hi"]), 2),
                        "flags": flags,
                        **fwd,
                    }
                    events.append(row)
                    day_phase_rows.append(row)
                    day_snaps.append(
                        PhaseSnap(
                            stock_id=sid,
                            stock_name=sid,
                            industry=ind,
                            role=role,
                            as_of=d,
                            close=float(ser["closes"][idx]),
                            phase=phase,
                            flags=flags,
                            near_year_vol_floor=float(m["floor"]),
                            vol_today=float(m["vol"]),
                            vol_year_max=float(m["ymax"]),
                            consec_near_year_vol=int(m["consec"]),
                            dist_to_low60_pct=float(m["dist_lo"]),
                            dist_to_high120_pct=float(m["dist_hi"]),
                            rs_5_vs_twii_pct=fwd.get("rs_5"),
                            note_zh="",
                        )
                    )

                if not day_snaps:
                    continue
                v = industry_vane(day_snaps)
                if v.get("vane_on") or v.get("anchor_active"):
                    # equal-weight fwd of active leaders that day
                    act = set(v.get("active_ids") or [])
                    act_rows = [r for r in day_phase_rows if r["stock_id"] in act]
                    if not act_rows:
                        continue
                    agg: Dict[str, Any] = {
                        "date": d,
                        "industry": ind,
                        "role": role,
                        "vane_on": bool(v.get("vane_on")),
                        "anchor_active": bool(v.get("anchor_active")),
                        "active_ids": list(act),
                        "active_n": len(act),
                    }
                    for h in HORIZONS:
                        fw = [r[f"fwd_{h}"] for r in act_rows if r.get(f"fwd_{h}") is not None]
                        rs = [r[f"rs_{h}"] for r in act_rows if r.get(f"rs_{h}") is not None]
                        agg[f"fwd_{h}"] = _mean([float(x) for x in fw]) if fw else None
                        agg[f"rs_{h}"] = _mean([float(x) for x in rs]) if rs else None
                    mdds = [r["mdd_20"] for r in act_rows if r.get("mdd_20") is not None]
                    agg["mdd_20"] = _med([float(x) for x in mdds]) if mdds else None
                    vane_events.append(agg)

        # baselines: quiet + mid/low for comparison within taught_oral
        by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in events:
            if r["phase"] not in ("low_explode", "sediment", "high_explode", "quiet"):
                continue
            key = f"{r['industry']}|{r['phase']}|{r['zone']}"
            by_key[key].append(r)

        cells = []
        for key, rows in sorted(by_key.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            ind, phase, zone = key.split("|")
            cells.append(
                {
                    "industry": ind,
                    "phase": phase,
                    "zone": zone,
                    "role": rows[0]["role"],
                    **summarize(rows),
                }
            )

        # focus: non-quiet with n>=5 first; also quiet baselines
        signal_cells = [
            c
            for c in cells
            if c["phase"] in ("low_explode", "sediment", "high_explode") and c["n"] >= 5
        ]
        quiet_low = [c for c in cells if c["phase"] == "quiet" and c["zone"] == "low" and c["n"] >= 20]

        vane_by_ind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for v in vane_events:
            if v.get("vane_on"):
                vane_by_ind[v["industry"]].append(v)
        vane_summary = []
        for ind, rows in sorted(vane_by_ind.items()):
            vane_summary.append({"industry": ind, "role": rows[0]["role"], **summarize(rows)})

        # feasibility hints (not buy signal)
        findings = []
        for c in signal_cells:
            if c["zone"] == "low" and c["phase"] in ("low_explode", "sediment"):
                q = next(
                    (x for x in quiet_low if x["industry"] == c["industry"]),
                    None,
                )
                note = {
                    "industry": c["industry"],
                    "cell": f"{c['phase']}/{c['zone']}",
                    "n": c["n"],
                    "fwd_10_med": c.get("fwd_10_med"),
                    "rs_10_med": c.get("rs_10_med"),
                    "quiet_low_fwd_10_med": q.get("fwd_10_med") if q else None,
                    "beat_quiet_low_fwd10": (
                        None
                        if q is None or c.get("fwd_10_med") is None or q.get("fwd_10_med") is None
                        else c["fwd_10_med"] > q["fwd_10_med"]
                    ),
                }
                findings.append(note)

        # G2: low vs high explode overall (taught+oral only)
        lo = [r for r in events if r["phase"] == "low_explode" and r["zone"] == "low" and r["role"] in ("taught_oral", "taught", "taught_mix")]
        hi = [r for r in events if r["phase"] == "high_explode" and r["zone"] == "high" and r["role"] in ("taught_oral", "taught", "taught_mix", "contrast")]

        return {
            "ok": True,
            "phone_sync": "blocked",
            "buy_signal": False,
            "not_buy_signal": True,
            "as_of_range": {"start": days[0] if days else "", "end": days[-1] if days else ""},
            "n_days_scanned": len(usable),
            "n_stock_day_events": len(events),
            "n_vane_or_anchor_days": len(vane_events),
            "panels": BACKTEST_PANELS,
            "g2_lo_hi_split": {
                "low_explode_low": summarize(lo),
                "high_explode_high": summarize(hi),
                "note_zh": "有根組：低位爆量 vs 高位爆量後續漲幅／RS（觀察）",
            },
            "signal_cells_n_ge_5": signal_cells[:80],
            "quiet_low_baselines": quiet_low,
            "vane_on_by_industry": vane_summary,
            "feasibility_vs_quiet_low": findings,
            "written_at": datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "method_zh": (
                "量級距（近一年前巨量近似）×相對位置（低／中／高）×量相"
                "→對5／10／20日漲幅與相對加權；分產業分角色。"
            ),
        }
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--step", type=int, default=1, help="交易日步長（1=全日）")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    out = run_backtest(args.db, step=args.step)
    path = Path(args.out) if args.out else LAB / "biaoke_vol_position_return_backtest_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stamped = LAB / f"biaoke_vol_position_return_backtest_{out.get('as_of_range', {}).get('end', 'x')}.json"
    stamped.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    # short console
    print(
        json.dumps(
            {
                "ok": out.get("ok"),
                "range": out.get("as_of_range"),
                "n_events": out.get("n_stock_day_events"),
                "g2": out.get("g2_lo_hi_split"),
                "vane_n": len(out.get("vane_on_by_industry") or []),
                "findings_n": len(out.get("feasibility_vs_quiet_low") or []),
                "out": str(path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
