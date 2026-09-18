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
    meta = load(conn)
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

    def fwd(sids: Sequence[str], d: str) -> Tuple[bool, bool, Optional[float]]:
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

    regimes = {
        "追當天第一名": [],
        "昨天第一名今天佔比在退": [],
        "佔比升還沒當第一": [],
        "佔比升還沒當第一＋黃金買點": [],
        "追第一名＋黃金買點": [],
        "昨天第一名今天在退＋黃金買點": [],
        "佔比升最多還沒第一": [],
        "佔比升最多還沒第一＋黃金買點": [],
        "佔比升≥1pt還沒第一": [],
        "佔比升≥1pt還沒第一＋黃金買點": [],
        "連升兩日還沒第一": [],
        "連升兩日還沒第一＋黃金買點": [],
        "升還沒第一且非金控銀行": [],
        "升還沒第一且非金控銀行＋黃金買點": [],
        "佔比升最多且非金控銀行": [],
        "佔比升最多且非金控銀行＋黃金買點": [],
        "升還沒第一＋vs20≤−12": [],
        "升還沒第一＋vs20≤−12＋黃金買點": [],
        "升還沒第一＋volr≥1.2": [],
        "升還沒第一＋volr≥1.2＋黃金買點": [],
        "升還沒第一＋龍頭未過20高": [],
        "升還沒第一＋龍頭未過20高＋黃金買點": [],
    }

    def take(
        label: str,
        chain: str,
        d: str,
        lz: bool,
        *,
        vs20_max: float = PRE_VS20,
        volr_min: Optional[float] = None,
    ) -> None:
        if not chain:
            return
        sids = laggards(chain, d, lz=lz, vs20_max=vs20_max, volr_min=volr_min)
        if not sids:
            return
        lu, gain, best = fwd(sids, d)
        regimes[label].append(
            {
                "d": d,
                "chain": chain,
                "sids": sids,
                "lu": lu,
                "gain": gain or lu,
                "best": best,
                "names": ",".join(f"{s}{names.get(s, s)}" for s in sids),
            }
        )

    for d in test_days:
        ranked = ranked_day(d)
        if not ranked:
            continue
        hot_sh, hot = ranked[0]
        prev = yest.get(d)
        prev_ranked = ranked_day(prev) if prev else []
        y_hot = prev_ranked[0][1] if prev_ranked else ""
        y_sh = prev_ranked[0][0] if prev_ranked else 0.0
        leaving = y_hot and share(y_hot, d) + 1e-9 < y_sh

        rising = []
        for sh, chain in ranked[1:8]:
            if prev and share(chain, prev) > sh + 1e-9:
                continue
            if sh <= 0:
                continue
            rising.append((sh, chain))
        pre = rising[0][1] if rising else ""
        max_up = ""
        if rising:
            max_up = max(rising, key=lambda x: chg(x[1], d))[1]
        up1 = ""
        up1_rows = [(chg(c, d), c) for _sh, c in rising if chg(c, d) >= 1.0]
        if up1_rows:
            up1_rows.sort(reverse=True)
            up1 = up1_rows[0][1]
        rise2_c = ""
        rise2_rows = [(sh, c) for sh, c in rising if rise2(c, d)]
        if rise2_rows:
            rise2_c = rise2_rows[0][1]
        no_park = ""
        for _sh, c in rising:
            if not is_parking(c):
                no_park = c
                break
        max_up_np = ""
        np_rising = [(sh, c) for sh, c in rising if not is_parking(c)]
        if np_rising:
            max_up_np = max(np_rising, key=lambda x: chg(x[1], d))[1]

        take("追當天第一名", hot, d, False)
        take("追第一名＋黃金買點", hot, d, True)
        if leaving:
            take("昨天第一名今天佔比在退", y_hot, d, False)
            take("昨天第一名今天在退＋黃金買點", y_hot, d, True)
        if pre:
            take("佔比升還沒當第一", pre, d, False)
            take("佔比升還沒當第一＋黃金買點", pre, d, True)
            take("升還沒第一＋vs20≤−12", pre, d, False, vs20_max=-12.0)
            take("升還沒第一＋vs20≤−12＋黃金買點", pre, d, True, vs20_max=-12.0)
            take("升還沒第一＋volr≥1.2", pre, d, False, volr_min=1.2)
            take("升還沒第一＋volr≥1.2＋黃金買點", pre, d, True, volr_min=1.2)
            if leader_under_20(pre, d):
                take("升還沒第一＋龍頭未過20高", pre, d, False)
                take("升還沒第一＋龍頭未過20高＋黃金買點", pre, d, True)
        if max_up:
            take("佔比升最多還沒第一", max_up, d, False)
            take("佔比升最多還沒第一＋黃金買點", max_up, d, True)
        if up1:
            take("佔比升≥1pt還沒第一", up1, d, False)
            take("佔比升≥1pt還沒第一＋黃金買點", up1, d, True)
        if rise2_c:
            take("連升兩日還沒第一", rise2_c, d, False)
            take("連升兩日還沒第一＋黃金買點", rise2_c, d, True)
        if no_park:
            take("升還沒第一且非金控銀行", no_park, d, False)
            take("升還沒第一且非金控銀行＋黃金買點", no_park, d, True)
        if max_up_np:
            take("佔比升最多且非金控銀行", max_up_np, d, False)
            take("佔比升最多且非金控銀行＋黃金買點", max_up_np, d, True)
        del hot_sh

    def summarize(label: str) -> None:
        rows = regimes[label]
        n = len(rows)
        print(f"\n=== {label} 日={n} ===")
        if not n:
            return
        lu = sum(1 for r in rows if r["lu"])
        gain = sum(1 for r in rows if r["gain"])
        stuck = sum(
            1 for r in rows if r["best"] is not None and r["best"] < 0 and not r["lu"]
        )
        print(
            f"  次級後{FWD}日漲停 {lu}/{n}={100.0 * lu / n:.1f}%  "
            f"漲停或漲≥8% {gain}/{n}={100.0 * gain / n:.1f}%  "
            f"後十日最高仍虧 {stuck}/{n}={100.0 * stuck / n:.1f}%"
        )
        for r in rows[:6]:
            best = r["best"]
            bt = f"{best * 100:+.1f}%" if best is not None else "—"
            print(f"   {r['d']} {r['chain']} {r['names']} {bt} {'漲停' if r['lu'] else ('漲8%' if r['gain'] else '沒')}")

    print("\n=== 進場前徵兆走查（次級 vs20≤−8% 且仍低於60高） ===")
    for label in regimes:
        summarize(label)

    # encode-ready one-liners
    def rate(label: str) -> Tuple[int, float, float]:
        rows = regimes[label]
        n = len(rows)
        if not n:
            return 0, 0.0, 0.0
        gain = 100.0 * sum(1 for r in rows if r["gain"]) / n
        stuck = 100.0 * sum(
            1 for r in rows if r["best"] is not None and r["best"] < 0 and not r["lu"]
        ) / n
        return n, gain, stuck

    n1, g1, s1 = rate("追當天第一名")
    n2, g2, s2 = rate("佔比升還沒當第一")
    n3, g3, s3 = rate("昨天第一名今天佔比在退")
    n4, g4, s4 = rate("佔比升還沒當第一＋黃金買點")
    print("\n=== 規則（只留會改判斷的） ===")
    print(f"追第一名 勝{g1:.1f}% 套{s1:.1f}% n={n1}")
    print(f"升還沒第一 勝{g2:.1f}% 套{s2:.1f}% n={n2}")
    print(f"昨天第一今天退 勝{g3:.1f}% 套{s3:.1f}% n={n3}")
    print(f"升還沒第一∩黃金買點 勝{g4:.1f}% 套{s4:.1f}% n={n4}")
    prefer_pre = n2 >= 20 and (g2 >= g1 or s2 + 0.5 < s1)
    skip_leave = n3 >= 15 and (s3 > s2 or g3 + 1.0 < g2)
    print(f"ENCODE prefer_rising_not_lead={prefer_pre} skip_leaving_hot={skip_leave}")

    def beats(label: str, base_n: int, base_g: float, base_s: float, *, min_n: int = 20) -> bool:
        n, g, s = rate(label)
        if n < min_n:
            print(f"SKIP {label} n={n}<{min_n}")
            return False
        gain_ok = g + 1e-9 >= base_g
        better = g >= base_g + 1.0 or (gain_ok and s + 0.5 < base_s)
        ok = gain_ok and better
        delta = f"勝{g:.1f}({g - base_g:+.1f}) 套{s:.1f}({s - base_s:+.1f}) n={n}"
        print(f"{'ENCODE' if ok else 'KEEP'} {label} {delta}")
        return ok

    print("\n=== 額外切片 vs 升還沒第一 ===")
    extras = [
        "佔比升最多還沒第一",
        "佔比升≥1pt還沒第一",
        "連升兩日還沒第一",
        "升還沒第一且非金控銀行",
        "佔比升最多且非金控銀行",
        "升還沒第一＋vs20≤−12",
        "升還沒第一＋volr≥1.2",
        "升還沒第一＋龍頭未過20高",
    ]
    winners = [lab for lab in extras if beats(lab, n2, g2, s2)]
    print("\n=== 額外切片 vs 升還沒第一∩黃金買點 ===")
    lz_extras = [lab + "＋黃金買點" for lab in extras]
    lz_winners = [lab for lab in lz_extras if beats(lab, n4, g4, s4)]
    n5, g5, s5 = rate("升還沒第一且非金控銀行")
    skip_park = n5 >= 20 and g5 >= g2 + 1.0
    print(f"ENCODE skip_parking={skip_park} 勝{g5:.1f} 套{s5:.1f} n={n5}")
    print(f"\nWINNERS chain={winners} leave_zero={lz_winners}")


if __name__ == "__main__":
    main()
