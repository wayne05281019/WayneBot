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
    _leave_zero_left_n_ago,
    _leave_zero_pick_ok,
    _stock_card_html,
    mark_leave_zero_stars,
)
from screen_sessions import save_screen_session, session_as_of_n_ago
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


def test_leave_days_pick_not_capped_at_five_pct():
    assert _leave_zero_pick_ok("ago", 0.1)
    assert _leave_zero_pick_ok("ago", 5.0)
    assert _leave_zero_pick_ok("ago", 53.0)
    assert not _leave_zero_pick_ok("ago", 0.0)
    assert _leave_zero_pick_ok("zero", 0.0)
    assert not _leave_zero_pick_ok("zero", 0.1)
    import pandas as pd

    first_leave_yest = pd.Series([0.0, 0.0, 0.8, 1.2])
    assert _leave_zero_left_n_ago(first_leave_yest, 1)
    assert not _leave_zero_left_n_ago(first_leave_yest, 2)
    still_zero = pd.Series([0.0, 0.0, 0.0, 0.0])
    assert not _leave_zero_left_n_ago(still_zero, 1)
    from decision_card_signals import LEAVE_ZERO_SCREEN_MAX_PCT

    assert LEAVE_ZERO_SCREEN_MAX_PCT == 5.0


def test_mark_leave_zero_stars_caps_at_five():
    rows = [
        {"stock_id": "1", "profit_pct": 1.0, "is_s_tier": True},
        {"stock_id": "2", "profit_pct": 1.0},
        {"stock_id": "3", "profit_pct": 12.0, "chase_warning": True},
    ]
    out = mark_leave_zero_stars(rows)
    assert LEAVE_ZERO_STAR_N == 5
    assert [r["entry_stars"] for r in out] == [5, 4, 0]
    assert [r["buy_star"] for r in out] == [True, False, False]
    few = mark_leave_zero_stars([{"stock_id": "1"}, {"stock_id": "2"}])
    assert all(r["entry_stars"] == 3 and r["buy_star"] is False for r in few)


def test_stock_card_html_stars_name():
    starred = _stock_card_html(
        {
            "stock_id": "1101",
            "stock_name": "台泥",
            "close": 50.2,
            "profit_pct": 1.0,
            "is_s_tier": True,
        },
        1,
        bucket_label="剛離零",
    )
    plain = _stock_card_html(
        {"stock_id": "1101", "stock_name": "台泥", "close": 50.2, "golden_buy": True},
        2,
        bucket_label="重點觀察",
    )
    assert "★★★★★" in starred
    assert "★★★★★" not in plain
    assert "☆" in plain


def test_trend_not_up_caps_stars_and_shows_label():
    from screening_engine import mark_leave_zero_stars

    capped = mark_leave_zero_stars(
        [
            {
                "stock_id": "1201",
                "profit_pct": 1.0,
                "is_s_tier": True,
                "trend_up_now": False,
                "trend_now_label": "趨勢還沒向上",
            }
        ]
    )
    assert capped[0]["entry_stars"] <= 4
    assert capped[0]["buy_star"] is False
    html = _stock_card_html(capped[0], 1, bucket_label="剛離1")
    assert "趨勢還沒向上" in html
    up = _stock_card_html(
        {
            "stock_id": "1101",
            "stock_name": "台泥",
            "close": 51.0,
            "profit_pct": 1.0,
            "trend_up_now": True,
            "trend_now_label": "趨勢已向上",
        },
        1,
        bucket_label="剛離1",
    )
    assert "趨勢已向上" in up


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
    assert all(1 <= int(r.get("entry_stars") or 0) <= 5 for r in rows)
    html0 = _stock_card_html(rows[0], 1, bucket_label="剛離零")
    assert "★" in html0 or "☆" in html0
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
    assert 3 <= int(rows[0].get("entry_stars") or 0) <= 5
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
    assert [b.callback_data for b in kb.inline_keyboard[0]] == ["lz:1", "lz:2", "lz:3"]
    assert "lz:0" not in flat and "lz:z" not in flat
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert texts[:3] == ["剛離1", "剛離2", "剛離3"]


