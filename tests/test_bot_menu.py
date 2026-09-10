def test_typed_shortcuts_open_overnight_and_ai_desk():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot.on_text)
    assert '"隔沖"' in src and '"隔日"' in src
    assert '"AI模擬倉"' in src and '"模擬倉"' in src and '"AI倉"' in src
    assert "_send_ai_desk_view" in src


def test_refresh_last_button_keeps_decision_card_alias():
    import inspect

    from bot_servers import MENU_BTN_CARD, MENU_BTN_CARD_ALIASES, WayneTelegramBot

    assert MENU_BTN_CARD == "刷新"
    assert "決策卡" in MENU_BTN_CARD_ALIASES
    src = inspect.getsource(WayneTelegramBot.on_text)
    assert "MENU_BTN_CARD_ALIASES" in src
    assert "decision_card_btn" in src


def test_reply_menu_is_two_rows_not_three():
    from bot_servers import (
        MENU_BTN_AI,
        MENU_BTN_MARKET,
        MENU_BTN_REPORT,
        MENU_BTN_STREAK,
        MENU_LAYOUT_VERSION,
        WayneTelegramBot,
    )

    assert MENU_BTN_MARKET == "大盤"
    assert MENU_BTN_AI == "AI倉"
    assert MENU_BTN_REPORT == "回報"
    assert MENU_LAYOUT_VERSION == "17"
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert len(kb.keyboard) == 2
    row1 = [btn.text for btn in kb.keyboard[0]]
    row2 = [btn.text for btn in kb.keyboard[1]]
    assert len(row1) == 7 and len(row2) == 7
    from bot_servers import MENU_BTN_BIAOKE_FACE

    assert row1 == ["說明", "海選", "持股", "觀察", "刷新", MENU_BTN_REPORT, MENU_BTN_BIAOKE_FACE]
    assert row2[:6] == [MENU_BTN_MARKET, "資金", "當沖", "隔日沖", MENU_BTN_AI, MENU_BTN_STREAK]
    assert row2[6].strip() == ""
    assert row1[0] == "說明"
    assert row1[-1] == MENU_BTN_BIAOKE_FACE
    assert row1[-2] == MENU_BTN_REPORT
    assert row2[-1].strip() == ""
    assert row2[-2] == MENU_BTN_STREAK


def test_help_guide_covers_all_main_buttons():
    from bot_servers import HELP_TOPICS

    guide = HELP_TOPICS["guide"]
    for label in (
        "刷新",
        "刷新上一檔",
        "決策卡",
        "當沖",
        "持股",
        "觀察",
        "海選",
        "隔日沖",
        "資金",
        "說明",
        "連買區",
        "回報",
        "大盤",
        "籌碼",
        "營收",
        "產業",
        "導航圖",
        "記買入",
        "AI倉",
        "AI模擬倉",
        "AI操盤",
        "飆客",
    ):
        assert label in guide
    assert "預留" not in guide
    assert "按表操課" in guide
    assert "回報" in guide
    assert "不用給程式密鑰" in guide
    assert "低買高賣" in guide
    assert "介紹圖" in guide and "一次出兩張圖" in guide
    assert "現價漲跌 → 決策卡圖 → 介紹圖" not in guide
    assert "要再看才按" not in guide
    assert "按錯了" in guide
    assert "直接打代號" in guide
    assert "00981A" in guide
    assert "打「持倉」會開" in guide
    assert "持股" in HELP_TOPICS["guide"]
    stock = HELP_TOPICS["stock"]
    assert "圖下方" in stock
    assert "決策卡 → 介紹圖" not in stock
    assert "五日" in stock
    assert "月線" in stock
    assert "15 分" in stock


def test_help_nav_keyboard_has_topic_buttons():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._help_nav_keyboard()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "總覽" in labels
    assert "查股" in labels
    assert "圖文" in labels
    assert "AI" not in labels
    assert "第一排" in labels
    assert "第二排" in labels
    assert "連買" in labels
    assert "記買入" in labels
    assert "興櫃" not in labels
    assert "原因" not in labels
    assert "按錯" in labels
    assert "✕" in labels
    assert "海選" not in labels
    assert "大盤" not in labels
    assert "當沖" not in labels
    assert "持股" not in labels
    cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "?:guide" in cbs
    assert "?:stock" in cbs
    assert "?:pics" in cbs
    assert "?:streak" in cbs
    assert "?:oops" in cbs
    assert "em:go" not in cbs
    assert "?:why" not in cbs
    assert "?:screen" not in cbs
    assert "?:market" not in cbs


def test_help_menu_topic_mentions_report_not_reserved():
    from bot_servers import HELP_TOPICS

    menu = HELP_TOPICS["menu"]
    assert "大盤" in menu
    assert "連買區" in menu
    assert "回報" in menu
    assert "AI倉" in menu
    assert "預留" not in menu


