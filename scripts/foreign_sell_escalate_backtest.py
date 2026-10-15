#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小賣→大賣＋起點大賣分軌｜密窗全樣本（不是買訊）。

母體並行（分開 n）：千金(收≥1000)、近半年日均量(張) Top500、上市櫃流動對照
大賣分軌：單日賣超張數、超比％、連續N日、10日累（單位張）
主訊號：小賣→大賣升級 A（連賣＋超比爬升→後 K 日達極端分位）

全量不准抽測；本庫優先；過程中文。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
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
    unit_consistency_report,
)
from foreign_sell_escalate import (  # noqa: E402
    GRID_CUM10_THR,
    GRID_LOTS_THR,
    LIQUID_MIN_TURNOVER_K,
    LIQUID_MIN_VOL_LOTS,
    QIANJIN_PX,
    UNIVERSE_LIQUID,
    UNIVERSE_QIANJIN,
    UNIVERSE_TOP500_VOL,
    EscalateParams,
    evaluate_escalate_A,
    hit_within_k,
    iter_escalate_param_grid,
    lit_dump_cum10,
    lit_dump_lots,
    lit_dump_share,
    lit_dump_streak,
    sell_lots,
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
UNIVERSES = (UNIVERSE_TOP500_VOL, UNIVERSE_QIANJIN, UNIVERSE_LIQUID)
SHARE_THR_GRID = (0.10, 0.15, 0.20, 0.30)
STREAK_GRID = (3, 5)


def _now_iso() -> str:
    return datetime.now(TP).isoformat(timespec="seconds")


def _universe_members(
    day: str,
    *,
    top500: Sequence[str],
    bars: Dict[str, Dict[str, Any]],
) -> Dict[str, List[str]]:
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


def _score_escalate_universe(
    *,
    days: Sequence[str],
    panel: Dict[str, Dict[str, Dict[str, Any]]],
    pctls: Dict[str, Dict[str, float]],
    ex_by_day: Dict[str, Set[str]],
    members_by_day: Dict[str, Dict[str, List[str]]],
    universe: str,
    params: EscalateParams,
) -> Dict[str, Any]:
    lit_events: List[Dict[str, Any]] = []
    for di, d in enumerate(days):
        if di + 1 < params.n_days:
            continue
        window_days = days[di - params.n_days + 1 : di + 1]
        ex = ex_by_day.get(d) or set()
        sids = members_by_day.get(d, {}).get(universe) or []
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
            fut = []
            for koff in range(1, params.k_ahead + 1):
                j = di + koff
                fut.append(None if j >= len(days) else pctls.get(days[j], {}).get(sid))
            h = hit_within_k(fut, k=params.k_ahead, theta_pctl=params.theta_pctl)
            lit_events.append(
                {
                    "as_of": d,
                    "universe": universe,
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

    # 基線：同宇宙賣超但未 lit，後 K 日達 θ
    base_hit = base_n = 0
    lit_set = {(e["as_of"], e["sid"]) for e in lit_events}
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
            if (_f(b.get("foreign_net")) or 0) >= 0:
                continue
            if sid not in (pctls.get(d) or {}):
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
    return {
        "universe": universe,
        "params_key": params.key(),
        "n_lit_events": len(lit_events),
        "n_lit_days": len({e["as_of"] for e in lit_events}),
        "hit": hits,
        "miss": miss,
        "pending": pend,
        "hit_rate": (hits / (hits + miss)) if (hits + miss) else None,
        "baseline_n": base_n,
        "baseline_hit": base_hit,
        "baseline_hit_rate": (base_hit / base_n) if base_n else None,
        "events": lit_events,
    }


def _score_dump_track(
    *,
    days: Sequence[str],
    panel: Dict[str, Dict[str, Dict[str, Any]]],
    pctls: Dict[str, Dict[str, float]],
    ex_by_day: Dict[str, Set[str]],
    members_by_day: Dict[str, Dict[str, List[str]]],
    universe: str,
    track: str,
    thr: float,
    k_ahead: int = 3,
    theta_pctl: float = 90.0,
    streak_n: int = 3,
) -> Dict[str, Any]:
    """大賣分軌：亮日後 K 日內是否達極端分位（與升級同一後驗，分軌記）。"""
    lit_hit = lit_n = 0
    base_hit = base_n = 0
    n_days_lit = set()
    for di, d in enumerate(days):
        if di + k_ahead >= len(days):
            continue
        if track == "cum10" and di < 9:
            continue
        if track == "streak" and di + 1 < streak_n:
            continue
        ex = ex_by_day.get(d) or set()
        lit_sids: Set[str] = set()
        for sid in members_by_day.get(d, {}).get(universe) or []:
            if sid in ex:
                continue
            b = (panel.get(d) or {}).get(sid)
            if not b or (_f(b.get("volume")) or 0) < MIN_VOLUME_LOTS:
                continue
            lit = False
            if track == "lots":
                lit = lit_dump_lots(b.get("foreign_net"), thr)
            elif track == "share":
                lit = lit_dump_share(b.get("foreign_net"), b.get("volume"), thr)
            elif track == "streak":
                hist = []
                for k in range(streak_n):
                    bb = (panel.get(days[di - streak_n + 1 + k]) or {}).get(sid)
                    hist.append(None if not bb else bb.get("foreign_net"))
                lit = lit_dump_streak(hist, streak_n)
            elif track == "cum10":
                hist = []
                for k in range(10):
                    bb = (panel.get(days[di - 9 + k]) or {}).get(sid)
                    hist.append(None if not bb else bb.get("foreign_net"))
                lit = lit_dump_cum10(hist, thr)
            if not lit:
                continue
            lit_sids.add(sid)
            fut = [
                pctls.get(days[di + k], {}).get(sid)
                for k in range(1, k_ahead + 1)
                if di + k < len(days)
            ]
            h = hit_within_k(fut, k=k_ahead, theta_pctl=theta_pctl)
            if h.get("hit") is None:
                continue
            lit_n += 1
            n_days_lit.add(d)
            if h.get("hit"):
                lit_hit += 1

        for sid in members_by_day.get(d, {}).get(universe) or []:
            if sid in ex or sid in lit_sids:
                continue
            b = (panel.get(d) or {}).get(sid)
            if not b or (_f(b.get("foreign_net")) or 0) >= 0:
                continue
            if (_f(b.get("volume")) or 0) < MIN_VOLUME_LOTS:
                continue
            fut = [
                pctls.get(days[di + k], {}).get(sid)
                for k in range(1, k_ahead + 1)
                if di + k < len(days)
            ]
            h = hit_within_k(fut, k=k_ahead, theta_pctl=theta_pctl)
            if h.get("hit") is None:
                continue
            base_n += 1
            if h.get("hit"):
                base_hit += 1

    return {
        "universe": universe,
        "track": track,
        "thr": thr,
        "streak_n": streak_n if track == "streak" else None,
        "unit": "張" if track in ("lots", "cum10") else ("比率" if track == "share" else "日"),
        "n_lit": lit_n,
        "n_lit_days": len(n_days_lit),
        "hit": lit_hit,
        "hit_rate": (lit_hit / lit_n) if lit_n else None,
        "baseline_n": base_n,
        "baseline_hit": base_hit,
        "baseline_hit_rate": (base_hit / base_n) if base_n else None,
    }


def run_backtest(db: str, *, start: str, end: str, out_dir: str) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    start, end = _ymd(start), _ymd(end)
    print("== 密窗法人日全量 ==", flush=True)
    days = _trading_days(db, start, end)
    print(f"  n={len(days)} {days[0] if days else '—'}→{days[-1] if days else '—'}", flush=True)
    if len(days) < 20:
        raise SystemExit("密窗過短")

    print("== 載入擴大池 panel（供三母體）==", flush=True)
    # 擴大池：日均量前 2500，覆蓋千金／流動
    pool = _top_sids(db, days[-1], max(TOP_N * 5, 2500))
    top500 = _top_sids(db, days[-1], TOP_N)
    print(f"  pool={len(pool)} top500_vol={len(top500)}", flush=True)
    panel = _load_panel(db, days, pool)

    print("== 截面分位＋單位核 ==", flush=True)
    pctls: Dict[str, Dict[str, float]] = {}
    unit_rows: List[Dict[str, Any]] = []
    members_by_day: Dict[str, Dict[str, List[str]]] = {}
    ex_by_day = {d: _ex_set(db, d) for d in days}
    for d in days:
        bars = panel.get(d) or {}
        pctls[d] = _day_pctls(bars)
        members_by_day[d] = _universe_members(d, top500=top500, bars=bars)
        for b in bars.values():
            unit_rows.append(
                {"foreign_net": b.get("foreign_net"), "volume": b.get("volume")}
            )
    units_rep = unit_consistency_report(unit_rows)
    print(
        f"  units_ok={units_rep['units_ok']} n_sell={units_rep['n_sell_rows']} "
        f"gt10={units_rep['n_sell_share_gt10']}",
        flush=True,
    )
    # 宇宙規模快照（末日）
    uni_sizes = {
        u: len(members_by_day[days[-1]].get(u) or []) for u in UNIVERSES
    }
    print(f"  末日宇宙規模 {uni_sizes}", flush=True)

    grid = iter_escalate_param_grid()
    print(f"== 升級 A 網格×三母體（{len(grid)}×{len(UNIVERSES)}）==", flush=True)
    escalate_grid: List[Dict[str, Any]] = []
    default = EscalateParams()
    default_events: Dict[str, List[Dict[str, Any]]] = {}
    for gi, params in enumerate(grid):
        for uni in UNIVERSES:
            print(f"  [{gi+1}/{len(grid)}] {params.key()} @ {uni}", flush=True)
            cell = _score_escalate_universe(
                days=days,
                panel=panel,
                pctls=pctls,
                ex_by_day=ex_by_day,
                members_by_day=members_by_day,
                universe=uni,
                params=params,
            )
            events = cell.pop("events")
            escalate_grid.append(cell)
            print(
                f"    lit={cell['n_lit_events']} hit_rate={cell['hit_rate']} "
                f"base={cell['baseline_hit_rate']}",
                flush=True,
            )
            if params.key() == default.key():
                default_events[uni] = events
                path = os.path.join(out_dir, f"escalate_events_{uni}.jsonl")
                with open(path, "w", encoding="utf-8") as f:
                    for e in events:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print("== 起點大賣分軌×三母體 ==", flush=True)
    dump_grid: List[Dict[str, Any]] = []
    for uni in UNIVERSES:
        for thr in GRID_LOTS_THR:
            dump_grid.append(
                _score_dump_track(
                    days=days,
                    panel=panel,
                    pctls=pctls,
                    ex_by_day=ex_by_day,
                    members_by_day=members_by_day,
                    universe=uni,
                    track="lots",
                    thr=float(thr),
                )
            )
            print(f"  lots thr={thr}張 @{uni} hit={dump_grid[-1]['hit_rate']}", flush=True)
        for thr in SHARE_THR_GRID:
            dump_grid.append(
                _score_dump_track(
                    days=days,
                    panel=panel,
                    pctls=pctls,
                    ex_by_day=ex_by_day,
                    members_by_day=members_by_day,
                    universe=uni,
                    track="share",
                    thr=float(thr),
                )
            )
        for sn in STREAK_GRID:
            dump_grid.append(
                _score_dump_track(
                    days=days,
                    panel=panel,
                    pctls=pctls,
                    ex_by_day=ex_by_day,
                    members_by_day=members_by_day,
                    universe=uni,
                    track="streak",
                    thr=0.0,
                    streak_n=int(sn),
                )
            )
        for thr in GRID_CUM10_THR:
            dump_grid.append(
                _score_dump_track(
                    days=days,
                    panel=panel,
                    pctls=pctls,
                    ex_by_day=ex_by_day,
                    members_by_day=members_by_day,
                    universe=uni,
                    track="cum10",
                    thr=float(thr),
                )
            )

    report = {
        "generated_at": _now_iso(),
        "tz": "Asia/Taipei",
        "track": "foreign_sell_escalate",
        "not_buy_signal": True,
        "separate_from_fear_preopen": True,
        "window": {"start": start, "end": end, "n_dense_days": len(days)},
        "universes": {
            "definitions": {
                UNIVERSE_TOP500_VOL: "近半年日均成交張數 Top500",
                UNIVERSE_QIANJIN: f"收盤≥{QIANJIN_PX}元",
                UNIVERSE_LIQUID: (
                    f"日量≥{LIQUID_MIN_VOL_LOTS}張且日額≥{LIQUID_MIN_TURNOVER_K}千元"
                ),
            },
            "size_at_end": uni_sizes,
        },
        "units": {**units_banner(), "consistency": units_rep},
        "escalate_A_grid": escalate_grid,
        "dump_def_grid": dump_grid,
        "default_params_key": default.key(),
    }
    with open(os.path.join(out_dir, "foreign_sell_escalate_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "units_consistency.json"), "w", encoding="utf-8") as f:
        json.dump(report["units"], f, ensure_ascii=False, indent=2)
    md = _zh_summary(report)
    with open(os.path.join(out_dir, "foreign_sell_escalate_summary_zh.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(f"== 完成 {out_dir}", flush=True)
    return report


def _pct(x: Any) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _zh_summary(report: Dict[str, Any]) -> str:
    u = report.get("units") or {}
    c = u.get("consistency") or {}
    lines = [
        "# 小賣→大賣＋起點大賣分軌｜全樣本摘要",
        "",
        f"- 產生：`{report.get('generated_at')}`（台北）",
        f"- 窗：`{report['window']['start']}`→`{report['window']['end']}` "
        f"密日 n={report['window']['n_dense_days']}（全日非抽樣）",
        f"- 末日宇宙：{report['universes']['size_at_end']}",
        f"- 單位：1張＝{LOTS_PER_SHARE}股；volume／foreign_net＝張；sell_share＝張/張",
        f"- 單位核 ok={c.get('units_ok')} 賣超列={c.get('n_sell_rows')} 佔量>10={c.get('n_sell_share_gt10')}",
        "- **不是買訊**；與 Fear 分軌；不准改 leave_zero。",
        "",
        "## 升級 A（連賣＋超比爬升）×三母體",
    ]
    for g in report.get("escalate_A_grid") or []:
        if g.get("params_key") != report.get("default_params_key"):
            continue
        lines.append(
            f"- **{g['universe']}** `{g['params_key']}`：lit事件={g['n_lit_events']} "
            f"日={g['n_lit_days']} 命中率={_pct(g.get('hit_rate'))} "
            f"基線={_pct(g.get('baseline_hit_rate'))}（n={g['baseline_n']}）"
        )
    lines += ["", "### 全網格一覽（精簡）"]
    for g in report.get("escalate_A_grid") or []:
        lines.append(
            f"- `{g['params_key']}`@{g['universe']}: lit={g['n_lit_events']} "
            f"hit={_pct(g.get('hit_rate'))} base={_pct(g.get('baseline_hit_rate'))}"
        )
    lines += ["", "## 起點大賣分軌（後K日達極端分位）×三母體"]
    for g in report.get("dump_def_grid") or []:
        thr = g.get("thr")
        extra = f" N={g.get('streak_n')}" if g.get("track") == "streak" else f" thr={thr}"
        lines.append(
            f"- {g['track']}{extra}（{g.get('unit')}）@{g['universe']}: "
            f"lit={g['n_lit']} 命中={_pct(g.get('hit_rate'))} "
            f"基線={_pct(g.get('baseline_hit_rate'))}"
        )
    lines += [
        "",
        "## 硬邊界",
        "- 三母體分開 n；四大賣分軌分開；Lead＝pre；除權息排除；全量不准抽測。",
        "- 未過閘不上話筒觀察標。",
        "",
    ]
    return "\n".join(lines)


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
