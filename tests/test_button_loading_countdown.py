"""全鍵 LOADING／倒數＋魔法消逝（UX，不改買訊／出圖公式）。"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

from bot_servers import WayneTelegramBot


def test_wait_bubble_has_loading_and_elapsed():
    txt0 = WayneTelegramBot._wait_bubble("大盤進行中", 0, now="讀指數", fill_sec=20.0)
    txt12 = WayneTelegramBot._wait_bubble("大盤進行中", 12, now="讀指數", fill_sec=20.0)
    assert "LOADING" in txt0
    assert "大盤進行中" in txt0
    assert "□" * 10 in txt0
    assert "已 0 秒" in txt0 or "已 0" in txt0
    assert "■" in txt12
    assert "已 12 秒" in txt12
    assert "好了這則會消失" in txt0
    for ch in ("⏳", "🔄", "📊", "🔍"):
        assert ch not in txt0


def test_magic_dismiss_frames_no_emoji():
    frames = WayneTelegramBot._magic_dismiss_frames()
    assert len(frames) >= 2
    blob = "\n".join(frames)
    assert "魔法收起" in blob or "完成" in blob
    for ch in ("⏳", "🔄", "✨", "🪄"):
        assert ch not in blob


def test_stop_plain_wait_uses_magic_dismiss():
    src = inspect.getsource(WayneTelegramBot._stop_plain_wait)
    assert "_magic_dismiss" in src


def test_menu_slow_paths_start_plain_wait():
    paths = {
        "market_cmd": "大盤進行中",
        "flow_cmd": "資金輪動進行中",
        "portfolio_cmd": "持股進行中",
        "watch_cmd": "觀察進行中",
        "_run_trade_bucket": "進行中",
        "_run_emerging_screening": "興櫃海選進行中",
        "_run_winrate_buypoint": "勝率買點進行中",
        "_run_leave_zero_now": "剛脫離零進行中",
        "_send_dongzhu_page": "洞燭先機進行中",
        "_run_manual_screening": "_screening_progress_text",
        "_send_ai_desk_view": "AI倉進行中",
        "_run_ai_now": "AI倉進行中",
        "_streak_show_days": "連買區進行中",
        "_send_trade_journal": "成交進行中",
    }
    for name, needle in paths.items():
        src = inspect.getsource(getattr(WayneTelegramBot, name))
        if name == "_run_manual_screening":
            assert needle in src
            continue
        assert "_start_plain_wait" in src or "_wait_bubble" in src, name
        assert needle in src, name


def test_magic_dismiss_edits_then_deletes():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    msg = MagicMock()
    msg.edit_text = AsyncMock()
    msg.delete = AsyncMock()

    async def run():
        await bot._magic_dismiss(msg)

    asyncio.run(run())
    assert msg.edit_text.await_count >= 2
    msg.delete.assert_awaited()
