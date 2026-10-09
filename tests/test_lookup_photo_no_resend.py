# -*- coding: utf-8 -*-
"""查股送圖：TimedOut 不准重送（聯亞高低卡連出三張的根因）。"""
from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot_servers import WayneTelegramBot


def _bot():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot.charts_dir = tempfile.mkdtemp()
    bot._lookup_locks = {}
    return bot


def _message():
    user = SimpleNamespace(id=1, first_name="u")
    message = MagicMock()
    message.chat_id = 99
    message.from_user = user
    message.reply_photo = AsyncMock()
    return message


def _png(path: str) -> str:
    with open(path, "wb") as f:
        f.write(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            + b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4"
            + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    return path


def test_timedout_counts_as_delivered_no_resend():
    bot = _bot()
    msg = _message()
    path = _png(os.path.join(bot.charts_dir, "card.jpg"))

    class TimedOut(Exception):
        pass

    TimedOut.__name__ = "TimedOut"
    msg.reply_photo = AsyncMock(side_effect=TimedOut("read timeout"))

    ok = asyncio.run(
        bot._reply_lookup_photo(msg, path, caption="聯亞", kind="card", code="3081")
    )
    assert ok is True
    assert msg.reply_photo.await_count == 1


def test_network_error_retries_once_only():
    bot = _bot()
    msg = _message()
    path = _png(os.path.join(bot.charts_dir, "card.jpg"))

    class NetworkError(Exception):
        pass

    NetworkError.__name__ = "NetworkError"
    msg.reply_photo = AsyncMock(side_effect=NetworkError("reset"))

    ok = asyncio.run(
        bot._reply_lookup_photo(msg, path, caption="聯亞", kind="card", code="3081")
    )
    assert ok is False
    assert msg.reply_photo.await_count == 2


def test_old_send_photo_loop_gone():
    import inspect

    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "_reply_lookup_photo" in src
    assert 'err_name in ("TimedOut", "NetworkError", "RetryAfter")' not in src
    src2 = inspect.getsource(WayneTelegramBot._reply_lookup_photo)
    assert "視同已送達" in src2
    assert "for attempt in range(3)" not in src2


def test_send_card_to_acquires_lock_before_await():
    import inspect

    src = inspect.getsource(WayneTelegramBot._send_card_to)
    # 檢查與 acquire 之間不准夾雜 reply_text await（重入雙開）
    locked_i = src.index("if lock.locked()")
    acquire_i = src.index("await lock.acquire()")
    assert acquire_i > locked_i
    between = src[locked_i:acquire_i]
    assert "reply_text" in between  # busy 提示在 locked 分支內
    assert between.count("await ") == 1  # 只有 busy 那條 await，acquire 前無其他 await
    assert "await lock.acquire()" in src
    assert "lock.release()" in src
