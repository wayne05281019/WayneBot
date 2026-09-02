def test_reply_menu_is_two_rows_not_three():
    from bot_servers import MENU_BTN_MARKET, MENU_LAYOUT_VERSION, WayneTelegramBot

    assert MENU_BTN_MARKET == "大盤"
    assert MENU_LAYOUT_VERSION == "4"
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert len(kb.keyboard) == 2
    row1 = [btn.text for btn in kb.keyboard[0]]
    row2 = [btn.text for btn in kb.keyboard[1]]
    assert row1 == ["決策卡", "當沖", "持股", "觀察", "海選"]
    assert row2 == ["隔日沖", "資金", "說明", "選單", MENU_BTN_MARKET]


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
        "選單",
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


def test_help_nav_keyboard_has_topic_buttons():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._help_nav_keyboard()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "總覽" in labels
    assert "海選" in labels
    assert "大盤" in labels
    assert "✕" in labels
    cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "?:guide" in cbs
    assert "?:screen" in cbs
    assert "?:market" in cbs


def test_help_menu_topic_mentions_market_not_reserved():
    from bot_servers import HELP_TOPICS

    menu = HELP_TOPICS["menu"]
    assert "大盤" in menu
    assert "預留" not in menu


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


def test_portfolio_keyboard_shows_stock_name():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._portfolio_keyboard(
        [{"stock_code": "1303", "stock_name": "南亞"}, {"stock_code": "6526", "stock_name": "達發"}]
    )
    left = [row[0].text for row in kb.inline_keyboard if row[0].callback_data.startswith("k:")]
    assert left[0] == "1303 南亞"
    assert left[1] == "6526 達發"

    from bot_servers import WayneTelegramBot

    assert "海選開始" in WayneTelegramBot._screening_progress_text(0)
    body = WayneTelegramBot._screening_progress_text(45)
    assert "45 秒" in body
    assert "▓" in body
    assert WayneTelegramBot._format_elapsed(95) == "1:35"
    assert "完成" in WayneTelegramBot._screening_progress_text(0, done=True)
