#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""極端大賣日→D+1～D+5｜密窗全樣本（確認層；不是買訊）。

三母體×四大賣 lit×（價回撤／續極端）分標；全量不准抽測；張≠股。
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

from fear_composite import VOLUME_UNIT, FOREIGN_NET_UNIT, _f, unit_consistency_report  # noqa: E402
from foreign_sell_escalate import (  # noqa: E402
    LIQUID_MIN_TURNOVER_K,
    LIQUID_MIN_VOL_LOTS,
    QIANJIN_PX,
    UNIVERSE_LIQUID,
    UNIVERSE_QIANJIN,
    UNIVERSE_TOP500_VOL,
    units_banner,
)
from foreign_sell_escalate_verify import (  # noqa: E402
    MIN_VOLUME_LOTS,
    TOP_N,
    _ex_set,
    _load_panel,
    _top_sids,
    _trading_days,
)
from foreign_sell_extreme import (  # noqa: E402
    DD_THR_GRID,
    K_AHEAD_GRID,
    TAG_CONT_EXTREME,
    TAG_PRICE_DD,
    ExtremeTrack,
    hit_continue_extreme,
    hit_price_dd,
    iter_extreme_tracks,
    lit_extreme_day,
    sell_lots,
    sync_same_day_crash,
)

TP = ZoneInfo("Asia/Taipei")
UNIVERSES = (UNIVERSE_TOP500_VOL, UNIVERSE_QIANJIN, UNIVERSE_LIQUID)


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


def _nets_window(
    panel: Dict[str, Dict[str, Dict[str, Any]]],
    days: Sequence[str],
    di: int,
    sid: str,
    n: int,
) -> List[Any]:
    out = []
    for j in range(max(0, di - n + 1), di + 1):
        b = (panel.get(days[j]) or {}).get(sid) or {}
        out.append(b.get("foreign_net"))
    return out


