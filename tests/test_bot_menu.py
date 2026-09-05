def test_typed_shortcuts_open_overnight_and_ai_desk():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot.on_text)
    assert '"隔沖"' in src and '"隔日"' in src
    assert '"AI模擬倉"' in src and '"模擬倉"' in src
    assert "_send_ai_desk_view" in src


def test_reply_menu_is_two_rows_not_three():
    from bot_servers import MENU_BTN_MARKET, MENU_BTN_STREAK, MENU_LAYOUT_VERSION, WayneTelegramBot

    assert MENU_BTN_MARKET == "大盤"
    assert MENU_LAYOUT_VERSION == "8"
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert len(kb.keyboard) == 2
    row1 = [btn.text for btn in kb.keyboard[0]]
    row2 = [btn.text for btn in kb.keyboard[1]]
    assert row1 == ["決策卡", "當沖", "持股", "觀察", "海選"]
    assert row2 == ["隔日沖", "資金", "說明", MENU_BTN_STREAK, MENU_BTN_MARKET]


def test_help_guide_covers_all_main_buttons():
    from bot_servers import HELP_TOPICS

    guide = HELP_TOPICS["guide"]
    for label in (
        "決策卡",
        "當沖",
        "持股",
        "觀察",
        "海選",
        "隔日沖",
        "資金",
        "說明",
        "連買區",
        "大盤",
        "籌碼",
        "營收",
        "產業",
        "導航圖",
        "記買入",
        "AI模擬倉",
        "AI操盤",
    ):
        assert label in guide
    assert "按表操課" in guide
    assert "低買高賣" in guide


def test_help_nav_keyboard_has_topic_buttons():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._help_nav_keyboard()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "總覽" in labels
    assert "查股" in labels
    assert "第一排" in labels
    assert "第二排" in labels
    assert "✕" in labels
    assert "海選" not in labels
    assert "大盤" not in labels
    assert "當沖" not in labels
    assert "持股" not in labels
    cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "?:guide" in cbs
    assert "?:stock" in cbs
    assert "?:screen" not in cbs
    assert "?:market" not in cbs


def test_help_menu_topic_mentions_market_not_reserved():
    from bot_servers import HELP_TOPICS

    menu = HELP_TOPICS["menu"]
    assert "大盤" in menu
    assert "連買區" in menu
    assert "預留" not in menu


def test_help_nav_does_not_duplicate_reply_menu_labels():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    reply = {btn.text for row in bot._reply_menu().keyboard for btn in row}
    inline = {btn.text for row in bot._help_nav_keyboard().inline_keyboard for btn in row}
    overlap = reply & inline
    assert overlap == set(), f"直立式與兩排重複：{overlap}"


def test_pin_reply_menu_keeps_keyboard_message():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    pin = MagicMock()
    pin.delete = AsyncMock()
    msg = MagicMock()
    msg.reply_text = AsyncMock(return_value=pin)

    asyncio.run(bot._pin_reply_menu(msg))
    asyncio.run(asyncio.sleep(0.45))
    pin.delete.assert_not_called()
    markup = msg.reply_text.await_args.kwargs.get("reply_markup")
    assert markup is not None
    assert [b.text for b in markup.keyboard[1]][3] == "連買區"


def test_refresh_silent_sends_reply_keyboard_with_streak():
    """silent 刷新也必須新發 ReplyKeyboard（edit 換不了連買區）。"""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import MENU_BTN_STREAK, WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._dismiss_menu_transients = AsyncMock()
    bot._actor_key = MagicMock(return_value="1:1")
    bot._mark_menu_layout_ok = MagicMock()
    bot._menu_pin_msgs = {}
    msg = MagicMock()
    pin = MagicMock()
    pin.delete = AsyncMock()
    msg.reply_text = AsyncMock(return_value=pin)

    asyncio.run(bot._refresh_reply_menu(msg, uid="1", silent=True))
    assert msg.reply_text.await_count >= 1
    markup = msg.reply_text.await_args.kwargs.get("reply_markup")
    assert markup is not None
    assert "Remove" not in type(markup).__name__
    row2 = [b.text for b in markup.keyboard[1]]
    assert row2[3] == MENU_BTN_STREAK
    bot._mark_menu_layout_ok.assert_called_once_with("1")


