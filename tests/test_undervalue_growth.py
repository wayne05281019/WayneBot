# -*- coding: utf-8 -*-
"""真成長低估鐵律：毛利／循環黑名單／本業比／PE 封頂／三段卡。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from wayne_db import ensure_core_schema, init_database


def test_cyclical_and_gross_gates():
    from undervalue_growth import (
        capped_peer_median,
        format_core_ratio,
        growth_gate,
        industry_bucket,
        is_cyclical_trap,
        is_hard_excluded,
        passes_gross_margin,
        price_targets,
        resolve_industry_label,
    )

    assert is_cyclical_trap("石化-原物料", [], "和桐")
    assert is_cyclical_trap("航運-散裝", [], "慧洋")
    assert is_cyclical_trap("營建-建設", [], "興富發")
    assert not is_cyclical_trap("電子中游-光通訊", ["光通訊"], "光聖")
    # D3：DRAM／通路進濾網；成熟晶圓代工仍不進
    assert not is_cyclical_trap("電子上游-IC-代工", ["成熟製程"], "力積電")
    assert is_cyclical_trap("電子上游-記憶體IC設計", ["DRAM"], "晶豪科")
    assert is_cyclical_trap("電子上游-記憶體", ["標準型記憶體"], "南亞科")
    assert is_cyclical_trap("電子上游-IC-通路", ["通路"], "方土昶")
    assert is_hard_excluded("3006") and is_hard_excluded("6265")
    assert not is_hard_excluded("6442")
    assert resolve_industry_label("8069", ["TFT面板"], "電子中游-LCD-TFT面板") == "電子紙"
    assert format_core_ratio(123.4) == "純本業"
    assert format_core_ratio(94.0) == "94%"

    # 今年／明年目標不准靜默相同
    tg = price_targets(100.0, 20.0, 10.0, 12.5, 20.0, 16.0)
    # 10*20=200；12.5*16=200 → 應上修明年
    assert abs(tg["fair_year"] - 200.0) < 1e-6
    assert tg["target_next"] > tg["fair_year"] + 1.0

    assert passes_gross_margin(20.0)
    assert not passes_gross_margin(19.9)
    assert passes_gross_margin(
        12.5, yoy_pct=120, bucket="ai_server_oem", gm_prev=11.0
    )
    assert not passes_gross_margin(
        12.5, yoy_pct=50, bucket="ai_server_oem", gm_prev=11.0
    )

    ok, why = growth_gate(
        chain="電子中游-通訊設備-光通訊",
        tags=["光通訊"],
        name="光聖",
        gm=59.0,
        gm_prev=50.0,
        op=100,
        net=110,
        yoy_pct=80,
        bucket="optical",
    )
    assert ok and why == ""

    ok2, why2 = growth_gate(
        chain="石化",
        tags=[],
        name="和桐",
        gm=30,
        gm_prev=28,
        op=100,
        net=110,
        yoy_pct=20,
        bucket="default",
    )
    assert not ok2 and "黑名單" in why2

    assert industry_bucket("光通訊", ["CPO"], "光聖") == "optical"
    assert industry_bucket("電子上游-記憶體IC設計", ["DRAM"], "晶豪科") == "cyclical"
    assert industry_bucket("電子上游-IC-代工", ["成熟製程"], "力積電") == "default"
    assert industry_bucket("航運", [], "華航") == "cyclical"
    # 爆表也不用產業表冒充；有中位就回中位
    assert capped_peer_median(62.5, "optical") == 62.5
    assert capped_peer_median(20.0, "optical") == 20.0
    assert capped_peer_median(None, "optical") is None

    from undervalue_growth import select_fair_pe_pair

    # 有同業中位→市場共識；明年按產業表比例略縮
    y, n, disp = select_fair_pe_pair(13.2, "default")
    assert abs(y - 13.2) < 1e-9
    assert abs(disp - 13.2) < 1e-9
    assert n < y  # 明年倍數略低
    y2, n2, disp2 = select_fair_pe_pair(62.5, "optical")
    assert abs(y2 - 62.5) < 1e-9
    assert abs(disp2 - 62.5) < 1e-9
    assert n2 < y2
    # 缺同業中位→不編造（不准產業表冒充共識）
    y3, n3, d3 = select_fair_pe_pair(None, "cyclical")
    assert (y3, n3, d3) == (None, None, None)
    y4, n4, d4 = select_fair_pe_pair(None, "default")
    assert (y4, n4, d4) == (None, None, None)


def test_chip_capsule_from_daily_quotes_nets():
    from undervalue_growth import _streak_from_nets

    both = _streak_from_nets([(100, 50), (80, 40), (-10, 20)])
    assert both["capsule"] == "外投同買"
    sell = _streak_from_nets([(-20, -10), (-5, -1)])
    assert sell["capsule"] == "外投同賣"
    trust = _streak_from_nets([(0, 30), (-5, 20), (10, 15)])
    assert trust["capsule"].startswith("投信連買")
    adj = _streak_from_nets([(-10, 20), (0, 0)])
    assert adj["capsule"] == "投信買・外資調節"


def test_growth_card_renders_zones(tmp_path):
    import pytest
    from PIL import Image

    from undervalue_card import BASE_H, BASE_W, render_undervalue_png
    from undervalue_card_html import playwright_available

    if not playwright_available():
        pytest.skip("無 Playwright")

    rows = [
        {
            "mark": "star",
            "stock_id": "6442",
            "name": "光聖",
            "industry": "光通訊",
            "close": 1045,
            "pe": 20,
            "gross_margin": 59.3,
            "core_ratio_pct": 94,
            "yoy_pct": 83,
            "eps_earned": 34.9,
            "eps_2026": 52,
            "eps_2027": 68,
            "fair_year": 1300,
            "target_next": 1625,
            "ups_fair_pct": 24,
            "ups_tgt_pct": 55,
            "rev_threshold_yi": 20.5,
            "rev_oct_yi": 18,
            "support": 1045,
            "resistance": 1210,
            "tech_status": "站回支撐區",
            "chip_note": "外投同買",
        },
        {
            "mark": "watch",
            "stock_id": "2383",
            "name": "台光電",
            "industry": "CCL",
            "close": 3795,
            "pe": 18,
            "gross_margin": 37.7,
            "core_ratio_pct": 92,
            "yoy_pct": 203,
            "fair_year": 4800,
            "target_next": 6120,
            "ups_fair_pct": 26,
            "ups_tgt_pct": 61,
            "rev_threshold_yi": 95,
            "rev_oct_yi": 80,
            "support": 4160,
            "resistance": 5200,
            "tech_broken": True,
            "tech_status": "跌破大量區撐 4160",
        },
        {
            "mark": "emerging",
            "stock_id": "3595",
            "name": "山太士",
            "industry": "興櫃",
            "close": 580,
            "pe": 25,
            "gross_margin": 77.4,
            "core_ratio_pct": 90,
            "yoy_pct": 40,
            "fair_year": 700,
            "target_next": 900,
            "ups_fair_pct": 20,
            "ups_tgt_pct": 55,
            "rev_threshold_yi": 1.5,
            "rev_oct_yi": 1.2,
            "tech_status": "60日均量過小",
            "chip_note": "興櫃無法人",
        },
    ]
    out = str(tmp_path / "uv_growth.png")
    assert Path(render_undervalue_png(rows, out, as_of="20261116")).is_file()
    im = Image.open(out)
    assert im.size == (BASE_W, BASE_H)
    assert Path(out).stat().st_size > 12000


def test_scan_rejects_cyclical_seed(tmp_path, monkeypatch):
    from undervalue_scan import RULE_PHONE, run_undervalue_scan

    db = str(tmp_path / "uv_cyc.db")
    init_database(db)
    ensure_core_schema(db)
    try:
        from industry_fine import ensure_fine_industry_table

        ensure_fine_industry_table(db)
    except Exception:
        pass
    try:
        from fundamentals import ensure_fundamentals_tables

        ensure_fundamentals_tables(db)
    except Exception:
        pass
    as_of = "20261113"
    conn = sqlite3.connect(db)
    try:
        for sid, name, chain, tags, pe in (
            ("6442", "光聖", "電子中游-通訊設備-光通訊", '["光通訊"]', 18.0),
            ("1714", "和桐", "石化-原物料", '["石化"]', 8.0),
            ("3081", "聯亞", "電子中游-通訊設備-光通訊", '["光通訊"]', 60.0),
            ("2455", "全新", "電子中游-通訊設備-光通訊", '["光通訊"]', 55.0),
            ("3105", "穩懋", "電子中游-通訊設備-光通訊", '["光通訊"]', 50.0),
        ):
            conn.execute(
                "INSERT OR REPLACE INTO stock_universe "
                "(stock_id, stock_name, market_type, is_active, asset_type, updated_at) "
                "VALUES (?, ?, 'TW', 1, 'STOCK', ?)",
                (sid, name, as_of),
            )
            conn.execute(
                "INSERT OR REPLACE INTO stock_fine_industry "
                "(stock_id, chain, tags_json, source, fetched_at) "
                "VALUES (?, ?, ?, 'test', ?)",
                (sid, chain, tags, as_of),
            )
            for i in range(13):
                d = as_of if i == 12 else (f"202610{i+1:02d}" if i >= 9 else f"2026100{i+1}")
                pe_i = pe if i == 12 else pe + (12 - i)
                conn.execute(
                    "INSERT OR REPLACE INTO daily_valuation "
                    "(stock_id, date, pe, pb, dividend_yield, source, updated_at) "
                    "VALUES (?, ?, ?, 1.0, 0, 'test', ?)",
                    (sid, d, pe_i, as_of),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO daily_quotes "
                    "(date, stock_id, stock_name, market, open, high, low, close, "
                    "volume, turnover_k, pct_change, avg_price) "
                    "VALUES (?, ?, ?, 'TW', 100, 110, 95, 100, 5000, 0, 0, 100)",
                    (d, sid, name),
                )
            for mm, rev, mom, ytd in (
                ("202608", 900, 3.0, 7000),
                ("202609", 950, 5.0, 7950),
                ("202610", 1000, 5.0, 9000),
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO monthly_revenue "
                    "(stock_id, yyyymm, stock_name, market, industry, revenue, "
                    "revenue_prev_month, revenue_prev_year, mom_pct, yoy_pct, "
                    "ytd_revenue, ytd_prev_year, ytd_yoy_pct, published_roc, updated_at) "
                    "VALUES (?, ?, ?, 'TW', '', ?, 900, 800, ?, 25.0, ?, 7000, 20.0, '', ?)",
                    (sid, mm, name, rev, mom, ytd, as_of),
                )
            for season, gm, op, net, eps, rev_q in (
                (1, 40.0, 200, 220, 2.0, 3000),
                (2, 42.0, 420, 450, 4.2, 6200),
                (3, 45.0, 700, 750, 6.5, 9500),
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO quarterly_income "
                    "(stock_id, year, season, stock_name, market, revenue, cogs, "
                    "gross_profit, gross_margin_pct, operating_income, net_income, "
                    "eps, published_roc, updated_at) "
                    "VALUES (?, 2026, ?, ?, 'TW', ?, 0, 0, ?, ?, ?, ?, '', ?)",
                    (sid, season, name, rev_q, gm, op, net, eps, as_of),
                )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("undervalue_scan._leader_ids", lambda *_a, **_k: {"6442"})
    monkeypatch.setattr(
        "undervalue_scan._peer_index",
        lambda _db: {
            "6442": ["6442", "3081", "2455", "3105"],
            "1714": ["1714", "3081", "2455", "3105"],
            "3081": ["6442", "3081", "2455", "3105"],
            "2455": ["6442", "3081", "2455", "3105"],
            "3105": ["6442", "3081", "2455", "3105"],
        },
    )
    out = run_undervalue_scan(db, as_of, rule_key=RULE_PHONE)
    assert out["ok"]
    ids = {r["stock_id"] for r in out["rows"]}
    assert "1714" not in ids
    assert "6442" in ids
    row = next(r for r in out["rows"] if r["stock_id"] == "6442")
    assert row.get("fair_year") is not None
    assert row.get("target_next") is not None
    # 合理 PE＝同業市場成交中位（≈52.5），不准再用產業表 26 冒充
    assert abs(float(row["peer_pe_median"]) - 52.5) < 1e-6
    assert abs(float(row["pe_year"]) - 52.5) < 1e-6
    detail = row.get("detail") or {}
    if detail.get("pe_year") is not None:
        assert abs(float(detail["pe_year"]) - 52.5) < 1e-6


def test_eps_year_uses_ytd_cum_not_q3_times_three():
    """全年估＝前三季官方累計＋Q4；世芯 11/18 曾誤成 Q3×3＋Q4＝155。"""
    from undervalue_growth import estimate_eps_year_next

    out = estimate_eps_year_next(
        eps_ytd_cum=75.94,
        eps_q3_single=38.37,
        last_season=3,
        ytd_rev=1_000_000.0,
        last_rev=100_000.0,
        moms=[0.0, 0.0, 0.0],
        m_last=10,
        yoy_pct=20.0,
    )
    assert out["ok"]
    assert abs(out["eps_2026"] - (75.94 + 38.37)) < 0.01
    assert out["eps_2026"] < 75.94 + 38.37 * 1.2
    assert "Q1–Q3" in out["method"]


def test_eps_year_projects_remaining_quarters_from_q2():
    """只公布到 Q2：累計＋Q3＋Q4（末季×(1+g/2) 兩步），一月前也能估。"""
    from undervalue_growth import estimate_eps_year_next

    out = estimate_eps_year_next(
        eps_ytd_cum=10.0,
        eps_q_last_single=4.0,
        last_season=2,
        ytd_rev=600_000.0,
        last_rev=100_000.0,
        moms=[0.0, 0.0, 0.0],
        m_last=6,
        yoy_pct=10.0,
    )
    assert out["ok"]
    # g=0 → Q3=4、Q4=4；全年=10+4+4=18
    assert abs(out["eps_2026"] - 18.0) < 0.01
    assert "剩餘2季" in out["method"]


def test_eps_year_before_q1_uses_prior_year():
    """尚無今年季報（一月）：去年全年×YoY夾限；月營收仍停在去年。"""
    from undervalue_growth import estimate_eps_year_next

    out = estimate_eps_year_next(
        eps_ytd_cum=None,
        last_season=0,
        prior_year_eps=20.0,
        ytd_rev=1_200_000.0,
        last_rev=100_000.0,
        moms=[0.0, 0.0, 0.0],
        m_last=12,
        yoy_pct=10.0,
        rev_year_matches=False,
    )
    assert out["ok"]
    assert abs(out["eps_2026"] - 22.0) < 0.01
    assert "去年全年" in out["method"]
