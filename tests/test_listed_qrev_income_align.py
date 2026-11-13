# -*- coding: utf-8 -*-
"""上市介紹卡：季營收必須與毛利／EPS 同綜合損益口徑。"""
from __future__ import annotations

import sqlite3

from fundamentals import ensure_fundamentals_tables, format_yi, glance_fundamentals_plain
from wayne_db import ensure_core_schema


def _seed_2383_mismatch(db: str) -> None:
    """月只種 Q3 三個月（加總會偏短），損益表種前三季累計——舊碼會把兩者混標。"""
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("2383", "台光電", "TWSE", "STOCK", "PCB", "2026-11-13"),
    )
    for ym, rev in (
        ("202607", 19206698.0),
        ("202608", 20145589.0),
        ("202609", 21532230.0),
    ):
        conn.execute(
            "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("2383", ym, "台光電", "TW", "PCB", rev, 5.0, 100.0, 90.0),
        )
    # 綜合損益 season=3＝前三季累計（千元）
    conn.execute(
        "INSERT INTO quarterly_income(stock_id,year,season,stock_name,market,revenue,cogs,"
        "gross_profit,gross_margin_pct,operating_income,net_income,eps) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "2383",
            2026,
            3,
            "台光電",
            "TW",
            141226994.0,
            92544063.0,
            48682931.0,
            34.47,
            38548717.0,
            29709539.0,
            82.92,
        ),
    )
    conn.commit()
    conn.close()


def test_listed_qrev_uses_income_not_short_monthly(tmp_path, monkeypatch):
    db = str(tmp_path / "2383.db")
    _seed_2383_mismatch(db)
    monkeypatch.setattr("fundamentals.ensure_stock_fundamentals", lambda *a, **k: {})
    monkeypatch.setattr("fundamentals.glance_fund_split_layout", lambda *a, **k: None)
    plain = glance_fundamentals_plain("2383", db)
    by = {a: b for a, b in plain}
    assert "季營收" in by
    # 必須是損益表 1412.27億，不准月彙 608.85
    assert format_yi(141226994.0) in by["季營收"]
    assert "608.85" not in by["季營收"]
    assert "前三季" in by["季營收"]
    assert by.get("毛利") == format_yi(48682931.0)
    assert "34.5%" in (by.get("毛利率") or "")
    assert by.get("EPS") == "82.92"
    # 不准再多一列「季報（綜合損益）」空殼
    assert "季報" not in by
    # 毛利／營收同口徑：毛利率 ≈ 毛利÷營收
    assert abs(48682931.0 / 141226994.0 * 100.0 - 34.47) < 0.05


def test_monthly_only_quarter_label_is_single_season(tmp_path, monkeypatch):
    """無損益表時，月彙季只能標『第N季合計』，不准『前三季』。"""
    db = str(tmp_path / "m.db")
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("9999", "測股", "TWSE", "STOCK", "測", "2026-11-13"),
    )
    for ym, rev in (
        ("202607", 100000.0),
        ("202608", 110000.0),
        ("202609", 120000.0),
    ):
        conn.execute(
            "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue) "
            "VALUES (?,?,?,?,?,?)",
            ("9999", ym, "測股", "TW", "測", rev),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr("fundamentals.ensure_stock_fundamentals", lambda *a, **k: {})
    monkeypatch.setattr("fundamentals.glance_fund_split_layout", lambda *a, **k: None)
    plain = glance_fundamentals_plain("9999", db)
    qrev = " ".join(b for a, b in plain if a.startswith("季營收"))
    assert "第3季合計" in qrev
    assert "前三季" not in qrev
