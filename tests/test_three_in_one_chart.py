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
    assert tio.TG_CLICK_MAX_SIDE <= 2560
    assert tio.COMPOSE_INNER_W <= 1600
    assert tio.TG_WH_BUDGET <= 4500
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
    assert "TG_CLICK_MAX_SIDE" in src
    assert "COMPOSE_INNER_W" in src
    assert "_header_price_chip_style" in src
    assert "quote_limit_chip_colors" in src
    assert "vol_zone_day_path_label" in src
    assert "NotoSansTC-w860.ttf" in src
    assert "/workspace/assets/fonts" not in src
    assert "ymax > 1500" not in src
    assert "COMPOSE_INNER_W" in src
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


def test_header_price_chip_only_limit_up_down():
    """普通漲＝白底紅字；漲停才紅底。跟高低卡 quote_limit_chip_colors 同源。"""
    from three_in_one_chart import CANDLE_UP, _header_price_chip_style

    fill, ink, outline, up = _header_price_chip_style(5995, 5700, 5.18)
    assert up is True
    assert fill.lower() in ("#ffffff", "#fff")
    assert ink.lower() == CANDLE_UP.lower()
    fill_u, ink_u, outline_u, _ = _header_price_chip_style(143, 130, 10.0)
    assert fill_u.lower() == "#c62828"
    assert ink_u.lower() == "#ffffff"
    fill_d, ink_d, _, _ = _header_price_chip_style(117, 130, -10.0)
    assert fill_d.lower() == "#2e7d32"
    fill_e, _, _, _ = _header_price_chip_style(143, 130, 10.0, emerging=True)
    assert fill_e.lower() in ("#ffffff", "#fff")


def test_pick_vol_axes_not_fooled_by_high_price():
    """價 5000、量 800 張：量軸仍是最下面那條，不准用 ymax>1500。"""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    from three_in_one_chart import _pick_vol_axes

    fig = Figure(figsize=(4, 6), dpi=80)
    gs = fig.add_gridspec(3, 1, height_ratios=[4.8, 0.4, 1.8], hspace=0.05)
    ax_p = fig.add_subplot(gs[0])
    ax_s = fig.add_subplot(gs[1])
    ax_v = fig.add_subplot(gs[2])
    ax_p.set_ylim(4200, 7200)
    ax_s.set_ylim(-0.2, 1.2)
    ax_v.set_ylim(0, 800)
    fig.canvas.draw()
    price, sig, vol = _pick_vol_axes(fig)
    assert price is ax_p
    assert sig is ax_s
    assert vol is ax_v


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


