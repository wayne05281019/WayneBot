# -*- coding: utf-8 -*-
"""BK-CHART：近窗對質／三鍋標籤／盤中未收不當收。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.bk_chart_learn_confront import (
    POT_HIS,
    POT_INFER,
    POT_OFFICIAL,
    Bar,
    ChartMark,
    confront_price_mark,
    cross_theme_compare,
    near_window_dates,
    run_confront,
    ymd_compact,
)


def test_ymd_compact_normalizes():
    assert ymd_compact("2026-07-23") == "20260723"
    assert ymd_compact("20260723") == "20260723"


def test_near_window_includes_center_and_neighbors():
    dates = [f"202607{d:02d}" for d in range(1, 32) if d not in (4, 5, 11, 12, 18, 19, 25, 26)]
    # simplify: weekdays-ish fake list
    dates = [
        "20260701",
        "20260702",
        "20260703",
        "20260706",
        "20260707",
        "20260708",
        "20260709",
        "20260713",
        "20260714",
        "20260715",
        "20260716",
        "20260717",
        "20260720",
        "20260721",
        "20260722",
        "20260723",
        "20260724",
        "20260727",
        "20260728",
        "20260729",
        "20260730",
        "20260731",
    ]
    win = near_window_dates(dates, "20260723", half=3)
    assert "20260723" in win
    assert win[0] < "20260723" < win[-1]
    assert len(win) == 7


def test_near_window_non_trading_snaps_left():
    dates = ["20260722", "20260723", "20260724", "20260727"]
    win = near_window_dates(dates, "20260726", half=1)
    assert "20260724" in win  # 26 非交易 → 左側 24


def test_confront_exact_touch_is_dui():
    mark = ChartMark(
        "t",
        "20260720",
        "theme",
        "price_label",
        41967.75,
        "60m 低",
        "TWII",
        "x",
    )
    bars = [
        Bar("20260717", 45000, 45200, 42600, 42671, 1e6, "TWII"),
        Bar("20260720", 42793, 43084, 41967.75, 42449, 1e6, "TWII"),
        Bar("20260721", 42566, 44232, 42566, 44232, 1e6, "TWII"),
    ]
    row = confront_price_mark(mark, bars, as_of_today="20261123")
    assert row.verdict == "對"
    assert row.pot_official == POT_OFFICIAL
    assert mark.pot == POT_HIS
    assert any(h["date"] == "20260720" for h in row.hit_bars)


def test_confront_skips_today_incomplete_bar():
    """盤中未收不當收：今日柱不進命中。"""
    mark = ChartMark(
        "t",
        "20261123",
        "theme",
        "price_label",
        40000.0,
        "假想",
        "TWII",
        "x",
    )
    bars = [
        Bar("20261121", 41000, 41200, 40500, 40800, 1e6, "TWII"),
        Bar("20261123", 40100, 40200, 39900, 40050, 1e6, "TWII"),  # 今日＝未收
    ]
    row = confront_price_mark(mark, bars, as_of_today="20261123")
    assert all(h["date"] != "20261123" for h in row.hit_bars)
    assert "20261123" not in row.window_dates


def test_cross_theme_marks_reuse():
    m1 = ChartMark("a", "20260902", "micro_wave_band", "price_label", 45415.0, "x", "TX", "p")
    m2 = ChartMark("b", "20260909", "micro_wave_band", "price_label", 45415.0, "y", "TX", "p")
    bars = [Bar("20260831", 45800, 46060, 45415, 45983, 1, "TX")]
    rows = [
        confront_price_mark(m1, bars, as_of_today="20261123"),
        confront_price_mark(m2, bars, as_of_today="20261123"),
    ]
    themes = cross_theme_compare(rows)
    assert themes[0]["reused_across_periods"] is True
    assert themes[0]["pot"] == POT_INFER


def test_run_confront_on_real_db_smoke():
    db = Path("data/wayne_market.db")
    if not db.exists():
        pytest.skip("no local wayne_market.db")
    # 需要 TWII／TX 有 2026-07～09 柱
    conn = sqlite3.connect(str(db))
    try:
        n_tw = conn.execute(
            "SELECT COUNT(*) FROM index_daily WHERE symbol='TWII' AND date BETWEEN '20260701' AND '20260915'"
        ).fetchone()[0]
        n_tx = conn.execute(
            "SELECT COUNT(*) FROM futures_daily WHERE symbol='TX' AND session='regular' AND date BETWEEN '20260701' AND '20260915'"
        ).fetchone()[0]
    finally:
        conn.close()
    if n_tw < 10 or n_tx < 10:
        pytest.skip("official bars window too thin")

    payload = run_confront(db, as_of_today="20261123")
    assert payload["track"] == "BK-CHART"
    assert set(payload["pots"]) == {POT_HIS, POT_OFFICIAL, POT_INFER}
    assert payload["inventory"]["price_confronted"] >= 10
    assert payload["inventory"]["compare_groups"] >= 2
    # 41967 應在 7/20 近窗對上 TWII 低
    rows = [
        r
        for r in payload["confront_rows"]
        if r["value"] and abs(float(r["value"]) - 41967.75) < 0.1
    ]
    assert rows, "missing 41967.75 mark"
    assert rows[0]["verdict"] == "對"
    assert any(r["id"].startswith("R") for r in payload["operable_rules"])
    # 規則皆標試標推論、非他原文
    assert all(r["pot"] == POT_INFER and r["not_his_literal"] for r in payload["operable_rules"])


def test_41967_exact_low_in_db():
    db = Path("data/wayne_market.db")
    if not db.exists():
        pytest.skip("no local wayne_market.db")
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT date, low FROM index_daily WHERE symbol='TWII' AND date='20260720'"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        pytest.skip("missing TWII 20260720")
    assert abs(float(row[1]) - 41967.75) < 0.01


def test_script_module_importable_and_json_roundtrip(tmp_path):
    db = Path("data/wayne_market.db")
    if not db.exists():
        pytest.skip("no local wayne_market.db")
    out = tmp_path / "chart_learn_test.json"
    from scripts.bk_chart_learn_confront import main

    rc = main(["--db", str(db), "--out", str(out), "--as-of-today", "20261123"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["warning"].startswith("試標")
    assert "gaps" in payload
