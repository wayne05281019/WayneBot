# -*- coding: utf-8 -*-
"""低估掃描：融合後寫庫；空名單分還沒算完／算完 0 檔。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from wayne_db import init_database


def _seed_as_of(db: str, as_of: str = "20261114") -> None:
    from wayne_db import ensure_core_schema

    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    try:
        # daily_quotes PK＝(date, stock_id)
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes "
            "(date, stock_id, stock_name, market, open, high, low, close, "
            "volume, turnover_k, pct_change, avg_price) "
            "VALUES (?, '2330', '台積電', 'TW', 100, 101, 99, 100.5, 1000, 0, 0, 100)",
            (as_of,),
        )
        conn.commit()
    finally:
        conn.close()


def test_run_undervalue_sync_stub_success_zero_rows(tmp_path, monkeypatch):
    from undervalue_sync import (
        empty_note_for_button,
        load_picks,
        load_run,
        run_undervalue_sync,
    )

    db = str(tmp_path / "uv.db")
    init_database(db)
    _seed_as_of(db)
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda _p: "20261114"
    )
    monkeypatch.setattr(
        "tw_holidays.closed_tw_session", lambda **_k: None
    )
    out = run_undervalue_sync(db, skip_if_done=False)
    assert out["ok"] is True
    assert out["as_of"] == "20261114"
    assert out["n"] == 0
    run = load_run(db, "20261114")
    assert run and run["status"] == "success"
    assert load_picks(db, "20261114") == []
    assert empty_note_for_button(db, "20261114") == "已算完 0 檔"
    # skip_if_done
    out2 = run_undervalue_sync(db, skip_if_done=True)
    assert out2["ok"] is True
    assert "略過" in (out2.get("note") or "")


def test_empty_note_before_scan(tmp_path):
    from undervalue_sync import empty_note_for_button, ensure_tables

    db = str(tmp_path / "uv2.db")
    init_database(db)
    ensure_tables(db)
    assert empty_note_for_button(db, "20261114") == "盤後還沒算完（融合後掃描）"


def test_resolve_button_as_of_falls_back_to_success(tmp_path, monkeypatch):
    """latest_complete 已新、該日還沒掃 → 話筒退回最近 success，不准空卡。"""
    from undervalue_sync import (
        ensure_tables,
        resolve_button_as_of,
    )

    db = str(tmp_path / "uv_fb.db")
    init_database(db)
    ensure_tables(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO undervalue_runs "
            "(as_of, status, n_star, n_watch, note, started_at, finished_at) "
            "VALUES ('20261109', 'success', 2, 8, 'uv_growth_fair_v1', 't', 't')"
        )
        conn.execute(
            "INSERT INTO undervalue_picks "
            "(as_of, stock_id, name, mark, close, pe, pe_est, peer_pe_median, "
            "dist_to_floor_pct, flow_shares, reason, detail_json) "
            "VALUES ('20261109', '2383', '台光電', 'star', 4000, 40, 0, 35, "
            "-10, 1000, 'x', '{}')"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda _p: "20261116"
    )
    assert resolve_button_as_of(db) == "20261109"


def test_post_fuse_hook_calls_undervalue(monkeypatch):
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner._run_post_fuse_silent_tracks)
    assert "undervalue" in src
    assert "run_undervalue_sync" in src


def test_menu_undervalue_without_ai_button():
    from bot_servers import MENU_BTN_AI, MENU_BTN_UNDERVALUE, MENU_ROW2, MENU_LAYOUT_VERSION

    assert MENU_LAYOUT_VERSION == "38"
    assert MENU_BTN_UNDERVALUE == "低估名單"
    assert MENU_ROW2[3] == MENU_BTN_UNDERVALUE
    assert MENU_BTN_AI not in MENU_ROW2
    assert MENU_BTN_AI == "AI倉"  # 打字別名仍認


def test_undervalue_page_callback_routed():
    import inspect

    from bot_servers import WayneTelegramBot

    cb = inspect.getsource(WayneTelegramBot._on_callback_bound)
    assert 'data.startswith("uv:page:")' in cb
    assert "_handle_undervalue_page_callback" in cb
    send = inspect.getsource(WayneTelegramBot._send_undervalue_view)
    assert "render_undervalue_pages" in send
    kb = inspect.getsource(WayneTelegramBot._undervalue_pick_keyboard)
    assert "uv:page:" in kb


def test_ai_desk_type_alias_still_routes():
    """主選單無 AI倉鈕；打字 AI倉／模擬倉仍進假錢倉。"""
    import inspect

    from bot_servers import MENU_BTN_AI, MENU_ROW2, WayneTelegramBot

    assert MENU_BTN_AI not in MENU_ROW2
    src = inspect.getsource(WayneTelegramBot._on_text_bound)
    assert '"AI倉"' in src
    assert "模擬倉" in src
    assert "_send_ai_desk_view" in src