def test_dongzhu_keyboard_is_industry_temp_intro():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    rows = bot._dongzhu_pick_rows("2449", "京元電子", win_btn="勝71%")
    assert len(rows) == 1
    assert len(rows[0]) == 4
    texts = [b.text for r in rows for b in r]
    assert any("2449" in t for t in texts)
    assert any("勝71%" in t for t in texts)
    assert "觀察" not in texts
    assert "記買入" not in texts
    assert texts[1:] == ["產業", "高低溫度卡", "介紹卡"]
    data = [b.callback_data for r in rows for b in r]
    assert data == ["dzq:2449", "n:2449", "d:2449", "i:2449"]
    kb = bot._dongzhu_picks_keyboard(
        [("2449", "京元電子", "勝71%"), ("6257", "矽格", "")]
    )
    assert all(len(r) == 4 for r in kb.inline_keyboard)
    flat_txt = [b.text for r in kb.inline_keyboard for b in r]
    assert any("勝71%" in t for t in flat_txt)
    assert not any("勝71%" in t and "6257" in t for t in flat_txt)
    flat = [b.callback_data for r in kb.inline_keyboard for b in r]
    assert "i:6257" in flat and "n:6257" in flat and "d:6257" in flat
    hold_kb = bot._dongzhu_hold_keyboard("2449")
    hold_txt = [b.text for r in hold_kb.inline_keyboard for b in r]
    assert hold_txt == ["產業", "高低溫度卡", "介紹卡"]


def test_dongzhu_hits_keyboard_stays_in_dongzhu():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._dongzhu_hits_keyboard(
        [
            {"stock_id": "1303", "stock_name": "南亞"},
            {"stock_id": "2408", "stock_name": "南亞科"},
        ]
    )
    datas = [b.callback_data for r in kb.inline_keyboard for b in r]
    assert datas == ["dzq:1303", "dzq:2408"]
    assert not any(d.startswith("k:") or d.startswith("w:") for d in datas)


def test_dongzhu_picker_callback_opens_hold_not_card():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._actor_key = lambda message, uid="": f"{uid}"
    bot._send_dongzhu_hold = AsyncMock()
    bot._send_card_to = AsyncMock()
    q = SimpleNamespace(
        data="dzq:1303",
        from_user=SimpleNamespace(id=11),
        message=MagicMock(),
        answer=AsyncMock(),
    )
    asyncio.run(bot._on_callback_bound(None, None, q, "11"))
    q.answer.assert_awaited()
    bot._send_dongzhu_hold.assert_awaited()
    assert bot._send_dongzhu_hold.await_args.args[1] == "1303"
    bot._send_card_to.assert_not_awaited()
    assert bot._pending.get("11") == "dongzhu"


def test_intent_and_menu_label():
    from bot_servers import leave_zero_pick_from_text

    assert MENU_BTN_LEAVE_ZERO == "剛脫離零"
    assert parse_intent("剛脫離零").kind == "leave_zero"
    assert parse_intent("剛離零").kind == "leave_zero"
    assert parse_intent("獲利剛剛脫離零").kind == "leave_zero"
    assert parse_intent("剛離1").kind == "leave_zero"
    assert parse_intent("剛離3").kind == "leave_zero"
    assert parse_intent("獲利為零").kind == "leave_zero"
    assert parse_intent("脫離1").kind == "leave_zero"
    assert parse_intent("脫離3").kind == "leave_zero"
    assert parse_intent("剛為零").kind == "leave_zero"
    assert leave_zero_pick_from_text("剛脫離零") == ""
    assert leave_zero_pick_from_text("剛離2") == "2"
    assert leave_zero_pick_from_text("脫離2") == "2"
    assert leave_zero_pick_from_text("獲利為零") == "z"
    assert leave_zero_pick_from_text("剛為零") == "z"


def _bare_leave_zero_bot(db: str) -> WayneTelegramBot:
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot.screener = ScreeningEngine(db)
    bot._pending = {}
    bot._trade_running = set()
    bot._enter_main_menu = AsyncMock()
    bot._reply_menu = MagicMock(return_value=None)
    bot._start_plain_wait = AsyncMock(return_value=(None, None, None))
    bot._stop_plain_wait = AsyncMock()
    bot._actor_key = lambda message, uid="": f"{uid}"
    return bot


