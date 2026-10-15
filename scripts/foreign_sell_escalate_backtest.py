#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小賣→大賣升級｜密窗全樣本離線回測（不是買訊）。

本庫優先（T86／volume／ex_rights 皆在 daily_quotes／ex_rights）；
單位：張／張；全開市密日×Top500 全檔；網格全跑；Lead／Sync／除權息分表。
不准抽測。

用法：
  .venv/bin/python scripts/foreign_sell_escalate_backtest.py \\
    --db data/wayne_market.db \\
    --out /opt/cursor/artifacts/foreign-sell-escalate-20261015
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fear_composite import (  # noqa: E402
    FOREIGN_NET_UNIT,
    LOTS_PER_SHARE,
    SELL_SHARE_UNIT,
    VOLUME_UNIT,
    _f,
    _ymd,
    sell_share,
    unit_consistency_report,
)
from foreign_sell_escalate import (  # noqa: E402
    EscalateParams,
    classify_lead_sync_vs_extreme,
    cross_sectional_percentile,
    evaluate_escalate_A,
    evaluate_escalate_B,
    hit_within_k,
    iter_escalate_param_grid,
    units_banner,
)
from foreign_sell_escalate_verify import (  # noqa: E402
    MIN_VOLUME_LOTS,
    TOP_N,
    _day_pctls,
    _ex_set,
    _load_panel,
    _top_sids,
    _trading_days,
)

TP = ZoneInfo("Asia/Taipei")


def _now_iso() -> str:
    return datetime.now(TP).isoformat(timespec="seconds")


