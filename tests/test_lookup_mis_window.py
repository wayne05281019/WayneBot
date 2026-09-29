# -*- coding: utf-8 -*-
"""查股 MIS：只在合併窗等現價；盤後不准空等擋出圖。"""
from __future__ import annotations

import inspect
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from bot_servers import WayneTelegramBot


def test_prefetch_mis_skips_outside_live_merge_window():
    src = inspect.getsource(WayneTelegramBot._prefetch_mis_quote)
    assert "is_live_merge_window" in src
    assert "不准空等擋出圖" in src or "非合併窗" in src

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    evening = datetime(2026, 9, 29, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    with patch("live_quote.is_lookup_trading_day", return_value=True), patch(
        "live_quote.is_live_merge_window", return_value=False
    ), patch("live_quote.fetch_lookup_quote") as fetch:
        assert bot._prefetch_mis_quote("2330", [{"market": "TW", "close": 1}]) is None
        fetch.assert_not_called()

    with patch("live_quote.is_lookup_trading_day", return_value=True), patch(
        "live_quote.is_live_merge_window", return_value=True
    ), patch(
        "live_quote.fetch_lookup_quote", return_value={"close": 100.0}
    ) as fetch:
        out = bot._prefetch_mis_quote("2330", [{"market": "TW", "close": 1}])
        assert out and out.get("close") == 100.0
        fetch.assert_called_once()
    _ = evening  # 記錄場景：台北盤後


def test_name_lookup_off_event_loop():
    from bot_servers import WayneTelegramBot

    send = inspect.getsource(WayneTelegramBot._send_card_to)
    # 查名／代號字典查詢不准卡死 Telegram 事件迴圈
    assert "await asyncio.to_thread(lookup_stocks" in send
    # 文字入口也要 to_thread（名稱「聯亞」冷查可 >1s）
    on_text_mod = open("bot_servers.py", encoding="utf-8").read()
    assert on_text_mod.count("await asyncio.to_thread(lookup_stocks") >= 2

def test_polling_heartbeat_interval_and_stall_watch():
    src = inspect.getsource(WayneTelegramBot.run_polling)
    assert "asyncio.sleep(60)" in src
    assert "_start_loop_stall_watch" in src
    assert "call_soon_threadsafe" in src
    from ops_watchdog import _POLLING_STALE_SECONDS

    assert _POLLING_STALE_SECONDS <= 300