def test_leave_zero_cmd_opens_profit_zero(tmp_path):
    import asyncio

    db = str(tmp_path / "empty.db")
    ensure_core_schema(db)
    bot = _bare_leave_zero_bot(db)
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=1)
    msg.text = "剛脫離零"
    msg.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=msg.from_user)

    with patch("live_quote.is_live_merge_window", return_value=True), patch(
        "trading_calendar.is_tw_equity_session", return_value=True
    ), patch(
        "screening_engine.ScreeningEngine.screen_leave_zero_pick",
        return_value=[],
    ) as pick_fn:
        asyncio.run(bot.leave_zero_cmd(upd, MagicMock()))
    assert pick_fn.call_args.kwargs.get("pick") == "z"
    html = "\n".join(
        str(c.args[0]) for c in msg.reply_html.await_args_list if c.args
    )
    assert "獲利為零" in html
    assert "先觀察" in html
    assert "🟥" not in html
    kb = msg.reply_html.await_args.kwargs.get("reply_markup") or msg.reply_html.await_args[1].get(
        "reply_markup"
    )
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert datas == ["lz:1", "lz:2", "lz:3"]
    assert bot._start_plain_wait.await_args_list


def test_leave_zero_cmd_empty_cache_asks_for_screen(tmp_path):
    import asyncio

    db = str(tmp_path / "empty.db")
    ensure_core_schema(db)
    bot = _bare_leave_zero_bot(db)
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=1)
    msg.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    msg.reply_html = AsyncMock()
    with patch("live_quote.is_live_merge_window", return_value=True), patch(
        "trading_calendar.is_tw_equity_session", return_value=True
    ):
        asyncio.run(bot._run_leave_zero_now(msg, pick="0"))
    html = "\n".join(
        str(c.args[0]) for c in msg.reply_html.await_args_list if c.args
    )
    assert "海選" in html
    assert "尚未就緒" in html
    assert "🟥" not in html
    assert "剛離" in html
    kb = msg.reply_html.await_args.kwargs.get("reply_markup") or msg.reply_html.await_args[1].get(
        "reply_markup"
    )
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert datas == ["lz:1", "lz:2", "lz:3"]


def test_leave_zero_cmd_off_hours_still_picks_days(tmp_path):
    import asyncio

    db = str(tmp_path / "off.db")
    ensure_core_schema(db)
    bot = _bare_leave_zero_bot(db)
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=1)
    msg.text = "剛脫離零"
    msg.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=msg.from_user)

    with patch("trading_calendar.is_tw_equity_session", return_value=False), patch(
        "screening_engine.ScreeningEngine.screen_leave_zero_pick",
        return_value=[],
    ) as pick_fn:
        asyncio.run(bot.leave_zero_cmd(upd, MagicMock()))
    assert pick_fn.call_args.kwargs.get("pick") == "z"
    html = "\n".join(str(c.args[0]) for c in msg.reply_html.await_args_list if c.args)
    assert "目前非盤中" in html
    assert "不抓現價" in html
    assert "剛離1" in html
    assert "獲利為零" in html
    assert "🟥" not in html
    kb = msg.reply_html.await_args.kwargs.get("reply_markup") or msg.reply_html.await_args[1].get(
        "reply_markup"
    )
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert datas == ["lz:1", "lz:2", "lz:3"]
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


def _set_close(db: str, sid: str, ymd: str, close: float) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE daily_quotes SET close=?, open=?, high=?, low=?, avg_price=? "
        "WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?",
        (close, close, close, close, close, sid, ymd),
    )
    conn.commit()
    conn.close()


