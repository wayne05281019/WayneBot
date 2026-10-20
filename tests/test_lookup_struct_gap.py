# -*- coding: utf-8 -*-
"""查股第 2 張送到第 3 張：結構圖不等大量區選窗；還要等就補一句。"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from bot_servers import WayneTelegramBot


def test_struct_gap_line_names_the_wait():
    assert WayneTelegramBot._struct_gap_line("volfill") == "結構圖在等官方成交量，補齊就送。"
    assert WayneTelegramBot._struct_gap_line("bars") == "結構圖在整理官方日K，好了就送。"
    assert WayneTelegramBot._struct_gap_line("paint") == "結構圖繪製中，好了就送。"
    assert WayneTelegramBot._struct_gap_line("") == "結構圖繪製中，好了就送。"


def test_lookup_source_splits_struct_bars_from_volume_zone():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "prepare_lookup_structure_bars" in src
    assert "prepare_volume_zone" in src
    assert "_struct_gap_line" in src
    # 1c-2g：結構 prepare 必須在建卡成功後才開，不准跟 get_decision_card 搶記憶體
    card_at = src.find("to_thread(_build_card)")
    struct_at = src.find("struct_prep_task = asyncio.create_task")
    assert card_at > 0 and struct_at > card_at
    assert src.find("live_rt = await _fetch_mis") < struct_at
    assert src.find("_struct_gap_line") < src.find("struct_item = await struct_task")
    assert src.find("struct_item = await struct_task") < src.find(
        "create_task(_vol_item())"
    )
    bars = inspect.getsource(
        __import__("vol_zone_chart", fromlist=["prepare_lookup_structure_bars"]).prepare_lookup_structure_bars
    )
    assert "hydrate_official_ex_for_gaps" not in bars
    send = inspect.getsource(WayneTelegramBot._send_card_to)
    assert send.find("_schedule_lookup_vol_ensure") < send.find("lookup_stocks")


def _png(td: str, name: str) -> str:
    path = os.path.join(td, name)
    Image.new("RGB", (800, 900), (12, 18, 28)).save(path, "PNG")
    return path


def _bot(td: str) -> WayneTelegramBot:
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = os.path.join(td, "x.db")
    bot.charts_dir = td
    bot._lookup_ctx = {}
    bot._lookup_fade_msgs = {}
    bot._menu_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._last_card = {}
    bot._pending = {}
    bot._lookup_locks = {}
    bot._lookup_op_state = {}
    return bot


class _Engine:
    def __init__(self, *_a, **_k):
        pass

    def get_decision_card(self, *_a, **_k):
        return {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100,
            "prev_close": 99,
            "open": 99,
            "high": 101,
            "low": 98,
            "volume": 1000,
            "table": [],
        }


def test_struct_paint_does_not_wait_for_volume_zone():
    """大量區選窗再慢，結構圖也先畫。不准為了第 4 張乾等。"""
    import pandas as pd

    td = tempfile.mkdtemp()
    bot = _bot(td)
    marks = {}
    work = pd.DataFrame(
        {
            "date": ["20260102"] * 8,
            "open": [1.0] * 8,
            "high": [2.0] * 8,
            "low": [0.5] * 8,
            "close": [1.0] * 8,
            "volume": [10.0] * 8,
        }
    )

    def _ensure(*_a, **_k):
        return {"sid": "2330", "confirmed_absent": [], "still_missing": [], "filled": []}

    def _bars(*_a, **_k):
        marks["bars"] = time.monotonic()
        face = work.to_dict("records")
        return {"sid": "2330", "bars": face, "work": work, "vol_ensure": _ensure()}

    def _zone(*_a, **_k):
        marks["zone_start"] = time.monotonic()
        time.sleep(0.6)
        marks["zone_end"] = time.monotonic()
        return None

    def _struct(*_a, **_k):
        marks["struct"] = time.monotonic()
        return _png(td, "s.png"), "結構圖（非買訊）　買點只認藍▲紅框"

    def _card(*_a, **_k):
        time.sleep(0.05)
        return _png(td, "c.png")

    def _glance(*_a, **_k):
        time.sleep(0.05)
        return _png(td, "g.png")

    def _vol(*_a, **_k):
        marks["vol"] = time.monotonic()
        return _png(td, "v.png"), "大量撐壓圖（非買訊）"

    message = MagicMock()
    message.from_user = SimpleNamespace(id=111, first_name="u")
    message.chat_id = 999
    message.reply_html = AsyncMock(return_value=MagicMock())
    message.reply_text = AsyncMock(return_value=MagicMock())
    message.reply_photo = AsyncMock()

    async def _run():
        with patch("wayne_navigator.NavigatorEngine", _Engine), patch(
            "chip_tape.build_tape", return_value={}
        ), patch(
            "stock_news.fetch_stock_news_stats", return_value=None
        ), patch(
            "wayne_navigator.render_first_glance_png", side_effect=_glance
        ), patch(
            "wayne_navigator.render_decision_card_png", side_effect=_card
        ), patch(
            "three_in_one_chart.render_lookup_structure_result", side_effect=_struct
        ), patch(
            "vol_zone_chart.render_lookup_vol_result", side_effect=_vol
        ), patch(
            "vol_zone_chart.ensure_official_volume_window", side_effect=_ensure
        ), patch(
            "vol_zone_chart.prepare_lookup_structure_bars", side_effect=_bars
        ), patch(
            "vol_zone_chart.prepare_volume_zone", side_effect=_zone
        ), patch.object(
            bot, "_prefetch_mis_quote", return_value=None
        ), patch.object(
            bot, "_hub_keyboard", return_value=None
        ), patch.object(
            bot, "_track_lookup_fade"
        ), patch.object(
            bot, "_dismiss_lookup_fades", new_callable=AsyncMock
        ), patch.object(
            bot, "_cache_lookup_ctx"
        ), patch.object(
            bot, "_remember_card"
        ), patch.object(
            WayneTelegramBot, "_png_looks_ok", return_value=True
        ), patch.object(
            WayneTelegramBot, "_chart_png_looks_ok", return_value=True
        ), patch.object(
            WayneTelegramBot, "_prepare_lookup_album_photo", side_effect=lambda p, kind="": p
        ):
            await bot._send_card_to_locked(
                message,
                "2330",
                "111",
                "999:111",
                [{"stock_id": "2330", "stock_name": "台積電", "close": 100}],
            )

    asyncio.run(_run())
    assert "struct" in marks and "zone_end" in marks
    assert marks["struct"] < marks["zone_end"]


def test_gap_line_while_official_volume_still_running():
    """第 2 張送出時官方量還沒齊：話筒要寫在等成交量，不准空白。"""
    td = tempfile.mkdtemp()
    bot = _bot(td)

    def _ensure(*_a, **_k):
        time.sleep(0.45)
        return {"sid": "2330", "confirmed_absent": [], "still_missing": [], "filled": []}

    def _bars(*_a, **_k):
        return {
            "sid": "2330",
            "bars": [
                {
                    "date": "20260102",
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 1,
                    "volume": 10,
                }
            ]
            * 8,
            "work": None,
            "vol_ensure": {"sid": "2330"},
        }

    def _png_fn(name):
        def _inner(*_a, **_k):
            time.sleep(0.04)
            return _png(td, name)

        return _inner

    message = MagicMock()
    message.from_user = SimpleNamespace(id=111, first_name="u")
    message.chat_id = 999
    message.reply_html = AsyncMock(return_value=MagicMock())
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_photo = AsyncMock()

    async def _run():
        with patch("wayne_navigator.NavigatorEngine", _Engine), patch(
            "chip_tape.build_tape", return_value={}
        ), patch(
            "stock_news.fetch_stock_news_stats", return_value=None
        ), patch(
            "wayne_navigator.render_first_glance_png", side_effect=_png_fn("g.png")
        ), patch(
            "wayne_navigator.render_decision_card_png", side_effect=_png_fn("c.png")
        ), patch(
            "three_in_one_chart.render_lookup_structure_result",
            side_effect=lambda *_a, **_k: (_png(td, "s.png"), "結構圖（非買訊）"),
        ), patch(
            "vol_zone_chart.render_lookup_vol_result",
            side_effect=lambda *_a, **_k: (_png(td, "v.png"), "大量撐壓圖（非買訊）"),
        ), patch(
            "vol_zone_chart.ensure_official_volume_window", side_effect=_ensure
        ), patch(
            "vol_zone_chart.prepare_lookup_structure_bars", side_effect=_bars
        ), patch.object(
            bot, "_prefetch_mis_quote", return_value=None
        ), patch.object(
            bot, "_hub_keyboard", return_value=None
        ), patch.object(
            bot, "_track_lookup_fade"
        ), patch.object(
            bot, "_dismiss_lookup_fades", new_callable=AsyncMock
        ), patch.object(
            bot, "_cache_lookup_ctx"
        ), patch.object(
            bot, "_remember_card"
        ), patch.object(
            WayneTelegramBot, "_png_looks_ok", return_value=True
        ), patch.object(
            WayneTelegramBot, "_chart_png_looks_ok", return_value=True
        ), patch.object(
            WayneTelegramBot, "_prepare_lookup_album_photo", side_effect=lambda p, kind="": p
        ):
            await bot._send_card_to_locked(
                message,
                "2330",
                "111",
                "999:111",
                [{"stock_id": "2330", "stock_name": "台積電", "close": 100}],
            )

    asyncio.run(_run())
    texts = [str(c.args[0]) for c in message.reply_text.await_args_list if c.args]
    assert any("結構圖在等官方成交量" in t for t in texts), texts
    # 第 3 張仍有送出
    caps = [
        str(c.kwargs.get("caption") or "")
        for c in message.reply_photo.await_args_list
    ]
    assert any("結構圖" in c for c in caps), caps
