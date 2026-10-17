# -*- coding: utf-8 -*-
"""AI 模擬倉：50=30+20、勝率買點母體、理由落檔、重跑閘、進化週報。"""
from __future__ import annotations

import os
import sqlite3

from ai_trader import (
    ACTIVE_BUDGET,
    DIP_RESERVE,
    MAX_ACTIVE_NAMES,
    RESTART_BUY_FROM,
    TOTAL_CAPITAL,
    buy_budget,
    buys_allowed_on,
    cash_reserve_floor,
    current_ai_encoding,
    format_evolve_report_html,
    mark_weekly_evolve_sent,
    persist_ai_lesson,
    should_send_weekly_evolve,
    slot_notional,
)
from wayne_db import ensure_core_schema


def test_ai_run_copy_matches_winrate_roster():
    import inspect

    from ai_trader import ai_no_fill_note, ai_run_wait_now
    from bot_servers import WayneTelegramBot

    assert ai_run_wait_now() == "依今日勝率買點名單"
    note = ai_no_fill_note(2)
    assert "候選 2 檔" in note
    assert "只從當天勝率買點名單模擬" in note
    assert "海選" not in note
    assert "高低卡" not in note
    assert "美股" not in note
    src = inspect.getsource(WayneTelegramBot._run_ai_now)
    assert "依今日海選紀律" not in src
    assert "名單被高低卡" not in src
    assert "ai_run_wait_now" in src
    assert "ai_no_fill_note" in src
    hub = inspect.getsource(WayneTelegramBot._show_pressure_hub)
    assert "不准當進場" not in hub
    assert "PRESSURE_HUB_LEAD" in hub


def test_persist_lesson_and_encoding_roundtrip(tmp_path):
    path = str(tmp_path / "e.db")
    ensure_core_schema(path)
    persist_ai_lesson(path, "ai_1", "20260904", "縮小單筆倉位")
    enc = current_ai_encoding(path, "ai_1")
    assert enc["entry"] == "winrate_buypoint"
    assert enc["observe"] == "golden_buy"
    assert enc["not_entry"] == "red_arrow_unconfirmed"
    assert enc["active_budget"] == ACTIVE_BUDGET
    assert enc["dip_reserve"] == DIP_RESERVE
    assert enc["total_capital"] == TOTAL_CAPITAL
    assert enc["max_active_names"] == MAX_ACTIVE_NAMES
    assert enc["cash_reserve"] is True
    assert 0.4 <= float(enc["size_mult"]) <= 1.2
    html = format_evolve_report_html(path, "ai_1")
    assert "勝率買點" in html
    assert "50 萬" in html
    assert "30 萬" in html
    assert "20 萬" in html
    assert "縮小單筆倉位" in html
    assert "2026/09/04" in html
    assert "量化積木" in html
    assert "不能塞進" in html
    assert "未確認紅箭頭不是買訊" in html
    conn = sqlite3.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM ai_lessons").fetchone()[0]
    conn.close()
    assert n == 1


def test_weekly_evolve_only_friday_once(tmp_path):
    path = str(tmp_path / "w.db")
    ensure_core_schema(path)
    assert should_send_weekly_evolve(path, "ai_1", "20260907") is False  # Monday
    assert should_send_weekly_evolve(path, "ai_1", "20260904") is True  # Friday
    mark_weekly_evolve_sent(path, "ai_1", "20260904")
    assert should_send_weekly_evolve(path, "ai_1", "20260904") is False


def test_evening_desk_stays_silent_and_digest_is_separate():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner.run_evening_screen)
    assert "notify=False" in src
    assert "_maybe_send_evolve_digest" in src
    desk = inspect.getsource(MainRunner._run_ai_desk)
    assert "notify: bool = True" in desk
    # 成交後才凍 AI倉；海選 snapshot 常在 AI 前，不准只靠按鈕才記
    assert "snapshot_ai_desk" in desk


def test_core_candidates_are_winrate_roster_hard_gate(tmp_path):
    """沒進勝率買點 roster → 不准買；海選 leave_zero 後備已拔掉。"""
    import inspect

    from ai_trader import _candidates
    from winrate_buypoint import ensure_winrate_table, save_winrate_roster

    src = inspect.getsource(_candidates)
    assert "winrate_buypoint_roster" in src or "勝率買點" in src
    assert "leave_zero" not in src or "不准" in src
    path = str(tmp_path / "wr.db")
    ensure_core_schema(path)
    ensure_winrate_table(path)
    # 無 roster：海選再多也不准買
    assert (
        _candidates(
            {
                "leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}],
                "ma60_lower": [{"stock_id": "6257", "stock_name": "矽格", "close": 99.0}],
            },
            path,
            as_of="20261012",
        )
        == []
    )
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT OR REPLACE INTO stock_universe(
            stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        ("2330", "台積電", "TWSE", "STOCK", "半導體業", 1, "2026-10-12 00:00:00"),
    )
    conn.commit()
    conn.close()
    save_winrate_roster(
        path,
        "20261012",
        [{"stock_id": "2330", "stock_name": "台積電", "pick_close": 100.0, "quote_source": "test"}],
    )
    cands = _candidates({}, path, as_of="20261012")
    assert [x["stock_id"] for x in cands] == ["2330"]
    assert {x.get("ai_bucket") for x in cands} == {"winrate_active"}
    dip = _candidates({}, path, dip_only=True, as_of="20261012")
    assert [x["stock_id"] for x in dip] == ["2330"]
    assert {x.get("ai_bucket") for x in dip} == {"dip_add"}


