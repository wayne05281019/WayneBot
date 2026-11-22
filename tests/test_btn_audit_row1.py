# -*- coding: utf-8 -*-
"""第一排七鍵＋查股介紹／高低巡檢 A：接線／不沉默／非買訊／子桶／來源對齊。

範圍：勝率買點、海選（含子桶／興櫃）、持股、加入觀察、飆大（對話／離開）、
台股大盤（文敘；三窗只核對不准改）、資金輪動；打代號介紹圖＋高低卡圖下鈕。
不准假數、未收當收、搶 getUpdates。
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import (
    MENU_BTN_BIAOKE,
    MENU_BTN_FLOW,
    MENU_BTN_LEAVE_BIAOKE,
    MENU_BTN_MARKET,
    MENU_BTN_SCREEN,
    MENU_BTN_WATCH,
    MENU_BTN_WINRATE,
    MENU_ROW1,
    WayneTelegramBot,
)


ROW1_LABELS = (
    MENU_BTN_WINRATE,
    MENU_BTN_SCREEN,
    "持股",
    MENU_BTN_WATCH,
    MENU_BTN_BIAOKE,
    MENU_BTN_MARKET,
    MENU_BTN_FLOW,
)


def test_menu_row1_seven_keys_order():
    assert len(MENU_ROW1) == 7
    assert MENU_ROW1 == ROW1_LABELS
    assert MENU_BTN_WINRATE == "勝率買點"
    assert MENU_BTN_SCREEN == "海選"
    assert MENU_BTN_WATCH == "加入觀察"
    assert MENU_BTN_BIAOKE == "飆大"
    assert MENU_BTN_MARKET == "台股大盤"
    assert MENU_BTN_FLOW == "資金輪動"
    assert MENU_BTN_LEAVE_BIAOKE == "離開飆大"


def test_row1_heavy_paths_have_wait_bubble():
    """重活入口必須有進行中泡泡；畫面不能沉默。"""
    wr = inspect.getsource(WayneTelegramBot._run_winrate_buypoint)
    assert "勝率買點進行中" in wr
    assert "_start_plain_wait" in wr

    screen = inspect.getsource(WayneTelegramBot._run_manual_screening)
    assert "_screening_progress_text" in screen
    assert screen.index("reply_text") < screen.index("_begin_actor_op")

    em = inspect.getsource(WayneTelegramBot._run_emerging_screening)
    assert "興櫃海選進行中" in em
    assert "_start_plain_wait" in em

    port = inspect.getsource(WayneTelegramBot.portfolio_cmd)
    assert "持股進行中" in port
    assert "_start_plain_wait" in port

    watch = inspect.getsource(WayneTelegramBot.watch_cmd)
    assert "觀察進行中" in watch
    assert "_start_plain_wait" in watch

    bk = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "_start_plain_wait" in bk

    market = inspect.getsource(WayneTelegramBot.market_cmd)
    assert "大盤進行中" in market
    assert "_start_plain_wait" in market

    flow = inspect.getsource(WayneTelegramBot.flow_cmd)
    assert "資金輪動進行中" in flow
    assert "_start_plain_wait" in flow


def test_market_page_no_trio_charts_wait_aligned():
    """大盤文敘可核；三窗只核對不准改 code——頁面不准再掛教具三窗。

    進度泡泡 rest 不准再寫「遠／近／超近窗」（已改走波浪位階）。
    """
    page = inspect.getsource(WayneTelegramBot._send_market_page)
    cmd = inspect.getsource(WayneTelegramBot.market_cmd)
    assert "_send_market_wave_charts" not in page
    assert "_send_market_wave_charts" not in cmd
    assert "_send_market_session_cards" in page
    assert "波浪位階" in page
    assert "遠／近／超近窗" not in page
    assert "遠／近／超近窗" not in cmd
    assert "盤後對照圖" in page
    assert "盤後對照圖" in cmd
    # 三窗實作仍在波浪鍵（只核對存在，本巡檢不准改）
    wave_charts = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "遠窗" in wave_charts or "第1張遠窗" in wave_charts
    wave_btn = inspect.getsource(WayneTelegramBot.wave_status_cmd)
    assert "_send_market_wave_charts" in wave_btn


def test_emerging_screening_payload_keeps_ma60_lower():
    """興櫃海選子桶：execute 有紅箭確認 → payload 不准漏 ma60_lower。"""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    result = {
        "universe": "EM",
        "as_of": "20261121",
        "leave_zero": [
            {"stock_id": "1260", "stock_name": "富味鄉", "close": 40.0}
        ],
        "ma60_lower": [
            {"stock_id": "3595", "stock_name": "山太士", "close": 12.0}
        ],
        "golden_buy": [
            {"stock_id": "1260", "stock_name": "富味鄉", "close": 40.0}
        ],
        "n": 3,
    }
    parts = bot._screening_payload(result)
    keys = {str(p.get("screen_pack_id") or p.get("line_pack_id") or "") for p in parts}
    assert "leave_zero" in keys
    assert "ma60_lower" in keys
    blob = "\n".join(str(p.get("html") or "") for p in parts)
    assert "興櫃海選" in blob
    assert "紅箭確認" in blob
    assert "3595" in blob
    # 還在零只觀察、不單獨成桶（併進黃金買點欄）
    assert "golden_buy" not in keys


def test_listed_screen_buckets_entry_only_two():
    """上市櫃海選畫面只出黃金買點＋紅箭確認；還在零觀察不當獨立買訊桶。"""
    from screening_engine import LINE_BUCKET_TITLES, SCREEN_PUSH_SPECS

    keys = [s[0] for s in SCREEN_PUSH_SPECS]
    assert keys == ["leave_zero", "ma60_lower"]
    assert LINE_BUCKET_TITLES["leave_zero"] == "黃金買點"
    assert LINE_BUCKET_TITLES["ma60_lower"] == "紅箭確認"
    assert LINE_BUCKET_TITLES["golden_buy"] == "還在零"
    hints = " ".join(str(s[3]) for s in SCREEN_PUSH_SPECS)
    assert "觀察不是買" in hints or "還在零" in hints


def test_biaoke_enter_leave_no_invent_price_guards():
    """飆大＝對話；離開鍵還主選單；不准發明沒說過的價（材料庫硬規則）。"""
    page = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "answer_biaoke" in page or "format_latest_focus" in page
    assert "_show_biaoke_leave_key" in page or "離開飆大" in page
    leave = inspect.getsource(WayneTelegramBot._leave_biaoke)
    assert "已離開" in leave
    assert "飆大" in leave
    enter = inspect.getsource(WayneTelegramBot._enter_biaoke_chat)
    assert "biaoke" in enter
    # 硬規則在 live／chain／level_learn（話筒路徑讀同一套）
    import biaoke_live
    import biaoke_chain

    live_src = inspect.getsource(biaoke_live)
    chain_src = inspect.getsource(biaoke_chain)
    assert "不准新價" in live_src or "沒說過的價" in live_src
    assert "不准新價" in chain_src
    assert "個股不數浪" in live_src or "個股不數浪" in chain_src


def test_lookup_intro_hub_industry_nav_buttons():
    """查股：介紹圖圖下可點；產業／高低導航圖下鈕；介紹不准重跑整套查股。"""
    hub = inspect.getsource(WayneTelegramBot._hub_keyboard)
    assert '介紹圖' in hub and 'callback_data=f"i:{c}"' in hub
    assert '產業' in hub and 'callback_data=f"n:{c}"' in hub
    assert '高低導航圖' in hub and 'callback_data=f"g:{c}"' in hub
    intro = inspect.getsource(WayneTelegramBot._send_intro_glance_to)
    assert "介紹圖進行中" in intro
    assert "render_first_glance_png" in intro
    assert "_send_card_to" not in intro
    cb = inspect.getsource(WayneTelegramBot._on_callback_bound)
    assert 'data.startswith("i:")' in cb
    assert 'data.startswith("g:")' in cb
    assert 'data.startswith("n:")' in cb
    assert "_send_intro_glance_to" in cb
    assert "_send_navigation_chart" in cb
    assert "_send_industry" in cb
    # 高低卡＝自動相簿第一張／決策卡路徑
    card = inspect.getsource(WayneTelegramBot._send_card_to)
    assert "_send_card_to_locked" in card


def test_portfolio_watch_empty_not_blank():
    """持股／觀察空名單必須有白話，不准空白泡泡。"""
    from portfolio_engine import PortfolioEngine

    eng = PortfolioEngine.__new__(PortfolioEngine)
    eng.db_path = None
    empty_h = PortfolioEngine.format_holdings_html(eng, [])
    assert "持股" in empty_h
    assert "記買入" in empty_h or "還沒記" in empty_h

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = None
    bot.WATCH_LIST_LIMIT = 30
    html, kb = bot._render_watch([])
    assert "觀察清單" in html
    assert "空" in html
    assert kb is None


def test_flow_empty_and_non_buy_bridge():
    flow = inspect.getsource(WayneTelegramBot.flow_cmd)
    assert "目前沒有可顯示的資金輪動" in flow
    assert "_FLOW_HTML_TIMEOUT" in flow or "TimeoutError" in flow
    from money_flow import format_flow_html

    src = inspect.getsource(format_flow_html)
    assert "不是買訊" in src


def test_winrate_empty_pending_and_non_fake():
    from winrate_buypoint import EMPTY_MSG, header_html

    assert EMPTY_MSG == "今天無勝率買點股票出現"
    wr = inspect.getsource(WayneTelegramBot._run_winrate_buypoint)
    assert "_trade_slot_try_begin" in wr
    assert "勝率買點進行中，請稍候" in wr
    assert "EMPTY_MSG" in wr
    head = header_html("20261121", 0, mode="roster", offset=0)
    assert head == EMPTY_MSG


def _msg(uid: int = 1001, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=99)
    message = MagicMock()
    message.chat_id = 99
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    return message


def _bot():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
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
    bot._touch_user = MagicMock()
    bot._keyboard = MagicMock(return_value=None)
    bot._reply_menu = MagicMock(return_value=None)
    bot._actor_key = MagicMock(return_value="99:1001")
    bot._uid_from_message = MagicMock(return_value="1001")
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), None, None))
    bot._stop_plain_wait = AsyncMock()
    bot._wait_bubble = MagicMock(
        side_effect=lambda title, s, **kw: f"⏳ LOADING\n{title}"
    )
    bot._enter_main_menu = AsyncMock()
    bot._send_market_page = AsyncMock()
    bot._send_portfolio = AsyncMock()
    bot._send_watch = AsyncMock()
    return bot


def test_market_cmd_wait_before_page():
    bot = _bot()
    # 用真 _wait_bubble，才能核對 rest＝盤後對照圖（不准再寫遠／近／超近窗）
    bot._wait_bubble = WayneTelegramBot._wait_bubble
    order: list = []

    async def track_wait(message, *, text_fn, **_kw):
        order.append("wait")
        order.append(text_fn(0))
        return MagicMock(), None, None

    bot._start_plain_wait = AsyncMock(side_effect=track_wait)
    msg = _msg()
    upd = SimpleNamespace(
        effective_message=msg,
        message=msg,
        effective_user=msg.from_user,
    )
    asyncio.run(WayneTelegramBot.market_cmd(bot, upd, MagicMock()))
    assert order[0] == "wait"
    assert "大盤進行中" in order[1]
    assert "遠／近／超近窗" not in order[1]
    assert "盤後對照圖" in order[1]
    bot._send_market_page.assert_awaited()
    bot._stop_plain_wait.assert_not_awaited()  # page owns stop via wait_h


def test_portfolio_and_watch_cmd_wait_then_send():
    bot = _bot()
    msg = _msg()
    upd = SimpleNamespace(
        effective_message=msg,
        message=msg,
        effective_user=msg.from_user,
    )
    asyncio.run(WayneTelegramBot.portfolio_cmd(bot, upd, MagicMock()))
    bot._start_plain_wait.assert_awaited()
    bot._send_portfolio.assert_awaited()
    bot._stop_plain_wait.assert_awaited()

    bot2 = _bot()
    asyncio.run(WayneTelegramBot.watch_cmd(bot2, upd, MagicMock()))
    bot2._start_plain_wait.assert_awaited()
    bot2._send_watch.assert_awaited()
    bot2._stop_plain_wait.assert_awaited()


def test_row1_menu_routes_in_on_text():
    """主選單文字路由：第一排七鍵＋別名進對應 handler（模擬層）。"""
    src = inspect.getsource(WayneTelegramBot._on_text_bound)
    assert "MENU_BTN_WINRATE" in src or "勝率買點" in src
    assert "screen_cmd" in src
    assert "_send_portfolio" in src or "portfolio_cmd" in src
    assert "_send_watch" in src or "watch_cmd" in src
    assert "_send_biaoke_page" in src
    assert "market_cmd" in src
    assert "flow_cmd" in src
    assert "MENU_BTN_LEAVE_BIAOKE" in src or "離開飆大" in src
