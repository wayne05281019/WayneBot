# -*- coding: utf-8 -*-
"""大量區專圖：不改導航，查股第三張；只認官方原柱。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pandas as pd
import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_find_volume_zone_prefers_active_overhead():
    from vol_zone_chart import find_volume_zone

    work = pd.DataFrame(
        [
            {
                "date": "20260806",
                "open": 1405,
                "high": 1530,
                "low": 1365,
                "close": 1530,
                "volume": 16305,
                "is_halt": False,
            },
            {
                "date": "20260917",
                "open": 1445,
                "high": 1460,
                "low": 1275,
                "close": 1320,
                "volume": 21653,
                "is_halt": False,
            },
            {
                "date": "20260924",
                "open": 1485,
                "high": 1530,
                "low": 1475,
                "close": 1495,
                "volume": 10047,
                "is_halt": False,
            },
        ]
    )
    zone = find_volume_zone(work, lookback=40)
    assert zone["date"] == "20260806"
    assert zone["high"] == 1530
    assert zone["low"] == 1365
    assert zone["active"] is True


def test_find_volume_zone_excludes_last_bar():
    """最後一根即使量最大也不當大量區參考日。"""
    from vol_zone_chart import find_volume_zone

    work = pd.DataFrame(
        [
            {
                "date": "20260901",
                "open": 100,
                "high": 120,
                "low": 90,
                "close": 110,
                "volume": 5000,
                "is_halt": False,
            },
            {
                "date": "20260902",
                "open": 110,
                "high": 115,
                "low": 105,
                "close": 112,
                "volume": 90000,
                "is_halt": False,
            },
        ]
    )
    zone = find_volume_zone(work, lookback=40)
    assert zone["date"] == "20260901"
    assert zone["volume"] == 5000


def test_render_volume_zone_png_6274():
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work, render_volume_zone_png

    db = get_db_path()
    work = official_work(load_official_ohlc("6274", db, 180))
    zone = find_volume_zone(work)
    assert zone and zone["date"] == "20260806"
    assert float(zone["high"]) == 1530.0
    assert float(zone["low"]) == 1365.0
    last = work.iloc[-1]
    assert float(last["high"]) == 1530.0
    assert float(last["close"]) == 1495.0
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "6274_vz.png")
        path = render_volume_zone_png("6274", "台燿", db, out)
        assert path and os.path.isfile(path)
        assert os.path.getsize(path) > 20000


def test_lookup_sends_volzone_third_photo():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "render_volume_zone_png" in src
    assert "vol_zone_photo_caption" in src
    assert "volzone" in src
    assert "大量區" in src
    assert src.find("_send_lookup_album") < src.find("await volzone_task")
    assert src.find("create_task(_volzone_item") < src.find("packed = await asyncio.gather")
    # 不准把決策卡還原 ohlc 塞進大量區
    assert "already_normalized=True" not in src
    assert "不准用決策卡除權還原" in src or "只吃官方原柱" in src
    # 興櫃與上市櫃同一條；不准另開跳過大量區的路徑
    assert "if is_em:" in src
    assert src.find("if is_em:") < src.find("render_volume_zone_png")
    assert "merge_live=not is_em" in src
    # 導航圖本身不再疊大量區
    nav = open("wayne_navigator.py", encoding="utf-8").read()
    assert "_paint_nav_volume_zone" not in nav
    assert "大量區壓" not in nav


def test_vol_zone_ignores_adjusted_card_ohlc():
    """有 db 時即使塞入除權還原假價，仍畫官方原柱高低。"""
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work, render_volume_zone_png

    db = get_db_path()
    work = official_work(load_official_ohlc("2330", db, 180))
    zone = find_volume_zone(work)
    assert zone and zone["date"] == "20260908"
    assert float(zone["high"]) == 2505.0
    assert float(zone["low"]) == 2460.0
    # 假還原價：高改成非整數
    fake = work.copy()
    fake.loc[fake["date"] == "20260908", "high"] = 2497.637
    fake.loc[fake["date"] == "20260908", "low"] = 2452.769
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "2330_vz.png")
        path = render_volume_zone_png("2330", "台積電", db, out, fake)
        assert path and os.path.isfile(path)
    # 選區仍以官方為準
    z2 = find_volume_zone(official_work(load_official_ohlc("2330", db, 180)))
    assert float(z2["high"]) == 2505.0


def test_vol_zone_bars_match_db_exactly():
    """畫面用的每一根開高低收量＝庫內官方列，不准漂浮小數還原價。"""
    from vol_zone_chart import load_official_ohlc, official_work

    db = get_db_path()
    con = sqlite3.connect(db)
    for sid in ("2330", "6488", "6274"):
        work = official_work(load_official_ohlc(sid, db, 60))
        assert work is not None and len(work) >= 20
        for _, row in work.tail(30).iterrows():
            d = str(row["date"])
            db_row = con.execute(
                "SELECT open,high,low,close,volume FROM daily_quotes WHERE stock_id=? AND date=?",
                (sid, d),
            ).fetchone()
            assert db_row, (sid, d)
            assert float(row["open"]) == float(db_row[0])
            assert float(row["high"]) == float(db_row[1])
            assert float(row["low"]) == float(db_row[2])
            assert float(row["close"]) == float(db_row[3])
            assert float(row["volume"]) == float(db_row[4])
            # 官方整數價不該出現還原漂浮
            for col in ("open", "high", "low", "close"):
                v = float(row[col])
                assert abs(v - round(v, 2)) < 1e-9, (sid, d, col, v)
    con.close()


def test_render_volume_zone_png_markets_twse_otc_emerging():
    """上市／上櫃／興櫃都能渲出大量區專圖（查股第三張同一條）。"""
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work, render_volume_zone_png

    db = get_db_path()
    cases = [
        ("2330", "台積電", "twse"),
        ("6488", "環球晶", "otc"),
        ("1260", "FLAVOR", "emerging"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for sid, name, kind in cases:
            raw = load_official_ohlc(sid, db, 120)
            work = official_work(raw)
            assert work is not None and len(work) >= 5, (sid, kind)
            assert work["dt"].iloc[0] <= work["dt"].iloc[-1], (sid, kind)
            if kind == "emerging":
                assert str(raw["quote_source"].iloc[-1]) == "emerging_quotes"
            zone = find_volume_zone(work)
            assert zone and zone["high"] > 0 and zone["low"] > 0, (sid, kind)
            out = os.path.join(tmp, f"{sid}_vz.png")
            path = render_volume_zone_png(sid, name, db, out)
            assert path and os.path.isfile(path), (sid, kind)
            assert os.path.getsize(path) > 15000, (sid, kind, os.path.getsize(path))


def test_vol_zone_xaxis_matches_k_and_volume_index():
    """底軸刻度 index＝該根 K／量；爆大量日與最後一根一定標月日。"""
    from vol_zone_chart import (
        VOL_ZONE_BARS,
        find_volume_zone,
        load_official_ohlc,
        official_work,
        render_volume_zone_png,
    )

    db = get_db_path()
    work = official_work(load_official_ohlc("6274", db, 180))
    zone = find_volume_zone(work)
    assert zone and zone["date"] == "20260806"
    n_all = len(work)
    show_n = min(max(VOL_ZONE_BARS, 30), n_all)
    start = max(0, n_all - show_n)
    if int(zone["i"]) < start:
        start = max(0, int(zone["i"]) - 8)
    view = work.iloc[start:].reset_index(drop=True)
    spike_i = int(zone["i"]) - start
    assert str(view["date"].iloc[spike_i]) == "20260806"
    assert str(view["date"].iloc[-1]) == str(work["date"].iloc[-1])
    assert view["dt"].iloc[0] < view["dt"].iloc[-1]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "6274_axis.png")
        path = render_volume_zone_png("6274", "台燿", db, out)
        assert path and os.path.isfile(path)


def test_vol_zone_press_hold_tags_are_large():
    """話筒紅圈：大量區壓／撐要比標題更容易讀。"""
    import inspect

    from vol_zone_chart import VOL_ZONE_TAG_PT, render_volume_zone_png

    assert VOL_ZONE_TAG_PT >= 14
    src = inspect.getsource(render_volume_zone_png)
    assert "VOL_ZONE_TAG_PT" in src
    assert src.count("VOL_ZONE_TAG_PT") >= 2


def test_emerging_help_mentions_volzone():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._em_no_listed_html)
    assert "大量區" in src
    mod = open("bot_servers.py", encoding="utf-8").read(800)
    assert "上市／上櫃／興櫃一律" in mod
    assert "大量區專圖" in mod


def test_official_work_drops_live_and_keeps_raw_prices():
    from vol_zone_chart import official_work

    df = pd.DataFrame(
        [
            {
                "date": "20260901",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "is_live": False,
            },
            {
                "date": "20260902",
                "open": 105.0,
                "high": 120.0,
                "low": 100.0,
                "close": 118.0,
                "volume": 2000,
                "is_live": True,
            },
        ]
    )
    work = official_work(df)
    assert list(work["date"]) == ["20260901"]
    assert float(work.iloc[0]["high"]) == 110.0