def test_evolve_report_mentions_split_and_research(tmp_path):
    path = str(tmp_path / "e2.db")
    ensure_core_schema(path)
    html = format_evolve_report_html(path, "ai_1")
    assert "還在零只觀察" in html
    assert "未取得" in html or "研究" in html
    assert "買進不得吃" in html
    assert "未確認紅箭頭不是買訊" in html


def test_cash_reserve_and_buy_budget():
    assert cash_reserve_floor(TOTAL_CAPITAL) == DIP_RESERVE
    assert slot_notional(TOTAL_CAPITAL, 1.0) == ACTIVE_BUDGET / MAX_ACTIVE_NAMES
    # 倍數拉高也不能吃進 20 萬保留
    assert buy_budget(TOTAL_CAPITAL, TOTAL_CAPITAL, 1.2) == slot_notional(TOTAL_CAPITAL, 1.2)
    assert buy_budget(250_000, TOTAL_CAPITAL, 1.0) == max(
        0.0, 250_000 - DIP_RESERVE
    )
    assert buy_budget(100_000, TOTAL_CAPITAL, 1.0) == 0.0
    # 抄底可動用保留額內現金
    assert buy_budget(200_000, TOTAL_CAPITAL, 1.0, dip=True) == min(
        slot_notional(TOTAL_CAPITAL, 1.0), 200_000
    )


def test_buys_gate_from_restart_day():
    assert buys_allowed_on("20261012") is False
    assert buys_allowed_on("20261013") is True
    assert buys_allowed_on(RESTART_BUY_FROM) is True
    assert buys_allowed_on("2026-10-14") is True


def test_encoding_marks_cash_reserve(tmp_path):
    path = str(tmp_path / "enc.db")
    ensure_core_schema(path)
    enc = current_ai_encoding(path, "ai_1")
    assert enc["cash_reserve"] is True
    assert enc["dip_open"] == "winrate_buypoint"
    assert enc["entry"] == "winrate_buypoint"
    assert enc["not_entry"] == "red_arrow_unconfirmed"


def test_help_topics_cancelled():
    from bot_servers import HELP_TOPICS

    assert HELP_TOPICS == {}


def test_research_and_reason_tables(tmp_path):
    path = str(tmp_path / "r.db")
    ensure_core_schema(path)
    from ai_research import (
        MISSING,
        gather_buy_research,
        persist_buy_reason,
        build_buy_reason_from_research,
    )

    # 無行情時仍落檔，缺欄＝未取得
    research = gather_buy_research(
        path, "ai_1", "20261012", "2330", "台積電", allow_public=False
    )
    assert research["stock_id"] == "2330"
    assert research["fundamentals_summary"] == MISSING or research["fundamentals_summary"]
    assert "researched_at" in research
    built = build_buy_reason_from_research(research, signal_label="勝率買點隔日操作")
    rid = persist_buy_reason(
        path,
        user_id="ai_1",
        as_of="20261012",
        stock_id="2330",
        stock_name="台積電",
        bucket="winrate_active",
        reason=built["reason"],
        sources_summary=built["sources_summary"],
        target_exit=built["target_exit"],
        stop_pct=-7.0,
        take_pct=8.0,
        research_id=research.get("research_id"),
    )
    assert rid > 0
    conn = sqlite3.connect(path)
    n_r = conn.execute("SELECT COUNT(*) FROM ai_buy_research").fetchone()[0]
    n_b = conn.execute("SELECT COUNT(*) FROM ai_buy_reasons").fetchone()[0]
    row = conn.execute(
        "SELECT reason, sources_summary, logged_at FROM ai_buy_reasons WHERE id=?",
        (rid,),
    ).fetchone()
    conn.close()
    assert n_r == 1 and n_b == 1
    assert "勝率買點" in row[0]
    assert row[1]
    assert row[2]  # 台北時間字串


