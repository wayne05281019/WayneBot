# -*- coding: utf-8 -*-
"""各產業龍頭／熱門／中等／冷門：決策卡收盤、漲跌、產業對官方。

近日話筒已對過的檔排除，改抽別檔。錯一檔再從同產業加抽十檔。
龍頭＝該產業當日成交額最高；熱門＝次高；中等＝中位數；冷門＝成交量最低。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

import pytest

from config import get_db_path
from universe import card_industry_label
from wayne_navigator import NavigatorEngine

pytestmark = pytest.mark.production_db

# 這幾天話筒／抽樣已確認過，改測別檔
RECENTLY_VERIFIED = frozenset(
    {
        "5276",
        "1341",
        "1423",
        "3523",
        "2383",
        "4915",
        "2845",
        "3703",
        "6177",
        "4127",
        "3078",
        "3290",
        "9958",
        "2324",
        "2330",
        "2454",
        "3105",
    }
)
SKIP_INDUSTRY = frozenset({"ETF", "存託憑證", "未分類"})
EXTRA_PER_FAIL = 10
CLOSE_TOL = 0.011
PCT_TOL = 0.011


def _conn():
    return sqlite3.connect(f"file:{get_db_path()}?mode=ro", uri=True)


def _latest_ymd(conn) -> str:
    row = conn.execute(
        "SELECT MAX(replace(date,'-','')) FROM daily_quotes WHERE close > 0"
    ).fetchone()
    return str(row[0] or "")


def _industry_rows(conn, ymd: str) -> dict[str, list[dict]]:
    rows = conn.execute(
        """
        SELECT u.industry, q.stock_id, q.stock_name, q.close, q.pct_change,
               q.volume, q.turnover_k
        FROM daily_quotes q
        JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','')=? AND q.close > 0 AND length(q.stock_id)=4
          AND u.asset_type IN ('STOCK','KY')
        """,
        (ymd,),
    )
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        ind = (r[0] or "").strip() or "未分類"
        if ind in SKIP_INDUSTRY:
            continue
        by[ind].append(
            {
                "industry": ind,
                "stock_id": str(r[1]),
                "stock_name": str(r[2] or ""),
                "close": float(r[3] or 0),
                "pct_change": float(r[4] or 0),
                "volume": float(r[5] or 0),
                "turnover_k": float(r[6] or 0),
            }
        )
    return by


def pick_industry_tiers(
    stocks: list[dict], *, exclude: frozenset[str] = RECENTLY_VERIFIED
) -> list[tuple[str, dict]]:
    avail = [s for s in stocks if s["stock_id"] not in exclude]
    if not avail:
        return []
    by_to = sorted(avail, key=lambda s: float(s["turnover_k"] or 0), reverse=True)
    by_vol = sorted(
        avail, key=lambda s: (float(s["volume"] or 0), float(s["turnover_k"] or 0))
    )
    picked: list[tuple[str, dict]] = []
    used: set[str] = set()

    def take(label: str, cands: list[dict]) -> None:
        for s in cands:
            if s["stock_id"] in used:
                continue
            used.add(s["stock_id"])
            picked.append((label, s))
            return

    take("龍頭", by_to)
    take("熱門", by_to[1:] if len(by_to) > 1 else by_to)
    mid = by_to[len(by_to) // 2]
    take("中等", [mid] + by_to)
    take("冷門", by_vol)
    return picked


def _same_industry_more(stocks: list[dict], seen: set[str], n: int) -> list[dict]:
    extra = []
    for s in sorted(stocks, key=lambda x: x["stock_id"]):
        if s["stock_id"] in seen or s["stock_id"] in RECENTLY_VERIFIED:
            continue
        extra.append(s)
        if len(extra) >= n:
            break
    return extra


def test_pick_skips_verified_and_fills_four_tiers():
    stocks = [
        {"stock_id": "2330", "turnover_k": 9e9, "volume": 9e5},
        {"stock_id": "AAAA", "turnover_k": 800, "volume": 80},
        {"stock_id": "BBBB", "turnover_k": 400, "volume": 40},
        {"stock_id": "CCCC", "turnover_k": 10, "volume": 1},
        {"stock_id": "DDDD", "turnover_k": 200, "volume": 20},
    ]
    picked = pick_industry_tiers(stocks)
    ids = [s["stock_id"] for _l, s in picked]
    labels = [l for l, _s in picked]
    assert "2330" not in ids
    assert labels == ["龍頭", "熱門", "中等", "冷門"]
    assert ids[0] == "AAAA"
    assert ids[1] == "BBBB"
    assert ids[-1] == "CCCC"


def test_recently_verified_are_not_in_fresh_sample():
    conn = _conn()
    try:
        ymd = _latest_ymd(conn)
        by = _industry_rows(conn, ymd)
    finally:
        conn.close()
    ids = []
    for stocks in by.values():
        for _label, s in pick_industry_tiers(stocks):
            ids.append(s["stock_id"])
    overlap = set(ids) & RECENTLY_VERIFIED
    assert not overlap, f"抽到近日已對檔 {sorted(overlap)}"
    assert "2330" not in ids and "5276" not in ids


def test_industry_tier_cards_match_official_expand_on_fail():
    """各產業四檔：決策卡收盤／漲跌／產業＝庫內官方。錯一檔＋同產業十檔。"""
    conn = _conn()
    try:
        ymd = _latest_ymd(conn)
        assert len(ymd) == 8
        by = _industry_rows(conn, ymd)
    finally:
        conn.close()

    queue: list[tuple[str, str, dict]] = []
    for ind, stocks in by.items():
        for label, s in pick_industry_tiers(stocks):
            queue.append((ind, label, s))
    assert len(queue) >= 80, f"抽樣太少 {len(queue)}"

    engine = NavigatorEngine(get_db_path())
    seen: set[str] = set()
    fails: list[str] = []

    while queue:
        ind, label, s = queue.pop(0)
        sid = s["stock_id"]
        if sid in seen:
            continue
        seen.add(sid)
        card = engine.get_decision_card(sid, merge_live=False)
        if card.get("error"):
            fails.append(f"{sid} {label} {ind} error={card.get('error')}")
            for extra in _same_industry_more(by.get(ind) or [], seen, EXTRA_PER_FAIL):
                queue.append((ind, "加抽", extra))
            continue
        got_c = float(card.get("close") or 0)
        want_c = float(s["close"] or 0)
        got_p = round(float(card.get("change_pct") or 0), 2)
        want_p = round(float(s["pct_change"] or 0), 2)
        card_ind = str(card.get("industry") or "").strip()
        uni_ind = card_industry_label(sid)
        bits = []
        if abs(got_c - want_c) > CLOSE_TOL:
            bits.append(f"close card={got_c} official={want_c}")
        if abs(got_p - want_p) > PCT_TOL:
            bits.append(f"pct card={got_p} official={want_p}")
        if uni_ind and card_ind and card_ind != uni_ind:
            bits.append(f"industry card={card_ind!r} universe={uni_ind!r}")
        if bits:
            fails.append(f"{sid} {s['stock_name']} {label} {ind}: " + "; ".join(bits))
            for extra in _same_industry_more(by.get(ind) or [], seen, EXTRA_PER_FAIL):
                queue.append((ind, "加抽", extra))

    assert not fails, (
        f"{len(fails)} 檔不符（已抽 {len(seen)} 檔，錯一檔加十檔）："
        + "; ".join(fails[:12])
    )
    assert len(seen) >= 80
