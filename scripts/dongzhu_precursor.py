#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""進場前徵兆：追當天第一名 vs 佔比升還沒當第一 vs 昨天第一名今天在退。

一次走查就收成規則，不鎖假起點％。盤中未收不當官方收。
切入仍只認高低卡黃金買點（獲利 0.05%～5%）。
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)

from biaoke_field_scan import PRE_VS20, _split_chain_text, _taught_for_chain  # noqa: E402
from dongzhu_prerally import (  # noqa: E402
    DB,
    FWD,
    GAIN,
    LOOKBACK,
    SHARE_DAYS,
    is_lu,
    load,
    stats_at,
)

LZ_MIN = 0.05
LZ_MAX = 5.0


def _ymd_dt(day: str) -> datetime:
    return datetime.strptime(day, "%Y%m%d")


def profit_cal60(bars: Sequence[Tuple], cap: str) -> Optional[float]:
    rows = [r for r in bars if r[0] <= cap]
    if not rows:
        return None
    last = rows[-1]
    floor = (_ymd_dt(cap) - timedelta(days=60)).strftime("%Y%m%d")
    lows = [r[3] for r in rows if r[0] >= floor]
    if not lows:
        lows = [r[3] for r in rows[-20:]]
    lo = min(x for x in lows if x > 0) if any(x > 0 for x in lows) else 0.0
    if lo <= 0 or last[3] <= 0:
        return None
    return (last[3] / lo - 1.0) * 100.0


def just_left_zero(bars: Sequence[Tuple], cap: str) -> bool:
    rows = [r for r in bars if r[0] <= cap]
    if len(rows) < 2:
        return False
    today = profit_cal60(rows, cap)
    prev = profit_cal60(rows[:-1], rows[-2][0])
    if today is None or prev is None:
        return False
    return prev <= LZ_MIN and LZ_MIN < today <= LZ_MAX


