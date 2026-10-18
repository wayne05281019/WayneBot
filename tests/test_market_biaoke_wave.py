# -*- coding: utf-8 -*-
"""台股大盤只畫飆大講過的位。不印他沒編號的浪，不把剩餘點數換成價。"""
from __future__ import annotations

import inspect
import os

import pandas as pd
from PIL import Image


def test_date_steps_match_his_october_26():
    from market_biaoke_wave import weekday_steps

    assert weekday_steps("20261016", "20261026") == 6
    assert weekday_steps("20261026", "20261016") is None


def test_caption_uses_only_labels_he_said():
    from market_biaoke_wave import market_wave_caption_lines

    lines = "\n".join(market_wave_caption_lines("20261016"))
    assert "2026/10/16" in lines
    assert "C-3-5" in lines
    assert "C-3-3" in lines
    assert "10/26" in lines
    assert "DC" in lines
    assert "多頭一年" in lines
    assert "過年後再下＝他沒說" in lines
    assert "1-2-3-4-5" not in lines
    assert "56000" not in lines
    assert "4000" not in lines


def test_overlay_source_does_not_invent_impulse_or_point_drop():
    import market_biaoke_wave as mod

    src = inspect.getsource(mod.paint_biaoke_market_marks)
    path_src = inspect.getsource(mod._biaoke_dc_proj_path)
    assert "1-2-3-4-5" not in src
    assert "56000" not in src
    assert "4000" not in src
    assert "56000" not in path_src
    assert "48240" in inspect.getsource(mod)
    assert "39000" in inspect.getsource(mod)
    assert "45000" in inspect.getsource(mod)
    assert mod.NOT_FLOOR == 45000.0
    assert "不止跌" in src
    # DC 臉：虛線未走、粉 pin、紅價標；路徑函式只吐他點過的價
    assert "_biaoke_dc_proj_path" in src
    assert "_draw_map_pin" in src
    assert "C-3-5" in src
    assert "不准壓到縮圖 K" in inspect.getsource(mod) or "不准壓" in inspect.getsource(mod)
    assert "axhspan" not in src  # 灰帶改 fill_between 右側，不准整幅蓋 K
    pts = mod._biaoke_dc_proj_path(10.0, 47111.26, 6)
    ys = {round(p[1], 2) for p in pts}
    assert 47111.26 in ys
    assert float(mod.NOT_FLOOR) in ys
    assert float(mod.ZONE_LO) in ys
    assert 56000.0 not in ys
    # 折點 x 都在最後一根右側
    assert all(p[0] > 10.0 for p in pts)


def test_market_chart_calls_overlay_and_keeps_us_refresh():
    import bot_servers
    import index_kline_chart as ik

    assert "paint_biaoke_market_marks" in inspect.getsource(ik.render_index_kline_png)
    page = inspect.getsource(bot_servers.WayneTelegramBot._send_market_page)
    assert page.index("refresh_us_for_market_page") < page.index("_send_market_kline")
    assert "他 10/17 說的 C 波區間" in inspect.getsource(
        bot_servers.WayneTelegramBot._send_market_kline
    )


def test_render_puts_zone_right_of_candles(tmp_path):
    from index_kline_chart import render_index_kline_png

    rows = []
    px = 45000.0
    for i, day in enumerate(range(1, 21)):
        ymd = f"202610{day:02d}"
        if day >= 18:
            break
        op = px
        cl = px + (80 if i % 2 == 0 else -120)
        rows.append(
            {
                "date": ymd,
                "open": op,
                "high": max(op, cl) + 40,
                "low": min(op, cl) - 40,
                "close": cl,
                "volume": 1_000_000 + i,
            }
        )
        px = cl
    rows[-1]["date"] = "20261016"
    rows[-1]["high"] = 47520.6
    rows[-1]["low"] = 46995.03
    rows[-1]["close"] = 47111.26
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    out = str(tmp_path / "mkt.png")
    path = render_index_kline_png(df, out, title="加權指數")
    assert path and os.path.isfile(path)
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        w, h = rgb.size
        # 右側演化區應比左側K棒更偏紫，且左上角報價底仍是淺色。
        def mean(box):
            crop = rgb.crop(box)
            pix = list(crop.getdata())
            n = max(len(pix), 1)
            return tuple(sum(p[i] for p in pix) / n for i in range(3))

        right = mean((int(w * 0.72), int(h * 0.48), int(w * 0.90), int(h * 0.62)))
        assert right[2] > right[1] + 8
        corner = rgb.getpixel((8, 8))
        assert corner[0] > 200 and corner[1] > 200 and corner[2] > 200


def test_index_view_starts_may_not_january():
    """五月短窗：1～4 月不進畫面，右側演化區才夠寬。"""
    import index_kline_chart as ik

    assert ik._VIEW_START_YMD == "20260501"
    rows = []
    px = 22000.0
    for ymd in (
        "20260115",
        "20260315",
        "20260415",
        "20260505",
        "20260605",
        "20260705",
        "20260805",
        "20260905",
        "20261001",
        "20261016",
    ):
        rows.append(
            {
                "date": ymd,
                "open": px,
                "high": px + 100,
                "low": px - 100,
                "close": px + 20,
                "volume": 1_000_000,
            }
        )
        px += 500
    rows[-1]["close"] = 47111.26
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    # 走裁窗邏輯（不真正存圖也能驗 work 起點）
    full = df.copy()
    ymd = full["date"].astype(str).str[:8]
    view = full.loc[ymd >= ik._VIEW_START_YMD]
    assert str(view["date"].iloc[0])[:8] >= "20260501"
    assert "20260115" not in set(view["date"].astype(str))
    assert "20260415" not in set(view["date"].astype(str))
