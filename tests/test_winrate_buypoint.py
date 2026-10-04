# -*- coding: utf-8 -*-
"""勝率買點：鍵盤、落檔、分頁、隔日盤中篩。不准改黃金買點公式。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from bot_servers import (
    MENU_BTN_WINRATE,
    MENU_LAYOUT_VERSION,
    MENU_ROW1,
    MENU_ROW2,
    WayneTelegramBot,
)
from winrate_buypoint import (
    EMPTY_MSG,
    NEXT_PAGE_LABEL,
    PAGE_SIZE,
    filter_intraday_from_roster,
    header_html,
    latest_roster_as_of,
    load_winrate_roster,
    next_page_callback,
    page_slice,
    parse_next_page_callback,
    resolve_button_rows,
    save_winrate_roster,
    should_apply_intraday_filter,
)


def _seed_elec_universe(db: str, rows) -> None:
    """測試庫補粗分產業，讓 AI-only 讀檔不過濾掉電子檔。"""
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS stock_universe("
            "stock_id TEXT PRIMARY KEY, stock_name TEXT, market_type TEXT,"
            "asset_type TEXT, industry TEXT, is_active INTEGER, updated_at TEXT)"
        )
        for sid, name, ind in rows:
            conn.execute(
                "INSERT OR REPLACE INTO stock_universe VALUES (?,?,?,?,?,?,?)",
                (sid, name, "TW", "STOCK", ind, 1, ""),
            )
        conn.commit()
    finally:
        conn.close()


def test_menu_winrate_first_hai_xuan_second():
    assert MENU_BTN_WINRATE == "勝率買點"
    assert MENU_LAYOUT_VERSION == "33"
    assert MENU_ROW1[0] == MENU_BTN_WINRATE
    assert MENU_ROW1[1] == "海選"
    assert len(MENU_ROW1) == 7 and len(MENU_ROW2) == 7
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    row1 = [b.text for b in bot._reply_menu().keyboard[0]]
    assert row1[0] == "勝率買點"
    assert row1[1] == "海選"


def test_screen_aliases_still_route_after_winrate_shift():
    """海選右移後，舊標「海選」與別名仍走 screen_cmd（不是勝率買點）。"""
    import inspect

    from bot_servers import MENU_BTN_SCREEN, MENU_BTN_SCREEN_ALIASES, WayneTelegramBot

    assert MENU_BTN_SCREEN == "海選"
    assert "海選" in MENU_BTN_SCREEN_ALIASES
    assert "海選名單" in MENU_BTN_SCREEN_ALIASES
    src = inspect.getsource(WayneTelegramBot._on_text_bound)
    assert "MENU_BTN_SCREEN_ALIASES" in src
    assert "screen_cmd" in src
    assert src.find("MENU_BTN_SCREEN_ALIASES") < src.find("self._touch_user")
    assert "MENU_BTN_WINRATE_ALIASES" in src
    assert "winrate_cmd" in src


def test_save_load_roster_and_empty_sentinel(tmp_path):
    db = str(tmp_path / "w.db")
    _seed_elec_universe(db, [("2330", "台積電", "半導體業")])
    n = save_winrate_roster(
        db,
        "20260930",
        [
            {"stock_id": "2330", "stock_name": "台積電", "close": 900.0, "profit_pct": 0.5},
            {"stock_id": "2330", "stock_name": "dup", "close": 901.0},  # 去重
        ],
    )
    assert n == 1
    rows = load_winrate_roster(db, "20260930")
    assert len(rows) == 1
    assert rows[0]["stock_id"] == "2330"
    assert float(rows[0]["pick_close"]) == 900.0
    assert latest_roster_as_of(db) == "20260930"
    from winrate_buypoint import SCAN_KIND, roster_is_current

    assert str(rows[0]["quote_source"]).startswith(f"{SCAN_KIND}|")

    n0 = save_winrate_roster(db, "20261001", [])
    assert n0 == 0
    assert load_winrate_roster(db, "20261001") == []
    assert latest_roster_as_of(db) == "20261001"

    assert roster_is_current(db, "20261001") is True


def test_roster_is_current_rejects_pre_ex5_scan_kind(tmp_path):
    """合進 ex5 後舊 quote_source（ex4／更早）不准當現行（要重掃）。"""
    import sqlite3

    from winrate_buypoint import ensure_winrate_table, roster_is_current

    db = str(tmp_path / "old.db")
    ensure_winrate_table(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            INSERT INTO winrate_buypoint_roster(
                as_of, stock_id, stock_name, pick_close, profit_pct,
                quote_source, created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                "20261002",
                "2330",
                "台積電",
                900.0,
                1.0,
                "card_lz_paint_ex4|daily_quotes",
                "2026-10-02 12:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    assert roster_is_current(db, "20261002") is False


def test_resolve_button_rows_ensures_missing_roster(tmp_path, monkeypatch):
    """當日完整收有、roster 缺 → 按鈕路徑當場補掃，不准空回。"""
    from winrate_buypoint import resolve_button_rows, roster_is_current

    db = str(tmp_path / "e.db")
    _seed_elec_universe(db, [("7892", "元鈦科", "電子零組件業")])
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *_a, **_k: "20261001",
    )

    def _fake_ensure(db_path, *, as_of=None, force=False):
        save_winrate_roster(
            db_path,
            as_of or "20261001",
            [{"stock_id": "7892", "stock_name": "元鈦科", "close": 500.0, "profit_pct": 2.3}],
        )
        return "20261001", load_winrate_roster(db_path, "20261001")

    monkeypatch.setattr("winrate_buypoint.ensure_winrate_roster", _fake_ensure)
    monkeypatch.setattr(
        "winrate_buypoint.should_apply_intraday_filter",
        lambda **kw: False,
    )
    as_of, rows, mode = resolve_button_rows(db)
    assert as_of == "20261001" and mode == "full"
    assert [r["stock_id"] for r in rows] == ["7892"]
    assert roster_is_current(db, "20261001")


def test_scan_uses_card_leave_zero_not_screen_pick(tmp_path, monkeypatch):
    """藍▲＝leave_zero_from_quote_df＋出圖仍畫買點；不走 screen_leave_zero_pick。"""
    import pandas as pd
    from winrate_buypoint import scan_winrate_leave_zero

    db = str(tmp_path / "s.db")
    _seed_elec_universe(db, [("7892", "元鈦科", "電子零組件業")])

    class _Eng:
        def get_latest_trading_date(self):
            return "20260930"

        def _load_profit_scan_frames(self, day):
            dates = [f"202609{d:02d}" for d in range(1, 30)] + ["20260930"]
            # 成交額夠 → 不被當天額刀誤殺；near_h20 已不進 live
            closes = [110.0] * 29 + [102.0]
            df = pd.DataFrame(
                {
                    "date": dates,
                    "stock_id": ["7892"] * 30,
                    "stock_name": ["元鈦科"] * 30,
                    "close": closes,
                    "volume": [1000.0] * 30,
                    "turnover_k": [20000.0] * 30,
                    "open": closes,
                    "high": closes,
                    "low": closes,
                }
            )
            return {"7892": df}, {"7892"}

    class _Nav:
        def get_decision_card(self, *a, **k):
            return {"stock_name": "元鈦科", "buy_verdict": "buy"}

    monkeypatch.setattr("screening_engine.ScreeningEngine", lambda *a, **k: _Eng())
    monkeypatch.setattr("wayne_navigator.NavigatorEngine", lambda *a, **k: _Nav())
    monkeypatch.setattr("universe.is_screen_equity", lambda *a, **k: True)
    monkeypatch.setattr(
        "wayne_navigator.frame_for_cal60_profit",
        lambda df, db_path: df,
    )
    monkeypatch.setattr(
        "decision_card_signals.leave_zero_from_quote_df",
        lambda df: True,
    )
    monkeypatch.setattr(
        "decision_card_signals.profit_pct_cal60_series",
        lambda df: pd.Series([0.0] * (len(df) - 1) + [2.3]),
    )
    monkeypatch.setattr(
        "decision_card_signals.cal60_low_close_at",
        lambda df, i: 100.0,
    )
    monkeypatch.setattr(
        "winrate_buypoint._chart_paints_buy_mark_today",
        lambda df, card: True,
    )
    day, rows = scan_winrate_leave_zero(db, as_of="20260930")
    assert day == "20260930"
    assert len(rows) == 1 and rows[0]["stock_id"] == "7892"
    assert float(rows[0]["close"]) == 102.0


def test_scan_drops_non_ai_even_if_leave_zero(tmp_path, monkeypatch):
    """生技 leave_zero 也不進勝率推播名單（AI-only keep-set）。"""
    import pandas as pd
    from winrate_buypoint import scan_winrate_leave_zero

    db = str(tmp_path / "bio.db")
    _seed_elec_universe(db, [("4743", "合一", "生技醫療業")])

    class _Eng:
        def get_latest_trading_date(self):
            return "20260930"

        def _load_profit_scan_frames(self, day):
            dates = [f"202609{d:02d}" for d in range(1, 30)] + ["20260930"]
            closes = [50.0] * 30
            df = pd.DataFrame(
                {
                    "date": dates,
                    "stock_id": ["4743"] * 30,
                    "stock_name": ["合一"] * 30,
                    "close": closes,
                    "volume": [1000.0] * 30,
                    "turnover_k": [20000.0] * 30,
                    "open": closes,
                    "high": [c + 1 for c in closes],
                    "low": [c - 1 for c in closes],
                }
            )
            return {"4743": df}, set()

    class _Nav:
        def get_decision_card(self, *a, **k):
            return {"stock_name": "合一", "buy_verdict": "buy"}

    monkeypatch.setattr("screening_engine.ScreeningEngine", lambda *a, **k: _Eng())
    monkeypatch.setattr("wayne_navigator.NavigatorEngine", lambda *a, **k: _Nav())
    monkeypatch.setattr("universe.is_screen_equity", lambda *a, **k: True)
    monkeypatch.setattr(
        "wayne_navigator.frame_for_cal60_profit",
        lambda df, db_path: df,
    )
    monkeypatch.setattr(
        "decision_card_signals.leave_zero_from_quote_df",
        lambda df: True,
    )
    monkeypatch.setattr(
        "decision_card_signals.profit_pct_cal60_series",
        lambda df: pd.Series([0.0] * 29 + [1.0]),
    )
    monkeypatch.setattr(
        "decision_card_signals.cal60_low_close_at",
        lambda df, i: 45.0,
    )
    monkeypatch.setattr(
        "winrate_buypoint._chart_paints_buy_mark_today",
        lambda df, card: True,
    )
    monkeypatch.setattr(
        "winrate_buypoint.silent_remember_non_ai_ctrl",
        lambda *a, **k: 1,
    )
    day, rows = scan_winrate_leave_zero(db, as_of="20260930")
    assert day == "20260930"
    assert rows == []


def test_scan_excludes_when_chart_strips_buy_mark(tmp_path, monkeypatch):
    """公式 leave_zero 但出圖 watch／賣點剝掉今日藍▲紅框 → 不准進勝率名單。"""
    import pandas as pd
    from winrate_buypoint import scan_winrate_leave_zero

    db = str(tmp_path / "strip.db")

    class _Eng:
        def get_latest_trading_date(self):
            return "20261001"

        def _load_profit_scan_frames(self, day):
            dates = [f"202609{d:02d}" for d in range(1, 31)] + ["20261001"]
            df = pd.DataFrame(
                {
                    "date": dates,
                    "stock_id": ["6637"] * len(dates),
                    "stock_name": ["醫影"] * len(dates),
                    "close": [50.0] * (len(dates) - 1) + [50.1],
                    "volume": [1000.0] * len(dates),
                    "open": [50.0] * len(dates),
                    "high": [50.0] * len(dates),
                    "low": [50.0] * len(dates),
                }
            )
            return {"6637": df}, set()

    class _Nav:
        def get_decision_card(self, *a, **k):
            return {"stock_name": "醫影", "buy_verdict": "buy", "sell_action": "直接減碼"}

    monkeypatch.setattr("screening_engine.ScreeningEngine", lambda *a, **k: _Eng())
    monkeypatch.setattr("wayne_navigator.NavigatorEngine", lambda *a, **k: _Nav())
    monkeypatch.setattr("universe.is_screen_equity", lambda *a, **k: True)
    monkeypatch.setattr(
        "wayne_navigator.frame_for_cal60_profit",
        lambda df, db_path: df,
    )
    monkeypatch.setattr(
        "decision_card_signals.leave_zero_from_quote_df",
        lambda df: True,
    )
    monkeypatch.setattr(
        "decision_card_signals.profit_pct_cal60_series",
        lambda df: pd.Series([0.0] * (len(df) - 1) + [0.2]),
    )
    monkeypatch.setattr(
        "decision_card_signals.cal60_low_close_at",
        lambda df, i: 50.0,
    )
    monkeypatch.setattr(
        "winrate_buypoint._chart_paints_buy_mark_today",
        lambda df, card: False,
    )
    day, rows = scan_winrate_leave_zero(db, as_of="20261001")
    assert day == "20261001"
    assert rows == []


def test_chart_paints_buy_mark_respects_nav_strip(monkeypatch):
    """直接減碼／watch 會剝最後一根買點標。"""
    import pandas as pd
    from winrate_buypoint import _chart_paints_buy_mark_today

    df = pd.DataFrame(
        {
            "date": ["20260930", "20261001"],
            "close": [50.0, 50.1],
            "open": [50.0, 50.0],
            "high": [50.0, 50.2],
            "low": [50.0, 49.9],
            "volume": [1.0, 1.0],
        }
    )

    def _marks(work, card):
        last = len(work) - 1
        if card and (
            str(card.get("sell_action") or "") == "直接減碼"
            or str(card.get("buy_verdict") or "") in ("watch", "no")
        ):
            return [], last if str(card.get("sell_action") or "") == "直接減碼" else None
        return [last], None

    monkeypatch.setattr("wayne_navigator._nav_trade_marks", _marks)
    assert _chart_paints_buy_mark_today(df, {"buy_verdict": "buy"}) is True
    assert _chart_paints_buy_mark_today(df, {"buy_verdict": "watch"}) is False
    assert (
        _chart_paints_buy_mark_today(
            df, {"buy_verdict": "buy", "sell_action": "直接減碼"}
        )
        is False
    )


def test_pipeline_run_key_bp_prefix():
    from winrate_buypoint import PIPELINE_KEY_PREFIX, pipeline_run_key

    assert PIPELINE_KEY_PREFIX == "winrate-bp"
    assert pipeline_run_key("20261001") == "winrate-bp-20261001"


def test_page_slice_and_callback():
    rows = [{"stock_id": str(i)} for i in range(37)]
    chunk, off, has_next = page_slice(rows, 0)
    assert len(chunk) == PAGE_SIZE == 15
    assert has_next is True
    chunk2, off2, has_next2 = page_slice(rows, 15)
    assert len(chunk2) == 15 and has_next2 is True
    chunk3, off3, has_next3 = page_slice(rows, 30)
    assert len(chunk3) == 7 and has_next3 is False
    assert parse_next_page_callback(next_page_callback(15)) == 15
    assert NEXT_PAGE_LABEL == "下一個 15 檔"
    assert EMPTY_MSG in header_html("20260930", 0)


def test_should_apply_intraday_filter_same_day_false():
    now = datetime(2026, 9, 30, 21, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    assert should_apply_intraday_filter(as_of="20260930", now=now) is False


def test_filter_intraday_keeps_lower_price_with_leave_zero(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    roster = [
        {"as_of": "20260930", "stock_id": "1111", "stock_name": "甲", "pick_close": 100.0},
        {"as_of": "20260930", "stock_id": "2222", "stock_name": "乙", "pick_close": 50.0},
        {"as_of": "20260930", "stock_id": "3333", "stock_name": "丙", "pick_close": 80.0},
    ]

    class _Eng:
        def get_latest_trading_date(self):
            return "20260930"

        def _load_close_frames(self, codes, as_of):
            return {c: object() for c in codes}

    monkeypatch.setattr(
        "screening_engine.ScreeningEngine", lambda *a, **k: _Eng()
    )
    monkeypatch.setattr(
        "winrate_buypoint._still_leave_zero_live",
        lambda db_path, sid, live_price, frames: sid in ("1111", "2222"),
    )
    quotes = {
        "1111": {"price": 95.0},  # 更低＋買點在 → 留
        "2222": {"price": 55.0},  # 更高 → 丟
        "3333": {"price": 70.0},  # 更低但買點沒了 → 丟
    }
    out = filter_intraday_from_roster(db, roster, quotes=quotes)
    assert [r["stock_id"] for r in out] == ["1111"]
    assert float(out[0]["live_price"]) == 95.0


def test_resolve_button_rows_full_vs_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "r.db")
    _seed_elec_universe(db, [("2330", "台積電", "半導體業")])
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *_a, **_k: "",
    )
    as_of, rows, mode = resolve_button_rows(db)
    assert mode == "empty" and rows == [] and as_of == ""

    save_winrate_roster(
        db,
        "20260930",
        [{"stock_id": "2330", "stock_name": "台積電", "close": 900.0}],
    )
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *_a, **_k: "20260930",
    )
    monkeypatch.setattr(
        "winrate_buypoint.should_apply_intraday_filter",
        lambda **kw: False,
    )
    as_of, rows, mode = resolve_button_rows(db)
    assert as_of == "20260930" and mode == "full" and len(rows) == 1


def test_bot_wires_winrate_handler():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._on_text_bound)
    assert "MENU_BTN_WINRATE_ALIASES" in src
    assert "winrate_cmd" in src
    cb = inspect.getsource(WayneTelegramBot._on_callback_bound)
    assert 'data.startswith("wr:")' in cb
    assert hasattr(WayneTelegramBot, "push_winrate_buypoint_page")
    assert hasattr(WayneTelegramBot, "_run_winrate_buypoint")
    run_src = inspect.getsource(WayneTelegramBot._run_winrate_buypoint)
    assert "render_stock_pair" in run_src
    assert "to_thread(_pair)" in run_src or "asyncio.to_thread(_pair)" in run_src
    # 不准再整頁 wait_for(render_page_pairs)（#489 加速後變壞）
    assert "render_page_pairs(" not in run_src
    push_src = inspect.getsource(WayneTelegramBot.push_winrate_buypoint_page)
    assert "pairs" in push_src
    assert "render_page_pairs" in push_src


def test_runner_has_winrate_job():
    import inspect

    from main_runner import MainRunner

    assert hasattr(MainRunner, "run_winrate_buypoint")
    sig = inspect.signature(MainRunner.run_winrate_buypoint)
    assert "notify" in sig.parameters
    src = open("main.py", encoding="utf-8").read()
    assert '(21, 0, "winrate")' in src
    assert "run_winrate_buypoint" in src
    runner_src = inspect.getsource(MainRunner.run_winrate_buypoint)
    assert "render_page_pairs" in runner_src
    assert "page_pairs" in runner_src


def test_render_page_pairs_cache_and_align(tmp_path, monkeypatch):
    """整頁出圖：同序對齊、磁碟快取二次極快；不准改買訊。"""
    import os
    import time

    from winrate_buypoint import render_page_pairs

    calls = {"n": 0}

    class _FakeEng:
        def __init__(self, *_a, **_k):
            pass

        def get_decision_card(self, sid, **_k):
            return {
                "stock_id": sid,
                "stock_name": f"名{sid}",
                "table": [],
            }

    def _fake_vz(sid, name, db_path, save_path, df=None, **kw):
        calls["n"] += 1
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(b"x" * 25_000)
        return save_path, "cap"

    def _fake_card_png(card, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"y" * 12_000)
        return path

    monkeypatch.setattr("wayne_navigator.NavigatorEngine", _FakeEng)
    monkeypatch.setattr("vol_zone_chart.render_volume_zone_result", _fake_vz)
    monkeypatch.setattr("wayne_navigator.render_decision_card_png", _fake_card_png)

    charts = str(tmp_path / "charts")
    rows = [
        {"stock_id": "2330", "stock_name": "台積電", "as_of": "20261002"},
        {"stock_id": "", "stock_name": "空"},
        {"stock_id": "2454", "stock_name": "聯發科", "as_of": "20261002"},
    ]
    t0 = time.perf_counter()
    a = render_page_pairs(
        str(tmp_path / "x.db"),
        rows,
        charts_dir=charts,
        uid="u1",
        as_of="20261002",
        reuse_cache=True,
    )
    cold = time.perf_counter() - t0
    assert len(a) == 3
    assert a[1] == ("", "", "空")
    assert a[0][0] and os.path.isfile(a[0][0]) and os.path.getsize(a[0][0]) >= 20000
    assert a[2][0] and a[2][1]
    assert calls["n"] == 2
    t0 = time.perf_counter()
    b = render_page_pairs(
        str(tmp_path / "x.db"),
        rows,
        charts_dir=charts,
        uid="u2",
        as_of="20261002",
        reuse_cache=True,
    )
    warm = time.perf_counter() - t0
    assert calls["n"] == 2  # 快取命中不再 prepare
    assert b[0][0] and b[2][1]
    assert warm < cold
    assert warm < 0.25


def test_live_rules_scan_kind_and_exclude_gates():
    """現行規則：ex5、無 live near_h20、空文、分頁 callback。"""
    from buy_exclude import REASON_NEAR_H20, buy_exclude_reasons
    from winrate_buypoint import (
        EMPTY_MSG,
        SCAN_KIND,
        next_page_callback,
        parse_next_page_callback,
    )
    from winrate_ai_priority import ELEC_INDUSTRIES

    assert SCAN_KIND == "card_lz_paint_ex5"
    assert EMPTY_MSG == "今天無勝率買點股票出現"
    assert "光電業" in ELEC_INDUSTRIES and "電機機械" in ELEC_INDUSTRIES
    # live 排除清單不准含 near_h20（靜默對照另軌）
    assert REASON_NEAR_H20 == "near_h20"
    import inspect

    src = inspect.getsource(buy_exclude_reasons)
    assert "REASON_DAY_TURNOVER_LOW" in src
    assert "REASON_NEAR_H20" not in src or "silent" in src.lower()
    # 更硬：函式體不 append near_h20
    assert "out.append(REASON_NEAR_H20)" not in src
    cb = next_page_callback(15)
    assert parse_next_page_callback(cb) == 15


def test_silent_remember_roster_and_filter(tmp_path, monkeypatch):
    from judge_tape import store_path
    from winrate_buypoint import (
        KIND_FILTER,
        KIND_ROSTER,
        save_winrate_roster,
        silent_remember_filter,
        silent_remember_roster,
    )
    from wayne_db import ensure_core_schema
    import json
    import sqlite3

    db = str(tmp_path / "wayne_market.db")
    ensure_core_schema(db)
    _seed_elec_universe(db, [("2330", "台積電", "半導體業")])
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO daily_quotes("
        "date,stock_id,stock_name,market,open,high,low,close,volume,"
        "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "20260930",
            "2330",
            "台積電",
            "TW",
            900,
            910,
            890,
            900,
            8000,
            400000,
            1.0,
            900,
            0,
            0,
            0,
        ),
    )
    conn.commit()
    conn.close()
    save_winrate_roster(
        db,
        "20260930",
        [{"stock_id": "2330", "stock_name": "台積電", "close": 900.0, "profit_pct": 0.4}],
    )
    n = silent_remember_roster(db, "20260930")
    assert n == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    row = conn.execute(
        "SELECT kind, sid, px, extra FROM live_judge WHERE kind=? AND as_of='20260930'",
        (KIND_ROSTER,),
    ).fetchone()
    conn.close()
    assert row and row[1] == "2330"
    extra = json.loads(row[3] or "{}")
    assert extra.get("why") == "leave_zero"
    assert extra.get("bucket_key") == KIND_ROSTER
    assert "o" in extra or "c" in extra

    nf = silent_remember_filter(
        db,
        roster_as_of="20260930",
        kept=[{"stock_id": "2330", "stock_name": "台積電", "live_price": 880.0}],
        filter_as_of="20261001",
    )
    assert nf == 1
    conn = sqlite3.connect(store)
    frow = conn.execute(
        "SELECT kind, sid, pick, extra FROM live_judge WHERE kind=? AND as_of='20261001'",
        (KIND_FILTER,),
    ).fetchone()
    conn.close()
    assert frow and frow[1] == "2330" and frow[2] == "20260930"
    fextra = json.loads(frow[3] or "{}")
    assert fextra.get("src_as_of") == "20260930"
    assert fextra.get("why") == "leave_zero_still"


def test_silent_catalog_lists_winrate():
    from button_silent_verify import BUTTON_CATALOG, snapshot_winrate_buypoint

    row = next(r for r in BUTTON_CATALOG if r["btn"] == "勝率買點")
    assert "winrate_buypoint" in row["kinds"]
    assert "winrate_filter" in row["kinds"]
    assert callable(snapshot_winrate_buypoint)