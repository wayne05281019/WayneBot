# -*- coding: utf-8 -*-
"""價值三圖：只吃官方欄；營業外可空；虧損／過期本益不上低估。"""
from __future__ import annotations

import os
import sqlite3

from fundamentals import ensure_fundamentals_tables, parse_income_row
from undervalue_scan import (
    _latest_cum_eps_positive,
    _pe_fresh_for_scan,
    run_undervalue_scan,
)
from value_fund_panels import load_value_fund_pack, render_value_fund_panels
from wayne_db import ensure_core_schema, init_database


def _seed_value_db(db: str, *, desk: str = "20261120") -> None:
    init_database(db)
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR REPLACE INTO stock_universe "
            "(stock_id, stock_name, market_type, is_active, asset_type, updated_at) "
            "VALUES ('6416','瑞祺電通','TW',1,'STOCK',?)",
            (desk,),
        )
        con.execute(
            "INSERT OR REPLACE INTO daily_valuation "
            "(stock_id, date, pe, pb, dividend_yield, source, updated_at) "
            "VALUES ('6416',?,16.86,2.22,2.45,'twse_bwibbu',?)",
            (desk, desk),
        )
        con.execute(
            "INSERT OR REPLACE INTO daily_quotes "
            "(date, stock_id, stock_name, market, open, high, low, close, "
            "volume, turnover_k, pct_change, avg_price) "
            "VALUES (?, '6416', '瑞祺電通', 'TW', 100, 101, 99, 114.5, 3000, 0, 0, 114.5)",
            (desk,),
        )
        for season, rev, gm, op, non, net, eps in (
            (1, 1057730, 25.67, 132490, 25900, 99000, 1.35),
            (2, 2391053, 24.84, 274820, 67400, 212946, 2.90),
            (3, 4097464, 24.67, 503785, 24265, 399116, 5.40),
        ):
            con.execute(
                "INSERT OR REPLACE INTO quarterly_income "
                "(stock_id, year, season, stock_name, market, revenue, cogs, "
                "gross_profit, gross_margin_pct, operating_income, non_operating, "
                "net_income, eps, published_roc, updated_at) "
                "VALUES ('6416',2026,?,?, 'TW', ?, 0, 0, ?, ?, ?, ?, ?, '', ?)",
                (season, "瑞祺電通", rev, gm, op, non, net, eps, desk),
            )
        for mm, rev, mom, yoy in (
            ("202608", 548128, 21.45, 109.34),
            ("202609", 707131, 29.01, 59.15),
            ("202610", 567160, -19.79, 126.81),
        ):
            con.execute(
                "INSERT OR REPLACE INTO monthly_revenue "
                "(stock_id, yyyymm, stock_name, market, industry, revenue, "
                "revenue_prev_month, revenue_prev_year, mom_pct, yoy_pct, "
                "ytd_revenue, ytd_prev_year, ytd_yoy_pct, published_roc, updated_at) "
                "VALUES ('6416',?,?, 'TW', '', ?, 0, 0, ?, ?, 0, 0, 0, '', ?)",
                (mm, "瑞祺電通", rev, mom, yoy, desk),
            )
        con.commit()
    finally:
        con.close()


def test_parse_income_keeps_non_operating():
    row = parse_income_row(
        {
            "公司代號": "6416",
            "公司名稱": "瑞祺電通",
            "年度": "115",
            "季別": "3",
            "營業收入": "4097464.00",
            "營業成本": "1",
            "營業毛利（毛損）淨額": "1010670.00",
            "營業利益（損失）": "503785.00",
            "營業外收入及支出": "24265.00",
            "本期淨利（淨損）": "399116.00",
            "基本每股盈餘（元）": "5.40",
            "出表日期": "1151121",
        },
        "TW",
    )
    assert row is not None
    assert abs(float(row["non_operating"]) - 24265.0) < 1e-6
    assert abs(float(row["eps"]) - 5.40) < 1e-6


def test_value_panels_render_6416(tmp_path):
    db = str(tmp_path / "vf.db")
    _seed_value_db(db)
    pack = load_value_fund_pack("6416", db)
    assert pack["ok"] is True
    assert pack["valuation"]["pe"] == 16.86
    assert pack["quarterly"][0]["eps"] == 5.40
    assert "ROE" in pack["omit"]
    out = render_value_fund_panels("6416", db, str(tmp_path / "charts"), uid="t")
    assert out["ok"] is True
    assert len(out["paths"]) == 3
    for p in out["paths"]:
        assert os.path.isfile(p) and os.path.getsize(p) > 1000


