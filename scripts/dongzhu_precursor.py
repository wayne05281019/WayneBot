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
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

# CMoney 鏈上對得上的族群。沒有的名不准發明一族。
# 矽光子／Ochoa → 半導體元件；MLCC → 被動元件；光電 → LED／光學／LCD。
# 塑化 → 塑膠＋化學工業；建築 → 營建；電信 → 電信服務。
# 軍工：CMoney 沒有軍工／國防細項（漢翔在航運、長榮航太在電機、雷虎在消費電子）。
# 飆大教過的電子次族群 vs 使用者點名要量的傳產／電信。教過才進「教過族群先機」。
TAUGHT_BUCKETS = (
    ("asic", ("電子上游-IP/ASIC",), "ASIC先機"),
    ("cool", ("電子中游-散熱零組件",), "散熱先機"),
    ("mem", ("電子上游-記憶體製造", "電子上游-記憶體IC設計", "電子上游-記憶體銷售"), "記憶體先機"),
    ("abf", ("電子上游-ABF",), "ABF先機"),
    ("pass", ("電子上游-被動元件",), "被動MLCC先機"),
    ("test", ("電子上游-IC-封測",), "封測先機"),
    ("pcb", ("電子上游-PCB",), "PCB先機"),
    ("inp", ("電子上游-半導體元件",), "光通訊矽光子先機"),
    ("opt", ("電子上游-LED照明及光元件", "電子中游-光學鏡片", "電子中游-LCD"), "光電先機"),
)
CYCLE_BUCKETS = (
    ("ship", ("傳產-航運",), "航運先機"),
    ("chem", ("傳產-塑膠", "傳產-化學工業"), "塑化先機"),
    ("tel", ("電子下游-電信服務",), "電信先機"),
    ("build", ("傳產-營建",), "建築先機"),
)
BUCKETS = TAUGHT_BUCKETS + CYCLE_BUCKETS
TAUGHT_KEYS = {k for k, _p, _lab in TAUGHT_BUCKETS}
MISSING_BUCKETS = (
    "軍工：CMoney 沒有軍工／國防細項，不發明一族。漢翔在傳產-航運、長榮航太在傳產-電機、雷虎在電子下游-消費電子。",
)
BUCKET_LABEL = {k: lab for k, _p, lab in BUCKETS}


def chain_bucket(chain: str) -> str:
    s = str(chain or "")
    for key, prefs, _lab in BUCKETS:
        for p in prefs:
            if s == p or s.startswith(p + "-"):
                return key
    return ""


def is_elec_chain(chain: str) -> bool:
    return str(chain or "").startswith("電子")


def _empty_seq() -> Dict[str, int]:
    return {
        "n": 0,
        "lag_first": 0,
        "lead_first": 0,
        "tie": 0,
        "none": 0,
        "lag_then_lead": 0,
        "lead_then_lag": 0,
        "lag_only": 0,
        "lead_only": 0,
        "recent_n": 0,
        "recent_lag_first": 0,
        "recent_lead_first": 0,
        "recent_lag_then_lead": 0,
        "recent_lead_then_lag": 0,
    }


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