def run_backtest(db: str, *, start: str, end: str, out_dir: str) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    start, end = _ymd(start), _ymd(end)
    print("== 小賣→大賣：密窗交易日（法人密日全量）==", flush=True)
    days = _trading_days(db, start, end)
    print(f"  密日 n={len(days)}  {days[0] if days else '—'}→{days[-1] if days else '—'}", flush=True)
    if len(days) < 10:
        raise SystemExit("密窗過短，拒跑")

    print("== Top500 母體（末日基準）＋全日 panel 一次載入 ==", flush=True)
    sids = _top_sids(db, days[-1], TOP_N)
    print(f"  Top500 n={len(sids)}", flush=True)
    panel = _load_panel(db, days, sids)
    print("== 每日截面 sell_share 分位（張/張）==", flush=True)
    pctls: Dict[str, Dict[str, float]] = {}
    unit_rows: List[Dict[str, Any]] = []
    for d in days:
        pctls[d] = _day_pctls(panel.get(d) or {})
        for b in (panel.get(d) or {}).values():
            unit_rows.append(
                {"foreign_net": b.get("foreign_net"), "volume": b.get("volume")}
            )
    units_rep = unit_consistency_report(unit_rows)
    print(
        f"  單位檢查 ok={units_rep['units_ok']} n_sell={units_rep['n_sell_rows']} "
        f"gt10={units_rep['n_sell_share_gt10']}",
        flush=True,
    )
    with open(os.path.join(out_dir, "units_consistency.json"), "w", encoding="utf-8") as f:
        json.dump({**units_banner(), "consistency": units_rep}, f, ensure_ascii=False, indent=2)

    # 除權息集合 by day
    ex_by_day = {d: _ex_set(db, d) for d in days}
    day_i = {d: i for i, d in enumerate(days)}

    grid = iter_escalate_param_grid()
    print(f"== 網格 {len(grid)} 組全跑 ==", flush=True)
    grid_out: List[Dict[str, Any]] = []
    default = EscalateParams()
    events_path = os.path.join(out_dir, "escalate_events_default.jsonl")

    for gi, params in enumerate(grid):
        print(f"  [{gi+1}/{len(grid)}] {params.key()}", flush=True)
        lit_events: List[Dict[str, Any]] = []
        # 基線：同日未亮檔數（全母體可評估列）
        for di, d in enumerate(days):
            if di + 1 < params.n_days:
                continue
            window_days = days[di - params.n_days + 1 : di + 1]
            ex = ex_by_day.get(d) or set()
            for sid in sids:
                if sid in ex:
                    continue
                fns, vols, ps = [], [], []
                ok = True
                for wd in window_days:
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
                if not today.get("close"):
                    continue
                ev = evaluate_escalate_A(
                    foreign_nets=fns, volumes=vols, pctls=ps, params=params
                )
                if not ev.get("lit"):
                    continue
                # 後驗
                fut = []
                for koff in range(1, params.k_ahead + 1):
                    j = di + koff
                    if j >= len(days):
                        fut.append(None)
                    else:
                        fut.append(pctls.get(days[j], {}).get(sid))
                h = hit_within_k(fut, k=params.k_ahead, theta_pctl=params.theta_pctl)
                lit_events.append(
                    {
                        "as_of": d,
                        "sid": sid,
                        "name": today.get("stock_name") or "",
                        "lead_sync": "lead",
                        "sell_share": ev.get("sell_share"),
                        "pctl": ev.get("pctl"),
                        "foreign_net": today.get("foreign_net"),
                        "volume": today.get("volume"),
                        "volume_unit": VOLUME_UNIT,
                        "foreign_net_unit": FOREIGN_NET_UNIT,
                        "sell_share_unit": SELL_SHARE_UNIT,
                        "open": today.get("open"),
                        "high": today.get("high"),
                        "low": today.get("low"),
                        "close": today.get("close"),
                        "hit": h.get("hit"),
                        "hit_day_offset": h.get("hit_day_offset"),
                        "verdict": (
                            "pending"
                            if h.get("hit") is None
                            else ("hit" if h.get("hit") else "miss")
                        ),
                    }
                )

        # 基線：隨機「非 lit」同結構代價高；用「同密日、有連賣但未爬升／已極端」對照
        # 簡正基線＝密日截面：當日賣超股中「未亮 escalate」其後 K 日達 θ 的比率
        base_hit = 0
        base_n = 0
        for di, d in enumerate(days):
            if di + params.k_ahead >= len(days):
                continue
            ex = ex_by_day.get(d) or set()
            lit_sids = {e["sid"] for e in lit_events if e["as_of"] == d}
            for sid, pctl in (pctls.get(d) or {}).items():
                if sid in ex or sid in lit_sids:
                    continue
                b = (panel.get(d) or {}).get(sid)
                if not b or (_f(b.get("volume")) or 0) < MIN_VOLUME_LOTS:
                    continue
                if (_f(b.get("foreign_net")) or 0) >= 0:
                    continue
                fut = [
                    pctls.get(days[di + k], {}).get(sid)
                    for k in range(1, params.k_ahead + 1)
                    if di + k < len(days)
                ]
                h = hit_within_k(fut, k=params.k_ahead, theta_pctl=params.theta_pctl)
                if h.get("hit") is None:
                    continue
                base_n += 1
                if h.get("hit"):
                    base_hit += 1

        hits = sum(1 for e in lit_events if e["verdict"] == "hit")
        miss = sum(1 for e in lit_events if e["verdict"] == "miss")
        pend = sum(1 for e in lit_events if e["verdict"] == "pending")
        n_days_lit = len({e["as_of"] for e in lit_events})
        cell = {
            "params": params.as_dict(),
            "params_key": params.key(),
            "n_lit_events": len(lit_events),
            "n_lit_days": n_days_lit,
            "hit": hits,
            "miss": miss,
            "pending": pend,
            "hit_rate": (hits / (hits + miss)) if (hits + miss) else None,
            "baseline_n": base_n,
            "baseline_hit": base_hit,
            "baseline_hit_rate": (base_hit / base_n) if base_n else None,
            "units": units_banner(),
        }
        grid_out.append(cell)
        print(
            f"    lit事件={len(lit_events)} 日={n_days_lit} "
            f"hit_rate={cell['hit_rate']} base={cell['baseline_hit_rate']}",
            flush=True,
        )
        if params.key() == default.key():
            with open(events_path, "w", encoding="utf-8") as f:
                for e in lit_events:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

    report = {
        "generated_at": _now_iso(),
        "tz": "Asia/Taipei",
        "track": "foreign_sell_escalate",
        "not_buy_signal": True,
        "separate_from_fear_preopen": True,
        "window": {"start": start, "end": end, "n_dense_days": len(days)},
        "universe": {"top_n": TOP_N, "n_sids": len(sids)},
        "units": {**units_banner(), "consistency": units_rep},
        "grid": grid_out,
        "default_params_key": default.key(),
        "events_path": events_path,
    }
    report_path = os.path.join(out_dir, "foreign_sell_escalate_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    md = _zh_summary(report)
    md_path = os.path.join(out_dir, "foreign_sell_escalate_summary_zh.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"== 完成 {report_path}", flush=True)
    return report


def _zh_summary(report: Dict[str, Any]) -> str:
    u = report.get("units") or {}
    c = u.get("consistency") or {}
    lines = [
        "# 小賣→大賣升級｜全樣本對質摘要",
        "",
        f"- 產生：`{report.get('generated_at')}`（台北）",
        f"- 窗：`{report['window']['start']}`→`{report['window']['end']}` "
        f"法人密日 n={report['window']['n_dense_days']}（全日非抽樣）",
        f"- 宇宙：Top{report['universe']['top_n']} 全檔",
        f"- 單位：1 張＝{LOTS_PER_SHARE} 股；volume={VOLUME_UNIT}；"
        f"foreign_net={FOREIGN_NET_UNIT}；sell_share={SELL_SHARE_UNIT}",
        f"- 單位一致性 ok={c.get('units_ok')} 賣超列 n={c.get('n_sell_rows')} "
        f"佔量>10={c.get('n_sell_share_gt10')}",
        "- **不是買訊**；勝率與 FearComposite 分開；不准改 leave_zero。",
        "",
        "## 網格結果（升級型 A）",
    ]
    for g in report.get("grid") or []:
        lines.append(
            f"- `{g['params_key']}`：lit事件={g['n_lit_events']} 日={g['n_lit_days']} "
            f"命中率={_pct(g.get('hit_rate'))} "
            f"（hit={g['hit']} miss={g['miss']} pending={g['pending']}）；"
            f"基線命中率={_pct(g.get('baseline_hit_rate'))}（n={g['baseline_n']}）"
        )
    lines += [
        "",
        "## 硬邊界",
        "- 密日全跑、Top500 全檔、網格全跑；Lead＝pre（未極端）；除權息排除。",
        "- 未過閘不上話筒觀察標；靜默骨架可留。",
        "",
    ]
    return "\n".join(lines)


def _pct(x: Any) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--start", default="20260401")
    ap.add_argument("--end", default="")
    ap.add_argument("--out", default="/opt/cursor/artifacts/foreign-sell-escalate")
    args = ap.parse_args()
    if not os.path.isfile(args.db):
        print("缺庫", file=sys.stderr)
        return 2
    end = _ymd(args.end)
    if not end:
        dens = _trading_days(args.db, "20260401", "20991231")
        end = dens[-1] if dens else ""
    run_backtest(args.db, start=_ymd(args.start), end=end, out_dir=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
