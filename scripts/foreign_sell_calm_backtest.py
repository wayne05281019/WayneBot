#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calm／小買→大買｜密窗全樣本（佈局環境；不是買訊）。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fear_composite import FOREIGN_NET_UNIT, VOLUME_UNIT, _f, unit_consistency_report  # noqa: E402
from foreign_sell_calm import (  # noqa: E402
    BuyEscalateParams,
    evaluate_buy_escalate_A,
    hit_buy_within_k,
    iter_buy_param_grid,
    units_banner,
)
from foreign_sell_calm_verify import _buy_day_pctls  # noqa: E402
from foreign_sell_escalate import (  # noqa: E402
    LIQUID_MIN_TURNOVER_K,
    LIQUID_MIN_VOL_LOTS,
    QIANJIN_PX,
    UNIVERSE_LIQUID,
    UNIVERSE_QIANJIN,
    UNIVERSE_TOP500_VOL,
)
from foreign_sell_escalate_verify import (  # noqa: E402
    MIN_VOLUME_LOTS,
    TOP_N,
    _ex_set,
    _load_panel,
    _top_sids,
    _trading_days,
)

TP = ZoneInfo("Asia/Taipei")
UNIVERSES = (UNIVERSE_TOP500_VOL, UNIVERSE_QIANJIN, UNIVERSE_LIQUID)


def _now_iso() -> str:
    return datetime.now(TP).isoformat(timespec="seconds")


def _universe_members(day: str, *, top500, bars) -> Dict[str, List[str]]:
    qj, liq = [], []
    for sid, b in bars.items():
        cl = _f(b.get("close")) or 0
        vol = _f(b.get("volume")) or 0
        to_k = _f(b.get("turnover_k"))
        if to_k is None and cl > 0 and vol > 0:
            to_k = cl * vol
        if cl >= QIANJIN_PX and vol > 0:
            qj.append(sid)
        if vol >= LIQUID_MIN_VOL_LOTS and (to_k or 0) >= LIQUID_MIN_TURNOVER_K:
            liq.append(sid)
    return {
        UNIVERSE_TOP500_VOL: list(top500),
        UNIVERSE_QIANJIN: sorted(qj),
        UNIVERSE_LIQUID: sorted(liq),
    }


