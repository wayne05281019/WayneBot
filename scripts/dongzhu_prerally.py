#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""近 100 個有法人日：起漲前因素彙整，並對質洞燭現在要推的檔。

盤中未收不當官方收。不鎖起點％。不進海選、不改黃金買點。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_field_scan import (  # noqa: E402
    FLOW_LOOKBACK,
    SHARE_DAYS,
    dongzhu_picks,
    _chip_cap,
    _cap,
    _split_chain_text,
    _taught_for_chain,
    _stats,
)
from universe import is_screen_equity  # noqa: E402

try:
    from config import get_db_path  # noqa: E402
except Exception:
    def get_db_path():
        return os.path.join(ROOT, "data", "wayne_market.db")

DB = os.environ.get("WAYNE_DB") or get_db_path()
LOOKBACK = 100
FWD = 10
LIMIT_PCT = 9.5
GAIN = 0.08


def _ymd(raw: Any) -> str:
    return str(raw or "").replace("-", "")[:8]


def equity_ok(sid: str, name: str) -> bool:
    if len(str(sid)) != 4:
        return False
    try:
        return bool(is_screen_equity(sid, name))
    except Exception:
        return True


def load(conn: sqlite3.Connection, lookback: Optional[int] = None) -> Dict[str, Any]:
    chip = [
        _ymd(r[0])
        for r in conn.execute(
            """
            SELECT d FROM (
              SELECT REPLACE(CAST(date AS TEXT),'-','') d,
                     SUM(IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0)) t
              FROM daily_quotes WHERE length(stock_id)=4
              GROUP BY 1 HAVING t != 0
            ) ORDER BY d DESC
            """
        )
    ]
    quotes = [
        _ymd(r[0])
        for r in conn.execute(
            "SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') d FROM daily_quotes ORDER BY d DESC"
        )
    ]
    take_n = LOOKBACK if lookback is None else int(lookback)
    if take_n <= 0:
        take_n = len(chip)
    chip100 = sorted(chip[:take_n])
    want_from = quotes[min(len(quotes) - 1, take_n + 80)]
    fine: Dict[str, str] = {}
    members: Dict[str, List[str]] = defaultdict(list)
    names: Dict[str, str] = {}
    for sid, chain in conn.execute("SELECT stock_id, chain FROM stock_fine_industry"):
        sid = str(sid or "").strip()
        parts = _split_chain_text(str(chain or ""))
        if not sid or not parts or parts[-1] == "其他":
            continue
        key = "-".join(parts)
        fine[sid] = key
        members[key].append(sid)
    for sid, name in conn.execute(
        "SELECT stock_id, IFNULL(stock_name,'') FROM stock_universe"
    ):
        names[str(sid)] = str(name or sid)
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), stock_id, IFNULL(stock_name,''),
               high, low, close, volume, IFNULL(pct_change,0),
               IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0)
        FROM daily_quotes
        WHERE REPLACE(CAST(date AS TEXT),'-','')>=?
          AND length(stock_id)=4
        """,
        (want_from,),
    ).fetchall()
    by_sid: Dict[str, List[Tuple]] = defaultdict(list)
    by_day: Dict[str, List[Tuple]] = defaultdict(list)
    for d, sid, name, h, l, c, v, pct, three in rows:
        day = _ymd(d)
        sid = str(sid)
        try:
            rec = (
                day,
                float(h or 0),
                float(l or 0),
                float(c or 0),
                float(v or 0),
                float(pct or 0),
                int(three or 0),
            )
        except (TypeError, ValueError):
            continue
        if not equity_ok(sid, name or names.get(sid) or ""):
            continue
        by_sid[sid].append(rec)
        by_day[day].append((sid, rec))
        if name and sid not in names:
            names[sid] = str(name)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda x: x[0])
    return {
        "chip100": chip100,
        "quotes": sorted(quotes, reverse=False),
        "fine": fine,
        "members": members,
        "names": names,
        "by_sid": by_sid,
        "by_day": by_day,
        "chip_all": sorted(chip, reverse=False),
    }


def is_lu(rec: Tuple) -> bool:
    _d, h, _l, c, _v, pct, _t = rec
    locked = c > 0 and h > 0 and abs(c - h) <= max(0.01, c * 0.001)
    return pct >= LIMIT_PCT or (locked and pct >= 9.0)


def stats_at(bars: Sequence[Tuple], cap: str) -> Optional[Dict[str, Any]]:
    rows = [(r[0], r[1], r[2], r[3], r[4]) for r in bars if r[0] <= cap]
    return _stats(rows)


def share_series(
    members: Sequence[str],
    days: Sequence[str],
    by_sid: Dict[str, List[Tuple]],
) -> List[float]:
    idx = {sid: {r[0]: r[6] for r in bars} for sid, bars in by_sid.items()}
    out = []
    for d in days:
        inn = 0
        three = 0
        # market_in from all by_day would be better; caller passes mkt
        del inn
        s = 0
        for sid in members:
            s += int(idx.get(sid, {}).get(d) or 0)
        out.append(s)
    return out


def main() -> None:
    print(f"LOOKBACK={LOOKBACK} FLOW_LOOKBACK={FLOW_LOOKBACK} FWD={FWD}")
    conn = sqlite3.connect(DB)
    meta = load(conn)
    conn.close()
    chip100 = meta["chip100"]
    by_sid = meta["by_sid"]
    by_day = meta["by_day"]
    fine = meta["fine"]
    members = meta["members"]
    names = meta["names"]
    quotes = [d for d in meta["quotes"] if chip100[0] <= d <= chip100[-1]]
    print(f"窗 {chip100[0]}..{chip100[-1]} chip={len(chip100)} quote_in_win={len(quotes)}")

    mkt_in: Dict[str, int] = {}
    for d, recs in by_day.items():
        inn = sum(r[6] for _s, r in recs if r[6] > 0)
        mkt_in[d] = inn

    chain_three: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for sid, bars in by_sid.items():
        chain = fine.get(sid)
        if not chain:
            continue
        for rec in bars:
            chain_three[chain][rec[0]] += rec[6]

    def share(chain: str, d: str) -> float:
        inn = mkt_in.get(d) or 0
        three = chain_three[chain].get(d) or 0
        if inn > 0 and three > 0:
            return 100.0 * three / inn
        return 0.0

    # limit-ups in window
    hits = []
    for d in quotes:
        for sid, rec in by_day.get(d, []):
            if not is_lu(rec):
                continue
            chain = fine.get(sid) or ""
            hits.append({"date": d, "sid": sid, "name": names.get(sid) or sid, "chain": chain, "pct": rec[5]})
    print(f"漲停 n={len(hits)}")

    by_chain = defaultdict(list)
    for h in hits:
        if h["chain"]:
            by_chain[h["chain"]].append(h)

    clustered = []
    for chain, rows in by_chain.items():
        sids = {r["sid"] for r in rows}
        if len(sids) < 3:
            continue
        clustered.append((chain, rows, min(r["date"] for r in rows)))
    clustered.sort(key=lambda x: -len({r["sid"] for r in x[1]}))
    print(f"漲停≥3檔細項鏈 {len(clustered)}")

    vs20s, vs60s, volrs, persists, share_pres, first_lag = [], [], [], [], [], 0
    first_lead = 0
    n_pre_ok = 0
    print("\n=== 起漲前一日（簇內首漲停前一收）次級／龍頭＋佔比 ===")
    for chain, rows, first in clustered[:40]:
        sids = members.get(chain) or list({r["sid"] for r in rows})
        # leaders by turnover 20d ending day before first
        pre_days = [d for d in chip100 if d < first][-SHARE_DAYS:]
        persist = sum(1 for d in pre_days if share(chain, d) > 0)
        last_sh = share(chain, pre_days[-1]) if pre_days else 0.0
        first_h = min(rows, key=lambda r: (r["date"], -r["pct"]))
        st = stats_at(by_sid.get(first_h["sid"]) or [], first)
        # previous quote day stats
        bars = by_sid.get(first_h["sid"]) or []
        prev = [r for r in bars if r[0] < first]
        st_pre = stats_at(prev, prev[-1][0]) if prev else None
        tv = []
        cap = pre_days[-1] if pre_days else first
        for sid in sids:
            tot = 0.0
            for rec in by_sid.get(sid) or []:
                if rec[0] <= cap:
                    tot += rec[3] * rec[4]
            tv.append((tot, sid))
        tv.sort(reverse=True)
        k = 1 if len(tv) <= 3 else 2
        leads = {sid for _t, sid in tv[:k]}
        role = "龍頭" if first_h["sid"] in leads else "次級"
        if role == "次級":
            first_lag += 1
        else:
            first_lead += 1
        vs20 = float((st_pre or {}).get("vs20") or 0)
        vs60 = float((st_pre or {}).get("vs60") or 0)
        volr = float((st_pre or {}).get("volr") or 0)
        vs20s.append(vs20)
        vs60s.append(vs60)
        volrs.append(volr)
        persists.append(persist)
        share_pres.append(last_sh)
        pre_ok = persist >= 2 and vs20 < 0 and vs60 < 0
        if pre_ok:
            n_pre_ok += 1
        if len(clustered[:40]) and (chain.endswith("封測") or chain.endswith("電信服務") or persist >= 2):
            print(
                f"  {chain:28} 首{first} {first_h['sid']}{first_h['name']} {role} "
                f"前vs20={vs20:+.1f} vs60={vs60:+.1f} volr={volr:.2f} "
                f"佔比{last_sh:.2f}% persist{persist}/{len(pre_days)} pre_ok={pre_ok}"
            )

    def med(xs):
        return median(xs) if xs else float("nan")

    print(
        f"\n簇{len(clustered)} 列印前40：persist中位 {med(persists):.0f} "
        f"前一日佔比中位 {med(share_pres):.2f}% "
        f"vs20中位 {med(vs20s):.1f}% vs60中位 {med(vs60s):.1f}% volr中位 {med(volrs):.2f}"
    )
    print(f"  先次級 {first_lag} 先端龍 {first_lead}  前一日仍低於20高且60高且persist≥2：{n_pre_ok}/{len(vs20s)}")
    print(f"  vs20<0 的首漲停檔 {sum(1 for x in vs20s if x < 0)}/{len(vs20s)}  vs20≥0 {sum(1 for x in vs20s if x >= 0)}")
    print(f"  persist≥2 {sum(1 for x in persists if x >= 2)}/{len(persists)}  persist≥3 {sum(1 for x in persists if x >= 3)}")

    # walk-forward
    quote_idx = {d: i for i, d in enumerate(meta["quotes"])}
    chip_list = chip100
    end_i = len(chip_list) - 1
    # last FWD chip days reserved for outcome
    test_days = chip_list[:-FWD] if len(chip_list) > FWD else []
    # skip first 5 so persist defined
    test_days = test_days[5:]

    def top_chain(d: str, persist_min: int, need_pre: bool) -> Tuple[str, float, int]:
        ranked = []
        for chain, sids in members.items():
            if len(sids) < 3 and not _taught_for_chain(_split_chain_text(chain)):
                continue
            sh = share(chain, d)
            if sh <= 0:
                continue
            pre = [x for x in chip_list if x <= d][-SHARE_DAYS:]
            persist = sum(1 for x in pre if share(chain, x) > 0)
            if persist < persist_min:
                continue
            pre_ok = 1
            if need_pre:
                pre_ok = 0
                tv = []
                for sid in sids:
                    tot = 0.0
                    for rec in by_sid.get(sid) or []:
                        if rec[0] <= d:
                            tot += rec[3] * rec[4]
                    tv.append((tot, sid))
                tv.sort(reverse=True)
                k = 1 if len(tv) <= 3 else 2
                leads = {sid for _t, sid in tv[:k]}
                rest = [sid for _t, sid in tv if sid not in leads][:8]
                for sid in rest:
                    st = stats_at(by_sid.get(sid) or [], d)
                    if st and float(st.get("vs20") or 0) < 0 and float(st.get("vs60") or 0) < 0:
                        pre_ok = 1
                        break
                if not pre_ok:
                    continue
            ranked.append((sh, persist, chain))
        ranked.sort(reverse=True)
        if not ranked:
            return "", 0.0, 0
        sh, persist, chain = ranked[0]
        return chain, sh, persist

    def pick_lags(chain: str, d: str, n: int = 3) -> List[str]:
        sids = members.get(chain) or []
        tv = []
        for sid in sids:
            tot = 0.0
            cum = 0
            for rec in by_sid.get(sid) or []:
                if rec[0] <= d:
                    tot += rec[3] * rec[4]
                if rec[0] <= d and rec[0] in set([x for x in chip_list if x <= d][-5:]):
                    cum += rec[6]
            tv.append((tot, cum, sid))
        tv.sort(reverse=True)
        k = 1 if len(tv) <= 3 else 2
        leads = {sid for _t, _c, sid in tv[:k]}
        rest = [(cum, sid) for _t, cum, sid in tv if sid not in leads]
        rest.sort(reverse=True)
        out = []
        for cum, sid in rest:
            st = stats_at(by_sid.get(sid) or [], d)
            if not st:
                continue
            if float(st.get("vs20") or 0) >= 0:
                continue
            out.append(sid)
            if len(out) >= n:
                break
        return out

    def fwd_hit(sids: Sequence[str], d: str) -> Tuple[bool, bool]:
        qi = quote_idx.get(d)
        if qi is None:
            return False, False
        future = meta["quotes"][qi + 1 : qi + 1 + FWD]
        lu = False
        gain = False
        for sid in sids:
            bars = by_sid.get(sid) or []
            here = next((r for r in bars if r[0] == d), None)
            px = here[3] if here else 0
            for rec in bars:
                if rec[0] not in future:
                    continue
                if is_lu(rec):
                    lu = True
                if px > 0 and rec[3] / px - 1.0 >= GAIN:
                    gain = True
        return lu, gain

    def run_wf(label: str, persist_min: int, need_pre: bool) -> None:
        n = hit_lu = hit_gain = empty = 0
        examples = []
        for d in test_days:
            chain, sh, persist = top_chain(d, persist_min, need_pre)
            if not chain:
                empty += 1
                continue
            lags = pick_lags(chain, d)
            if not lags:
                empty += 1
                continue
            n += 1
            lu, gain = fwd_hit(lags, d)
            if lu:
                hit_lu += 1
            if gain or lu:
                hit_gain += 1
            if len(examples) < 8:
                examples.append(
                    (
                        d,
                        chain,
                        ",".join(f"{s}{names.get(s,s)}" for s in lags),
                        f"{sh:.2f}%",
                        persist,
                        "漲停" if lu else ("漲8%" if gain else "沒"),
                    )
                )
        print(f"\n=== 走查 {label} 日={n} 空={empty} ===")
        if n:
            print(f"  次級後{FWD}日漲停 {hit_lu}/{n}={100.0*hit_lu/n:.1f}%  漲停或漲≥8% {hit_gain}/{n}={100.0*hit_gain/n:.1f}%")
        for ex in examples:
            print("   ", ex)

    print("\n=== 走查：每個有法人日用當時佔比推次級，對後10個交易日官方收 ===")
    run_wf("只看當日佔比最高", 0, False)
    run_wf("佔比＋近5日≥2天有買超佔比", 2, False)
    run_wf("佔比＋persist≥2＋次級仍低於20高與60高", 2, True)

    # current picks vs fingerprint
    print("\n=== 對質此刻洞燭要推的檔 ===")
    cap = _cap(DB)
    chip = _chip_cap(DB, cap)
    data = dongzhu_picks(DB, spoken="")
    print(
        f"官方收 {cap} 法人日 {chip} 此刻最像 {data.get('field')} "
        f"窗 {data.get('flow_window')} 佔比 {float((data.get('flow') or {}).get('share_last') or 0):.2f}%"
    )
    for tag, rows in (
        ("主推落後", data.get("laggards") or []),
        ("買點", data.get("buys") or []),
        ("觀察", data.get("watches") or []),
    ):
        for x in rows:
            sid = str(x.get("sid") or "")
            st = stats_at(by_sid.get(sid) or [], chip)
            vs20 = float((st or x).get("vs20") or 0)
            vs60 = float((st or x).get("vs60") or 0)
            volr = float((st or x).get("volr") or 0)
            ok = vs20 < 0 and vs60 < 0
            print(
                f"  {tag} {sid}{x.get('name')} vs20={vs20:+.1f} vs60={vs60:+.1f} volr={volr:.2f} "
                f"像起漲前={ok} broke={bool((st or {}).get('broke'))}"
            )
    for block in data.get("alt_laggards") or []:
        print(f"  次熱 {block.get('field')}")
        for x in block.get("items") or []:
            sid = str(x.get("sid") or "")
            st = stats_at(by_sid.get(sid) or [], chip)
            vs20 = float((st or x).get("vs20") or 0)
            vs60 = float((st or x).get("vs60") or 0)
            volr = float((st or x).get("volr") or 0)
            ok = vs20 < 0 and vs60 < 0
            print(
                f"    {sid}{x.get('name')} vs20={vs20:+.1f} vs60={vs60:+.1f} volr={volr:.2f} 像起漲前={ok}"
            )
    # 封測／電信 path over 100d last 12 chip
    print("\n=== 電信服務 vs 封測 近12個有法人日佔比 ===")
    for chain in ("電子下游-電信服務", "電子上游-IC-封測"):
        path = [f"{d[4:]}:{share(chain, d):.2f}" for d in chip100[-12:]]
        print(f"  {chain} " + " ".join(path))


if __name__ == "__main__":
    main()
