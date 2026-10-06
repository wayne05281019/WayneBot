# -*- coding: utf-8 -*-
"""查股三合一（T0118）產品路徑：官方柱、順序、子鍵去重。"""
from __future__ import annotations

import inspect
import os

import pytest


def test_three_in_one_module_lock_and_api():
    import three_in_one_chart as tio

    assert tio.LOCK_KEY == "T0118"
    assert tio.CHROME_SCALE >= 1.5
    assert tio.THREE_IN_ONE_JPEG_QUALITY >= 95
    assert "藍▲紅框" in (tio.THREE_IN_ONE_CAPTION_HEAD + open(tio.__file__, encoding="utf-8").read())
    src = open(tio.__file__, encoding="utf-8").read()
    assert "with_nav_signals=True" in src
    assert "不准盤中假柱" in src or "官方" in src
    assert "as_of != \"20261002\"" not in src
    assert "render_three_in_one_result" in src
    # 表頭股名必須吃 info，不准寫死 6526 達發
    assert '"6526  達發"' not in src and "'6526  達發'" not in src
    assert 'info.get("stock_id")' in src
    assert "CHROME_SCALE" in src
    assert "TG_WH_BUDGET" in src
    assert "NotoSansTC-w860.ttf" in src
    assert "/workspace/assets/fonts" not in src
    assert "PANE_DPI" in src
    assert tio.PANE_DPI == 220
    assert "18.6, 12.6" not in src
    # 表頭今K 跟 card／① 同源；不准只死釘官方末日
    assert "_header_quote_bar" in src
    assert "merge_live=True" in src
    assert "card_live" in src


def test_header_quote_bar_prefers_live_card():
    from three_in_one_chart import _header_quote_bar
    import pandas as pd

    official = pd.DataFrame(
        [
            {"date": "20261002", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1},
        ]
    )
    card = {
        "is_live": True,
        "latest_date": "20261006",
        "open": 120,
        "high": 130,
        "low": 115,
        "close": 125,
        "volume": 9,
        "prev_close": 105,
        "change_pct": 4.0,
    }
    bar, live, as_of = _header_quote_bar("2383", "", official, card)
    assert live is True
    assert as_of == "20261006"
    assert bar["close"] == 125
    assert bar["source"] == "card_live"
    assert abs(float(bar["pct"]) - 4.0) < 1e-6


def test_header_quote_bar_falls_back_to_official():
    from three_in_one_chart import _header_quote_bar
    import pandas as pd

    official = pd.DataFrame(
        [
            {"date": "20261001", "open": 100, "high": 110, "low": 90, "close": 100, "volume": 1},
            {"date": "20261005", "open": 101, "high": 111, "low": 91, "close": 108, "volume": 2},
        ]
    )
    bar, live, as_of = _header_quote_bar("9999", "", official, {"error": "x"})
    assert live is False
    assert as_of == "20261005"
    assert bar["close"] == 108
    assert bar["source"] == "official_as_of"


def test_three_in_one_pil_font_is_bundled_cjk():
    """聯亞真機表頭／圖例糊成點＝Pillow load_default；必須吃 repo NotoSansTC。"""
    from PIL import ImageFont

    from three_in_one_chart import _BUNDLE_BOLD, _font

    assert os.path.isfile(_BUNDLE_BOLD)
    f = _font(64, True)
    path = str(getattr(f, "path", "") or "")
    assert "NotoSansTC" in path or "NotoSansCJK" in path
    default = ImageFont.load_default()
    cjk = "聯亞"
    fb = f.getbbox(cjk)
    db = default.getbbox(cjk)
    assert (fb[2] - fb[0]) >= 90
    assert (fb[2] - fb[0]) > (db[2] - db[0]) * 4


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


@pytest.mark.production_db
def test_render_three_in_one_2383_header_name_and_budget(tmp_path, production_db):
    """台光電：表頭必須寫 2383／台光電；整張守 TG w+h；縮圖後表頭列高仍老花可讀。"""
    from PIL import Image

    from bot_servers import WayneTelegramBot, _LOOKUP_JPEG_QUALITY
    from three_in_one_chart import CHROME_SCALE, TG_WH_BUDGET, render_three_in_one_result

    out = str(tmp_path / "2383-three.png")
    path, cap = render_three_in_one_result("2383", "台光電", production_db, out)
    assert path and os.path.isfile(path)
    im = Image.open(path)
    assert im.width + im.height <= TG_WH_BUDGET + 50
    # 表頭列高至少鎖版×CHROME 的八成（合成後含 margin）
    head_band = im.crop((0, 0, im.width, min(im.height, int(500 * CHROME_SCALE) + 80)))
    # 粗檢：表頭帶不可幾乎全白／全灰（有色塊才算畫出來）
    extrema = head_band.convert("RGB").getextrema()
    assert any(hi - lo > 40 for lo, hi in extrema)

    prep = WayneTelegramBot._prepare_lookup_album_photo(path)
    assert prep and os.path.isfile(prep)
    assert _LOOKUP_JPEG_QUALITY >= 95
    pim = Image.open(prep)
    # 模擬氣泡寬 ~1113：表頭帶高度應 ≥ 280px（相對鎖版放大後老花可讀）
    chat_w = 1113
    chat_h = int(pim.height * chat_w / pim.width)
    head_chat_h = int((500 * CHROME_SCALE) * chat_w / pim.width)
    assert head_chat_h >= 280, head_chat_h
    assert chat_h > 1000
    assert "三合一" in (cap or "")
    # 氣泡寬 400：表頭國字必須是塊狀墨，不准只剩 load_default 小點
    bubble_w = 400
    bubble = pim.resize(
        (bubble_w, max(1, int(pim.height * bubble_w / pim.width))),
        Image.Resampling.LANCZOS,
    )
    head_h = max(40, int(head_band.height * bubble_w / pim.width))
    ink = bubble.crop((8, 8, bubble_w - 8, min(bubble.height, head_h))).convert("L")
    dark = sum(1 for px in ink.getdata() if px < 80)
    assert dark >= 400, dark
