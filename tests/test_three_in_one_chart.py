# -*- coding: utf-8 -*-
"""查股三合一（T0118）產品路徑：官方柱、順序、子鍵去重。"""
from __future__ import annotations

import inspect
import os

import pytest


def test_three_in_one_module_lock_and_api():
    import three_in_one_chart as tio

    assert tio.LOCK_KEY == "T0118"
    assert "藍▲紅框" in (tio.THREE_IN_ONE_CAPTION_HEAD + open(tio.__file__, encoding="utf-8").read())
    src = open(tio.__file__, encoding="utf-8").read()
    assert "with_nav_signals=True" in src
    assert "不准盤中假柱" in src or "官方" in src
    assert "as_of != \"20261002\"" not in src
    assert "render_three_in_one_result" in src


def test_hub_keyboard_drops_kline_and_nav():
    from bot_servers import WayneTelegramBot

    hub_src = inspect.getsource(WayneTelegramBot._hub_keyboard)
    assert 'callback_data=f"g:{c}"' not in hub_src
    assert 'InlineKeyboardButton("導航圖"' not in hub_src
    assert 'InlineKeyboardButton("K線"' not in hub_src
    assert "kline_page_url" not in hub_src
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    labels = [b.text for r in bot._hub_keyboard("2330").inline_keyboard for b in r]
    assert "導航圖" not in labels and "K線" not in labels


@pytest.mark.production_db
def test_render_three_in_one_6526_smoke(tmp_path, production_db):
    from three_in_one_chart import render_three_in_one_result

    out = str(tmp_path / "6526-three.png")
    path, cap = render_three_in_one_result("6526", "達發", production_db, out)
    assert path and os.path.isfile(path)
    assert os.path.getsize(path) > 80_000
    assert "三合一" in (cap or "")
    # 買點說明不准把紅箭頭當買訊
    assert "紅箭頭" not in (cap or "") or "不是買訊" in (cap or "") or "藍▲" in (cap or "")
