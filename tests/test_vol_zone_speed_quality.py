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
    assert "LineCollection" in src
    assert "VOL_ZONE_JPEG_QUALITY" in src or "pil_kwargs" in src


def test_pressure_list_two_phase_prepare_then_paint():
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._run_pressure_support)
    assert "prepare_volume_zone" in src
    assert "_paint_volume_zone" in src
    assert "asyncio.gather" in src
    assert src.find("prepare_volume_zone") < src.find("_paint_volume_zone")


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
