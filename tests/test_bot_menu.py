def test_reply_menu_two_rows_five_cols_with_reserved_slot():
    from bot_servers import MENU_BTN_RESERVED, WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert len(kb.keyboard) == 2
    assert len(kb.keyboard[0]) == 5
    assert len(kb.keyboard[1]) == 5
    row1 = [btn.text for btn in kb.keyboard[0]]
    row2 = [btn.text for btn in kb.keyboard[1]]
    assert row1 == ["決策卡", "當沖", "持股", "觀察", "海選"]
    assert row2 == ["隔日沖", "資金", "說明", "選單", MENU_BTN_RESERVED]
