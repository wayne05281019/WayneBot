# -*- coding: utf-8 -*-
"""流水線觀測：分層對質＋資金法人日不准用空殼現貨日。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


def _make_flow_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE daily_quotes ("
            "stock_id TEXT, market TEXT, date TEXT, close REAL, "
            "volume INTEGER, pct_change REAL, foreign_net INTEGER, "
            "trust_net INTEGER, dealer_net INTEGER)"
        )
        # 法人有料日
        for i in range(900):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?, 'TW', '20261103', 100, 1000, 1, 10, 0, 0)",
                (f"{i:04d}",),
            )
        for i in range(700):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?, 'OTC', '20261103', 50, 500, -1, -5, 0, 0)",
                (f"{i+2000:04d}",),
            )
        # 現貨齊但法人全 0
        for i in range(900):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?, 'TW', '20261117', 100, 1000, 1, 0, 0, 0)",
                (f"{i:04d}",),
            )
        for i in range(700):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?, 'OTC', '20261117', 50, 500, -1, 0, 0, 0)",
                (f"{i+2000:04d}",),
            )
        conn.commit()
    finally:
        conn.close()


def test_resolve_flow_as_of_falls_back_to_chip_day(tmp_path):
    """現貨齊到新日但法人全0 → 資金基準退回法人有料日，不准假輪動。"""
    from money_flow import clear_flow_html_cache, format_flow_html, resolve_flow_as_of

    db = str(tmp_path / "flow_chip.db")
    _make_flow_db(db)
    now = datetime(2026, 11, 19, 9, 40, tzinfo=ZoneInfo("Asia/Taipei"))
    as_of, lag = resolve_flow_as_of(db, now=now)
    assert as_of == "20261103"
    assert lag and "法人" in lag
    assert "2026/11/17" in lag
    # 完整 format_flow_html 需股名等欄；此測只鎖基準日對質
    clear_flow_html_cache()
    del format_flow_html


def test_pipeline_observe_builds_layers(tmp_path):
    from pipeline_observe import build_pipeline_observe, format_pipeline_observe_html
    from silent_track_runs import ensure_pipeline_table, mark_track
    from winrate_buypoint import ensure_winrate_table, save_winrate_roster

    db = str(tmp_path / "obs.db")
    ensure_pipeline_table(db)
    ensure_winrate_table(db)
    day = "20261117"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS index_daily ("
            "date TEXT, symbol TEXT, close REAL, volume REAL, pct_change REAL, "
            "ma20 REAL, ma60 REAL, regime TEXT, updated_at TEXT, "
            "open REAL, high REAL, low REAL, PRIMARY KEY(date, symbol))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS daily_quotes ("
            "date TEXT, stock_id TEXT, stock_name TEXT, market TEXT, "
            "close REAL, foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_daily "
            "(date, symbol, close, volume, pct_change, regime, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (day, "TWII", 40000.0, 1, -1.0, "bear", day),
        )
        conn.commit()
    finally:
        conn.close()
    save_winrate_roster(
        db,
        day,
        [
            {
                "stock_id": "2317",
                "stock_name": "鴻海",
                "pick_close": 100.0,
                "profit_pct": 0.5,
                "quote_source": "card_lz_paint_ex5|test",
            }
        ],
    )
    mark_track(db, "dongzhu", day, "success", "dongzhu=1")
    payload = build_pipeline_observe(
        db,
        uid="9",
        now=datetime(2026, 11, 19, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    html = format_pipeline_observe_html(payload)
    assert "非買訊" in html
    assert payload.get("layers")
    assert payload.get("not_buy_signal") is True
    # 勝率有檔、海選桶空 → 必須出現進場閘對質問題
    texts = " ".join(i.detail for i in payload.get("issues") or [])
    assert "勝率" in texts or "leave_zero" in texts or "進場閘" in html
