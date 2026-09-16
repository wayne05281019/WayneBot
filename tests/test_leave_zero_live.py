# -*- coding: utf-8 -*-
"""主選單剛離零：盤中現價複核獲利剛離零，★ 最多五檔，不寫未收盤。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import MENU_BTN_LEAVE_ZERO, WayneTelegramBot
from intent_router import parse_intent
from screening_engine import (
    LEAVE_ZERO_STAR_N,
    ScreeningEngine,
    _stock_card_html,
    mark_leave_zero_stars,
)
from screen_sessions import save_screen_session
from wayne_db import ensure_core_schema

AS_OF = "20260915"
NAMES = {
    "1101": "台泥",
    "1102": "亞泥",
    "1201": "味全",
    "1216": "統一",
    "1301": "台塑",
    "1303": "南亞",
    "1402": "遠東新",
}


def _seed_quotes(db: str, last_close: dict[str, float]) -> int:
    ensure_core_schema(db)
    start = datetime(2026, 8, 1)
    end = datetime.strptime(AS_OF, "%Y%m%d")
    n = 0
    conn = sqlite3.connect(db)
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        last = d == end
        for sid, name in NAMES.items():
            close = float(last_close.get(sid, 50.0) if last else 50.0)
            conn.execute(
                "INSERT OR REPLACE INTO daily_quotes("
                "date,stock_id,stock_name,market,open,high,low,close,volume,"
                "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ymd,
                    sid,
                    name,
                    "TW",
                    close,
                    close,
                    close,
                    close,
                    8000,
                    400000,
                    0.0 if not last else (close - 50.0) / 50.0 * 100.0,
                    close,
                ),
            )
            n += 1
        d += timedelta(days=1)
    conn.commit()
    conn.close()
    return n


def _save_buckets(db: str, *, golden: list[str], leave: list[str]) -> None:
    save_screen_session(
        db,
        AS_OF,
        "morning",
        {
            "golden_buy": [
                {"stock_id": sid, "stock_name": NAMES[sid], "close": 50.0}
                for sid in golden
            ],
            "leave_zero": [
                {"stock_id": sid, "stock_name": NAMES[sid], "close": 50.4}
                for sid in leave
            ],
        },
    )


def test_mark_leave_zero_stars_caps_at_five():
    rows = [{"stock_id": str(i)} for i in range(8)]
    out = mark_leave_zero_stars(rows)
    assert LEAVE_ZERO_STAR_N == 5
    assert [r["buy_star"] for r in out] == [True, True, True, True, True, False, False, False]
    few = mark_leave_zero_stars([{"stock_id": "1"}, {"stock_id": "2"}])
    assert [r["buy_star"] for r in few] == [True, True]


def test_stock_card_html_stars_name():
    starred = _stock_card_html(
        {"stock_id": "1101", "stock_name": "台泥", "buy_star": True, "close": 50.2},
        1,
        bucket_label="剛離零",
    )
    plain = _stock_card_html(
        {"stock_id": "1101", "stock_name": "台泥", "buy_star": False, "close": 50.2},
        2,
        bucket_label="剛離零",
    )
    assert "★" in starred
    assert "★" not in plain


def test_live_leave_zero_stars_top_five_and_does_not_write_unclosed(tmp_path, monkeypatch):
    db = str(tmp_path / "lz.db")
    before = _seed_quotes(db, {sid: 50.0 for sid in NAMES})
    golden = ["1101", "1102", "1201", "1216", "1301", "1303", "1402"]
    _save_buckets(db, golden=golden, leave=[])
    live = {
        "1101": {"price": 50.15, "yesterday_close": 50.0, "update_time": "13:10:00", "volume": 9000},
        "1102": {"price": 50.20, "yesterday_close": 50.0, "update_time": "13:10:00", "volume": 9000},
        "1201": {"price": 50.25, "yesterday_close": 50.0, "update_time": "13:10:00", "volume": 9000},
        "1216": {"price": 50.30, "yesterday_close": 50.0, "update_time": "13:10:00", "volume": 9000},
        "1301": {"price": 50.40, "yesterday_close": 50.0, "update_time": "13:10:00", "volume": 9000},
        "1303": {"price": 50.50, "yesterday_close": 50.0, "update_time": "13:10:00", "volume": 9000},
        "1402": {"price": 53.00, "yesterday_close": 50.0, "update_time": "13:10:00", "volume": 9000},
    }
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr("midday_review.fetch_mis_batch", lambda codes, db_path, timeout=12.0: live)
    engine = ScreeningEngine(db)
    rows = engine.screen_leave_zero_now(AS_OF)
    codes = [r["code"] for r in rows]
    assert "1402" not in codes
    assert codes[:5] == ["1101", "1102", "1201", "1216", "1301"]
    assert sum(1 for r in rows if r.get("buy_star")) == 5
    assert all(r.get("buy_star") for r in rows[:5])
    assert all(not r.get("buy_star") for r in rows[5:])
    assert all(r.get("live") for r in rows)
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM daily_quotes").fetchone()[0]
    mx = conn.execute("SELECT MAX(date) FROM daily_quotes").fetchone()[0]
    extra = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE date > ?", (AS_OF,)
    ).fetchone()[0]
    conn.close()
    assert n == before
    assert str(mx).replace("-", "")[:8] == AS_OF
    assert extra == 0


def test_after_hours_uses_official_leave_zero_only(tmp_path, monkeypatch):
    db = str(tmp_path / "lz2.db")
    _seed_quotes(db, {"1101": 50.4, "1102": 50.0})
    _save_buckets(db, golden=["1102"], leave=["1101"])
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: False)

    def _boom(*_a, **_k):
        raise AssertionError("收盤後不准抓未收盤 MIS")

    monkeypatch.setattr("midday_review.fetch_mis_batch", _boom)
    engine = ScreeningEngine(db)
    rows = engine.screen_leave_zero_now(AS_OF)
    codes = [r["code"] for r in rows]
    assert codes == ["1101"]
    assert rows[0].get("buy_star") is True
    assert "live" not in rows[0]


def test_lookup_like_row_has_watch_and_buy():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    row = bot._lookup_like_action_row("1101", "台泥")
    texts = [b.text for b in row]
    assert any("1101" in t or "台泥" in t for t in texts)
    assert "觀察" in texts
    assert "記買入" in texts
    assert [b.callback_data for b in row] == ["k:1101", "w:1101", "b:1101"]
    kb = bot._leave_zero_section_keyboard([("1101", "台泥")], include_menu=True)
    flat = [b.callback_data for r in kb.inline_keyboard for b in r]
    assert "k:1101" in flat and "w:1101" in flat and "b:1101" in flat


def test_intent_and_menu_label():
    assert MENU_BTN_LEAVE_ZERO == "剛脫離零"
    assert parse_intent("剛脫離零").kind == "leave_zero"
    assert parse_intent("剛離零").kind == "leave_zero"
    assert parse_intent("獲利剛剛脫離零").kind == "leave_zero"


def test_leave_zero_cmd_empty_cache_asks_for_screen(tmp_path):
    import asyncio

    db = str(tmp_path / "empty.db")
    ensure_core_schema(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot.screener = ScreeningEngine(db)
    bot._pending = {}
    bot._trade_running = set()
    bot._enter_main_menu = AsyncMock()
    bot._reply_menu = MagicMock(return_value=None)
    bot._actor_key = lambda message, uid="": f"{uid}"
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=1)
    msg.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=msg.from_user)
    with patch("live_quote.is_live_merge_window", return_value=True), patch(
        "trading_calendar.is_tw_equity_session", return_value=True
    ):
        asyncio.run(bot.leave_zero_cmd(upd, MagicMock()))
    html = "\n".join(
        str(c.args[0]) for c in msg.reply_html.await_args_list if c.args
    )
    assert "海選" in html
    assert "尚未就緒" in html
    assert "🟥" in html
    assert "剛脫離零" in html
    wait0 = str(msg.reply_text.await_args_list[0].args[0]) if msg.reply_text.await_args_list else ""
    assert "剛脫離零進行中" in wait0
    assert "□" in wait0 or "■" in wait0
    assert "｜" not in wait0
    assert "<pre>" not in wait0


def test_leave_zero_cmd_off_hours_points_to_screen(tmp_path):
    import asyncio

    db = str(tmp_path / "off.db")
    ensure_core_schema(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot.screener = ScreeningEngine(db)
    bot._pending = {}
    bot._trade_running = set()
    bot._enter_main_menu = AsyncMock()
    bot._reply_menu = MagicMock(return_value=None)
    bot._actor_key = lambda message, uid="": f"{uid}"
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=1)
    msg.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=msg.from_user)

    def _boom(*_a, **_k):
        raise AssertionError("非盤中不准掃現價")

    with patch("trading_calendar.is_tw_equity_session", return_value=False), patch(
        "screening_engine.ScreeningEngine.screen_leave_zero_now", _boom
    ):
        asyncio.run(bot.leave_zero_cmd(upd, MagicMock()))
    html = "\n".join(str(c.args[0]) for c in msg.reply_html.await_args_list if c.args)
    assert "目前非盤中交易時間" in html
    assert "不提供" in html
    assert "海選" in html
    assert "黃金買點" in html
    assert "09:00" in html
    kb = msg.reply_html.await_args.kwargs.get("reply_markup") or msg.reply_html.await_args[1].get(
        "reply_markup"
    )
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "screen" in datas
    assert not msg.reply_text.await_args_list


def test_stock_card_attention_flags_use_red_dot():
    html = _stock_card_html(
        {
            "stock_id": "2481",
            "stock_name": "強茂",
            "close": 168.5,
            "pct_change": 9.77,
            "q60r": 2.24,
            "volume": 62194,
            "chase_warning": True,
            "is_s_tier": True,
            "sector_inflow": True,
            "sector_flow_label": "剛輪到·半導體",
            "profit": 57.5,
        },
        7,
        bucket_label="站上季線",
    )
    assert "🔴<b>少追</b>" in html
    assert "🔴<b>S級</b>" in html
    assert "🔴<b>剛輪到·半導體</b>" in html
    assert "🔴<b>漲多了，今天別追</b>" in html or "別追" in html
    mild = _stock_card_html(
        {
            "stock_id": "3718",
            "stock_name": "中光電投控",
            "close": 64.9,
            "volume": 5315,
            "sector_inflow": True,
            "sector_flow_label": "剛輪到·光電",
            "profit": 8.9,
        },
        6,
        bucket_label="站上季線",
    )
    assert "🔴<b>剛輪到·光電</b>" in mild
    assert "少追" not in mild