def test_reset_ai_account_clears_and_sets_500k(tmp_path):
    path = str(tmp_path / "reset.db")
    ensure_core_schema(path)
    from portfolio_engine import PortfolioEngine
    from ai_trader import ensure_ai_restart_applied, reset_ai_account, ai_user_id
    from screen_review import ensure_ai_fills_table, persist_ai_fill

    eng = PortfolioEngine(path)
    uid = ai_user_id("9001")
    eng.ensure_user_exists(uid)
    eng.buy(uid, "20261001", "2330", "台積電", 100.0, 1000, reason="舊倉")
    ensure_ai_fills_table(path)
    persist_ai_fill(
        path,
        as_of="20261001",
        stock_id="2330",
        stock_name="台積電",
        action="BUY",
        price=100.0,
        shares=1000,
        user_id=uid,
        reason="舊倉",
        bucket="leave_zero",
    )
    assert eng.get_portfolio_summary(uid, {})["positions_count"] == 1
    out = reset_ai_account(eng, uid)
    assert out["success"] is True
    s = eng.get_portfolio_summary(uid, {})
    assert s["positions_count"] == 0
    assert s["cash"] == TOTAL_CAPITAL
    assert s["initial_capital"] == TOTAL_CAPITAL
    conn = sqlite3.connect(path)
    n_logs = conn.execute("SELECT COUNT(*) FROM trade_logs WHERE user_id=?", (uid,)).fetchone()[0]
    n_fills = conn.execute("SELECT COUNT(*) FROM ai_fills WHERE user_id=?", (uid,)).fetchone()[0]
    conn.close()
    assert n_logs == 0  # 舊買賣全刪，不留 RESET 成交
    assert n_fills == 0
    # 重跑旗標只清一次
    assert ensure_ai_restart_applied(eng, uid) is True
    assert ensure_ai_restart_applied(eng, uid) is False


def test_reset_refuses_non_ai_user(tmp_path):
    path = str(tmp_path / "safe.db")
    ensure_core_schema(path)
    from portfolio_engine import PortfolioEngine
    from ai_trader import reset_ai_account

    eng = PortfolioEngine(path)
    eng.ensure_user_exists("9001")  # 真實持股 uid 形狀
    eng.buy("9001", "20261001", "2330", "台積電", 100.0, 1000, reason="真倉")
    out = reset_ai_account(eng, "9001")
    assert out["success"] is False
    assert eng.get_portfolio_summary("9001", {})["positions_count"] == 1


def test_run_ai_desk_respects_buy_gate(tmp_path):
    path = str(tmp_path / "desk.db")
    ensure_core_schema(path)
    from portfolio_engine import PortfolioEngine
    from ai_trader import run_ai_desk, TOTAL_CAPITAL
    from winrate_buypoint import ensure_winrate_table, save_winrate_roster

    ensure_winrate_table(path)
    # 勝率名單 load 會過 AI 生態系過濾；測試先補粗分產業
    conn = sqlite3.connect(path)
    try:
        for sid, name in (("2330", "台積電"), ("2454", "聯發科")):
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_universe(
                    stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (sid, name, "TWSE", "STOCK", "半導體業", 1, "2026-10-12 00:00:00"),
            )
        conn.commit()
    finally:
        conn.close()
    save_winrate_roster(
        path,
        "20261012",
        [
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "pick_close": 100.0,
                "profit_pct": 5.0,
                "quote_source": "test",
            },
            {
                "stock_id": "2454",
                "stock_name": "聯發科",
                "pick_close": 80.0,
                "profit_pct": 4.0,
                "quote_source": "test",
            },
        ],
    )
    # 重跑當日（12）只清倉不買
    out0 = run_ai_desk(path, "9001", {}, "20261012")
    assert out0["buys_allowed"] is False
    assert out0["bought"] == []
    eng = PortfolioEngine(path)
    s0 = eng.get_portfolio_summary(out0["user_id"], {})
    assert s0["cash"] == TOTAL_CAPITAL
    assert s0["positions_count"] == 0
    # 13 日起可買，最多 3 檔
    out1 = run_ai_desk(path, "9001", {}, "20261013")
    assert out1["buys_allowed"] is True
    assert len(out1["bought"]) >= 1
    assert len(out1["bought"]) <= MAX_ACTIVE_NAMES
    s1 = eng.get_portfolio_summary(out1["user_id"], {})
    assert s1["positions_count"] <= MAX_ACTIVE_NAMES
    # 理由必落檔
    conn = sqlite3.connect(path)
    n_reason = conn.execute("SELECT COUNT(*) FROM ai_buy_reasons").fetchone()[0]
    n_research = conn.execute("SELECT COUNT(*) FROM ai_buy_research").fetchone()[0]
    conn.close()
    assert n_reason >= 1
    assert n_research >= 1
