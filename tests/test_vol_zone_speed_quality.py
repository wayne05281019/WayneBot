# -*- coding: utf-8 -*-
"""壓力區圖速度／畫質：假日快取、DPI、名單兩段式出圖。"""
from __future__ import annotations

import inspect
import os
import tempfile
import time

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_tw_holiday_rows_cached_across_lookups():
    from tw_holidays import _load_db_rows, clear_tw_holiday_row_cache, lookup_tw_session

    db = get_db_path()
    clear_tw_holiday_row_cache()
    t0 = time.perf_counter()
    for _ in range(200):
        lookup_tw_session("20260925", db)
    coldish = time.perf_counter() - t0
    # 第二次區間應吃到記憶體快取（遠快於每問開庫）
    t0 = time.perf_counter()
    for _ in range(200):
        lookup_tw_session("20260901", db)
    warm = time.perf_counter() - t0
    assert warm < 0.25, warm
    assert coldish < 1.5, coldish
    rows = _load_db_rows(db)
    assert isinstance(rows, dict)


def test_vol_zone_dpi_and_jpeg_quality_floor():
    from vol_zone_chart import (
        VOL_ZONE_DPI,
        VOL_ZONE_FIG_W,
        VOL_ZONE_JPEG_QUALITY,
        VOL_ZONE_TAG_PT,
        _paint_volume_zone,
    )

    assert VOL_ZONE_DPI >= 220
    assert VOL_ZONE_JPEG_QUALITY >= 92
    assert VOL_ZONE_TAG_PT >= 15
    assert VOL_ZONE_FIG_W >= 11.2
    src = inspect.getsource(_paint_volume_zone)
    # 日 K 影線 LineCollection 在共用 paint 內
    assert "paint_lookup_ohlc_candles" in src
    assert "VOL_ZONE_JPEG_QUALITY" in src or "pil_kwargs" in src


def test_pressure_list_streams_per_stock_not_whole_page():
    """壓撐名單逐檔送；不准整頁 two_phase 逾時讓後面檔消失。"""
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._run_pressure_support)
    assert "submit_mpl_paint" in src
    assert "render_volume_zone_result" in src
    assert "render_volume_zones_two_phase" not in src
    batch = open("chart_batch.py", encoding="utf-8").read()
    assert "prepare_volume_zone" in batch
    assert "_paint_volume_zone" in batch
    assert batch.find("prepare_volume_zones_parallel") < batch.find("paint_volume_zones_serial")


def test_vol_zone_render_memo_reuses_file(tmp_path):
    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    clear_vol_zone_render_cache()
    db = get_db_path()
    a = str(tmp_path / "a.jpg")
    b = str(tmp_path / "b.jpg")
    p1, c1 = render_volume_zone_result(
        "2330", "台積電", db, a, with_nav_signals=True
    )
    assert p1 and os.path.isfile(p1) and os.path.getsize(p1) > 20000
    t0 = time.perf_counter()
    p2, c2 = render_volume_zone_result(
        "2330", "台積電", db, b, with_nav_signals=True
    )
    elapsed = time.perf_counter() - t0
    assert p2 and os.path.isfile(p2)
    assert c1 == c2
    # 快取命中應遠快於完整重渲（本機通常 <0.05s）
    assert elapsed < 0.35, elapsed


def test_vol_zone_memo_hits_with_lookup_card(tmp_path):
    """查股路徑必帶 card；有卡也要暖命中，不准再整圖重渲。"""
    from wayne_navigator import NavigatorEngine
    from vol_zone_chart import clear_vol_zone_render_cache, render_lookup_vol_result

    clear_vol_zone_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    assert isinstance(card, dict) and not card.get("error")
    card.pop("_ohlc", None)
    a = str(tmp_path / "card_a.jpg")
    b = str(tmp_path / "card_b.jpg")
    p1, c1 = render_lookup_vol_result("2330", "台積電", db, a, card=card)
    assert p1 and os.path.isfile(p1) and os.path.getsize(p1) > 20000
    t0 = time.perf_counter()
    p2, c2 = render_lookup_vol_result("2330", "台積電", db, b, card=card)
    elapsed = time.perf_counter() - t0
    assert p2 and os.path.isfile(p2)
    assert c1 == c2
    assert elapsed < 0.35, elapsed