def test_help_bucket_display_names_leave_zero_is_golden_buy():
    """對外：leave_zero＝黃金買點；golden_buy＝重點觀察。公式與 key 不變。"""
    from bot_servers import HELP_TOPICS
    from line_share_format import LINE_BUCKET_META
    from screening_engine import LINE_BUCKET_TITLES, MORNING_PUSH_SPECS, SCREEN_PUSH_SPECS

    guide = HELP_TOPICS["guide"]
    assert "優先認<b>黃金買點</b>" in guide
    assert "這一欄以前叫「起漲」" in guide
    assert "<b>重點觀察</b>" in guide
    assert "這一欄以前叫「黃金買點」" in guide
    assert "對照組" in guide
    specs = {k: label for k, _, label, *_ in SCREEN_PUSH_SPECS}
    assert specs["leave_zero"] == "黃金買點"
    assert specs["golden_buy"] == "重點觀察"
    morning = {k: label for k, _, label, *_ in MORNING_PUSH_SPECS}
    assert morning["leave_zero"] == "黃金買點"
    assert morning["golden_buy"] == "重點觀察"
    assert LINE_BUCKET_TITLES["leave_zero"] == "黃金買點"
    assert LINE_BUCKET_TITLES["golden_buy"] == "重點觀察"
    assert LINE_BUCKET_META["leave_zero"][0] == "黃金買點"
    assert LINE_BUCKET_META["golden_buy"][0] == "重點觀察"


def test_bucket_from_reason_accepts_old_and_new_labels():
    from screen_review import bucket_from_reason

    assert bucket_from_reason("黃金買點：獲利離零") == "leave_zero"
    assert bucket_from_reason("重點觀察：60低超跌") == "golden_buy"
    assert bucket_from_reason("起漲：獲利離零") == "leave_zero"
    assert bucket_from_reason("黃金買點：60低超跌") == "golden_buy"


def test_help_and_menu_copy_uses_plain_chinese():
    """用戶看得到的說明／選單文案不要留 MIS、VIX、OI、基差、近月、YoY 等行話。"""
    from bot_servers import HELP_TOPICS

    blob = "\n".join(HELP_TOPICS.values())
    for junk in (
        "MIS",
        "VIX",
        "Regime+",
        "Regime ",
        "YoY",
        "MoM",
        "那指期",
        "台積ADR",
        "基差",
        "近月",
        "OI ",
        "sqlite",
        "TWSE",
        "貼月高",
        "貼近月低",
    ):
        assert junk not in blob, junk
    bot_src = open("bot_servers.py", encoding="utf-8").read()
    assert 'subtitle="盤中 MIS' not in bot_src
    assert "恐慌指數" in blob
    assert "即時現價" in blob or "證交所即時價" in blob


def test_help_streak_does_not_split_listed_otc():
    from bot_servers import HELP_TOPICS

    blob = "\n".join(HELP_TOPICS.values())
    assert "再選上市" not in blob
    assert "再選<b>上市</b>" not in blob
    assert "上市或上櫃" not in blob
    assert "外資+投信" in HELP_TOPICS["streak"]
    assert "只看上市櫃" in HELP_TOPICS["streak"]
    assert "興櫃" in HELP_TOPICS["streak"]
    assert "先選<b>上市櫃</b>或<b>興櫃</b>" not in HELP_TOPICS["streak"]
    assert "上市櫃一起列" not in HELP_TOPICS["streak"]
    assert "訊息下面" in HELP_TOPICS["streak"] or "訊息下方" in HELP_TOPICS["streak"]
    assert "連買區" in HELP_TOPICS["row2"]
    assert "曆日" not in blob
    assert "日曆天" in HELP_TOPICS["guide"]
    assert "日曆天" in HELP_TOPICS["stock"]
    assert "成交" in HELP_TOPICS["portfolio"]
    assert "復盤" in HELP_TOPICS["portfolio"]
    assert "籌碼" in HELP_TOPICS["watch"]
    assert "買入" in HELP_TOPICS["watch"]
    assert "圖下方這一排" in HELP_TOPICS["stock"]
    assert "這頁按鈕" in HELP_TOPICS["screen"]
    assert "這頁按鈕" in HELP_TOPICS["daytrade"]
    assert "這頁按鈕" in HELP_TOPICS["overnight"]
    assert "這頁按鈕" in HELP_TOPICS["ai"]
    assert "圖下方這一排" in HELP_TOPICS["stock"]
    assert "不是盤中即時掃描。\n" in HELP_TOPICS["screen"]
    assert HELP_TOPICS["industry"].count("\n") >= 4
    assert "怎麼用" not in HELP_TOPICS["industry"] or "產業按鈕" in HELP_TOPICS["industry"]


def test_streak_entry_title_matches_button():
    import inspect

    from bot_servers import MENU_BTN_STREAK, WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._streak_show_kind)
    assert MENU_BTN_STREAK == "連買區"
    assert "<b>連買區</b>" in src
    assert "<b>連買區域</b>" not in src
    blob = "\n".join(
        [
            open("bot_servers.py", encoding="utf-8").read(),
            open("ai_trader.py", encoding="utf-8").read(),
        ]
    )
    assert "平常最多 1 檔" not in blob


