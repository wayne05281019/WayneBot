#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從官方日 K 反推：漲停細項、法人佔比起點／斜率、龍頭 vs 次級誰先起漲。

五天太薄（佔比起點中位 0%＝窗截斷，不是規則）。結果窗＝近 20 個交易日，
再往前 15 個有法人日看佔比路徑。不鎖「起點必須 X%」。盤中未收不當官方收。
不進海選、不改黃金買點。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from industry_fine import split_chain  # noqa: E402
from universe import is_screen_equity  # noqa: E402

try:
    from config import get_db_path  # noqa: E402
except Exception:
    def get_db_path():
        return os.path.join(ROOT, "data", "wayne_market.db")

DB = os.environ.get("WAYNE_DB") or get_db_path()
RESULT_N = 20  # 五天太薄；近 20 個交易日當結果窗
FLOW_PRE = 15  # 再往前 15 日看佔比起點
LIMIT_PCT = 9.5  # 上市櫃 10% 漲停；盤後未收不當日


def _ymd(raw: Any) -> str:
    return str(raw or "").replace("-", "")[:8]


def _parts(chain: str) -> List[str]:
    return split_chain(str(chain or "").replace("／", "-"))


def load(conn: sqlite3.Connection) -> Dict[str, Any]:
    dates = [
        _ymd(r[0])
        for r in conn.execute(
            "SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') d FROM daily_quotes ORDER BY d DESC"
        )
    ]
    result_days = sorted(dates[:RESULT_N])
    flow_days = sorted(dates[: RESULT_N + FLOW_PRE])
    fine: Dict[str, List[str]] = {}
    for sid, chain in conn.execute("SELECT stock_id, chain FROM stock_fine_industry"):
        fine[str(sid)] = _parts(chain)
    uni: Dict[str, Tuple[str, str]] = {}
    for sid, name, asset, ind in conn.execute(
        "SELECT stock_id, stock_name, IFNULL(asset_type,''), IFNULL(industry,'') FROM stock_universe"
    ):
        uni[str(sid)] = (str(name or ""), str(ind or ""))
    return {
        "result_days": result_days,
        "flow_days": flow_days,
        "fine": fine,
        "uni": uni,
    }


def equity_ok(sid: str, name: str) -> bool:
    if len(str(sid)) != 4:
        return False
    try:
        return bool(is_screen_equity(sid, name))
    except Exception:
        return True


def limit_ups(conn: sqlite3.Connection, days: List[str]) -> List[Dict[str, Any]]:
    qmarks = ",".join("?" * len(days))
    rows = conn.execute(
        f"""
        SELECT REPLACE(CAST(date AS TEXT),'-','') d, stock_id, IFNULL(stock_name,''),
               close, high, pct_change, volume,
               IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) three
        FROM daily_quotes
        WHERE REPLACE(CAST(date AS TEXT),'-','') IN ({qmarks})
          AND length(stock_id)=4
        """,
        days,
    ).fetchall()
    out = []
    for d, sid, name, close, high, pct, vol, three in rows:
        if not equity_ok(str(sid), str(name)):
            continue
        try:
            pct = float(pct or 0)
            close = float(close or 0)
            high = float(high or 0)
        except (TypeError, ValueError):
            continue
        locked = close > 0 and high > 0 and abs(close - high) <= max(0.01, close * 0.001)
        if pct < LIMIT_PCT and not (locked and pct >= 9.0):
            continue
        out.append(
            {
                "date": _ymd(d),
                "sid": str(sid),
                "name": str(name or sid),
                "pct": pct,
                "close": close,
                "vol": int(vol or 0),
                "three": int(three or 0),
            }
        )
    return out


