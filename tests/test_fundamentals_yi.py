# -*- coding: utf-8 -*-
"""營收／MoM／YoY 改以億元顯示。"""
from __future__ import annotations

import sqlite3

from fundamentals import format_fundamentals_html, format_yi, glance_fundamentals_plain


def test_format_yi_converts_thousand_to_yi():
    # 1,146,434 千元 = 11.46434 億 → 11.46億元
    assert format_yi(1_146_434) == "11.46億元"
    assert format_yi(331_139) == "3.31億元"
    assert format_yi(50_000, signed=True) == "+0.50億元"
    assert format_yi(-12_500, signed=True, unit=False) == "-0.12億"


def test_format_fundamentals_html_uses_yi_not_mom_yoy_pct(tmp_path):
    db = str(tmp_path / "f.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE monthly_revenue (
            stock_id TEXT, yyyymm TEXT, stock_name TEXT, market TEXT, industry TEXT,
            revenue REAL, revenue_prev_month REAL, revenue_prev_year REAL,
            mom_pct REAL, yoy_pct REAL, ytd_revenue REAL, ytd_prev_year REAL, ytd_yoy_pct REAL,
            synced_at TEXT DEFAULT ''
        );
        CREATE TABLE quarterly_income (
            stock_id TEXT, year INTEGER, season INTEGER, stock_name TEXT, market TEXT,
            revenue REAL, gross_profit REAL, gross_margin_pct REAL,
            operating_income REAL, net_income REAL, eps REAL, synced_at TEXT DEFAULT ''
        );
        """
    )
    conn.execute(
        """
        INSERT INTO monthly_revenue VALUES
        ('2330','202607','台積電','TW','',1146434,893000,1030000,28.4,11.2,7000000,7600000,-7.9,'')
        """
    )
    conn.execute(
        """
        INSERT INTO quarterly_income VALUES
        ('2330',2026,2,'台積電','TW',1146434,331139,28.9,300000,250000,5.5,'')
        """
    )
    conn.commit()
    conn.close()

    html = format_fundamentals_html("2330", db)
    assert "11.46億元" in html
    assert "3.31億元" in html
    assert "較上月" in html
    assert "較去年同月" in html
    assert "較去年累計" in html
    assert "千元" not in html
    assert "MoM" not in html
    assert "YoY" not in html

    plain = glance_fundamentals_plain("2330", db)
    blob = " ".join(f"{a} {b}" for a, b in plain)
    assert "11.46億元" in blob
    assert "較上月" in blob
    assert "EPS" in blob
    assert "毛利／EPS" not in blob
    assert "MoM" not in blob
    assert "YoY" not in blob
