# -*- coding: utf-8 -*-
"""大盤遠／近／超近一次三張：缺張要補齊，不准只出近窗。"""
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


def test_market_wave_sends_trio_album_even_if_paint_only_near(tmp_path, monkeypatch):
    """活畫只出近窗時，仍要用已存遠／超近湊滿一次三張相簿。"""
    import asyncio

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "m.db")
    bot.charts_dir = str(tmp_path)
    bot._uid_from_message = lambda _m: "1"
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    bot._stop_plain_wait = AsyncMock()
    bot._prepare_lookup_album_photo = lambda p, *a, **k: p

    near = tmp_path / "near.png"
    far = tmp_path / "far.png"
    micro = tmp_path / "micro.png"
    _png(str(near))
    _png(str(far))
    _png(str(micro))
    assert bot._market_teach_path_ok(str(far))

    from concurrent.futures import Future

    fut = Future()
    fut.set_result(
        {
            "ok": True,
            "near_path": str(near),
            "far_path": "",
            "micro_path": "",
            "us_path": "",
            "thesis": "t",
            "as_of": "20261031",
        }
    )
    monkeypatch.setattr(
        "wayne_navigator.submit_mpl_paint",
        lambda fn: fut,
    )
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
        "biaoke_level_learn._build_live_pack",
        lambda *_a, **_k: {"thesis": "t", "chart_as_of": "20261031"},
    )
    monkeypatch.setattr(
        "biaoke_level_learn._wave_now_ladder",
        lambda *_a, **_k: {"one_line": "層級一句", "now_line": ""},
    )
    monkeypatch.setattr(
        "config.skip_chart_warmup",
        lambda: False,
    )

    msg = MagicMock()
    msg.reply_media_group = AsyncMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    msg.reply_photo = AsyncMock()
    msg.reply_text = AsyncMock()

    asyncio.run(bot._send_market_wave_charts(msg, uid="1"))
    assert msg.reply_media_group.await_count == 1
    media = msg.reply_media_group.await_args.kwargs.get("media") or msg.reply_media_group.await_args.args[0]
    assert len(media) == 3
    cap = getattr(media[0], "caption", None) or ""
    assert "一次三張" in cap or "遠／近／超近" in cap