def market_in_by_day(conn: sqlite3.Connection, days: List[str]) -> Dict[str, int]:
    qmarks = ",".join("?" * len(days))
    rows = conn.execute(
        f"""
        SELECT d, IFNULL(SUM(CASE WHEN t>0 THEN t ELSE 0 END),0)
        FROM (
          SELECT REPLACE(CAST(date AS TEXT),'-','') d,
                 IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) t
          FROM daily_quotes
          WHERE REPLACE(CAST(date AS TEXT),'-','') IN ({qmarks})
            AND length(stock_id)=4
        )
        GROUP BY d
        """,
        days,
    ).fetchall()
    return {_ymd(d): int(v or 0) for d, v in rows}


def fine_three(conn: sqlite3.Connection, sids: List[str], days: List[str]) -> Dict[str, int]:
    if not sids:
        return {}
    q1 = ",".join("?" * len(days))
    q2 = ",".join("?" * len(sids))
    rows = conn.execute(
        f"""
        SELECT REPLACE(CAST(date AS TEXT),'-',''),
               IFNULL(SUM(IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0)),0)
        FROM daily_quotes
        WHERE REPLACE(CAST(date AS TEXT),'-','') IN ({q1})
          AND stock_id IN ({q2})
        GROUP BY 1
        """,
        [*days, *sids],
    ).fetchall()
    return {_ymd(d): int(v or 0) for d, v in rows}


def turnover_leaders(conn: sqlite3.Connection, sids: List[str], cap: str, n: int = 20) -> List[str]:
    if not sids:
        return []
    q = ",".join("?" * len(sids))
    rows = conn.execute(
        f"""
        SELECT stock_id, SUM(IFNULL(close,0)*IFNULL(volume,0)) tv
        FROM daily_quotes
        WHERE stock_id IN ({q})
          AND REPLACE(CAST(date AS TEXT),'-','')<=?
        GROUP BY stock_id
        ORDER BY tv DESC
        """,
        [*sids, cap],
    ).fetchall()
    ranked = [str(r[0]) for r in rows]
    k = 1 if len(ranked) <= 3 else 2
    return ranked[:k]


