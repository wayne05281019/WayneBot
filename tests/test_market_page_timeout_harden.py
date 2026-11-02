# -*- coding: utf-8 -*-
"""大盤文字：美股／CNN 子逾時；整頁逾時只回文字（教具改走波浪位階）。"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import WayneTelegramBot, _MARKET_US_REFRESH_TIMEOUT


def test_market_page_us_refresh_timeout_falls_back_to_cache(tmp_path):
    """美股刷新卡住時改用庫內列，不准整頁 70s 空白；也不再附送三張教具。"""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "m.db")
    bot.charts_dir = str(tmp_path)
    bot._uid_from_message = lambda _m: "1"
    bot._keyboard = lambda: None
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    bot._stop_plain_wait = AsyncMock()
    bot._send_market_wave_charts = AsyncMock()
    bot._send_market_session_cards = AsyncMock()

    def _hang(*_a, **_k):
        time.sleep(_MARKET_US_REFRESH_TIMEOUT + 3)
        return {"ok": True}

    msg = MagicMock()
    msg.reply_html = AsyncMock()
    msg.reply_text = AsyncMock()

    with patch(
        "live_quote.fetch_mis_index_quote", return_value=None
    ), patch(
        "taiwan_market.analyze_taiwan_market",
        return_value={"ok": True, "as_of": "20261030", "regime": "ok", "brief": "x"},
    ), patch(
        "taiwan_market.format_taiwan_market_page_html",
        return_value="<b>台股大盤</b>\n加權指數",
    ), patch(
        "us_overnight.refresh_us_for_market_page", side_effect=_hang
    ), patch(
        "us_overnight.load_us_overnight",
        return_value={"ok": True, "us_session": "20261030", "regime": "ok", "ixic_pct": 0.1},
    ), patch(
        "cnn_fear.fetch_cnn_fear_greed", return_value=None
    ), patch(
        "market_session_cards.assemble_session_cards",
        return_value={
            "us": {"session": "", "cards": [], "missing": []},
            "tx": {"card": None, "missing": True},
            "fear": None,
            "notes": [],
        },
    ):
        t0 = time.perf_counter()
        asyncio.run(bot._send_market_page(msg))
        elapsed = time.perf_counter() - t0

    assert elapsed < _MARKET_US_REFRESH_TIMEOUT + 8.0
    assert msg.reply_html.await_count >= 1
    assert "逾時" not in " ".join(
        str(c.args[0]) for c in msg.reply_text.await_args_list if c.args
    )
    # v34：大盤成功路徑也不再掛教具
    bot._send_market_wave_charts.assert_not_awaited()
    bot._send_market_session_cards.assert_awaited()


def test_market_page_total_timeout_points_to_wave_status(tmp_path):
    """整頁逾時：只回文字並指波浪位階；不准再拖三張圖。"""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "m.db")
    bot.charts_dir = str(tmp_path)
    bot._uid_from_message = lambda _m: "1"
    bot._keyboard = lambda: None
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    bot._stop_plain_wait = AsyncMock()
    bot._send_market_wave_charts = AsyncMock()

    msg = MagicMock()
    msg.reply_html = AsyncMock()
    msg.reply_text = AsyncMock()

    async def _slow_to_thread(fn, *a, **k):
        await asyncio.sleep(0.2)
        return ("<b>x</b>", None, {})

    with patch("bot_servers._MARKET_PAGE_TIMEOUT", 0.01), patch(
        "asyncio.to_thread", side_effect=_slow_to_thread
    ):
        asyncio.run(bot._send_market_page(msg))

    texts = [str(c.args[0]) for c in msg.reply_text.await_args_list if c.args]
    assert any("波浪位階" in t for t in texts)
    assert any("逾時" in t for t in texts)
    bot._send_market_wave_charts.assert_not_awaited()
