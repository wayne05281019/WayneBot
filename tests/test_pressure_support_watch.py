# -*- coding: utf-8 -*-
"""壓撐觀察：三標籤門檻與主選單上六下七。"""
from __future__ import annotations

import pandas as pd

from pressure_support_watch import (
    SIDEWAYS_N,
    STAND_SUPPORT_W,
    TAG_SIDEWAYS,
    TAG_STAND_SUPPORT,
    TAG_TEST_PRESS,
    TEST_PRESS_DIST_PCT,
    classify_bars,
    normalize_tag,
    tag_label,
)


def _bars(rows):
    df = pd.DataFrame(rows)
    df["is_halt"] = False
    return df


def _zone(hi=100.0, lo=90.0, date="20260101", volume=10000):
    return {"high": hi, "low": lo, "date": date, "volume": volume, "active": True}


def test_tag_labels_and_thresholds():
    assert tag_label(TAG_SIDEWAYS) == "壓力橫盤"
    assert tag_label(TAG_TEST_PRESS) == "測壓未破"
    assert tag_label(TAG_STAND_SUPPORT) == "剛站上撐"
    assert normalize_tag("測壓未破") == TAG_TEST_PRESS
    assert SIDEWAYS_N == 2
    assert STAND_SUPPORT_W == 5
    assert TEST_PRESS_DIST_PCT == 0.5


def test_sideways_exactly_two_in_band():
    # zone day 0101; then two closes in band → hit; three would miss
    rows = [
        {"date": "20260101", "open": 95, "high": 100, "low": 90, "close": 95, "volume": 10000},
        {"date": "20260102", "open": 94, "high": 96, "low": 93, "close": 95, "volume": 1000},
        {"date": "20260103", "open": 94, "high": 97, "low": 93, "close": 96, "volume": 1000},
    ]
    work = _bars(rows)
    zone = _zone()
    hit = classify_bars(work, zone, tag=TAG_SIDEWAYS)
    assert hit and hit["streak"] == 2
    # add third in-band → exactly-2 fails
    rows2 = rows + [
        {"date": "20260104", "open": 94, "high": 97, "low": 93, "close": 95, "volume": 1000},
    ]
    assert classify_bars(_bars(rows2), zone, tag=TAG_SIDEWAYS) is None


def test_test_press_touch_and_half_pct():
    rows = [
        {"date": "20260101", "open": 95, "high": 100, "low": 90, "close": 95, "volume": 10000},
        {"date": "20260110", "open": 99, "high": 100.2, "low": 99, "close": 99.6, "volume": 2000},
    ]
    work = _bars(rows)
    zone = _zone()
    hit = classify_bars(work, zone, tag=TAG_TEST_PRESS)
    assert hit is not None
    assert hit["dist_to_press_pct"] <= 0.5 + 1e-9
    # too far from pressure
    rows_far = [
        rows[0],
        {"date": "20260110", "open": 96, "high": 100.2, "low": 95, "close": 96, "volume": 2000},
    ]
    assert classify_bars(_bars(rows_far), zone, tag=TAG_TEST_PRESS) is None
    # close above pressure = not test
    rows_over = [
        rows[0],
        {"date": "20260110", "open": 99, "high": 101, "low": 99, "close": 100.5, "volume": 2000},
    ]
    assert classify_bars(_bars(rows_over), zone, tag=TAG_TEST_PRESS) is None


def test_stand_support_exactly_five_from_below():
    rows = [
        {"date": "20260101", "open": 95, "high": 100, "low": 90, "close": 95, "volume": 10000},
        {"date": "20260102", "open": 88, "high": 89, "low": 87, "close": 88, "volume": 1000},  # below
    ]
    # five stands
    for i, d in enumerate(["20260103", "20260104", "20260105", "20260106", "20260107"]):
        rows.append(
            {"date": d, "open": 91, "high": 93, "low": 90.5, "close": 91 + i * 0.1, "volume": 1000}
        )
    work = _bars(rows)
    zone = _zone()
    hit = classify_bars(work, zone, tag=TAG_STAND_SUPPORT)
    assert hit and hit["streak"] == 5
    # only 3 stands → miss
    short = rows[:2] + rows[2:5]
    assert classify_bars(_bars(short), zone, tag=TAG_STAND_SUPPORT) is None
    # 參考日後連續站滿 5（邊界起算）仍可入選，對齊掃檔
    edge = [rows[0]] + [
        {"date": d, "open": 91, "high": 93, "low": 90.5, "close": 92, "volume": 1000}
        for d in ["20260103", "20260104", "20260105", "20260106", "20260107"]
    ]
    assert classify_bars(_bars(edge), zone, tag=TAG_STAND_SUPPORT) is not None
    # 連站 6 根 → 不是恰好 5
    six = [rows[0]] + [
        {"date": d, "open": 91, "high": 93, "low": 90.5, "close": 92, "volume": 1000}
        for d in ["20260102", "20260103", "20260104", "20260105", "20260106", "20260107"]
    ]
    assert classify_bars(_bars(six), zone, tag=TAG_STAND_SUPPORT) is None



