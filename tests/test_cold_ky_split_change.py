# -*- coding: utf-8 -*-
"""冷門／KY／分割：收盤漲跌必須跟官方 pct_change。錯一檔再加抽十檔。"""
from __future__ import annotations

import sqlite3

import pytest

from config import get_db_path
from wayne_navigator import NavigatorEngine

pytestmark = pytest.mark.production_db

EXTRA_PER_FAIL = 10
BASE_TW = 30
BASE_TWO = 30
BASE_KY = 20


def _conn():
    return sqlite3.connect(f"file:{get_db_path()}?mode=ro", uri=True)


def _latest_ymd(conn) -> str:
    row = conn.execute(
        "SELECT MAX(replace(date,'-','')) FROM daily_quotes WHERE close > 0"
    ).fetchone()
    return str(row[0] or "")


def _ids(conn, sql: str, params: tuple) -> list[str]:
    return [str(r[0]) for r in conn.execute(sql, params) if r and r[0]]


def _pools(conn, ymd: str) -> dict[str, list[str]]:
    cold = """
        SELECT q.stock_id FROM daily_quotes q
        JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','')=? AND u.asset_type='STOCK'
          AND u.market_type=? AND q.close > 0
        ORDER BY COALESCE(q.volume, 0) ASC, q.stock_id
    """
    ky = """
        SELECT q.stock_id FROM daily_quotes q
        JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','')=? AND q.close > 0
          AND (u.asset_type='KY' OR q.stock_name LIKE '%-KY%')
        ORDER BY COALESCE(q.volume, 0) ASC, q.stock_id
    """
    split = """
        SELECT DISTINCT e.stock_id FROM ex_rights e
        JOIN daily_quotes q ON q.stock_id = e.stock_id AND replace(q.date,'-','')=?
        WHERE e.kind='分割' AND q.close > 0
        ORDER BY e.stock_id
    """
    return {
        "TW": _ids(conn, cold, (ymd, "TW")),
        "TWO": _ids(conn, cold, (ymd, "TWO")),
        "KY": _ids(conn, ky, (ymd,)),
        "SPLIT": _ids(conn, split, (ymd,)),
    }


def test_card_change_matches_official_expand_on_fail():
    """上市／上櫃冷門、KY、分割同一套：決策卡漲跌＝庫內官方 pct。錯一檔＋10。"""
    conn = _conn()
    try:
        ymd = _latest_ymd(conn)
        assert len(ymd) == 8
        pools = _pools(conn, ymd)
        stored = {
            str(sid): float(pct or 0)
            for sid, pct in conn.execute(
                """
                SELECT stock_id, pct_change FROM daily_quotes
                WHERE replace(date,'-','')=?
                """,
                (ymd,),
            )
        }
    finally:
        conn.close()

    queue: list[str] = []
    for key, n in (("TW", BASE_TW), ("TWO", BASE_TWO), ("KY", BASE_KY)):
        queue.extend(pools[key][:n])
    queue.extend(pools["SPLIT"])
    # 真機已對過、官方漲跌對不上的兩檔一定進抽樣
    for sid in ("1423", "3523"):
        if sid in stored:
            queue.append(sid)

    engine = NavigatorEngine(get_db_path())
    seen: set[str] = set()
    fails: list[str] = []
    extras = {k: n for k, n in (("TW", BASE_TW), ("TWO", BASE_TWO), ("KY", BASE_KY))}

    def take_more(bucket: str, n: int) -> None:
        start = extras[bucket]
        more = pools[bucket][start : start + n]
        extras[bucket] = start + n
        queue.extend(more)

    while queue:
        sid = queue.pop(0)
        if sid in seen or sid not in stored:
            continue
        seen.add(sid)
        card = engine.get_decision_card(sid, merge_live=False)
        if card.get("error"):
            fails.append(f"{sid} error={card.get('error')}")
            take_more("TW", EXTRA_PER_FAIL)
            take_more("TWO", EXTRA_PER_FAIL)
            continue
        got = round(float(card.get("change_pct") or 0), 2)
        want = round(float(stored[sid] or 0), 2)
        if abs(got - want) > 0.011:
            fails.append(f"{sid} card={got} official={want}")
            take_more("TW", EXTRA_PER_FAIL)
            take_more("TWO", EXTRA_PER_FAIL)
            take_more("KY", EXTRA_PER_FAIL)

    assert not fails, (
        f"{len(fails)} 檔漲跌不符（已抽 {len(seen)} 檔，錯一檔加十檔）："
        + "; ".join(fails[:12])
    )
    assert len(seen) >= BASE_TW + BASE_TWO


def _table_ymd(card: dict) -> list[str]:
    table = card.get("table")
    if table is None or getattr(table, "empty", True):
        return []
    return [str(d).replace("-", "")[:8] for d in table["date"].tolist()]


def test_5276_card_table_keeps_sep2_and_sep3_when_in_db():
    """達輝-KY：庫內有 9/2、9/3 時，20 日表不能再跳過這兩天。"""
    conn = _conn()
    try:
        have = {
            str(r[0])
            for r in conn.execute(
                """
                SELECT replace(date,'-','') FROM daily_quotes
                WHERE stock_id='5276' AND replace(date,'-','') IN ('20260902','20260903')
                """
            )
        }
    finally:
        conn.close()
    if not have:
        pytest.skip("庫內尚無達輝-KY 20260902／20260903")
    card = NavigatorEngine(get_db_path()).get_decision_card("5276", merge_live=False)
    assert not card.get("error"), card.get("error")
    dates = _table_ymd(card)
    for d in sorted(have):
        assert d in dates, f"決策卡 20 日表缺 {d}，現有 {dates[:8]}"