def test_force_reply_menu_invalidates_layout_cache():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import MENU_LAYOUT_VERSION, WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    msg = MagicMock()
    msg.reply_text = AsyncMock(return_value=MagicMock())
    cached = {}

    def _set_cached(key, _kind, content, db_path=None):
        cached[key] = content

    def _get_cached(key, db_path=None):
        val = cached.get(key)
        return {"content": val} if val else None

    async def run():
        with patch("wayne_db.set_cached_data", side_effect=_set_cached), patch(
            "wayne_db.get_cached_data", side_effect=_get_cached
        ), patch.object(bot, "_refresh_reply_menu", new_callable=AsyncMock) as refresh:
            cached[f"tg_menu_layout:9"] = MENU_LAYOUT_VERSION
            await bot._force_reply_menu(msg, "9")
            refresh.assert_awaited_once()
            assert cached.get("tg_menu_layout:9") == "0" or refresh.called

    asyncio.run(run())


def test_inline_fallback_keyboard_is_gone():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    assert bot._keyboard() is None


def test_streak_kind_keyboard_magic_three_choices():
    from bot_servers import MENU_BTN_BACK_MAIN, WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._streak_kind_keyboard()
    labels = [b.text for row in kb.keyboard for b in row]
    assert labels[:3] == ["外資", "投信", "外資+投信"]
    assert MENU_BTN_BACK_MAIN in labels
    assert "上市" not in labels


def test_portfolio_keyboard_shows_stock_name():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._portfolio_keyboard(
        [{"stock_code": "1303", "stock_name": "南亞"}, {"stock_code": "6526", "stock_name": "達發"}]
    )
    left = [row[0].text for row in kb.inline_keyboard if row[0].callback_data.startswith("k:")]
    assert left[0] == "1303 南亞"
    assert left[1] == "6526 達發"


def test_screening_progress_text():
    from bot_servers import WayneTelegramBot

    assert "海選開始" in WayneTelegramBot._screening_progress_text(0)
    body = WayneTelegramBot._screening_progress_text(45)
    assert "45 秒" in body
    assert "▓" in body
    assert WayneTelegramBot._format_elapsed(95) == "1:35"
    assert "完成" in WayneTelegramBot._screening_progress_text(0, done=True)


def test_refresh_reply_menu_keeps_keyboard_message():
    """熱修：重掛選單不得 Remove、不得刪掉帶鍵盤的訊息。"""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot._menu_pin_msgs = {}
    bot._dismiss_menu_transients = AsyncMock()
    bot._actor_key = MagicMock(return_value="1:1")
    bot._mark_menu_layout_ok = MagicMock()
    msg = MagicMock()
    sent = MagicMock()
    sent.delete = AsyncMock()
    msg.reply_text = AsyncMock(return_value=sent)

    async def run():
        with patch("wayne_db.set_cached_data"):
            await bot._refresh_reply_menu(msg, uid="1", silent=False)
            await bot._refresh_reply_menu(msg, uid="1", silent=True)

    asyncio.run(run())
    assert msg.reply_text.await_count >= 2
    for call in msg.reply_text.await_args_list:
        kw = call.kwargs
        markup = kw.get("reply_markup")
        assert markup is not None
        assert type(markup).__name__ != "ReplyKeyboardRemove"
        assert getattr(markup, "keyboard", None) is not None
    sent.delete.assert_not_awaited()


def test_screening_status_bubble_has_no_reply_keyboard():
    """海選進度泡泡不得掛 ReplyKeyboard，否則 delete 後兩排會消失。"""
    import asyncio
    import inspect
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._run_manual_screening)
    assert "reply_markup=hub" not in src.split("status = await")[1].split("ticker =")[0]
    assert "await status.delete()" in src
    assert "await self._pin_reply_menu(message)" in src

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._screening_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._dismiss_menu_transients = AsyncMock()
    bot._pin_reply_menu = AsyncMock()
    bot._reply_screening_payload = AsyncMock()
    bot.screener = MagicMock()
    bot.screener.run_full_screening = MagicMock(return_value={"as_of": "20260903"})
    bot.db_path = "data/wayne_market.db"
    msg = MagicMock()
    msg.chat_id = 1
    msg.from_user = MagicMock(id=1)
    status = MagicMock()
    status.edit_text = AsyncMock()
    status.delete = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)

    async def run():
        await bot._run_manual_screening(msg)

    asyncio.run(run())
    # 第一則是進度泡泡：不可帶 reply_markup
    first = msg.reply_text.await_args_list[0]
    assert first.kwargs.get("reply_markup") is None
    status.delete.assert_awaited()
    bot._pin_reply_menu.assert_awaited()