def main() -> None:
    import sqlite3

    print(f"LOOKBACK={LOOKBACK} FWD={FWD} PRE_VS20={PRE_VS20} LZ={LZ_MIN}..{LZ_MAX}")
    conn = sqlite3.connect(DB)
    meta = load(conn, lookback=0)
    conn.close()
    chip100: List[str] = meta["chip100"]
    by_sid = meta["by_sid"]
    by_day = meta["by_day"]
    members: Dict[str, List[str]] = meta["members"]
    names = meta["names"]
    quotes: List[str] = meta["quotes"]
    quote_idx = {d: i for i, d in enumerate(quotes)}
    print(f"窗 {chip100[0]}..{chip100[-1]} chip={len(chip100)}")

    mkt_in: Dict[str, int] = {}
    for d, recs in by_day.items():
        mkt_in[d] = sum(r[6] for _s, r in recs if r[6] > 0)

    chain_three: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for sid, bars in by_sid.items():
        chain = meta["fine"].get(sid)
        if not chain:
            continue
        for rec in bars:
            chain_three[chain][rec[0]] += rec[6]

    chains = [
        c
        for c, sids in members.items()
        if len(sids) >= 3 or _taught_for_chain(_split_chain_text(c))
    ]

    def share(chain: str, d: str) -> float:
        inn = mkt_in.get(d) or 0
        three = chain_three[chain].get(d) or 0
        if inn > 0 and three > 0:
            return 100.0 * three / inn
        return 0.0

    def ranked_day(d: str) -> List[Tuple[float, str]]:
        rows = [(share(c, d), c) for c in chains]
        rows = [(sh, c) for sh, c in rows if sh > 0]
        rows.sort(reverse=True)
        return rows

    def leads_of(chain: str, d: str) -> set:
        tv = []
        for sid in members.get(chain) or []:
            tot = 0.0
            for rec in by_sid.get(sid) or []:
                if rec[0] <= d:
                    tot += rec[3] * rec[4]
            tv.append((tot, sid))
        tv.sort(reverse=True)
        k = 1 if len(tv) <= 3 else 2
        return {sid for _t, sid in tv[:k]}

    def laggards(
        chain: str,
        d: str,
        *,
        lz: bool,
        n: int = 3,
        vs20_max: float = PRE_VS20,
        volr_min: Optional[float] = None,
    ) -> List[str]:
        lead = leads_of(chain, d)
        rest = [sid for sid in (members.get(chain) or []) if sid not in lead]
        scored = []
        for sid in rest:
            st = stats_at(by_sid.get(sid) or [], d)
            if not st:
                continue
            vs20 = float(st.get("vs20") or 0)
            vs60 = float(st.get("vs60") or 0)
            if vs20 > vs20_max or vs60 >= 0:
                continue
            if volr_min is not None and float(st.get("volr") or 0) < volr_min:
                continue
            if lz and not just_left_zero(by_sid.get(sid) or [], d):
                continue
            scored.append((vs20, sid))
        scored.sort()
        return [sid for _v, sid in scored[:n]]

    def is_parking(chain: str) -> bool:
        return "金控" in chain or "銀行" in chain

    def chg(chain: str, d: str) -> float:
        prev = yest.get(d)
        if not prev:
            return 0.0
        return share(chain, d) - share(chain, prev)

    def rise2(chain: str, d: str) -> bool:
        p1 = yest.get(d)
        p2 = yest.get(p1) if p1 else None
        if not p1 or not p2:
            return False
        a, b, c = share(chain, p2), share(chain, p1), share(chain, d)
        return c > b + 1e-9 and b > a + 1e-9

    def leader_under_20(chain: str, d: str) -> bool:
        for sid in leads_of(chain, d):
            st = stats_at(by_sid.get(sid) or [], d)
            if st and float(st.get("vs20") or 0) >= 0:
                return False
        return True

    def fwd(
        sids: Sequence[str], d: str, nfwd: int = FWD
    ) -> Tuple[bool, bool, Optional[float]]:
        qi = quote_idx.get(d)
        if qi is None or not sids:
            return False, False, None
        future = set(quotes[qi + 1 : qi + 1 + FWD])
        lu = False
        gain = False
        best = None
        for sid in sids:
            bars = by_sid.get(sid) or []
            here = next((r for r in bars if r[0] == d), None)
            px = here[3] if here else 0
            mx = None
            for rec in bars:
                if rec[0] not in future:
                    continue
                if is_lu(rec):
                    lu = True
                if px > 0:
                    g = rec[3] / px - 1.0
                    mx = g if mx is None or g > mx else mx
                    if g >= GAIN:
                        gain = True
            if mx is not None:
                best = mx if best is None or mx > best else best
        return lu, gain, best

    test_days = chip100[SHARE_DAYS : -FWD] if len(chip100) > FWD + SHARE_DAYS else []
    yest = {chip100[i]: chip100[i - 1] for i in range(1, len(chip100))}
    recent_from = chip100[-100] if len(chip100) >= 100 else (chip100[0] if chip100 else "")
    print(f"全窗 {chip100[0]}..{chip100[-1]} n={len(chip100)} 近100起 {recent_from}")

    regimes = {
        "追當天第一名": [],
        "昨天第一名今天佔比在退": [],
        "佔比升還沒當第一": [],
        "非金控": [],
        "非金控＋連升兩日": [],
        "非金控＋升≥1pt": [],
        "非金控＋vs20≤−12": [],
        "非金控＋volr≥1.2": [],
        "非金控＋龍頭未過20高": [],
        "非金控＋最落後1檔": [],
        "非金控＋第2到4名": [],
        "非金控＋黃金買點逐檔": [],
    }

    def take(
        label: str,
        chain: str,
        d: str,
        lz: bool,
        *,
        vs20_max: float = PRE_VS20,
        volr_min: Optional[float] = None,
        n_lag: int = 3,
        each: bool = False,
    ) -> None:
        if not chain:
            return
        sids = laggards(chain, d, lz=lz, n=n_lag, vs20_max=vs20_max, volr_min=volr_min)
        if not sids:
            return
        win = "recent" if d >= recent_from else "prior"
        groups = [[s] for s in sids] if each else [sids]
        for group in groups:
            lu, gain, best = fwd(group, d)
            lu20 = gain20 = best20 = None
            if each:
                qi = quote_idx.get(d)
                if qi is not None and qi + 20 < len(quotes):
                    lu20, gain20, best20 = fwd(group, d, 20)
            st0 = stats_at(by_sid.get(group[0]) or [], d) if len(group) == 1 else None
            regimes[label].append(
                {
                    "d": d,
                    "chain": chain,
                    "sids": group,
                    "lu": lu,
                    "gain": gain or lu,
                    "best": best,
                    "win": win,
                    "vs20": float((st0 or {}).get("vs20") or 0) if st0 else None,
                    "volr": float((st0 or {}).get("volr") or 0) if st0 else None,
                    "profit": profit_cal60(by_sid.get(group[0]) or [], d) if len(group) == 1 else None,
                    "lead": group[0] in leads_of(chain, d) if len(group) == 1 else False,
                    "lu20": lu20,
                    "gain20": (gain20 or lu20) if lu20 is not None else None,
                    "best20": best20,
                    "names": ",".join(f"{s}{names.get(s, s)}" for s in group),
                }
            )

    for d in test_days:
        ranked = ranked_day(d)
        if not ranked:
            continue
        hot = ranked[0][1]
        prev = yest.get(d)
        prev_ranked = ranked_day(prev) if prev else []
        y_hot = prev_ranked[0][1] if prev_ranked else ""
        y_sh = prev_ranked[0][0] if prev_ranked else 0.0
        leaving = y_hot and share(y_hot, d) + 1e-9 < y_sh

        def _rising(rows: List[Tuple[float, str]]) -> List[Tuple[float, str]]:
            out = []
            for sh, chain in rows:
                if prev and share(chain, prev) > sh + 1e-9:
                    continue
                if sh <= 0:
                    continue
                out.append((sh, chain))
            return out

        rising = _rising(ranked[1:8])
        rising4 = _rising(ranked[1:4])
        pre = rising[0][1] if rising else ""
        no_park = ""
        for _sh, c in rising:
            if not is_parking(c):
                no_park = c
                break
        no_park4 = ""
        for _sh, c in rising4:
            if not is_parking(c):
                no_park4 = c
                break

        take("追當天第一名", hot, d, False)
        if leaving:
            take("昨天第一名今天佔比在退", y_hot, d, False)
        if pre:
            take("佔比升還沒當第一", pre, d, False)
        if no_park:
            take("非金控", no_park, d, False)
            take("非金控＋最落後1檔", no_park, d, False, n_lag=1)
            take("非金控＋黃金買點逐檔", no_park, d, True, each=True)
            if rise2(no_park, d):
                take("非金控＋連升兩日", no_park, d, False)
            if chg(no_park, d) >= 1.0:
                take("非金控＋升≥1pt", no_park, d, False)
            take("非金控＋vs20≤−12", no_park, d, False, vs20_max=-12.0)
            take("非金控＋volr≥1.2", no_park, d, False, volr_min=1.2)
            if leader_under_20(no_park, d):
                take("非金控＋龍頭未過20高", no_park, d, False)
        if no_park4:
            take("非金控＋第2到4名", no_park4, d, False)

    def summarize(label: str) -> None:
        rows = regimes[label]
        n = len(rows)
        print(f"\n=== {label} n={n} ===")
        if not n:
            return

        def _line(tag: str, part: List[dict]) -> None:
            pn = len(part)
            if not pn:
                print(f"  {tag} n=0")
                return
            lu = sum(1 for r in part if r["lu"])
            gain = sum(1 for r in part if r["gain"])
            stuck = sum(
                1 for r in part if r["best"] is not None and r["best"] < 0 and not r["lu"]
            )
            print(
                f"  {tag} n={pn} 漲停 {lu}/{pn}={100.0 * lu / pn:.1f}%  "
                f"漲停或≥8% {gain}/{pn}={100.0 * gain / pn:.1f}%  "
                f"套 {stuck}/{pn}={100.0 * stuck / pn:.1f}%"
            )

        _line("全窗", rows)
        _line("近100", [r for r in rows if r.get("win") == "recent"])
        _line("前段", [r for r in rows if r.get("win") == "prior"])

    print("\n=== 停車格之後增量（不重跑已否決切片） ===")
    for label in regimes:
        summarize(label)

    def rate(label: str, win: Optional[str] = None) -> Tuple[int, float, float]:
        rows = regimes[label]
        if win:
            rows = [r for r in rows if r.get("win") == win]
        n = len(rows)
        if not n:
            return 0, 0.0, 0.0
        gain = 100.0 * sum(1 for r in rows if r["gain"]) / n
        stuck = 100.0 * sum(
            1 for r in rows if r["best"] is not None and r["best"] < 0 and not r["lu"]
        ) / n
        return n, gain, stuck

    def beats(
        label: str,
        base_g: float,
        base_s: float,
        *,
        win: str = "recent",
        min_n: int = 20,
    ) -> bool:
        n, g, s = rate(label, win)
        pn, pg, ps = rate(label, "prior")
        _bn, bg, _bs = rate("非金控", "prior")
        if n < min_n:
            print(f"SKIP {label} {win} n={n}<{min_n}")
            return False
        gain_ok = g + 1e-9 >= base_g
        better = g >= base_g + 1.0 or (gain_ok and s + 0.5 < base_s)
        oos_ok = pn < 15 or pg + 1e-9 >= bg - 5.0
        ok = gain_ok and better and oos_ok
        print(
            f"{'ENCODE' if ok else 'KEEP'} {label} "
            f"近100 勝{g:.1f}({g - base_g:+.1f}) 套{s:.1f}({s - base_s:+.1f}) n={n}  "
            f"前段 勝{pg:.1f} 套{ps:.1f} n={pn} oos={oos_ok}"
        )
        return ok

    n_ch, g_ch, s_ch = rate("追當天第一名", "recent")
    n_pre, g_pre, s_pre = rate("佔比升還沒當第一", "recent")
    n_np, g_np, s_np = rate("非金控", "recent")
    print("\n=== 近100基線 ===")
    print(f"追第一 勝{g_ch:.1f} 套{s_ch:.1f} n={n_ch}")
    print(f"升還沒第一 勝{g_pre:.1f} 套{s_pre:.1f} n={n_pre}")
    print(f"非金控 勝{g_np:.1f} 套{s_np:.1f} n={n_np}")
    print(f"ENCODE skip_parking={n_np >= 20 and g_np >= g_pre + 1.0}")

    print("\n=== 增量 vs 非金控近100 ===")
    extras = [
        "非金控＋連升兩日",
        "非金控＋升≥1pt",
        "非金控＋vs20≤−12",
        "非金控＋volr≥1.2",
        "非金控＋龍頭未過20高",
        "非金控＋最落後1檔",
        "非金控＋第2到4名",
    ]
    winners = [lab for lab in extras if beats(lab, g_np, s_np)]
    print("\n=== 黃金買點逐檔 vs 非金控近100 ===")
    lz_ok = beats("非金控＋黃金買點逐檔", g_np, s_np, min_n=20)
    print(f"\nWINNERS incr={winners} leave_zero_each={lz_ok}")

    lz_recent = [r for r in regimes["非金控＋黃金買點逐檔"] if r.get("win") == "recent"]

    def lz_rate(part: List[dict]) -> Tuple[int, float, float]:
        n = len(part)
        if not n:
            return 0, 0.0, 0.0
        g = 100.0 * sum(1 for r in part if r["gain"]) / n
        s = 100.0 * sum(
            1 for r in part if r["best"] is not None and r["best"] < 0 and not r["lu"]
        ) / n
        return n, g, s

    print("\n=== 黃金買點逐檔近100內切片（n≥20才編碼排序） ===")
    bn, bg, bs = lz_rate(lz_recent)
    print(f"基線逐檔 勝{bg:.1f} 套{bs:.1f} n={bn}")
    slices = [
        ("次級", [r for r in lz_recent if not r.get("lead")]),
        ("龍頭", [r for r in lz_recent if r.get("lead")]),
        ("vs20≤−12", [r for r in lz_recent if r.get("vs20") is not None and r["vs20"] <= -12]),
        ("獲利≤2%", [r for r in lz_recent if r.get("profit") is not None and r["profit"] <= 2.0]),
        ("volr<1.2", [r for r in lz_recent if r.get("volr") is not None and r["volr"] < 1.2]),
        ("次級且vs20≤−12", [
            r for r in lz_recent
            if not r.get("lead") and r.get("vs20") is not None and r["vs20"] <= -12
        ]),
    ]
    lz_winners = []
    for name, part in slices:
        n, g, s = lz_rate(part)
        if n < 20:
            print(f"SKIP 買點/{name} n={n}<20")
            continue
        ok = (g >= bg + 1.0 and s + 1e-9 <= bs) or (g + 1e-9 >= bg and s + 0.5 < bs)
        print(f"{'ENCODE' if ok else 'KEEP'} 買點/{name} 勝{g:.1f}({g - bg:+.1f}) 套{s:.1f}({s - bs:+.1f}) n={n}")
        if ok:
            lz_winners.append(name)
    n20, g20, s20 = lz_rate(
        [
            {
                **r,
                "lu": bool(r.get("lu20")),
                "gain": bool(r.get("gain20")),
                "best": r.get("best20"),
            }
            for r in lz_recent
            if r.get("gain20") is not None
        ]
    )
    print(f"逐檔後20日 勝{g20:.1f} 套{s20:.1f} n={n20}")
    print(f"WINNERS buys={lz_winners}")


if __name__ == "__main__":
    main()