def main() -> None:
    conn = sqlite3.connect(DB)
    meta = load(conn)
    result_days = meta["result_days"]
    flow_days = meta["flow_days"]
    fine = meta["fine"]
    uni = meta["uni"]
    cap = result_days[-1]
    hits = limit_ups(conn, result_days)
    print(f"漲停 n={len(hits)} 窗={result_days[0]}..{result_days[-1]} cap={cap}")

    # attach layers
    for h in hits:
        parts = fine.get(h["sid"]) or []
        h["main"] = parts[0] if parts else (uni.get(h["sid"] or "") or ("", ""))[1] or "未分類"
        h["sub"] = parts[1] if len(parts) > 1 else ""
        h["fine"] = parts[2] if len(parts) > 2 else (parts[-1] if parts else "未分類")
        h["chain"] = "-".join(parts) if parts else (h["main"] or "未分類")
        h["cluster"] = h["chain"]
        if not h["name"] or h["name"] == h["sid"]:
            h["name"] = (uni.get(h["sid"]) or ("", ""))[0] or h["sid"]

    by_fine = defaultdict(list)
    by_sub = defaultdict(list)
    by_main = defaultdict(list)
    by_cluster = defaultdict(list)
    for h in hits:
        by_fine[h["fine"]].append(h)
        by_sub[h["sub"] or h["fine"]].append(h)
        by_main[h["main"]].append(h)
        by_cluster[h["cluster"]].append(h)

    print("\n=== 主產業 漲停家數 ===")
    for k, n in Counter(h["main"] for h in hits).most_common(12):
        print(f"  {k:16} {n:3}")
    print("\n=== 次產業 漲停家數 ===")
    for k, n in Counter((h["sub"] or "(無次產業)") for h in hits).most_common(15):
        print(f"  {k:16} {n:3}")
    print("\n=== 細項鏈 漲停≥3 檔（不是同一檔連板）===")
    clustered = []
    for k, rows in sorted(by_cluster.items(), key=lambda kv: -len({x["sid"] for x in kv[1]})):
        n_sid = len({r["sid"] for r in rows})
        if n_sid < 3:
            continue
        days = sorted({r["date"] for r in rows})
        clustered.append((k, rows, days))
        names = ",".join(
            f"{r['sid']}{r['name']}" for r in sorted(rows, key=lambda x: (x["date"], x["sid"]))[:8]
        )
        print(f"  {k:28} 檔{n_sid:2}次{len(rows):3}日={','.join(days)} {names}")

    # universe by fine
    members: Dict[str, List[str]] = defaultdict(list)
    for sid, parts in fine.items():
        chain = "-".join(parts) if parts else ""
        if chain:
            members[chain].append(sid)
        tag = parts[2] if len(parts) > 2 else (parts[-1] if parts else "")
        if tag:
            members[tag].append(sid)

    mkt = market_in_by_day(conn, flow_days)
    print("\n=== 細項資金：結果窗內漲停≥3 的細項，佔當日法人買超％ ===")
    share_starts = []
    rising_n = 0
    falling_n = 0
    for tag, rows, days in clustered:
        sids = members.get(tag) or list({r["sid"] for r in rows})
        th = fine_three(conn, sids, flow_days)
        series = []
        for d in flow_days:
            inn = mkt.get(d) or 0
            three = th.get(d) or 0
            share = (100.0 * three / inn) if inn > 0 and three > 0 else (0.0 if inn > 0 else None)
            series.append((d, three, share, inn))
        # skip trailing all-zero chip day
        usable = [(d, t, s, i) for d, t, s, i in series if i and i > 0]
        if len(usable) < 5:
            print(f"  {tag}: 法人日不足")
            continue
        first_lu = min(r["date"] for r in rows)
        before = [(d, t, s, i) for d, t, s, i in usable if d < first_lu and s is not None]
        at = [(d, t, s, i) for d, t, s, i in usable if d == first_lu and s is not None]
        pre5 = before[-5:] if before else []
        start = pre5[0][2] if pre5 else (before[0][2] if before else None)
        pre_last = pre5[-1][2] if pre5 else start
        at_share = at[0][2] if at else None
        last5 = [x[2] for x in usable[-5:] if x[2] is not None]
        up = (last5[-1] - last5[0]) if len(last5) >= 2 else None
        if up is not None and up > 0.05:
            rising_n += 1
        elif up is not None and up < -0.05:
            falling_n += 1
        if start is not None:
            share_starts.append(start)
        path = " → ".join(f"{s:.2f}%" for _, _, s, _ in usable[-6:] if s is not None)
        print(
            f"  {tag:16} 首漲停 {first_lu} 家數 {len(rows):2} "
            f"起點 {start if start is not None else float('nan'):.2f}% "
            f"漲停前 {pre_last if pre_last is not None else float('nan'):.2f}% "
            f"當日 {at_share if at_share is not None else float('nan'):.2f}% "
            f"近5日Δ {up if up is not None else float('nan'):+.2f}pt | {path}"
        )

    print(
        f"\n佔比起點（漲停≥3細項、漲停前）：n={len(share_starts)} "
        f"中位 {median(share_starts) if share_starts else float('nan'):.2f}% "
        f"最小 {min(share_starts) if share_starts else float('nan'):.2f}% "
        f"最大 {max(share_starts) if share_starts else float('nan'):.2f}%"
    )
    print(f"近5日佔比升 {rising_n} 降 {falling_n}")

    print("\n=== 同細項：龍頭(近20日成交金額前1–2) vs 次級 誰先漲停 ===")
    first_lag = first_lead = mixed = no_lead = 0
    spread_lag_then_lead = 0
    spread_lead_then_lag = 0
    only_lag = only_lead = 0
    examples = []
    for tag, rows, days in clustered:
        sids = members.get(tag) or list({r["sid"] for r in rows})
        leads = set(turnover_leaders(conn, sids, cap))
        if not leads:
            no_lead += 1
            continue
        lu_sids = {r["sid"] for r in rows}
        first = min(rows, key=lambda r: (r["date"], -r["pct"]))
        first_is_lead = first["sid"] in leads
        later_leads = [r for r in rows if r["sid"] in leads and r["date"] > first["date"]]
        later_lags = [r for r in rows if r["sid"] not in leads and r["date"] > first["date"]]
        has_lead_lu = bool(lu_sids & leads)
        has_lag_lu = bool(lu_sids - leads)
        if first_is_lead:
            first_lead += 1
            if later_lags:
                spread_lead_then_lag += 1
            elif not has_lag_lu:
                only_lead += 1
        else:
            first_lag += 1
            if later_leads:
                spread_lag_then_lead += 1
            elif not has_lead_lu:
                only_lag += 1
        examples.append(
            (
                tag,
                first["date"],
                first["sid"],
                first["name"],
                "龍頭" if first_is_lead else "次級",
                ",".join(leads),
                has_lead_lu,
                has_lag_lu,
            )
        )

    print(f"  細項簇 {len(clustered)}  先次級 {first_lag} 先端龍 {first_lead} 無龍頭定義 {no_lead}")
    print(f"  次級先漲停後龍頭也漲停 {spread_lag_then_lead}")
    print(f"  龍頭先漲停後次級也漲停 {spread_lead_then_lag}")
    print(f"  只有次級漲停 {only_lag}  只有龍頭漲停 {only_lead}")
    print("  例（細項 首漲停日 代號 名 角色 龍頭代號 簇內有龍頭漲停 簇內有次級漲停）")
    for ex in examples[:20]:
        print("   ", ex)

    # 封測 / 矽格 欣銓 路徑（即使 9/17 漲停不在庫）
    print("\n=== 封測細項 近窗佔比（對早上矽格／欣銓）===")
    test_sids = members.get("電子上游-IC-封測") or members.get("封測") or []
    print("封測成員", len(test_sids))
    th = fine_three(conn, test_sids, flow_days)
    for d in flow_days[-12:]:
        inn = mkt.get(d) or 0
        three = th.get(d) or 0
        share = 100.0 * three / inn if inn > 0 and three > 0 else (0.0 if inn > 0 else float("nan"))
        print(f"  {d} three={three:7d} mkt_in={inn:8d} share={share:6.2f}%")
    for sid in ("6257", "3264", "6515", "6223"):
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), close, pct_change, volume,
                   IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0)
            FROM daily_quotes WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')>=?
            ORDER BY 1
            """,
            (sid, flow_days[0]),
        ).fetchall()
        print(sid, [(r[0], r[1], r[2], r[4]) for r in rows[-8:]])

    # 沒漲停簇的細項：佔比升最多但還沒爆漲停 → 準備進場
    print("\n=== 準備資金：近5個有法人日佔比升最多的三層細項鏈（漲停檔<3）===")
    usable_days = [d for d in flow_days if (mkt.get(d) or 0) > 0]
    last5 = usable_days[-5:]
    scored = []
    chains = {"-".join(p) for p in fine.values() if len(p) >= 3}
    for tag in chains:
        sids = list({x for x in (members.get(tag) or [])})
        if len(sids) < 3:
            continue
        th = fine_three(conn, sids, last5)
        shares = []
        for d in last5:
            inn = mkt.get(d) or 0
            three = th.get(d) or 0
            if inn <= 0:
                continue
            shares.append(100.0 * three / inn if three > 0 else 0.0)
        if len(shares) < 3:
            continue
        up = shares[-1] - shares[0]
        lu_n = len({r["sid"] for r in (by_cluster.get(tag) or [])})
        scored.append((up, shares[-1], shares[0], lu_n, tag, len(sids)))
    scored.sort(reverse=True)
    for row in scored[:15]:
        print(
            f"  Δ{row[0]:+6.2f}pt  今 {row[1]:5.2f}%  起 {row[2]:5.2f}%  漲停家 {row[3]:2}  n={row[5]:3}  {row[4]}"
        )


if __name__ == "__main__":
    main()