def test_hub_keyboard_keeps_nav_and_kline():
    from bot_servers import WayneTelegramBot

    hub_src = inspect.getsource(WayneTelegramBot._hub_keyboard)
    assert 'callback_data=f"g:{c}"' in hub_src
    assert 'InlineKeyboardButton("高低導航圖"' in hub_src
    assert 'InlineKeyboardButton("K線"' in hub_src
    assert "kline_page_url" in hub_src
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    labels = [b.text for r in bot._hub_keyboard("2330").inline_keyboard for b in r]
    assert "高低導航圖" in labels and "K線" in labels


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

    from bot_servers import WayneTelegramBot, _LOOKUP_ALBUM_MAX, _LOOKUP_JPEG_QUALITY
    from three_in_one_chart import (
        COMPOSE_INNER_W,
        TG_CLICK_MAX_SIDE,
        TG_WH_BUDGET,
        render_three_in_one_result,
    )

    out = str(tmp_path / "2383-three.png")
    path, cap = render_three_in_one_result("2383", "台光電", production_db, out)
    assert path and os.path.isfile(path)
    im = Image.open(path)
    assert max(im.size) <= TG_CLICK_MAX_SIDE + 8
    assert im.width + im.height <= TG_WH_BUDGET + 80
    assert im.width <= COMPOSE_INNER_W + 120
    # 表頭列高（合成後 400px 帶）不可幾乎全白
    head_band = im.crop((0, 0, im.width, min(im.height, 480)))
    extrema = head_band.convert("RGB").getextrema()
    assert any(hi - lo > 40 for lo, hi in extrema)

    prep = WayneTelegramBot._prepare_lookup_album_photo(path)
    assert prep and os.path.isfile(prep)
    assert _LOOKUP_JPEG_QUALITY >= 95
    pim = Image.open(prep)
    # 查股四張統一直式 4:5（1920×2400）；表頭列高跟畫布寬成比
    assert pim.size == _LOOKUP_ALBUM_MAX
    assert pim.size[0] * 5 == pim.size[1] * 4
    chat_w = 1113
    head_chat_h = int(400 * chat_w / pim.width)
    assert head_chat_h >= int(400 * chat_w / _LOOKUP_ALBUM_MAX[0]) - 1, head_chat_h
    assert head_chat_h >= 220, head_chat_h
    assert "三合一" in (cap or "")
    bubble_w = 400
    bubble = pim.resize(
        (bubble_w, max(1, int(pim.height * bubble_w / pim.width))),
        Image.Resampling.LANCZOS,
    )
    head_h = max(40, int(head_band.height * bubble_w / pim.width))
    ink = bubble.crop((8, 8, bubble_w - 8, min(bubble.height, head_h))).convert("L")
    dark = sum(1 for px in ink.getdata() if px < 80)
    assert dark >= 400, dark
    # 收盤非漲停：表頭價塊不准整塊紅底（抽今K欄中段）
    rgb = pim.convert("RGB")
    w, h = pim.size
    band = rgb.crop((int(w * 0.26), 40, int(w * 0.50), 130))
    red_fill = 0
    pale = 0
    for px in band.getdata():
        r, g, b = px
        if r > 180 and g < 90 and b < 90:
            red_fill += 1
        elif r > 220 and g > 220 and b > 220:
            pale += 1
    # 字／小K會有紅像素；底必須是白多過實心紅底
    assert pale > red_fill, (pale, red_fill)


@pytest.mark.production_db
def test_render_three_in_one_3081_volume_bars_survive_click(tmp_path, production_db):
    """聯亞：③日量柱在模擬 Telegram 點開壓縮後仍要有色柱，不准整條空白。"""
    import io

    from PIL import Image

    from bot_servers import WayneTelegramBot
    from three_in_one_chart import TG_CLICK_MAX_SIDE, render_three_in_one_result

    out = str(tmp_path / "3081-three.png")
    path, cap = render_three_in_one_result("3081", "聯亞", production_db, out)
    assert path and os.path.isfile(path)
    assert "三合一" in (cap or "")
    prep = WayneTelegramBot._prepare_lookup_album_photo(path)
    im = Image.open(prep).convert("RGB")
    assert max(im.size) <= TG_CLICK_MAX_SIDE + 8
    # 模擬點開：再 JPEG q82 4:2:0（比我們送出的還兇）
    phone_w, phone_h = 1170, 2532
    scale = min(phone_w / im.width, phone_h / im.height, 1.0)
    shown = im.resize(
        (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
        Image.Resampling.LANCZOS,
    )
    buf = io.BytesIO()
    shown.save(buf, "JPEG", quality=82, subsampling=2)
    buf.seek(0)
    click = Image.open(buf).convert("RGB")
    # ③在最下約 28%
    y0 = int(click.height * 0.72)
    band = click.crop((int(click.width * 0.08), y0, int(click.width * 0.92), click.height - 8))
    colored = 0
    for px in band.getdata():
        r, g, b = px
        if r > 160 and g < 120 and b < 110:
            colored += 1
        elif g > 110 and r < 90 and b < 130:
            colored += 1
        elif r > 180 and g > 140 and b < 80:
            colored += 1
    assert colored >= 80, colored