def test_leave_zero_pick_days_and_at_zero(tmp_path, monkeypatch):
    db = str(tmp_path / "lz_days.db")
    _seed_quotes(
        db,
        {"1101": 53.0, "1102": 50.4, "1201": 50.6, "1303": 50.0, "1216": 53.0},
    )
    _set_close(db, "1101", "20260914", 50.4)
    _set_close(db, "1201", "20260913", 50.4)
    _set_close(db, "1201", "20260914", 50.5)
    save_screen_session(
        db,
        "20260913",
        "morning",
        {"leave_zero": [{"stock_id": "1201", "stock_name": "味全", "close": 50.4}]},
    )
    save_screen_session(
        db,
        "20260914",
        "morning",
        {"leave_zero": [{"stock_id": "1101", "stock_name": "台泥", "close": 50.4}]},
    )
    save_screen_session(
        db,
        AS_OF,
        "morning",
        {
            "leave_zero": [{"stock_id": "1102", "stock_name": "亞泥", "close": 50.4}],
            "golden_buy": [
                {"stock_id": "1303", "stock_name": "南亞", "close": 50.0},
                {"stock_id": "1216", "stock_name": "統一", "close": 53.0},
            ],
        },
    )
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: False)
    engine = ScreeningEngine(db)
    assert session_as_of_n_ago(db, AS_OF, 1) == "20260914"
    assert session_as_of_n_ago(db, AS_OF, 2) == "20260913"
    just = [r["code"] for r in engine.screen_leave_zero_pick(AS_OF, pick="0")]
    d1 = [r["code"] for r in engine.screen_leave_zero_pick(AS_OF, pick="1")]
    d2 = [r["code"] for r in engine.screen_leave_zero_pick(AS_OF, pick="2")]
    zero = engine.screen_leave_zero_pick(AS_OF, pick="z")
    zero_codes = [r["code"] for r in zero]
    assert just == ["1102"]
    assert d1 == ["1101"]
    assert d2 == ["1201"]
    assert "1303" in zero_codes
    assert "1301" in zero_codes
    assert "1402" in zero_codes
    assert "1216" not in zero_codes
    assert "1101" not in zero_codes
    assert all(int(r.get("entry_stars") or 0) <= 4 for r in zero)
    over = engine.screen_leave_zero_pick(AS_OF, pick="1")
    assert over and float(over[0]["profit_pct"]) > 5.0


def test_live_leave_days_keeps_band_and_does_not_write(tmp_path, monkeypatch):
    db = str(tmp_path / "lz_live_days.db")
    before = _seed_quotes(db, {"1101": 50.5})
    _set_close(db, "1101", "20260914", 50.4)
    save_screen_session(
        db,
        "20260914",
        "morning",
        {"leave_zero": [{"stock_id": "1101", "stock_name": "台泥", "close": 50.4}]},
    )
    save_screen_session(
        db,
        AS_OF,
        "morning",
        {"leave_zero": [], "golden_buy": []},
    )
    live = {
        "1101": {
            "price": 50.55,
            "yesterday_close": 50.5,
            "update_time": "13:10:00",
            "volume": 9000,
        }
    }
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr("midday_review.fetch_mis_batch", lambda codes, db_path, timeout=12.0: live)
    engine = ScreeningEngine(db)
    rows = engine.screen_leave_zero_pick(AS_OF, pick="1")
    assert [r["code"] for r in rows] == ["1101"]
    assert rows[0].get("live")
    live["1101"]["price"] = 50.0
    gone = engine.screen_leave_zero_pick(AS_OF, pick="1")
    assert gone == []
    live["1101"]["price"] = 53.0
    ran = engine.screen_leave_zero_pick(AS_OF, pick="1")
    assert [r["code"] for r in ran] == ["1101"]
    assert float(ran[0]["profit_pct"]) > 5.0
    conn = sqlite3.connect(db)
    extra = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE REPLACE(CAST(date AS TEXT),'-','') > ?",
        (AS_OF,),
    ).fetchone()[0]
    n = conn.execute("SELECT COUNT(*) FROM daily_quotes").fetchone()[0]
    conn.close()
    assert extra == 0
    assert n == before


def _seed_one_listed(db: str, sid: str, name: str, last_close: float, *, market: str = "TW") -> None:
    ensure_core_schema(db)
    start = datetime(2026, 8, 1)
    end = datetime.strptime(AS_OF, "%Y%m%d")
    conn = sqlite3.connect(db)
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        last = d == end
        close = float(last_close if last else 50.0 if sid != "8069" else 100.0)
        if sid == "8069":
            close = 100.0
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes("
            "date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ymd,
                sid,
                name,
                market,
                close,
                close,
                close,
                close,
                8000,
                400000,
                0.0,
                close,
            ),
        )
        d += timedelta(days=1)
    conn.commit()
    conn.close()