def test_pressure_screen_cache_hit():
    from pressure_support_watch import (
        clear_pressure_screen_cache,
        screen_pressure_support,
    )

    clear_pressure_screen_cache()
    db = get_db_path()
    t0 = time.perf_counter()
    a = screen_pressure_support(db, "sideways")
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    b = screen_pressure_support(db, "sideways")
    warm = time.perf_counter() - t0
    assert [r["code"] for r in a] == [r["code"] for r in b]
    assert warm < 0.05, warm
    assert cold > warm


def test_pressure_screen_cold_under_budget_and_frame_reuse():
    """名單掃檔：numpy＋日Ｋ快取後冷啟動應遠低於舊 pandas 牆鐘。"""
    from pressure_support_watch import (
        clear_pressure_screen_cache,
        screen_pressure_support,
    )

    clear_pressure_screen_cache()
    db = get_db_path()
    t0 = time.perf_counter()
    a = screen_pressure_support(db, "sideways")
    cold = time.perf_counter() - t0
    # 舊路徑約 8s；快路徑目標 <4s（本機常 <2s）
    assert cold < 4.0, cold
    # 換標籤：名單快取未命中，但同 as_of 日Ｋ框應复用
    t0 = time.perf_counter()
    b = screen_pressure_support(db, "test_press")
    other = time.perf_counter() - t0
    assert other < 4.0, other
    assert other < cold + 0.5, (other, cold)
    t0 = time.perf_counter()
    c = screen_pressure_support(db, "test_press")
    warm = time.perf_counter() - t0
    assert [r["code"] for r in b] == [r["code"] for r in c]
    assert warm < 0.05, warm
    assert isinstance(a, list) and isinstance(b, list)


def test_pressure_numpy_matches_pandas_classify():
    """快路徑門檻與舊 pandas light_work＋find_volume_zone 一致。"""
    from pressure_support_watch import (
        TAG_SIDEWAYS,
        _bars_from_frame,
        _classify_bars_np,
        _find_volume_zone_np,
        _load_frames,
        _universe_ids,
        _ymd,
        classify_bars,
        clear_pressure_screen_cache,
        light_work,
    )
    from vol_zone_chart import VOL_ZONE_LOOKBACK, find_volume_zone
    from import_health import latest_complete_quote_date

    clear_pressure_screen_cache()
    db = get_db_path()
    as_of = str(latest_complete_quote_date(db) or "")
    codes = [s for s, _ in _universe_ids(db)][:400]
    frames = _load_frames(db, as_of, codes)
    checked = 0
    for sid, df in frames.items():
        work = light_work(df)
        bars = _bars_from_frame(df)
        if work is None or bars is None:
            continue
        z1 = find_volume_zone(work)
        dates, _o, highs, lows, closes, vols, halt = bars
        z2 = _find_volume_zone_np(
            dates, highs, lows, closes, vols, halt, lookback=VOL_ZONE_LOOKBACK
        )
        if (z1 is None) != (z2 is None):
            raise AssertionError(sid)
        if z1 and z2:
            assert abs(float(z1["high"]) - float(z2["high"])) < 1e-6
            assert abs(float(z1["low"]) - float(z2["low"])) < 1e-6
            assert _ymd(z1.get("date")) == _ymd(z2.get("date"))
            h1 = classify_bars(work, z1, tag=TAG_SIDEWAYS)
            h2 = _classify_bars_np(
                dates, highs, lows, closes, vols, halt, z2, tag=TAG_SIDEWAYS
            )
            assert bool(h1) == bool(h2)
        checked += 1
        if checked >= 120:
            break
    assert checked >= 80
