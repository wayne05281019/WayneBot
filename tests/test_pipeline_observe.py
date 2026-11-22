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
    from pipeline_observe import build_combo_screen, format_combo_screen_html
    from unittest.mock import patch

    # 無 lists 時仍可渲染（今日無），不准炸
    combo_bare = format_combo_screen_html(payload)
    assert "綜合篩選" in combo_bare
    assert "機構式節點" in combo_bare
    assert "非買訊" in combo_bare
    assert "總分" in combo_bare
    assert "進場｜勝率買點" in combo_bare
    # 有名單：勝率買點必須出現真實代號，不准只剩對質統計
    # tmp DB 無產業鏈標 → AI-only 會清空；測組頁路徑時放行 roster
    with patch(
        "winrate_ai_priority.filter_winrate_rows_ai_only",
        side_effect=lambda rows, db_path="": list(rows),
    ):
        combo_payload = build_combo_screen(
            db,
            uid="9",
            now=datetime(2026, 11, 19, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )
    assert combo_payload.get("combo") is True
    wr = (combo_payload.get("lists") or {}).get("winrate") or {}
    assert any(str(it.get("sid")) == "2317" for it in (wr.get("items") or []))
    # 海選離零空＋勝率有檔 → 不准冒充可進場臉
    assert wr.get("buy_ok") is False
    assert "勝率軌≠海選離零" in str(wr.get("face") or "")
    combo = format_combo_screen_html(combo_payload)
    assert "2317" in combo and "鴻海" in combo
    assert "進場｜勝率買點" in combo
    assert "勝率軌≠海選離零" in combo
    # 勝率有檔、海選桶空＝產品層差異說明，不准當失真 issues
    gate = next((L for L in payload["layers"] if getattr(L, "id", None) == "gate"), None)
    assert gate is not None
    gate_txt = " ".join(gate.lines)
    assert "產品層" in gate_txt or "母閘" in gate_txt
    assert gate.status != "失真"
    assert not any("兩套掃描脫鉤" in (i.detail or "") for i in payload.get("issues") or [])
    # 海選無 session＝缺，不准收尾翻成齊
    pool = next((L for L in payload["layers"] if getattr(L, "id", None) == "pool"), None)
    assert pool is not None
    assert pool.status == "缺"



def test_combo_leave_zero_screen_buy_ok_radar_observe(tmp_path):
    """剛離零：海選桶＝可進場；僅雷達＝雷達／觀察，不准 buy_ok。"""
    from unittest.mock import patch

    from pipeline_observe import build_combo_screen, format_combo_screen_html
    from screen_sessions import save_screen_session
    from silent_track_runs import ensure_pipeline_table
    from winrate_buypoint import ensure_winrate_table

    db = str(tmp_path / "combo_lz.db")
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
            "close REAL, open REAL, high REAL, low REAL, volume INTEGER, "
            "foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER)"
        )
        for i in range(900):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, f"{i:04d}", f"T{i}", "TW", 100, 100, 100, 100, 1000, 0, 0, 0),
            )
        for i in range(700):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, f"{i+2000:04d}", f"O{i}", "OTC", 50, 50, 50, 50, 500, 0, 0, 0),
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
    save_screen_session(
        db,
        day,
        "morning",
        {
            "leave_zero": [
                {"stock_id": "2330", "stock_name": "台積電", "pick_close": 1000}
            ],
            "ma60_lower": [],
            "golden_buy": [],
        },
    )
    now = datetime(2026, 11, 17, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    with patch(
        "winrate_ai_priority.filter_winrate_rows_ai_only",
        side_effect=lambda rows, db_path="": list(rows),
    ):
        payload = build_combo_screen(db, uid="9", now=now)
    assert payload.get("desk_as_of") == day
    lz = (payload.get("lists") or {}).get("leave_zero") or {}
    assert lz.get("source") == "screen"
    assert lz.get("buy_ok") is True
    assert lz.get("face") == "可進場"
    assert any(it.get("sid") == "2330" for it in (lz.get("items") or []))
    html = format_combo_screen_html(payload)
    assert "進場｜剛離零" in html
    assert "海選 leave_zero" in html

    save_screen_session(
        db,
        day,
        "morning",
        {"leave_zero": [], "ma60_lower": [], "golden_buy": []},
    )
    with patch(
        "pipeline_observe._live_judge_pack",
        side_effect=lambda *a, **k: (
            (day, [{"sid": "1605", "name": "華新"}])
            if a[1] == "leave_zero"
            else ("", [])
        ),
    ), patch(
        "winrate_ai_priority.filter_winrate_rows_ai_only",
        side_effect=lambda rows, db_path="": list(rows),
    ):
        radar_payload = build_combo_screen(db, uid="9", now=now)
    lz2 = (radar_payload.get("lists") or {}).get("leave_zero") or {}
    assert lz2.get("source") == "radar"
    assert lz2.get("buy_ok") is False
    assert "雷達" in str(lz2.get("face") or "")
    html2 = format_combo_screen_html(radar_payload)
    assert "觀察｜剛離零雷達" in html2
    assert "〔雷達／觀察〕" in html2
    lz_chunk = html2.split("剛離零雷達")[1].split("紅箭")[0]
    assert "〔可進場〕" not in lz_chunk


def test_combo_streak_stale_chip_face():
    """連買 as_of≪desk → 醒目標舊日，不當日選股臉。"""
    from pipeline_observe import format_combo_screen_html

    payload = {
        "desk_as_of": "20261117",
        "fuse_as_of": "20261120",
        "today": "20261122",
        "summary": {"ok_n": 0, "layer_n": 6, "bad_n": 0, "issue_n": 0},
        "layers": [],
        "issues": [],
        "lists": {
            "winrate": {"as_of": "20261117", "items": [], "buy_ok": False, "face": "勝率軌"},
            "leave_zero": {
                "as_of": "20261117",
                "items": [],
                "buy_ok": False,
                "face": "雷達／觀察",
                "source": "none",
            },
            "ma60_lower": {
                "as_of": "20261117",
                "items": [],
                "buy_ok": False,
                "face": "觀察非買",
            },
            "undervalue_star": {
                "as_of": "20261117",
                "items": [],
                "buy_ok": False,
                "face": "觀察非買",
            },
            "streak_foreign": {
                "as_of": "20261103",
                "items": [{"sid": "2330", "name": "台積電", "days": 5}],
                "buy_ok": False,
                "face": "籌碼舊日・觀察",
                "stale": True,
            },
            "streak_trust": {
                "as_of": "20261103",
                "items": [],
                "buy_ok": False,
                "face": "籌碼舊日・觀察",
                "stale": True,
            },
            "streak_both": {
                "as_of": "20261103",
                "items": [],
                "buy_ok": False,
                "face": "籌碼舊日・觀察",
                "stale": True,
            },
        },
    }
    html = format_combo_screen_html(payload)
    assert "籌碼舊日≠基準" in html
    assert "籌碼舊日・觀察" in html
    assert "2330" in html

def test_pipeline_observe_empty_buckets_not_ok(tmp_path):
    """海選有 session 但三桶皆空＝空，不是齊。"""
    from pipeline_observe import ST_EMPTY, build_pipeline_observe
    from screen_sessions import save_screen_session
    from silent_track_runs import ensure_pipeline_table
    from winrate_buypoint import ensure_winrate_table

    db = str(tmp_path / "obs_empty.db")
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
            "close REAL, open REAL, high REAL, low REAL, volume INTEGER, "
            "foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER)"
        )
        for i in range(900):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, f"{i:04d}", f"T{i}", "TW", 100, 100, 100, 100, 1000, 0, 0, 0),
            )
        for i in range(700):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, f"{i+2000:04d}", f"O{i}", "OTC", 50, 50, 50, 50, 500, 0, 0, 0),
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
    save_screen_session(
        db,
        day,
        "morning",
        {"leave_zero": [], "ma60_lower": [], "golden_buy": []},
    )
    payload = build_pipeline_observe(
        db,
        uid="9",
        now=datetime(2026, 11, 17, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    pool = next(L for L in payload["layers"] if L.id == "pool")
    assert pool.status == ST_EMPTY
    assert any("不是齊" in ln for ln in pool.lines)