def _seed_emerging_leave_yesterday(db: str) -> None:
    from emerging_quotes import ensure_emerging_table

    ensure_core_schema(db)
    ensure_emerging_table(db)
    start = datetime(2026, 8, 1)
    end = datetime.strptime(AS_OF, "%Y%m%d")
    leave_day = "20260914"
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO stock_universe("
        "stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at)"
        " VALUES (?,?,?,?,?,?,?)",
        ("3595", "山太士", "EM", "STOCK", "", 1, AS_OF),
    )
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        if ymd == leave_day:
            close = 10.08
        elif ymd == AS_OF:
            close = 10.10
        else:
            close = 10.00
        conn.execute(
            "INSERT OR REPLACE INTO emerging_quotes("
            "date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ymd,
                "3595",
                "山太士",
                "EM",
                close,
                close,
                close,
                close,
                120,
                1200,
                0.0,
                close,
                "tpex_esb_csv",
            ),
        )
        # 上市櫃撞號：若誤用 daily_quotes 會變成今天才離零，剛離1找不到。
        listed_close = 20.0 if ymd == AS_OF else 10.0
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes("
            "date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ymd,
                "3595",
                "撞號",
                "TW",
                listed_close,
                listed_close,
                listed_close,
                listed_close,
                8000,
                400000,
                0.0,
                listed_close,
            ),
        )
        d += timedelta(days=1)
    conn.commit()
    conn.close()


def test_leave_zero_pick_scans_profit_including_emerging(tmp_path, monkeypatch):
    db = str(tmp_path / "lz_profit_scan.db")
    ensure_core_schema(db)
    _seed_one_listed(db, "8069", "元太", 100.0)
    _seed_one_listed(db, "0050", "元大台灣50", 50.0)
    _seed_emerging_leave_yesterday(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO stock_universe("
        "stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at)"
        " VALUES (?,?,?,?,?,?,?)",
        ("8069", "元太", "TW", "STOCK", "", 1, AS_OF),
    )
    conn.execute(
        "INSERT OR REPLACE INTO stock_universe("
        "stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at)"
        " VALUES (?,?,?,?,?,?,?)",
        ("0050", "元大台灣50", "TW", "ETF_PASSIVE", "", 1, AS_OF),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: False)
    engine = ScreeningEngine(db)
    zero = [r["code"] for r in engine.screen_leave_zero_pick(AS_OF, pick="z")]
    d1 = engine.screen_leave_zero_pick(AS_OF, pick="1")
    d1_codes = [r["code"] for r in d1]
    d2 = [r["code"] for r in engine.screen_leave_zero_pick(AS_OF, pick="2")]
    assert "8069" in zero
    assert "3595" not in zero
    assert "0050" not in zero
    assert d1_codes == ["3595"]
    assert d1[0]["name"] == "山太士"
    assert d1[0].get("quote_source") == "emerging_quotes"
    assert d1[0].get("trend_now_label")
    assert "3595" not in d2
    assert "8069" not in d1_codes
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr("midday_review.fetch_mis_batch", lambda *a, **k: {})
    live_d1 = [r["code"] for r in engine.screen_leave_zero_pick(AS_OF, pick="1")]
    assert live_d1 == ["3595"]
    live_zero = [r["code"] for r in engine.screen_leave_zero_pick(AS_OF, pick="z")]
    assert "8069" in live_zero


def test_leave_days_keeps_no_trend_and_sorts_up_first(tmp_path, monkeypatch):
    import screening_engine as se

    db = str(tmp_path / "lz_trend.db")
    _seed_quotes(db, {"1101": 51.0, "1201": 50.8})
    _set_close(db, "1101", "20260914", 50.4)
    _set_close(db, "1201", "20260914", 50.4)
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: False)
    real = se._leave_zero_trend_ok

    def fake(info):
        sid = str(info.get("stock_id") or "")
        if sid == "1101":
            return True
        if sid == "1201":
            return False
        return real(info)

    monkeypatch.setattr("screening_engine._leave_zero_trend_ok", fake)
    engine = ScreeningEngine(db)
    rows = engine.screen_leave_zero_pick(AS_OF, pick="1")
    codes = [r["code"] for r in rows]
    assert "1101" in codes and "1201" in codes
    assert codes.index("1101") < codes.index("1201")
    by = {r["code"]: r for r in rows}
    assert by["1101"]["trend_up_now"] is True
    assert by["1201"]["trend_up_now"] is False
    assert int(by["1201"].get("entry_stars") or 0) <= 4
    assert by["1201"].get("buy_star") is False
    assert "趨勢已向上" in _stock_card_html(by["1101"], 1, bucket_label="剛離1")
    assert "趨勢還沒向上" in _stock_card_html(by["1201"], 2, bucket_label="剛離1")
    from decision_card_signals import LEAVE_ZERO_SCREEN_MAX_PCT

    assert LEAVE_ZERO_SCREEN_MAX_PCT == 5.0