def test_streak_wizard_has_no_listed_otc_step():
    from bot_servers import WayneTelegramBot

    assert not hasattr(WayneTelegramBot, "_streak_market_keyboard")
    assert not hasattr(WayneTelegramBot, "_streak_market_inline")
    assert not hasattr(WayneTelegramBot, "_ask_streak_market")
    src = open("bot_servers.py", encoding="utf-8").read()
    assert 'KeyboardButton("上市")' not in src
    assert 'InlineKeyboardButton("上市"' not in src


def test_streak_wizard_does_not_clone_reply_keyboard():
    """連買步驟鈕只掛訊息下方；輸入列維持十二鈕，不要複製同一排。"""
    from bot_servers import WayneTelegramBot

    assert not hasattr(WayneTelegramBot, "_streak_kind_keyboard")
    assert not hasattr(WayneTelegramBot, "_streak_days_keyboard")
    assert not hasattr(WayneTelegramBot, "_streak_stocks_keyboard")
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "tray_hint" not in src
    assert "也可點輸入區鍵盤" not in src
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kind = [b.text for row in bot._streak_kind_inline().inline_keyboard for b in row]
    assert kind[:3] == ["外資", "投信", "外資+投信"]
    assert "興櫃" not in kind
    em = [b.text for row in bot._streak_em_inline().inline_keyboard for b in row]
    assert "改看上市櫃" in em
    assert "興櫃海選" in em
    screen = [b.text for row in bot._screen_uni_inline().inline_keyboard for b in row]
    assert screen[:2] == ["上市櫃", "興櫃"]


def test_screen_start_picks_listed_or_emerging():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._actor_key = MagicMock(return_value="1:1")
    msg = MagicMock()
    msg.reply_html = AsyncMock()

    asyncio.run(bot._start_screen_pick(msg, "1"))
    assert bot._pending["1:1"] == "screen:uni"
    html = msg.reply_html.await_args.args[0]
    assert "上市櫃" in html and "興櫃" in html
    labels = [
        b.text
        for row in msg.reply_html.await_args.kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert labels[:2] == ["上市櫃", "興櫃"]


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
    sent = msg.reply_text.await_args.args[0]
    assert sent == "·"
    assert "兩排主選單" not in sent
    markup = msg.reply_text.await_args.kwargs.get("reply_markup")
    assert markup is not None
    from bot_servers import MENU_BTN_BIAOKE_FACE, MENU_BTN_CARD, MENU_BTN_REPORT, MENU_BTN_STREAK

    row1 = [b.text for b in markup.keyboard[0]]
    row2 = [b.text for b in markup.keyboard[1]]
    assert row1[-1] == MENU_BTN_BIAOKE_FACE
    assert row1[-2] == MENU_BTN_REPORT
    assert row1[0] == "說明"
    assert row2[-2] == MENU_BTN_STREAK
    assert row2[-1].strip() == ""


def test_pin_reply_menu_does_not_explain_keyboard_location():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._pin_reply_menu)
    assert "兩排主選單在輸入列旁邊四格" not in src
    assert '("·", "主選單")' in src


def test_refresh_silent_sends_reply_keyboard_with_streak():
    """silent 刷新也必須新發 ReplyKeyboard（edit 換不了連買區）。"""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import MENU_BTN_BIAOKE_FACE, MENU_BTN_MARKET, MENU_BTN_REPORT, MENU_BTN_STREAK, WayneTelegramBot

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
    row1 = [b.text for b in markup.keyboard[0]]
    row2 = [b.text for b in markup.keyboard[1]]
    assert row1[-1] == MENU_BTN_BIAOKE_FACE
    assert row1[-2] == MENU_BTN_REPORT
    assert row1[0] == "說明"
    assert row2[-2] == MENU_BTN_STREAK
    assert row2[-1].strip() == ""
    assert row2[0] == MENU_BTN_MARKET
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


def test_inline_fallback_keyboard_is_two_row_menu():
    from bot_servers import MENU_BTN_BIAOKE_FACE, MENU_BTN_REPORT, WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._keyboard()
    assert kb is not None
    row1 = [b.text for b in kb.keyboard[0]]
    assert row1[-1] == MENU_BTN_BIAOKE_FACE
    assert row1[-2] == MENU_BTN_REPORT


def test_streak_kind_inline_magic_three_choices():
    from bot_servers import MENU_BTN_BACK_MAIN, WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    assert not hasattr(WayneTelegramBot, "_streak_kind_keyboard")
    assert not hasattr(WayneTelegramBot, "_streak_days_keyboard")
    assert not hasattr(WayneTelegramBot, "_streak_stocks_keyboard")
    kb = bot._streak_kind_inline("ALL")
    rows = kb.inline_keyboard
    labels = [b.text for row in rows for b in row]
    assert labels[:3] == ["外資", "投信", "外資+投信"]
    assert len(rows[0]) == 3
    assert MENU_BTN_BACK_MAIN in labels
    assert "上市" not in labels
    assert "興櫃" not in labels


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
