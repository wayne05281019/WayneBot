# -*- coding: utf-8 -*-
"""近 n 季 EPS 精確窗：上半年累計＝近2季；只認以最新季收尾的窗；比價同一把尺。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from fundamentals import recent_eps_windows
from industry_brief import _recent_eps_sum, attach_price_eps_bijia, has_positive_eps
from wayne_db import ensure_core_schema


def _rows(*items):
    return [{"year": y, "season": s, "eps": e} for y, s, e in items]


def test_h1_only_is_exact_two_quarter_sum():
    """2330 庫內只有 2026 上半年累計 49.33 → 近2季＝49.33；拆不出單季就沒有近1季。"""
    w = recent_eps_windows(_rows((2026, 2, 49.33)))
    assert set(w) == {2}
    assert abs(w[2]["eps_sum"] - 49.33) < 1e-9
    assert w[2]["eps_seasons"] == ["2026Q2", "2026Q1"]


def test_q2_q3_without_q1_only_last_quarter():
    w = recent_eps_windows(_rows((2026, 2, 2.0), (2026, 3, 3.0)))
    assert set(w) == {1}
    assert abs(w[1]["eps_sum"] - 1.0) < 1e-9
    assert w[1]["eps_seasons"] == ["2026Q3"]


def test_full_year_rows_give_both_windows():
    w = recent_eps_windows(_rows((2026, 1, 1.27), (2026, 2, 3.02), (2026, 3, 5.99)))
    assert abs(w[1]["eps_sum"] - 2.97) < 1e-9
    assert abs(w[2]["eps_sum"] - 4.72) < 1e-9


def test_cross_year_window_uses_prior_full_year_minus_q3():
    w = recent_eps_windows(_rows((2026, 3, 5.99), (2026, 4, 8.00), (2027, 1, 1.10)))
    assert abs(w[1]["eps_sum"] - 1.10) < 1e-9
    assert abs(w[2]["eps_sum"] - (1.10 + 8.00 - 5.99)) < 1e-9
    assert w[2]["eps_seasons"] == ["2027Q1", "2026Q4"]


def test_orphan_q3_and_stale_quarters_not_used():
    assert recent_eps_windows(_rows((2026, 3, 5.99))) == {}
    # 最新是 2026 上半年；不准拿 2025 的季湊近1季
    w = recent_eps_windows(_rows((2025, 1, 1.0), (2025, 2, 2.0), (2026, 2, 3.0)))
    assert set(w) == {2}
    assert abs(w[2]["eps_sum"] - 3.0) < 1e-9


def _seed(db: str, stocks) -> None:
    ensure_core_schema(db)
    from fundamentals import ensure_fundamentals_tables

    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stock_fine_industry (stock_id TEXT PRIMARY KEY, "
        "chain TEXT NOT NULL, tags_json TEXT NOT NULL, cat_id TEXT DEFAULT '', "
        "source TEXT DEFAULT '', fetched_at TEXT NOT NULL)"
    )
    for sid, name, close, incomes in stocks:
        conn.execute(
            "INSERT OR REPLACE INTO stock_universe"
            "(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (sid, name, "TW", "STOCK", "半導體業", now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes"
            "(date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
            "VALUES (?,?,?,'TW',100,101,99,?,1000,100000,1.0,?,0,0,0)",
            ("20261113", sid, name, close, close),
        )
        for y, s, eps in incomes:
            conn.execute(
                "INSERT OR REPLACE INTO quarterly_income"
                "(stock_id,year,season,stock_name,market,revenue,eps) VALUES (?,?,?,?,?,?,?)",
                (sid, y, s, name, "TW", 1e6 * s, eps),
            )
        conn.execute(
            "INSERT OR REPLACE INTO stock_fine_industry"
            "(stock_id,chain,tags_json,cat_id,source,fetched_at) VALUES (?,?,?,?,?,?)",
            (sid, "測試鏈", json.dumps(["測試鏈"], ensure_ascii=False), "", "test", now),
        )
    conn.commit()
    conn.close()


def test_has_positive_eps_keeps_h1_only_stock(tmp_path):
    db = str(tmp_path / "h1.db")
    _seed(db, [("2330", "台積電", 1450.0, [(2026, 2, 49.33)])])
    assert has_positive_eps(db, "2330") is True
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rec = _recent_eps_sum(conn, "2330")
    conn.close()
    assert rec["eps_n"] == 2 and abs(rec["eps_sum"] - 49.33) < 1e-9


def _bijia(db: str, sid: str, peer_ids):
    snap = {"stock_id": sid, "fine_chain": "測試鏈", "peer_ids": list(peer_ids)}
    return attach_price_eps_bijia(snap, db)["bijia"]


def test_bijia_never_mixes_one_and_two_quarter_sums(tmp_path):
    db = str(tmp_path / "mix.db")
    stocks = [
        ("3081", "聯亞", 300.0, [(2026, 1, 1.0), (2026, 2, 2.2), (2026, 3, 3.6)]),
        ("2455", "全新", 200.0, [(2026, 2, 2.0)]),  # 只有上半年 → 只有近2季
        ("6442", "光聖", 150.0, [(2026, 2, 2.0), (2026, 3, 3.0)]),  # 只有近1季
        ("4979", "華星光", 90.0, [(2026, 1, 0.5), (2026, 2, 1.2), (2026, 3, 2.0)]),
    ]
    _seed(db, stocks)
    bj = _bijia(db, "3081", [s[0] for s in stocks])
    assert bj["ok"] is True
    # 近1季、近2季各 3 檔可比 → 同數取長窗
    assert bj["eps_label"] == "近2季EPS"
    assert {r["eps_n"] for r in bj["rows"]} == {2}
    ids = {r["stock_id"] for r in bj["rows"]}
    assert ids == {"3081", "2455", "4979"}
    mine = bj["mine"]
    assert abs(mine["eps_sum"] - 2.6) < 1e-9
    assert abs(mine["mult"] - 300.0 / 2.6) < 1e-9

    _seed(db, [("3363", "上詮", 120.0, [(2026, 2, 1.0), (2026, 3, 1.6)])])
    bj1 = _bijia(db, "3081", [s[0] for s in stocks] + ["3363"])
    assert bj1["eps_label"] == "近1季EPS"
    assert {r["eps_n"] for r in bj1["rows"]} == {1}
    assert "2455" not in {r["stock_id"] for r in bj1["rows"]}
    assert abs(bj1["mine"]["eps_sum"] - 1.4) < 1e-9