def test_menu_six_plus_seven_pressure_after_overnight():
    from bot_servers import (
        MENU_BTN_PRESSURE,
        MENU_LAYOUT_VERSION,
        MENU_ROW1,
        MENU_ROW2,
        WayneTelegramBot,
    )

    assert MENU_LAYOUT_VERSION == "31"
    assert len(MENU_ROW1) == 6 and len(MENU_ROW2) == 7
    assert MENU_ROW2[0] == "當沖"
    assert MENU_ROW2[1] == "隔日沖"
    assert MENU_ROW2[2] == MENU_BTN_PRESSURE
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert [b.text for b in kb.keyboard[1]] == list(MENU_ROW2)
    tags = [b.text for b in bot._pressure_tag_keyboard().inline_keyboard[0]]
    assert tags == ["壓力橫盤", "測壓未破", "剛站上撐"]
    # 點股票 callback＝psk（一次三張），不是一般 k:
    row = bot._pressure_pick_row("2330", "台積電", "test_press")
    assert row[0].callback_data.startswith("psk:2330")
    hub = bot._pressure_hub_keyboard("2330")
    labels = [b.text for r in hub.inline_keyboard for b in r]
    assert "介紹圖" in labels and "導航圖" in labels and "產業" in labels


def test_vol_zone_with_nav_signals_flag(tmp_path):
    from vol_zone_chart import render_volume_zone_png
    import inspect
    import os

    from wayne_navigator import overlay_nav_marks_on_zone

    # 疊加必須含殘影（跟導航圖同一套），不准只有觸發／接近
    ov = inspect.getsource(overlay_nav_marks_on_zone)
    assert "_NAV_GHOST" in ov
    assert "仍貼 20 高" in ov or "殘影" in ov
    assert "alpha=0.42" in ov

    db = "/workspace/data/wayne_market.db"
    if not os.path.isfile(db):
        return
    out = str(tmp_path / "vz_nav.jpg")
    path = render_volume_zone_png(
        "2330", "台積電", db, out, with_nav_signals=True
    )
    assert path and os.path.isfile(path)
    assert os.path.getsize(path) > 50_000


def test_vol_zone_layout_k_first_no_fake_bars():
    """中間 K 為主：標題列含圖例、壓撐圖內角、爆大量貼柱頂、無灰假柱。"""
    import inspect

    from vol_zone_chart import _paint_volume_zone
    from wayne_navigator import _draw_nav_legend, overlay_nav_marks_on_zone, _paint_nav_on_axes

    src = inspect.getsource(_paint_volume_zone)
    assert "ex_labels" in src
    assert "left_guard" in src
    assert "GridSpec" in src and "ax_head" in src
    assert "panel=True" in src
    assert "draw_legend=False" in src
    # 壓撐回圖內左上／左下
    assert "0.012" in src and "0.975" in src and "0.025" in src
    assert "left=0.16" not in src
    assert "xytext=(0, 2)" in src
    assert "stub_h" not in src
    # 分隔線用 #90a4ae；不准再畫灰假柱（stub_h 已禁）
    assert 'axhline(0.70, color="#90a4ae"' in src
    leg = inspect.getsource(_draw_nav_legend)
    assert "panel" in leg
    assert 'loc="upper left" if panel' in leg
    assert "0.66" in leg  # 圖例頂在分隔線下，往下長
    assert "0.70" in src  # 介紹／圖例分隔
    assert "0.84" in src  # 開高低收在分隔線上方
    # 量能列上下三角同尺寸
    for fn in (overlay_nav_marks_on_zone, _paint_nav_on_axes):
        s = inspect.getsource(fn)
        assert s.count("scale=1.15") >= 2
        assert "scale=0.78" not in s


def test_pressure_not_buy_signal_in_rows():
    from pressure_support_watch import pressure_card_html

    item = {
        "stock_id": "2330",
        "stock_name": "台積電",
        "tag": TAG_TEST_PRESS,
        "tag_label": "測壓未破",
        "close": 99.6,
        "pressure": 100,
        "support": 90,
        "volume": 1000,
        "dist_to_press_pct": 0.4,
        "zone_date": "20260101",
        "why": "測壓貼壓0.40%",
        "entry_stars": 0,
        "buy_gate": "no",
    }
    html = pressure_card_html(item, 1)
    assert "只觀察，不是買訊" in html
    assert "★" not in html
    assert "黃金買點" not in html
