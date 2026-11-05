# -*- coding: utf-8 -*-
"""季報 ensure：已有上半年仍要補已開窗的前三季；標籤用累計名。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fundamentals import (
    ensure_fundamentals_tables,
    ensure_stock_fundamentals,
    filing_income_target_season,
    income_row_behind_filing_target,
)
from industry_brief import format_season_zh
from wayne_db import ensure_core_schema


def test_format_season_zh_cumulative_labels():
    assert format_season_zh(2026, 2) == "2026年上半年"
    assert format_season_zh(2026, 3) == "2026年前三季"


def test_filing_target_includes_q3_in_november():
    assert filing_income_target_season("20261105") == (2026, 3)
    assert filing_income_target_season("20260815") == (2026, 2)


def test_h1_row_is_behind_november_target():
    assert income_row_behind_filing_target(
        {"year": 2026, "season": 2}, "20261105"
    )
    assert not income_row_behind_filing_target(
        {"year": 2026, "season": 3}, "20261105"
    )


def test_ensure_refreshes_when_behind(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "f.db")
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("3595", "山太士", "EM", "STOCK", "光電業", "2026-11-05"),
    )
    conn.execute(
        "INSERT INTO quarterly_income("
        "stock_id,year,season,stock_name,market,revenue,cogs,gross_profit,"
        "gross_margin_pct,operating_income,net_income,eps,published_roc,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "3595",
            2026,
            2,
            "山太士",
            "EM",
            332692,
            0,
            222758,
            66.96,
            148986,
            122835,
            3.02,
            "",
            "2026-09-28",
        ),
    )
    # 給月營收一列，避免 ensure 先卡在月營收全抓
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("3595", "202609", "山太士", "EM", "光電業", 93000, 9.7, 1.0, 1.0),
    )
    conn.commit()
    conn.close()

    calls = {"n": 0}

    def _fake_refresh(path, force=False, reason=""):
        calls["n"] += 1
        calls["reason"] = reason
        calls["force"] = bool(force)
        return {"ok": True, "skipped": "test"}

    monkeypatch.setattr("fundamentals.refresh_announced_income", _fake_refresh)
    monkeypatch.setattr(
        "fundamentals.refresh_announced_monthly",
        lambda *a, **k: {"ok": True, "skipped": "test"},
    )
    monkeypatch.setattr(
        "fundamentals.previous_calendar_yyyymm", lambda: "202609"
    )
    monkeypatch.setattr(
        "fundamentals.filing_month_coverage",
        lambda *a, **k: {"thin": False},
    )
    monkeypatch.setattr(
        "fundamentals.stock_month_row",
        lambda *a, **k: {"yyyymm": "202609"},
    )

    out = ensure_stock_fundamentals(db, "3595")
    assert calls["n"] == 1
    assert calls.get("force") is True
    assert "behind=True" in str(calls.get("reason") or "")
    assert out.get("latest_quarter") == "2026Q2"