def test_undervalue_rejects_stale_pe_and_loss(tmp_path, monkeypatch):
    from undervalue_scan import RULE_PHONE

    db = str(tmp_path / "uv_loss.db")
    init_database(db)
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    as_of = "20261120"
    con = sqlite3.connect(db)
    try:
        for sid, name, pe, pe_day, eps in (
            ("6442", "光聖", 18.0, as_of, 6.5),
            ("3081", "聯亞", 40.0, as_of, 3.0),
            ("2455", "全新", 35.0, as_of, 2.0),
            ("3105", "穩懋", 30.0, as_of, 2.5),
            ("4979", "華星光", 32.0, as_of, 2.2),
            ("3685", "元創精密", None, as_of, -0.14),  # 虧損
            ("5314", "世紀", 4.6, "20261109", 1.0),  # 本益過舊
        ):
            con.execute(
                "INSERT OR REPLACE INTO stock_universe "
                "(stock_id, stock_name, market_type, is_active, asset_type, updated_at) "
                "VALUES (?, ?, 'TW', 1, 'STOCK', ?)",
                (sid, name, as_of),
            )
            if pe is not None:
                for i in range(13):
                    d = f"202610{i+1:02d}" if i < 12 else pe_day
                    if i < 9:
                        d = f"2026100{i+1}"
                    elif i < 12:
                        d = f"202610{i+1}"
                    else:
                        d = pe_day
                    con.execute(
                        "INSERT OR REPLACE INTO daily_valuation "
                        "(stock_id, date, pe, pb, dividend_yield, source, updated_at) "
                        "VALUES (?, ?, ?, 1.0, 0, 'test', ?)",
                        (sid, d, pe, as_of),
                    )
            for j in range(20):
                day = f"202610{j+1:02d}" if j < 9 else (
                    as_of if j == 19 else f"202611{j-8:02d}"
                )
                con.execute(
                    "INSERT OR REPLACE INTO daily_quotes "
                    "(date, stock_id, stock_name, market, open, high, low, close, "
                    "volume, turnover_k, pct_change, avg_price) "
                    "VALUES (?, ?, ?, 'TW', 100, 101, 99, 100, 5000, 0, 0, 100)",
                    (day, sid, name),
                )
            for mm, rev, mom in (
                ("202608", 900, 3.0),
                ("202609", 950, 5.0),
                ("202610", 1000, 5.0),
            ):
                con.execute(
                    "INSERT OR REPLACE INTO monthly_revenue "
                    "(stock_id, yyyymm, stock_name, market, industry, revenue, "
                    "revenue_prev_month, revenue_prev_year, mom_pct, yoy_pct, "
                    "ytd_revenue, ytd_prev_year, ytd_yoy_pct, published_roc, updated_at) "
                    "VALUES (?, ?, ?, 'TW', '', ?, 900, 800, ?, 25.0, "
                    "9000, 7000, 20.0, '', ?)",
                    (sid, mm, name, rev, mom, as_of),
                )
            con.execute(
                "INSERT OR REPLACE INTO quarterly_income "
                "(stock_id, year, season, stock_name, market, revenue, cogs, "
                "gross_profit, gross_margin_pct, operating_income, non_operating, "
                "net_income, eps, published_roc, updated_at) "
                "VALUES (?, 2026, 3, ?, 'TW', 9500, 0, 0, 45.0, 700, 10, 750, ?, '', ?)",
                (sid, name, eps, as_of),
            )
        con.commit()
    finally:
        con.close()

    assert _latest_cum_eps_positive(sqlite3.connect(db), "6442") is True
    assert _latest_cum_eps_positive(sqlite3.connect(db), "3685") is False
    assert _pe_fresh_for_scan("20261120", as_of, "TW") is True
    assert _pe_fresh_for_scan("20261109", as_of, "TW") is False

    monkeypatch.setattr("undervalue_scan._leader_ids", lambda *_a, **_k: {"6442"})
    peers = ["6442", "3081", "2455", "3105", "4979"]
    monkeypatch.setattr(
        "undervalue_scan._peer_index",
        lambda _db: {s: peers for s in peers + ["3685", "5314"]},
    )
    out = run_undervalue_scan(db, as_of, rule_key=RULE_PHONE)
    by = {r["stock_id"]: r for r in out["rows"]}
    assert "3685" not in by
    assert "5314" not in by
