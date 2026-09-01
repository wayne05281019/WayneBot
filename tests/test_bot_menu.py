def test_reply_menu_has_decision_card_button():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    labels = []
    for row in kb.keyboard:
        for btn in row:
            labels.append(btn.text)
    assert "決策卡" in labels
    assert labels.count("決策卡") == 1