def _score_cell(
    *,
    days: Sequence[str],
    panel: Dict[str, Dict[str, Dict[str, Any]]],
    ex_by_day: Dict[str, Set[str]],
    members_by_day: Dict[str, Dict[str, List[str]]],
    universe: str,
    track: ExtremeTrack,
    k: int,
    thr_dd: float,
) -> Dict[str, Any]:
    lit_price: List[Dict[str, Any]] = []
    lit_cont: List[Dict[str, Any]] = []
    # 基線：賣超但未 lit
    base_price_n = base_price_hit = 0
    base_cont_n = base_cont_hit = 0

    for di, d in enumerate(days):
        if di + k >= len(days):
            continue
        if track.track == "cum10" and di < 9:
            continue
        if track.track == "streak" and di + 1 < int(track.thr):
            continue
        ex = ex_by_day.get(d) or set()
        sids = members_by_day.get(d, {}).get(universe) or []
        lit_sids: Set[str] = set()
        fut_days = days[di + 1 : di + 1 + k]
        for sid in sids:
            if sid in ex:
                continue
            b = (panel.get(d) or {}).get(sid)
            if not b or (_f(b.get("volume")) or 0) < MIN_VOLUME_LOTS:
                continue
            hist = _nets_window(panel, days, di, sid, max(14, int(track.thr) if track.track == "streak" else 10))
            nets10 = _nets_window(panel, days, di, sid, 10)
            if not lit_extreme_day(
                track,
                foreign_net=b.get("foreign_net"),
                volume=b.get("volume"),
                foreign_nets_hist=hist,
                foreign_nets_10=nets10,
            ):
                continue
            lit_sids.add(sid)
            crash = sync_same_day_crash(open_=b.get("open"), close=b.get("close"))
            closes = [
                ((panel.get(fd) or {}).get(sid) or {}).get("close") for fd in fut_days
            ]
            fut_lits: List[Optional[bool]] = []
            for fd in fut_days:
                bb = (panel.get(fd) or {}).get(sid)
                if not bb:
                    fut_lits.append(None)
                    continue
                fdi = days.index(fd)
                fh = _nets_window(panel, days, fdi, sid, max(14, int(track.thr) if track.track == "streak" else 10))
                f10 = _nets_window(panel, days, fdi, sid, 10)
                fut_lits.append(
                    lit_extreme_day(
                        track,
                        foreign_net=bb.get("foreign_net"),
                        volume=bb.get("volume"),
                        foreign_nets_hist=fh,
                        foreign_nets_10=f10,
                    )
                )
            hp = hit_price_dd(b.get("close"), closes, k=k, thr_dd=thr_dd)
            hc = hit_continue_extreme(fut_lits, k=k)
            base_row = {
                "as_of": d,
                "universe": universe,
                "sid": sid,
                "track": track.key(),
                "sync_crash": crash,
                "sell_lots": sell_lots(b.get("foreign_net")),
                "foreign_net": b.get("foreign_net"),
                "volume": b.get("volume"),
                "close": b.get("close"),
                "volume_unit": VOLUME_UNIT,
                "foreign_net_unit": FOREIGN_NET_UNIT,
            }
            if hp.get("hit") is not None:
                lit_price.append({**base_row, "tag": TAG_PRICE_DD, **hp})
            if hc.get("hit") is not None:
                lit_cont.append({**base_row, "tag": TAG_CONT_EXTREME, **hc})

        # baseline：賣超非 lit
        for sid in sids:
            if sid in ex or sid in lit_sids:
                continue
            b = (panel.get(d) or {}).get(sid)
            if not b or (_f(b.get("volume")) or 0) < MIN_VOLUME_LOTS:
                continue
            if (_f(b.get("foreign_net")) or 0) >= 0:
                continue
            closes = [
                ((panel.get(fd) or {}).get(sid) or {}).get("close") for fd in fut_days
            ]
            fut_lits = []
            for fd in fut_days:
                bb = (panel.get(fd) or {}).get(sid)
                if not bb:
                    fut_lits.append(None)
                    continue
                fdi = days.index(fd)
                fh = _nets_window(panel, days, fdi, sid, 14)
                f10 = _nets_window(panel, days, fdi, sid, 10)
                fut_lits.append(
                    lit_extreme_day(
                        track,
                        foreign_net=bb.get("foreign_net"),
                        volume=bb.get("volume"),
                        foreign_nets_hist=fh,
                        foreign_nets_10=f10,
                    )
                )
            hp = hit_price_dd(b.get("close"), closes, k=k, thr_dd=thr_dd)
            hc = hit_continue_extreme(fut_lits, k=k)
            if hp.get("hit") is not None:
                base_price_n += 1
                if hp.get("hit"):
                    base_price_hit += 1
            if hc.get("hit") is not None:
                base_cont_n += 1
                if hc.get("hit"):
                    base_cont_hit += 1

    def _summ(evs: List[Dict[str, Any]], bn: int, bh: int, tag: str) -> Dict[str, Any]:
        hits = sum(1 for e in evs if e.get("hit") is True)
        miss = sum(1 for e in evs if e.get("hit") is False)
        return {
            "universe": universe,
            "track_key": track.key(),
            "tag": tag,
            "k_ahead": k,
            "thr_dd": thr_dd if tag == TAG_PRICE_DD else None,
            "n_lit_events": len(evs),
            "n_lit_days": len({e["as_of"] for e in evs}),
            "hit": hits,
            "miss": miss,
            "hit_rate": (hits / (hits + miss)) if (hits + miss) else None,
            "baseline_n": bn,
            "baseline_hit": bh,
            "baseline_hit_rate": (bh / bn) if bn else None,
            "sync_crash_n": sum(1 for e in evs if e.get("sync_crash")),
        }

    return {
        "price_dd": _summ(lit_price, base_price_n, base_price_hit, TAG_PRICE_DD),
        "cont_extreme": _summ(lit_cont, base_cont_n, base_cont_hit, TAG_CONT_EXTREME),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("WAYNE_DB_PATH", "data/wayne_market.db"))
    ap.add_argument("--start", default="20260401")
    ap.add_argument("--end", default="")
    ap.add_argument("--out", default="/opt/cursor/artifacts/foreign-sell-extreme-dplus")
    ap.add_argument("--k", type=int, default=5, help="主評 K（另掃 1..5）")
    args = ap.parse_args()
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    start = args.start
    end = args.end or "20991231"
    days = _trading_days(args.db, start, end)
    if len(days) < 20:
        print(json.dumps({"error": "days_too_few", "n": len(days)}, ensure_ascii=False))
        return 2

    print(f"[extreme] 載入 panel 密日 n={len(days)} …", flush=True)
    pool = _top_sids(args.db, days[-1], max(TOP_N * 5, 2500))
    top500 = _top_sids(args.db, days[-1], TOP_N)
    panel = _load_panel(args.db, days, pool)
    ex_by_day = {d: _ex_set(args.db, d) for d in days}
    members_by_day: Dict[str, Dict[str, List[str]]] = {}
    for d in days:
        members_by_day[d] = _universe_members(d, top500=top500, bars=panel.get(d) or {})

    # 單位核
    unit_rows: List[Dict[str, Any]] = []
    for d in days:
        for b in (panel.get(d) or {}).values():
            unit_rows.append({"foreign_net": b.get("foreign_net"), "volume": b.get("volume")})
    units = unit_consistency_report(unit_rows)
    with open(os.path.join(out_dir, "units_consistency.json"), "w", encoding="utf-8") as f:
        json.dump({"banner": units_banner(), "consistency": units}, f, ensure_ascii=False, indent=2)

    tracks = iter_extreme_tracks()
    # 主掃：k=5、dd=-0.05；另附 k 網格精簡
    cells: List[Dict[str, Any]] = []
    k_main = int(args.k)
    thr_dd_main = -0.05
    for uni in UNIVERSES:
        for tr in tracks:
            cell = _score_cell(
                days=days,
                panel=panel,
                ex_by_day=ex_by_day,
                members_by_day=members_by_day,
                universe=uni,
                track=tr,
                k=k_main,
                thr_dd=thr_dd_main,
            )
            cells.append(cell)
            p = cell["price_dd"]
            print(
                f"[extreme] {uni} {tr.key()} k={k_main} "
                f"price lit={p['n_lit_events']} hit={p['hit_rate']} base={p['baseline_hit_rate']}",
                flush=True,
            )

    # k 網格（精簡：只 top500 × lots_th5000 × price_dd）
    k_grid_rows = []
    tr_focus = ExtremeTrack("lots", 5000.0)
    for k in K_AHEAD_GRID:
        for thr_dd in DD_THR_GRID:
            cell = _score_cell(
                days=days,
                panel=panel,
                ex_by_day=ex_by_day,
                members_by_day=members_by_day,
                universe=UNIVERSE_TOP500_VOL,
                track=tr_focus,
                k=int(k),
                thr_dd=float(thr_dd),
            )
            k_grid_rows.append(cell["price_dd"])

    report = {
        "track": "foreign_sell_extreme_dplus",
        "generated_at": _now_iso(),
        "window": {"start": days[0], "end": days[-1], "n_days": len(days)},
        "universe_sizes_last": {
            u: len(members_by_day[days[-1]].get(u) or []) for u in UNIVERSES
        },
        "units_ok": bool(units.get("units_ok")),
        "k_main": k_main,
        "thr_dd_main": thr_dd_main,
        "not_buy_signal": True,
        "cells": cells,
        "k_grid_top500_lots5000": k_grid_rows,
    }
    with open(os.path.join(out_dir, "foreign_sell_extreme_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lines = [
        "# 極端大賣→D+1～D+5｜全樣本摘要",
        "",
        f"- 產生：`{_now_iso()}`（台北）",
        f"- 窗：`{days[0]}`→`{days[-1]}` 密日 n={len(days)}（全日非抽樣）",
        f"- 單位核 ok={units.get('units_ok')}；**不是買訊**；與 Fear／escalate 分軌。",
        "",
        f"## 主掃 k={k_main} thr_dd={thr_dd_main}（價回撤／續極端分標）",
        "",
    ]
    for cell in cells:
        p, c = cell["price_dd"], cell["cont_extreme"]
        lines.append(
            f"- **{p['universe']}** `{p['track_key']}` 價回撤：lit={p['n_lit_events']} "
            f"命中={p['hit_rate']} 基線={p['baseline_hit_rate']}；"
            f"續極端：lit={c['n_lit_events']} 命中={c['hit_rate']} 基線={c['baseline_hit_rate']}"
        )
    lines += ["", "## top500 lots5000 × K／dd 網格（價回撤）", ""]
    for r in k_grid_rows:
        lines.append(
            f"- k={r['k_ahead']} dd={r['thr_dd']}: lit={r['n_lit_events']} "
            f"hit={r['hit_rate']} base={r['baseline_hit_rate']}"
        )
    lines += ["", "## 硬邊界", "", "- 未過閘不上話筒；Sync 當日大崩另標；顯示等隊列後。", ""]
    with open(os.path.join(out_dir, "foreign_sell_extreme_summary_zh.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[extreme] 寫入 {out_dir}", flush=True)
    return 0 if units.get("units_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