def analyze(db_path: Optional[str] = None) -> Dict[str, Any]:
    import sqlite3

    print(f"LOOKBACK={LOOKBACK} FWD={FWD} PRE_VS20={PRE_VS20} LZ={LZ_MIN}..{LZ_MAX}")
    conn = sqlite3.connect(db_path or DB)
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

    def sids_of(key: str) -> List[str]:
        if key in members:
            return list(members[key])
        out: List[str] = []
        seen = set()
        for c, sids in members.items():
            if c == key or c.startswith(str(key) + "-"):
                for sid in sids:
                    if sid not in seen:
                        seen.add(sid)
                        out.append(sid)
        return out

    def leads_of(chain: str, d: str) -> set:
        tv = []
        for sid in sids_of(chain):
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
        rest = [sid for sid in sids_of(chain) if sid not in lead]
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
    for line in MISSING_BUCKETS:
        print(line)

    regimes = {
        "追當天第一名": [],
        "昨天第一名今天佔比在退": [],
        "佔比升還沒當第一": [],
        "非金控": [],
        "非金控＋最落後1檔": [],
        "非金控＋黃金買點逐檔": [],
        "非金控＋次產業未退": [],
        "非金控＋次產業也升": [],
        "非金控＋檔本身買超": [],
        "非金控＋檔本身買超1檔": [],
        "非金控＋買超剛轉正": [],
        "非金控＋黃金買點＋買超逐檔": [],
        "主產業先機": [],
        "次產業先機": [],
        "電子細項先機": [],
        "教過族群先機": [],
        "細項剩餘第2": [],
        "細項剩餘第3": [],
        **{lab: [] for _k, _p, lab in BUCKETS},
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
        sids: Optional[List[str]] = None,
    ) -> None:
        if not chain:
            return
        if sids is None:
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

    def parent_key(chain: str) -> str:
        parts = [p for p in str(chain).split("-") if p]
        return "-".join(parts[:-1]) if len(parts) >= 2 else ""

    def parent_share(chain: str, d: str) -> float:
        pk = parent_key(chain)
        if not pk:
            return 0.0
        inn = mkt_in.get(d) or 0
        if inn <= 0:
            return 0.0
        three = 0
        for c, days in chain_three.items():
            if c == pk or c.startswith(pk + "-"):
                three += days.get(d) or 0
        return 100.0 * three / inn if three > 0 else 0.0

    def net_at(sid: str, d: str) -> int:
        for rec in by_sid.get(sid) or []:
            if rec[0] == d:
                return int(rec[6] or 0)
        return 0

    def layer_key(chain: str, depth: int) -> str:
        parts = [p for p in str(chain).split("-") if p]
        if len(parts) < depth:
            return ""
        return "-".join(parts[:depth])

    def layer_keys(depth: int) -> List[str]:
        keys = set()
        for c in chains:
            k = layer_key(c, depth)
            if k:
                keys.add(k)
        return list(keys)

    def layer_share(key: str, d: str) -> float:
        inn = mkt_in.get(d) or 0
        if inn <= 0 or not key:
            return 0.0
        three = 0
        for c, days in chain_three.items():
            if c == key or c.startswith(key + "-"):
                three += days.get(d) or 0
        return 100.0 * three / inn if three > 0 else 0.0

    def ranked_layer(d: str, depth: int) -> List[Tuple[float, str]]:
        rows = [(layer_share(k, d), k) for k in layer_keys(depth)]
        rows = [(sh, k) for sh, k in rows if sh > 0]
        rows.sort(reverse=True)
        return rows

    def pick_rising_layer(d: str, depth: int, prev_d: str) -> str:
        ranked = ranked_layer(d, depth)
        if len(ranked) < 2:
            return ""
        for sh, key in ranked[1:8]:
            if is_parking(key) or key == "金融":
                continue
            if prev_d and layer_share(key, prev_d) > sh + 1e-9:
                continue
            if sh <= 0:
                continue
            return key
        return ""

    def first_gain_day(sid: str, d: str) -> Optional[int]:
        qi = quote_idx.get(d)
        if qi is None:
            return None
        future = quotes[qi + 1 : qi + 1 + FWD]
        bars = by_sid.get(sid) or []
        here = next((r for r in bars if r[0] == d), None)
        px = here[3] if here else 0
        for i, day in enumerate(future, 1):
            rec = next((r for r in bars if r[0] == day), None)
            if not rec:
                continue
            hit = is_lu(rec) or (px > 0 and rec[3] / px - 1.0 >= GAIN)
            if hit:
                return i
        return None

    seq = _empty_seq()
    bucket_seq = {k: _empty_seq() for k, _p, _lab in BUCKETS}
    elec_seq = _empty_seq()
    fine_trans: Dict[Tuple[str, str], int] = defaultdict(int)
    mid_trans: Dict[Tuple[str, str], int] = defaultdict(int)
    taught_trans: Dict[Tuple[str, str], int] = defaultdict(int)
    last_fine = last_mid = last_taught = ""
    cluster = {
        "n": 0,
        "recent_n": 0,
        "rising_not1": 0,
        "recent_rising": 0,
        "rank1": 0,
        "rank2_8": 0,
        "rank9": 0,
        "caught": 0,
        "recent_caught": 0,
        "elec": 0,
        "taught": 0,
        "lookback_rise": 0,
        "lookback_n": 0,
    }
    cluster_hit_days: List[int] = []
    cluster_hot_days: List[int] = []
    burst = {
        "n": 0,
        "recent_n": 0,
        "t1_rising_not1": 0,
        "t1_top8": 0,
        "t1_no_park": 0,
        "t1_elec": 0,
        "t3_rising_not1": 0,
    }
    stock_by_day: List[Tuple[str, List[dict]]] = []
    rev = {
        "n": 0,
        "rank1": 0,
        "rank2_4": 0,
        "rank5_8": 0,
        "rank9": 0,
        "rising_not1": 0,
        "caught_nopark": 0,
        "elec": 0,
        "recent_n": 0,
        "recent_rising_not1": 0,
        "recent_caught": 0,
        **{f"b_{k}": 0 for k, _p, _lab in BUCKETS},
    }

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
        pre = rising[0][1] if rising else ""
        park_free = [(sh, c) for sh, c in rising if not is_parking(c)]
        no_park = park_free[0][1] if park_free else ""

        take("追當天第一名", hot, d, False)
        if leaving:
            take("昨天第一名今天佔比在退", y_hot, d, False)
        if pre:
            take("佔比升還沒當第一", pre, d, False)
        if no_park:
            take("非金控", no_park, d, False)
            take("非金控＋最落後1檔", no_park, d, False, n_lag=1)
            take("非金控＋黃金買點逐檔", no_park, d, True, each=True)
            if prev and parent_share(no_park, d) + 1e-9 >= parent_share(no_park, prev):
                take("非金控＋次產業未退", no_park, d, False)
            if prev and parent_share(no_park, d) > parent_share(no_park, prev) + 1e-9:
                take("非金控＋次產業也升", no_park, d, False)
            pool = laggards(no_park, d, lz=False, n=8)
            net_sids = [s for s in pool if net_at(s, d) > 0]
            if net_sids:
                take("非金控＋檔本身買超", no_park, d, False, sids=net_sids[:3])
                take(
                    "非金控＋檔本身買超1檔",
                    no_park,
                    d,
                    False,
                    sids=[max(net_sids, key=lambda s: net_at(s, d))],
                )
            turned = [
                s
                for s in pool
                if prev and net_at(s, prev) <= 0 < net_at(s, d)
            ]
            if turned:
                take("非金控＋買超剛轉正", no_park, d, False, sids=turned[:3])
            lz_net = [s for s in laggards(no_park, d, lz=True, n=8) if net_at(s, d) > 0]
            if lz_net:
                take("非金控＋黃金買點＋買超逐檔", no_park, d, True, each=True, sids=lz_net)
            if is_elec_chain(no_park):
                take("電子細項先機", no_park, d, False)
            if len(park_free) >= 2:
                take("細項剩餘第2", park_free[1][1], d, False)
            if len(park_free) >= 3:
                take("細項剩餘第3", park_free[2][1], d, False)
            taught_rising = []
            extra_rising = []
            for _sh, c in park_free:
                b = chain_bucket(c)
                if b in TAUGHT_KEYS:
                    taught_rising.append((c, b))
                elif b:
                    extra_rising.append((c, b))
            if taught_rising:
                take("教過族群先機", taught_rising[0][0], d, False)
            seen_b = set()
            for c, b in taught_rising + extra_rising:
                if b in seen_b:
                    continue
                seen_b.add(b)
                take(BUCKET_LABEL[b], c, d, False)
            main_pre = pick_rising_layer(d, 1, prev or "")
            mid_pre = pick_rising_layer(d, 2, prev or "")
            if main_pre:
                take("主產業先機", main_pre, d, False)
            if mid_pre:
                take("次產業先機", mid_pre, d, False)
            if last_fine and last_fine != no_park:
                fine_trans[(last_fine, no_park)] += 1
            last_fine = no_park
            if mid_pre:
                if last_mid and last_mid != mid_pre:
                    mid_trans[(last_mid, mid_pre)] += 1
                last_mid = mid_pre
            taught_now = chain_bucket(no_park) or (
                taught_rising[0][1] if taught_rising else ""
            )
            if taught_now:
                if last_taught and last_taught != taught_now:
                    taught_trans[(last_taught, taught_now)] += 1
                last_taught = taught_now

            def _bump(sc: Dict[str, int], lag_i, lead_i, recent: bool) -> None:
                sc["n"] += 1
                if recent:
                    sc["recent_n"] += 1
                if lead_i is None and lag_i is None:
                    sc["none"] += 1
                elif lead_i is None or (lag_i is not None and lag_i < lead_i):
                    sc["lag_first"] += 1
                    if recent:
                        sc["recent_lag_first"] += 1
                    if lead_i is not None:
                        sc["lag_then_lead"] += 1
                        if recent:
                            sc["recent_lag_then_lead"] += 1
                    else:
                        sc["lag_only"] += 1
                elif lag_i is None or (lead_i is not None and lead_i < lag_i):
                    sc["lead_first"] += 1
                    if recent:
                        sc["recent_lead_first"] += 1
                    if lag_i is not None:
                        sc["lead_then_lag"] += 1
                        if recent:
                            sc["recent_lead_then_lag"] += 1
                    else:
                        sc["lead_only"] += 1
                else:
                    sc["tie"] += 1

            leads = list(leads_of(no_park, d))
            lags = laggards(no_park, d, lz=False, n=3)
            if leads and lags:
                lead_days = [first_gain_day(s, d) for s in leads]
                lag_days = [first_gain_day(s, d) for s in lags]
                lead_i = min((x for x in lead_days if x is not None), default=None)
                lag_i = min((x for x in lag_days if x is not None), default=None)
                recent = d >= recent_from
                _bump(seq, lag_i, lead_i, recent)
                if is_elec_chain(no_park):
                    _bump(elec_seq, lag_i, lead_i, recent)
                bk = chain_bucket(no_park)
                if bk:
                    _bump(bucket_seq[bk], lag_i, lead_i, recent)

            rank_of = {c: i + 1 for i, (_sh, c) in enumerate(ranked)}
            lead_cache: Dict[str, set] = {}

            def _leads(ch: str) -> set:
                got = lead_cache.get(ch)
                if got is None:
                    got = leads_of(ch, d)
                    lead_cache[ch] = got
                return got

            qi = quote_idx.get(d)
            px = {sid: rec[3] for sid, rec in by_day.get(d, [])}
            hit_sids = set()
            if qi is not None:
                future = quotes[qi + 1 : qi + 1 + FWD]
                for fd in future:
                    for sid, rec in by_day.get(fd, []):
                        p0 = px.get(sid) or 0
                        if is_lu(rec) or (p0 > 0 and rec[3] / p0 - 1.0 >= GAIN):
                            hit_sids.add(sid)
            recent = d >= recent_from
            hits_by_chain: Dict[str, set] = defaultdict(set)
            for sid in hit_sids:
                chain = meta["fine"].get(sid) or ""
                if not chain or is_parking(chain):
                    continue
                st = stats_at(by_sid.get(sid) or [], d)
                if not st:
                    continue
                if float(st.get("vs20") or 0) > PRE_VS20 or float(st.get("vs60") or 0) >= 0:
                    continue
                if sid in _leads(chain):
                    continue
                rk = int(rank_of.get(chain) or 99)
                sh_up = (not prev) or share(chain, d) + 1e-9 >= share(chain, prev)
                rev["n"] += 1
                if recent:
                    rev["recent_n"] += 1
                if rk == 1:
                    rev["rank1"] += 1
                elif rk <= 4:
                    rev["rank2_4"] += 1
                elif rk <= 8:
                    rev["rank5_8"] += 1
                else:
                    rev["rank9"] += 1
                if sh_up and rk >= 2:
                    rev["rising_not1"] += 1
                    if recent:
                        rev["recent_rising_not1"] += 1
                if chain == no_park:
                    rev["caught_nopark"] += 1
                    if recent:
                        rev["recent_caught"] += 1
                if is_elec_chain(chain):
                    rev["elec"] += 1
                bk = chain_bucket(chain)
                if bk:
                    rev[f"b_{bk}"] += 1
                hits_by_chain[chain].add(sid)

            for chain, sids in hits_by_chain.items():
                if len(sids) < 2:
                    continue
                rk = int(rank_of.get(chain) or 99)
                if rk > 8:
                    continue
                sh_up = (not prev) or share(chain, d) + 1e-9 >= share(chain, prev)
                cluster["n"] += 1
                if recent:
                    cluster["recent_n"] += 1
                if rk == 1:
                    cluster["rank1"] += 1
                elif 2 <= rk <= 8:
                    cluster["rank2_8"] += 1
                else:
                    cluster["rank9"] += 1
                if sh_up and rk >= 2:
                    cluster["rising_not1"] += 1
                    if recent:
                        cluster["recent_rising"] += 1
                if chain == no_park:
                    cluster["caught"] += 1
                    if recent:
                        cluster["recent_caught"] += 1
                if is_elec_chain(chain):
                    cluster["elec"] += 1
                if chain_bucket(chain) in TAUGHT_KEYS:
                    cluster["taught"] += 1
                ds = [first_gain_day(s, d) for s in sids]
                first = min((x for x in ds if x is not None), default=None)
                if first:
                    cluster_hit_days.append(first)
                if qi is not None:
                    future = quotes[qi + 1 : qi + 1 + FWD]
                    for i, fd in enumerate(future, 1):
                        if fd not in mkt_in:
                            continue
                        rr = ranked_day(fd)
                        if rr and rr[0][1] == chain:
                            cluster_hot_days.append(i)
                            break
                p1 = yest.get(d)
                p2 = yest.get(p1) if p1 else None
                if p1:
                    cluster["lookback_n"] += 1
                    sh1 = share(chain, p1)
                    sh0 = share(chain, d)
                    if sh0 + 1e-9 >= sh1:
                        cluster["lookback_rise"] += 1

            day_lags: List[dict] = []
            for sid in sids_of(no_park):
                if sid in _leads(no_park):
                    continue
                st = stats_at(by_sid.get(sid) or [], d)
                if not st:
                    continue
                vs20 = float(st.get("vs20") or 0)
                vs60 = float(st.get("vs60") or 0)
                if vs20 > PRE_VS20 or vs60 >= 0:
                    continue
                lu, gain, best = fwd([sid], d)
                day_lags.append(
                    {
                        "sid": sid,
                        "vs20": vs20,
                        "volr": float(st.get("volr") or 0),
                        "lz": just_left_zero(by_sid.get(sid) or [], d),
                        "net": net_at(sid, d),
                        "hit": bool(gain or lu),
                        "lu": lu,
                        "best": best,
                        "d": d,
                        "win": "recent" if recent else "prior",
                    }
                )
            if day_lags:
                stock_by_day.append((d, day_lags))

            if prev:
                burst_map: Dict[str, set] = defaultdict(set)
                px_prev = {sid: rec[3] for sid, rec in by_day.get(prev, [])}
                for sid, rec in by_day.get(d, []):
                    p0 = px_prev.get(sid) or 0
                    if not (is_lu(rec) or (p0 > 0 and rec[3] / p0 - 1.0 >= GAIN)):
                        continue
                    chain = meta["fine"].get(sid) or ""
                    if not chain or is_parking(chain):
                        continue
                    st = stats_at(by_sid.get(sid) or [], prev)
                    if not st:
                        continue
                    if float(st.get("vs20") or 0) > PRE_VS20 or float(st.get("vs60") or 0) >= 0:
                        continue
                    if sid in leads_of(chain, prev):
                        continue
                    burst_map[chain].add(sid)
                prev_ranked = ranked_day(prev)
                prev_rank = {c: i + 1 for i, (_sh, c) in enumerate(prev_ranked)}
                prev2 = yest.get(prev)
                for chain, sids in burst_map.items():
                    if len(sids) < 2:
                        continue
                    burst["n"] += 1
                    if recent:
                        burst["recent_n"] += 1
                    rk = int(prev_rank.get(chain) or 99)
                    if rk > 8:
                        continue
                    sh_up = (not prev2) or share(chain, prev) + 1e-9 >= share(chain, prev2)
                    if 2 <= rk <= 8:
                        burst["t1_top8"] += 1
                    if sh_up and rk >= 2:
                        burst["t1_rising_not1"] += 1
                    prev_free = []
                    for sh, c in prev_ranked[1:8]:
                        if is_parking(c):
                            continue
                        if prev2 and share(c, prev2) > sh + 1e-9:
                            continue
                        prev_free.append(c)
                    if prev_free and prev_free[0] == chain:
                        burst["t1_no_park"] += 1
                    if is_elec_chain(chain):
                        burst["t1_elec"] += 1
                    if prev2:
                        sh2 = share(chain, prev2)
                        sh1 = share(chain, prev)
                        p3 = yest.get(prev2)
                        sh3 = share(chain, p3) if p3 else sh2
                        if sh1 + 1e-9 >= sh2 and sh2 + 1e-9 >= sh3:
                            burst["t3_rising_not1"] += 1

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

    print("\n=== 停車格之後增量（舊切片只出編碼裁決、不重印明細） ===")
    for label in (
        "追當天第一名",
        "佔比升還沒當第一",
        "非金控",
        "電子細項先機",
        "教過族群先機",
    ):
        summarize(label)

    def _seq_line(tag: str, sc: Dict[str, int], *, recent: bool = False) -> None:
        n = sc["recent_n"] if recent else sc["n"]
        if not n:
            print(f"  {tag} n=0")
            return
        if recent:
            print(
                f"  {tag} n={n} 次級先 {100.0 * sc['recent_lag_first'] / n:.1f}% "
                f"龍頭先 {100.0 * sc['recent_lead_first'] / n:.1f}% "
                f"次級再龍頭 {100.0 * sc['recent_lag_then_lead'] / n:.1f}% "
                f"龍頭再次級 {100.0 * sc['recent_lead_then_lag'] / n:.1f}%"
            )
            return
        print(
            f"  {tag} n={n} 次級先 {100.0 * sc['lag_first'] / n:.1f}% "
            f"龍頭先 {100.0 * sc['lead_first'] / n:.1f}% "
            f"次級再龍頭 {100.0 * sc['lag_then_lead'] / n:.1f}% "
            f"龍頭再次級 {100.0 * sc['lead_then_lag'] / n:.1f}% "
            f"只有次級 {100.0 * sc['lag_only'] / n:.1f}% "
            f"只有龍頭 {100.0 * sc['lead_only'] / n:.1f}% "
            f"都沒 {100.0 * sc['none'] / n:.1f}% 同日 {100.0 * sc['tie'] / n:.1f}%"
        )

    print("\n=== 龍頭／次級誰先動（細項非金控，後10日漲停或≥8%） ===")
    _seq_line("全窗", seq)
    _seq_line("近100", seq, recent=True)
    _seq_line("電子全窗", elec_seq)
    _seq_line("電子近100", elec_seq, recent=True)

    def _rev_line(tag: str, n: int, rising: int, caught: int) -> None:
        if not n:
            print(f"  {tag} n=0")
            return
        print(
            f"  {tag} n={n} 佔比升還沒第一 {100.0 * rising / n:.1f}% "
            f"當日非金控先機抓到 {100.0 * caught / n:.1f}%"
        )

    print("\n=== 全市場次級回推（太寬，只作對照） ===")
    print(
        f"  近100 n={rev['recent_n']} 升還沒第一 {rev['recent_rising_not1']} "
        f"抓到 {rev['recent_caught']}"
    )

    def _pctn(num: int, den: int) -> str:
        if not den:
            return "n=0"
        return f"{num}/{den}={100.0 * num / den:.1f}%"

    print("\n=== 反向：同細項≥2檔次級後10日起漲（輪動簇） ===")
    cn = cluster["n"]
    cr = cluster["recent_n"]
    print(
        f"  全窗 n={cn} 升還沒第一 {_pctn(cluster['rising_not1'], cn)} "
        f"2–8名 {_pctn(cluster['rank2_8'], cn)} 已第一 {_pctn(cluster['rank1'], cn)} "
        f"9名外 {_pctn(cluster['rank9'], cn)}"
    )
    print(
        f"  近100 n={cr} 升還沒第一 {_pctn(cluster['recent_rising'], cr)} "
        f"當日先機抓到 {_pctn(cluster['recent_caught'], cr)} "
        f"電子 {_pctn(cluster['elec'], cn)} 教過 {_pctn(cluster['taught'], cn)}"
    )
    if cluster_hit_days:
        print(
            f"  簇內次級首漲距先機日 中位 {median(cluster_hit_days):.0f}日 "
            f"n={len(cluster_hit_days)}"
        )
    if cluster_hot_days:
        print(
            f"  細項變成第一名距先機日 中位 {median(cluster_hot_days):.0f}日 "
            f"n={len(cluster_hot_days)}（之後偏晚）"
        )
    print(
        f"  簇當日佔比≥昨日 {_pctn(cluster['lookback_rise'], cluster['lookback_n'])}"
    )

    print("\n=== 反向：當日同細項≥2檔次級已起漲，回看前一收 ===")
    bn = burst["n"]
    br = burst["recent_n"]
    print(
        f"  全窗 n={bn} T-1升還沒第一 {_pctn(burst['t1_rising_not1'], bn)} "
        f"T-1在2–8名 {_pctn(burst['t1_top8'], bn)} "
        f"T-1就是當日先機 {_pctn(burst['t1_no_park'], bn)} "
        f"電子 {_pctn(burst['t1_elec'], bn)}"
    )
    print(f"  近100 n={br}  T-3連升 {_pctn(burst['t3_rising_not1'], bn)}")

    def _top_trans(tag: str, trans: Dict[Tuple[str, str], int], n: int = 8) -> None:
        print(f"\n=== {tag} ===")
        rows = sorted(trans.items(), key=lambda x: -x[1])[:n]
        if not rows:
            print("  n=0")
            return
        tot = sum(trans.values())
        for (a, b), c in rows:
            print(f"  {a} → {b}  {c}/{tot}={100.0 * c / tot:.1f}%")

    _top_trans("細項輪動脈絡（非金控先機日切換）", fine_trans)
    _top_trans(
        "教過族群輪動脈絡",
        {
            (
                BUCKET_LABEL.get(a, a).replace("先機", ""),
                BUCKET_LABEL.get(b, b).replace("先機", ""),
            ): c
            for (a, b), c in taught_trans.items()
        },
    )

    def _stock_pick_rate(picker, win: Optional[str] = None) -> Tuple[int, float, float]:
        recs = []
        for _d, lags in stock_by_day:
            use = [r for r in lags if (not win or r.get("win") == win)]
            if not use:
                continue
            sid = picker(use)
            recs.extend(r for r in use if r["sid"] == sid)
        n = len(recs)
        if not n:
            return 0, 0.0, 0.0
        g = 100.0 * sum(1 for r in recs if r["hit"]) / n
        s = 100.0 * sum(
            1 for r in recs if r["best"] is not None and r["best"] < 0 and not r["lu"]
        ) / n
        return n, g, s

    print("\n=== 單檔淨化：先機細項裡的次級，一天只推1檔 ===")
    pickers = [
        ("最落後1檔", lambda rows: min(rows, key=lambda r: r["vs20"])["sid"]),
        ("最貼−8%1檔", lambda rows: max(rows, key=lambda r: r["vs20"])["sid"]),
        ("量比最高1檔", lambda rows: max(rows, key=lambda r: r["volr"])["sid"]),
        (
            "非黃金買點最落後",
            lambda rows: min(
                [r for r in rows if not r["lz"]] or rows,
                key=lambda r: r["vs20"],
            )["sid"],
        ),
        (
            "買超最多1檔",
            lambda rows: max(rows, key=lambda r: r["net"])["sid"],
        ),
    ]
    stock_recent: Dict[str, Tuple[int, float, float, int, float, float]] = {}
    for name, fn in pickers:
        n, g, s = _stock_pick_rate(fn, "recent")
        pn, pg, ps = _stock_pick_rate(fn, "prior")
        stock_recent[name] = (n, g, s, pn, pg, ps)
        print(
            f"  {name} 近100 n={n} 勝{g:.1f}% 套{s:.1f}%  前段 n={pn} 勝{pg:.1f}%"
        )

    all_recent = [r for _d, lags in stock_by_day for r in lags if r.get("win") == "recent"]
    if all_recent:
        nh = sum(1 for r in all_recent if r["hit"])
        print(
            f"  該細項全部次級 近100 n={len(all_recent)} 勝"
            f"{100.0 * nh / len(all_recent):.1f}%（母體，不是1檔）"
        )

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
        if pn < 15:
            print(
                f"KEEP {label} {win} 勝{g:.1f} n={n} 前段 n={pn}<15 不准自動過"
            )
            return False
        gain_ok = g + 1e-9 >= base_g
        better = g >= base_g + 1.0 or (gain_ok and s + 0.5 < base_s)
        oos_ok = pg + 1e-9 >= bg - 5.0
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
        "非金控＋次產業未退",
        "非金控＋次產業也升",
        "非金控＋檔本身買超",
        "非金控＋買超剛轉正",
        "主產業先機",
        "次產業先機",
        "電子細項先機",
        "教過族群先機",
        "細項剩餘第2",
        "細項剩餘第3",
    ] + [lab for _k, _p, lab in BUCKETS]
    winners = [lab for lab in extras if beats(lab, g_np, s_np)]
    n1, g1, s1 = rate("非金控＋最落後1檔", "recent")
    print("\n=== 單檔 vs 最落後1檔近100 ===")
    print(f"最落後1檔 勝{g1:.1f} 套{s1:.1f} n={n1}")
    one_winners = [
        lab for lab in ("非金控＋檔本身買超1檔",) if beats(lab, g1, s1)
    ]
    print("\n=== 單檔反推淨化 vs 最落後1檔 ===")
    stock_winner = ""
    base_st = stock_recent.get("最落後1檔")
    if base_st:
        _sn, sg, ss, _spn, spg, _sps = base_st
        for name, tup in stock_recent.items():
            if name == "最落後1檔":
                continue
            n, g, s, pn, pg, _ps = tup
            if n < 20:
                print(f"SKIP {name} n={n}<20")
                continue
            if pn < 15:
                print(f"KEEP {name} 前段 n={pn}<15 不准自動過")
                continue
            ok = (
                g + 1e-9 >= sg
                and (g >= sg + 1.0 or s + 0.5 < ss)
                and pg + 1e-9 >= spg - 5.0
            )
            print(
                f"{'ENCODE' if ok else 'KEEP'} {name} "
                f"近100 勝{g:.1f}({g - sg:+.1f}) 套{s:.1f} n={n} 前段 勝{pg:.1f} n={pn}"
            )
            if ok and not stock_winner:
                stock_winner = name
    print(f"WINNERS stock={stock_winner or []}")
    print("\n=== 黃金買點逐檔 vs 非金控近100 ===")
    lz_ok = beats("非金控＋黃金買點逐檔", g_np, s_np, min_n=20)
    print(f"\nWINNERS incr={winners} one={one_winners} leave_zero_each={lz_ok}")

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

    print("\n=== 黃金買點逐檔近100 ===")
    bn, bg, bs = lz_rate(lz_recent)
    print(f"基線逐檔 勝{bg:.1f} 套{bs:.1f} n={bn}")
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
    n_lz_net, g_lz_net, s_lz_net = rate("非金控＋黃金買點＋買超逐檔", "recent")
    print(
        f"黃金買點∩買超 勝{g_lz_net:.1f}({g_lz_net - bg:+.1f}) 套{s_lz_net:.1f} n={n_lz_net}"
    )
    lz_net_ok = (
        n_lz_net >= 20
        and g_lz_net >= bg + 1.0
        and s_lz_net + 1e-9 <= bs
    )
    print(
        f"{'ENCODE' if lz_net_ok else 'KEEP'} 非金控＋黃金買點＋買超逐檔 "
        f"近100 勝{g_lz_net:.1f}({g_lz_net - bg:+.1f}) 套{s_lz_net:.1f}({s_lz_net - bs:+.1f}) n={n_lz_net} "
        f"（套沒降或前段太薄＝不編碼）"
    )
    lz_winners = ["黃金買點＋買超"] if lz_net_ok else []
    print(f"WINNERS buys={lz_winners}")
    n_lv, g_lv, s_lv = rate("昨天第一名今天佔比在退", "recent")
    skip_park = n_np >= 20 and g_np >= g_pre + 1.0
    n_main, g_main, s_main = rate("主產業先機", "recent")
    n_mid, g_mid, s_mid = rate("次產業先機", "recent")
    n_el, g_el, s_el = rate("電子細項先機", "recent")
    n_tg, g_tg, s_tg = rate("教過族群先機", "recent")
    n_as, g_as, s_as = rate("ASIC先機", "recent")
    rank_unit = "fine"
    if "次產業先機" in winners:
        rank_unit = "mid"
    elif "主產業先機" in winners:
        rank_unit = "main"
    prefer_taught = "教過族群先機" in winners
    prefer_asic = "ASIC先機" in winners
    prefer_elec = "電子細項先機" in winners
    lag_n = int(seq.get("recent_n") or 0)
    lag_first_rate = (
        100.0 * seq["recent_lag_first"] / lag_n if lag_n else 0.0
    )
    lead_first_rate = (
        100.0 * seq["recent_lead_first"] / lag_n if lag_n else 0.0
    )
    rev_n = int(rev.get("recent_n") or 0)
    rev_cover = (
        100.0 * rev["recent_rising_not1"] / rev_n if rev_n else 0.0
    )
    rev_caught = (
        100.0 * rev["recent_caught"] / rev_n if rev_n else 0.0
    )
    return {
        "cap": chip100[-1] if chip100 else "",
        "window": [chip100[0], chip100[-1]] if len(chip100) >= 2 else list(chip100),
        "recent_from": recent_from,
        "prefer_rising_not_lead": n_pre >= 20 and g_pre >= g_ch,
        "skip_leaving_hot": n_lv >= 15 and (g_lv + 1.0 < g_pre or s_lv > s_pre),
        "skip_parking": skip_park if n_np >= 20 else None,
        "incr_winners": list(winners) + list(one_winners) + list(lz_winners),
        "require_parent_hold": "非金控＋次產業未退" in winners,
        "require_parent_up": "非金控＋次產業也升" in winners,
        "require_own_net": "非金控＋檔本身買超" in winners,
        "require_net_turn": "非金控＋買超剛轉正" in winners,
        "pick_max_net": "非金控＋檔本身買超1檔" in one_winners,
        "lz_require_net": bool(lz_net_ok),
        "rank_unit": rank_unit,
        "prefer_taught": prefer_taught,
        "prefer_asic": prefer_asic,
        "prefer_elec": prefer_elec,
        "seq": seq,
        "rev": rev,
        "cluster": cluster,
        "burst": burst,
        "stock_pick": stock_winner,
        "rates": {
            "chase": {"n": n_ch, "gain": g_ch, "stuck": s_ch},
            "pre": {"n": n_pre, "gain": g_pre, "stuck": s_pre},
            "leave": {"n": n_lv, "gain": g_lv, "stuck": s_lv},
            "no_park": {"n": n_np, "gain": g_np, "stuck": s_np},
            "lz_each": {"n": bn, "gain": bg, "stuck": bs},
            "lz_each_20": {"n": n20, "gain": g20, "stuck": s20},
            "main": {"n": n_main, "gain": g_main, "stuck": s_main},
            "mid": {"n": n_mid, "gain": g_mid, "stuck": s_mid},
            "elec": {"n": n_el, "gain": g_el, "stuck": s_el},
            "taught": {"n": n_tg, "gain": g_tg, "stuck": s_tg},
            "asic": {"n": n_as, "gain": g_as, "stuck": s_as},
            "seq_recent": {
                "n": lag_n,
                "lag_first": round(lag_first_rate, 1),
                "lead_first": round(lead_first_rate, 1),
            },
            "rev_recent": {
                "n": rev_n,
                "rising_not1": round(rev_cover, 1),
                "caught": round(rev_caught, 1),
            },
        },
    }


def refresh_dongzhu_judgment(db_path: str, cap: str = "") -> Dict[str, Any]:
    """盤後官方收齊後重跑走查，寫回庫。n 不夠沿用上一筆旗標。"""
    from biaoke_field_scan import load_dongzhu_precursor, store_dongzhu_precursor

    prev = load_dongzhu_precursor(db_path)
    result = analyze(db_path)
    if result.get("skip_parking") is None:
        result["skip_parking"] = bool(prev.get("skip_parking", True))
    as_of = str(cap or result.get("cap") or "")[:8]
    result["cap"] = as_of or str(result.get("cap") or "")
    if result.get("cap"):
        store_dongzhu_precursor(db_path, result["cap"], result)
    return result


def main() -> None:
    refresh_dongzhu_judgment(os.environ.get("WAYNE_DB") or DB)


if __name__ == "__main__":
    main()