def _score(
    *,
    days,
    panel,
    pctls,
    ex_by_day,
    members_by_day,
    universe: str,
    params: BuyEscalateParams,
) -> Dict[str, Any]:
    lit_events = []
    for di, d in enumerate(days):
        if di + 1 < params.n_days:
            continue
        window = days[di - params.n_days + 1 : di + 1]
        ex = ex_by_day.get(d) or set()
        for sid in members_by_day.get(d, {}).get(universe) or []:
            if sid in ex:
                continue
            fns, vols, ps = [], [], []
            ok = True
            for wd in window:
                b = (panel.get(wd) or {}).get(sid)
                if not b:
                    ok = False
                    break
                fns.append(b.get("foreign_net"))
                vols.append(b.get("volume"))
                ps.append(pctls.get(wd, {}).get(sid))
            if not ok:
                continue
            today = (panel.get(d) or {}).get(sid) or {}
            if (_f(today.get("volume")) or 0) < MIN_VOLUME_LOTS:
                continue
            ev = evaluate_buy_escalate_A(
                foreign_nets=fns, volumes=vols, pctls=ps, params=params
            )
            if not ev.get("lit"):
                continue
            fut = [
                None if di + k >= len(days) else pctls.get(days[di + k], {}).get(sid)
                for k in range(1, params.k_ahead + 1)
            ]
            h = hit_buy_within_k(fut, k=params.k_ahead, theta_pctl=params.theta_pctl)
            lit_events.append(
                {
                    "as_of": d,
                    "sid": sid,
                    "hit": h.get("hit"),
                    "verdict": "pending"
                    if h.get("hit") is None
                    else ("hit" if h.get("hit") else "miss"),
                }
            )
    # baseline：買超未 lit
    lit_set = {(e["as_of"], e["sid"]) for e in lit_events}
    base_n = base_hit = 0
    for di, d in enumerate(days):
        if di + params.k_ahead >= len(days):
            continue
        ex = ex_by_day.get(d) or set()
        for sid in members_by_day.get(d, {}).get(universe) or []:
            if sid in ex or (d, sid) in lit_set:
                continue
            b = (panel.get(d) or {}).get(sid)
            if not b or (_f(b.get("volume")) or 0) < MIN_VOLUME_LOTS:
                continue
            if (_f(b.get("foreign_net")) or 0) <= 0:
                continue
            if sid not in (pctls.get(d) or {}):
                continue
            fut = [
                pctls.get(days[di + k], {}).get(sid)
                for k in range(1, params.k_ahead + 1)
                if di + k < len(days)
            ]
            h = hit_buy_within_k(fut, k=params.k_ahead, theta_pctl=params.theta_pctl)
            if h.get("hit") is None:
                continue
            base_n += 1
            if h.get("hit"):
                base_hit += 1
    hits = sum(1 for e in lit_events if e["verdict"] == "hit")
    miss = sum(1 for e in lit_events if e["verdict"] == "miss")
    return {
        "universe": universe,
        "params_key": params.key(),
        "n_lit_events": len(lit_events),
        "n_lit_days": len({e["as_of"] for e in lit_events}),
        "hit": hits,
        "miss": miss,
        "hit_rate": (hits / (hits + miss)) if (hits + miss) else None,
        "baseline_n": base_n,
        "baseline_hit": base_hit,
        "baseline_hit_rate": (base_hit / base_n) if base_n else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--start", default="20260401")
    ap.add_argument("--end", default="")
    ap.add_argument("--out", default="/opt/cursor/artifacts/foreign-sell-calm")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    end = args.end or "20991231"
    days = _trading_days(args.db, args.start, end)
    if len(days) < 20:
        print(json.dumps({"error": "days_too_few", "n": len(days)}))
        return 2
    print(f"[calm] n={len(days)} {days[0]}→{days[-1]}", flush=True)
    pool = _top_sids(args.db, days[-1], max(TOP_N * 5, 2500))
    top500 = _top_sids(args.db, days[-1], TOP_N)
    panel = _load_panel(args.db, days, pool)
    pctls = {d: _buy_day_pctls(panel.get(d) or {}) for d in days}
    ex_by_day = {d: _ex_set(args.db, d) for d in days}
    members = {
        d: _universe_members(d, top500=top500, bars=panel.get(d) or {}) for d in days
    }
    unit_rows = [
        {"foreign_net": b.get("foreign_net"), "volume": b.get("volume")}
        for d in days
        for b in (panel.get(d) or {}).values()
    ]
    units = unit_consistency_report(unit_rows)
    grid = []
    for params in iter_buy_param_grid():
        for uni in UNIVERSES:
            cell = _score(
                days=days,
                panel=panel,
                pctls=pctls,
                ex_by_day=ex_by_day,
                members_by_day=members,
                universe=uni,
                params=params,
            )
            grid.append(cell)
            print(
                f"[calm] {uni} {params.key()} lit={cell['n_lit_events']} "
                f"hit={cell['hit_rate']} base={cell['baseline_hit_rate']}",
                flush=True,
            )
    report = {
        "track": "foreign_sell_calm_env",
        "generated_at": _now_iso(),
        "window": {"start": days[0], "end": days[-1], "n_days": len(days)},
        "units_ok": bool(units.get("units_ok")),
        "not_buy_signal": True,
        "buy_escalate_grid": grid,
        "note": "Calm fear-fade 需 fear tape 有史；本腳本主掃小買→大買對稱升級",
    }
    with open(os.path.join(args.out, "foreign_sell_calm_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "units_consistency.json"), "w", encoding="utf-8") as f:
        json.dump({"banner": units_banner(), "consistency": units}, f, ensure_ascii=False, indent=2)
    lines = [
        "# Calm／小買→大買｜全樣本摘要",
        "",
        f"- 產生：`{_now_iso()}`（台北）",
        f"- 窗：`{days[0]}`→`{days[-1]}` n={len(days)}；units_ok={units.get('units_ok')}",
        "- **不是買訊**；佈局環境觀察。",
        "",
        "## 小買→大買升級網格",
        "",
    ]
    for g in grid:
        lines.append(
            f"- **{g['universe']}** `{g['params_key']}`：lit={g['n_lit_events']} "
            f"命中={g['hit_rate']} 基線={g['baseline_hit_rate']}"
        )
    lines += ["", "## 硬邊界", "", "- 未過閘只靜默；顯示等隊列後。", ""]
    with open(os.path.join(args.out, "foreign_sell_calm_summary_zh.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[calm] 寫入 {args.out}", flush=True)
    return 0 if units.get("units_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