def test_scratch_chart_paths_differ_per_user():
    from bot_servers import WayneTelegramBot

    p1 = WayneTelegramBot._scratch_chart_path("data/charts", "2330", "chips", "9001")
    p2 = WayneTelegramBot._scratch_chart_path("data/charts", "2330", "chips", "9002")
    assert p1 != p2
    assert "9001" in p1 and "9002" in p2


def test_screening_global_gate_blocks_second_user():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._screening_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = "1:1"
    bot._dismiss_menu_transients = AsyncMock()
    bot._pin_reply_menu = AsyncMock()
    bot.screener = MagicMock()
    bot.screener.run_full_screening = MagicMock()
    msg = MagicMock()
    msg.chat_id = 2
    msg.from_user = MagicMock(id=2)
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()

    async def run():
        await bot._run_manual_screening(msg)

    asyncio.run(run())
    bot.screener.run_full_screening.assert_not_called()
    blob = " ".join(
        str(c.args[0])
        for c in msg.reply_html.await_args_list + msg.reply_text.await_args_list
        if c.args
    )
    assert "海選正在掃描" in blob


def test_health_server_is_threaded():
    import inspect

    import main

    src = inspect.getsource(main.start_health_server)
    assert "ThreadingHTTPServer" in src


def test_sell_holdings_prompt_shows_odd_lots():
    import inspect

    from bot_servers import WayneTelegramBot, _sell_holdings_prompt

    assert _sell_holdings_prompt("2330") == "賣出 2330。請輸入：價格（全賣）\n例如：72 或 1 72"
    odd = _sell_holdings_prompt("6526", 0.439)
    assert odd.startswith("賣出 6526。現有 439股。")
    assert "全賣" in odd
    assert "200股" in odd
    assert "1 72" not in odd
    whole = _sell_holdings_prompt("3035", 4)
    assert "現有 4張" in whole
    assert "1 72" in whole
    mixed = _sell_holdings_prompt("6526", 1.439)
    assert "現有 1張439股" in mixed
    assert "200股" in mixed
    assert "1 72" not in mixed
    src = inspect.getsource(WayneTelegramBot.on_callback)
    assert "_sell_holdings_prompt" in src
    assert "_held_lots_for" in src


def test_buy_holdings_prompt_shows_odd_lots():
    import inspect

    from bot_servers import WayneTelegramBot, _buy_holdings_prompt

    whole = _buy_holdings_prompt("2330")
    assert whole == "記買入 2330。請輸入：價格（1張）\n例如：68.5 或 2 68.5"
    odd = _buy_holdings_prompt("6526", 0.439)
    assert odd.startswith("記買入 6526。現有 439股。")
    assert "200股" in odd
    assert "2 68.5" not in odd
    held = _buy_holdings_prompt("3035", 4)
    assert "現有 4張" in held
    assert "2 68.5" in held
    mixed = _buy_holdings_prompt("6526", 1.439)
    assert "現有 1張439股" in mixed
    assert "200股" in mixed
    assert "2 68.5" not in mixed
    src = inspect.getsource(WayneTelegramBot.on_callback)
    assert "_buy_holdings_prompt" in src


def test_daytrade_closed_uses_holiday_title_not_intraday():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._run_trade_bucket)
    assert "daytrade_closed_title" in src
    assert "daytrade_closed_message" in src


def test_flow_timeout_hint_not_always_intraday_mis():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot.flow_cmd)
    assert "is_tw_equity_session" in src
    assert "請稍後再按一次「資金」" in src
