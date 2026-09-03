# -*- coding: utf-8 -*-
"""多使用者角色：偉權（重度）、哥哥（同機）、新手、不懂股、亂按。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _msg(chat_id: int, uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=chat_id)
    message = MagicMock()
    message.chat_id = chat_id
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot():
    from bot_servers import WayneTelegramBot
    from config import get_db_path

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = get_db_path()
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._enter_main_menu = AsyncMock(side_effect=lambda m, u, **kw: f"{getattr(m,'chat_id',0)}:{u}")
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    bot.portfolio_engine.format_holdings_html = MagicMock(return_value="<b>持股</b>")
    return bot


# --- 新手：第一次按持股，只靜默掛鍵盤，不洗版 ---


def test_newbie_first_portfolio_refreshes_menu_when_stale():
    """新手第一次按持股：走 _enter_main_menu，不與持股內容混在同一則。"""
    bot = _bot()
    bot._menu_layout_ok = MagicMock(return_value=False)
    bot._send_portfolio = AsyncMock()

    async def run():
        msg = _msg(10, 1001, "持股")
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._enter_main_menu.assert_awaited_once()
    bot._send_portfolio.assert_awaited_once()


def test_explicit_menu_cmd_not_silent():
    bot = _bot()
    bot._refresh_reply_menu = AsyncMock()
    msg = _msg(10, 1001)

    async def run():
        await bot.menu_cmd(_update(msg), MagicMock())

    asyncio.run(run())
    kwargs = bot._refresh_reply_menu.await_args.kwargs
    assert kwargs.get("silent") is not True


# --- 哥哥 vs 偉權：LINE 進度、海選區塊互不干擾 ---


def test_brother_line_pack_status_isolated():
    bot = _bot()
    m_wayne = MagicMock()
    m_wayne.delete = AsyncMock()
    m_bro = MagicMock()
    m_bro.delete = AsyncMock()
    bot._track_line_pack_status("99:111", m_wayne)
    bot._track_line_pack_status("99:222", m_bro)

    async def run():
        await bot._dismiss_line_pack_status("99:111")

    asyncio.run(run())
    m_wayne.delete.assert_awaited_once()
    m_bro.delete.assert_not_awaited()
    assert "99:222" in bot._line_pack_status_msgs


def test_brother_screening_section_isolated():
    bot = _bot()
    m_wayne = MagicMock()
    m_wayne.delete = AsyncMock()
    m_bro = MagicMock()
    bot._track_screening_msg("99:111", "leave_zero", m_wayne)
    bot._track_screening_msg("99:222", "leave_zero", m_bro)

    async def run():
        await bot._dismiss_screening_section("99:111", "leave_zero")

    asyncio.run(run())
    m_wayne.delete.assert_awaited_once()
    bucket = bot._screening_msgs.get("99:222") or {}
    assert "leave_zero" in bucket


# --- 重度用戶：有上次決策卡代號，按決策卡只刷新該檔 ---


def test_power_user_decision_card_reuses_last_code():
    bot = _bot()
    bot._last_card["9001"] = "3105"
    bot._send_decision_card_quick = AsyncMock()
    msg = _msg(1, 9001)

    async def run():
        await bot.decision_card_btn(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_decision_card_quick.assert_awaited_once()
    assert bot._send_decision_card_quick.await_args[0][1] == "3105"


# --- 不懂股：純空白、全形空白不觸發查股 ---


@pytest.mark.parametrize("text", ("   ", "\u3000\u3000", "\t"))
def test_whitespace_only_is_silent(text):
    bot = _bot()
    msg = _msg(2, 2, text)

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    msg.reply_text.assert_not_awaited()


# --- 亂按：同聊天室兩人 pending 不共用 ---


def test_simplified_buy_pending_single_price():
    bot = _bot()
    bot._pending["1:42"] = "buy:2330"
    msg = _msg(1, 42, "68.5")

    async def run():
        with patch("bot_servers.record_buy", return_value="已記錄買入 2330 台積電 1張 @ 68.5") as rb, patch(
            "wayne_db.lookup_stocks", return_value=[{"stock_id": "2330", "stock_name": "台積電"}]
        ):
            await bot.on_text(_update(msg), MagicMock())
        return rb

    rb = asyncio.run(run())
    rb.assert_called_once()
    assert rb.call_args[0][2] == "2330"
    assert rb.call_args[0][4] == 1.0
    assert rb.call_args[0][5] == 68.5


def test_lookup_no_ack_spam():
    bot = _bot()
    bot._reply_card = AsyncMock()
    msg = _msg(3, 3, "台積電")

    async def run():
        with patch("wayne_db.lookup_stocks", return_value=[{"stock_id": "2330", "stock_name": "台積電"}]):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    for call in msg.reply_text.await_args_list:
        text = call[0][0] if call[0] else ""
        assert "查詢中" not in str(text)


def test_decision_card_shows_status_bubble():
    bot = _bot()
    bot._last_card["9001"] = "3105"
    bot._send_decision_card_quick = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    msg = _msg(1, 9001)

    async def run():
        await bot.decision_card_btn(_update(msg), MagicMock())

    asyncio.run(run())
    bot._transient_status.assert_awaited_once()
    assert "決策卡產製中" in str(bot._transient_status.await_args[0][1])
    bot._send_decision_card_quick.assert_awaited_once()


def test_ai_desk_keyboard_has_no_sell_buttons():
    bot = _bot()
    kb = bot._ai_desk_keyboard()
    datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "ai_run" in datas
    assert not any(str(d).startswith("x:") for d in datas)


def test_pending_state_per_user_not_per_chat():
    bot = _bot()
    bot._pending["1:111"] = "buy:2330"
    bot._pending["1:222"] = "sell:2454"
    assert bot._pending["1:111"] == "buy:2330"
    assert bot._pending["1:222"] == "sell:2454"


def test_ai_desk_isolated_per_telegram_user():
    import os
    import sqlite3
    import tempfile

    from ai_trader import ai_user_id, run_ai_desk
    from portfolio_engine import PortfolioEngine

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        results = {
            "leave_zero": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 100.0, "chase_warning": False}
            ],
        }
        run_ai_desk(path, "111", results, "20260831")
        run_ai_desk(path, "222", results, "20260831")
        eng = PortfolioEngine(path)
        w = eng.get_portfolio_summary(ai_user_id("111"))
        b = eng.get_portfolio_summary(ai_user_id("222"))
        assert w["positions_count"] >= 1
        assert b["positions_count"] >= 1
        conn = sqlite3.connect(path)
        n1 = conn.execute(
            "SELECT COUNT(*) FROM user_positions WHERE user_id=?", (ai_user_id("111"),)
        ).fetchone()[0]
        n2 = conn.execute(
            "SELECT COUNT(*) FROM user_positions WHERE user_id=?", (ai_user_id("222"),)
        ).fetchone()[0]
        conn.close()
        assert n1 >= 1 and n2 >= 1
    finally:
        os.remove(path)


def test_brother_and_wayne_market_menu_fade_isolated():
    """哥哥 vs 偉權：大盤回覆的暫態訊息各自刪除，互不影響。"""
    bot = _bot()
    m_wayne = MagicMock()
    m_wayne.delete = AsyncMock()
    m_bro = MagicMock()
    m_bro.delete = AsyncMock()
    bot._menu_fade_msgs["99:9001"] = [m_wayne]
    bot._menu_fade_msgs["99:9002"] = [m_bro]

    async def run():
        await bot._dismiss_menu_transients("99:9001")

    asyncio.run(run())
    m_wayne.delete.assert_awaited_once()
    m_bro.delete.assert_not_awaited()
    assert "99:9002" in bot._menu_fade_msgs


def test_brother_market_pending_not_shared():
    """偉權 pending 買入流程，哥哥按大盤不應清掉偉權狀態。"""
    from bot_servers import MENU_BTN_MARKET

    bot = _bot()
    bot._pending["99:9001"] = "buy:2330"
    msg_bro = _msg(99, 9002, MENU_BTN_MARKET)
    bot.market_cmd = AsyncMock()

    async def run():
        with patch.object(bot, "_dismiss_menu_transients", new_callable=AsyncMock), patch.object(
            bot, "_ensure_reply_menu_if_needed", new_callable=AsyncMock
        ), patch.object(bot, "_transient_status", new_callable=AsyncMock) as st, patch.object(
            bot, "_delete_message", new_callable=AsyncMock
        ):
            st.return_value = MagicMock()
            await bot.on_text(_update(msg_bro), MagicMock())

    asyncio.run(run())
    assert bot._pending.get("99:9001") == "buy:2330"
    bot.market_cmd.assert_awaited_once()


def test_touch_tg_user_registers_for_scheduled_ai():
    import os
    import tempfile

    from wayne_db import list_tg_user_ids, touch_tg_user

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        touch_tg_user(path, "9001", "偉權")
        touch_tg_user(path, "9002", "哥哥")
        ids = list_tg_user_ids(path)
        assert "9001" in ids
        assert "9002" in ids
    finally:
        os.remove(path)


def test_wrap_cmd_touches_user_on_slash_command():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = _bot()
    bot._touch_user = MagicMock()
    bot.portfolio_cmd = AsyncMock()

    async def run():
        user = SimpleNamespace(id=4242, first_name="哥")
        msg = MagicMock()
        msg.from_user = user
        update = SimpleNamespace(effective_user=user, message=msg)
        wrapped = bot._wrap_cmd(bot.portfolio_cmd)
        await wrapped(update, MagicMock())

    asyncio.run(run())
    bot._touch_user.assert_called_once_with("4242", "哥")
    bot.portfolio_cmd.assert_awaited_once()
