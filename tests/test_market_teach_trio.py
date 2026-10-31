# -*- coding: utf-8 -*-
"""大盤遠／近／超近：第1張必遠窗；休市齊檔不重畫；缺遠窗不准只出近窗。"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

from bot_servers import WayneTelegramBot


def _png(path: str, w: int = 1200, h: int = 700) -> None:
    """產足夠大的假 PNG（過 _png_looks_ok 的 8KB／480×280 閘）。"""
    from PIL import Image
    import numpy as np

    # 雜訊圖才壓不小；單色會遠低於 8KB
    arr = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
    Image.fromarray(arr, mode="RGB").save(path, format="PNG", compress_level=1)


def test_merge_market_teach_kit_fills_missing_far_and_micro(tmp_path):
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    near = tmp_path / "near.png"
    far = tmp_path / "far.png"
    micro = tmp_path / "micro.png"
    _png(str(near))
    _png(str(far))
    _png(str(micro))
    painted = {"near_path": str(near), "far_path": "", "micro_path": ""}
    stored = {
        "far_path": str(far),
        "near_path": str(tmp_path / "old-near.png"),
        "micro_path": str(micro),
        "thesis": "stored",
    }
    merged = bot._merge_market_teach_kit(painted, stored)
    assert merged["near_path"] == str(near)
    assert merged["far_path"] == str(far)
    assert merged["micro_path"] == str(micro)


def test_market_wave_sends_numbered_trio_far_first(tmp_path, monkeypatch):
    """休市齊檔：不重畫；第1張遠窗→近→超近逐張，caption 標第N張。"""
    import asyncio

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "m.db")
    bot.charts_dir = str(tmp_path)
    bot._uid_from_message = lambda _m: "1"
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    bot._stop_plain_wait = AsyncMock()
    bot._safe_edit_text = AsyncMock()
    bot._prepare_lookup_album_photo = lambda p, *a, **k: p

    near = tmp_path / "near.png"
    far = tmp_path / "far.png"
    micro = tmp_path / "micro.png"
    _png(str(near))
    _png(str(far))
    _png(str(micro))
    assert bot._market_teach_path_ok(str(far))

    paint_calls = {"n": 0}

    def _no_paint(*_a, **_k):
        paint_calls["n"] += 1
        raise AssertionError("休市齊檔不准 force 重畫")

    monkeypatch.setattr(
        "biaoke_level_learn.latest_teach_kit",
        lambda *_a, **_k: {
            "far_path": str(far),
            "near_path": str(near),
            "micro_path": str(micro),
            "us_path": "",
            "thesis": "t",
            "as_of": "20261031",
        },
    )
    monkeypatch.setattr(
        "biaoke_level_learn.paint_open_day_hypothesis",
        _no_paint,
    )
    monkeypatch.setattr(
        "biaoke_level_learn._build_live_pack",
        lambda *_a, **_k: {"thesis": "t", "chart_as_of": "20261031"},
    )
    monkeypatch.setattr(
        "biaoke_level_learn._wave_now_ladder",
        lambda *_a, **_k: {"one_line": "層級一句", "now_line": ""},
    )
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda: False)
    monkeypatch.setattr("config.skip_chart_warmup", lambda: False)

    msg = MagicMock()
    msg.reply_media_group = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.reply_text = AsyncMock()

    asyncio.run(bot._send_market_wave_charts(msg, uid="1"))
    assert paint_calls["n"] == 0
    assert msg.reply_media_group.await_count == 0
    assert msg.reply_photo.await_count == 3
    caps = []
    for call in msg.reply_photo.await_args_list:
        caps.append(call.kwargs.get("caption") or "")
    assert "第1張・遠窗" in caps[0]
    assert "第2張・近窗" in caps[1]
    assert "第3張・超近窗" in caps[2]


def test_market_wave_blocks_near_if_far_missing(tmp_path, monkeypatch):
    """遠窗缺且重渲失敗：白話停，不准只出近窗。"""
    import asyncio

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "m.db")
    bot.charts_dir = str(tmp_path)
    bot._uid_from_message = lambda _m: "1"
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    bot._stop_plain_wait = AsyncMock()
    bot._safe_edit_text = AsyncMock()
    bot._prepare_lookup_album_photo = lambda p, *a, **k: p
    bot._retry_market_far_paint = AsyncMock(return_value="")

    near = tmp_path / "near.png"
    micro = tmp_path / "micro.png"
    _png(str(near))
    _png(str(micro))

    from concurrent.futures import Future

    fut = Future()
    fut.set_result(
        {
            "ok": True,
            "near_path": str(near),
            "far_path": "",
            "micro_path": str(micro),
            "us_path": "",
            "thesis": "t",
            "as_of": "20261031",
        }
    )
    monkeypatch.setattr("wayne_navigator.submit_mpl_paint", lambda fn: fut)
    monkeypatch.setattr(
        "biaoke_level_learn.latest_teach_kit",
        lambda *_a, **_k: {
            "far_path": "",
            "near_path": str(near),
            "micro_path": str(micro),
            "us_path": "",
            "thesis": "t",
            "as_of": "20261031",
        },
    )
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda: True)
    monkeypatch.setattr("config.skip_chart_warmup", lambda: False)
    monkeypatch.setattr(
        "biaoke_level_learn._build_live_pack",
        lambda *_a, **_k: {"thesis": "t"},
    )
    monkeypatch.setattr(
        "biaoke_level_learn._wave_now_ladder",
        lambda *_a, **_k: {"one_line": "", "now_line": ""},
    )

    msg = MagicMock()
    msg.reply_photo = AsyncMock()
    msg.reply_text = AsyncMock()
    asyncio.run(bot._send_market_wave_charts(msg, uid="1"))
    assert msg.reply_photo.await_count == 0
    assert msg.reply_text.await_count >= 1
    assert "遠窗" in (msg.reply_text.await_args.args[0] if msg.reply_text.await_args.args else "")


def test_market_page_sends_teach_before_session_cards():
    import inspect

    src = inspect.getsource(WayneTelegramBot._send_market_page)
    assert src.index("_send_market_wave_charts") < src.index("_send_market_session_cards")
