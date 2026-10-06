# -*- coding: utf-8 -*-
"""導航 180＋多檔兩段式出圖速度。"""
from __future__ import annotations

import inspect
import os
import tempfile
import time

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_paint_nav_uses_linecollection():
    from wayne_navigator import _paint_nav_on_axes, paint_lookup_ohlc_candles

    src = inspect.getsource(_paint_nav_on_axes)
    # 導航日 K 走查股共用 paint（影線 LineCollection 在 paint 內）
    assert "paint_lookup_ohlc_candles" in src
    paint_src = inspect.getsource(paint_lookup_ohlc_candles)
    assert "LineCollection" in paint_src
    assert "add_collection" in paint_src


def test_align_ohlc_cached_hits():
    from wayne_navigator import (
        _load_ohlc,
        align_ohlc_cached,
        clear_align_ohlc_cache,
        _nav_work_or_none,
    )

    clear_align_ohlc_cache()
    db = get_db_path()
    raw = _load_ohlc("2330", db, 180)
    work = _nav_work_or_none(raw, already_normalized=False)
    assert work is not None and len(work) > 30
    t0 = time.perf_counter()
    a = align_ohlc_cached(work, "2330")
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    b = align_ohlc_cached(work, "2330")
    warm = time.perf_counter() - t0
    assert a is not None and len(a) >= len(work) - 5
    assert len(a) == len(b)
    assert warm < cold
    assert warm < 0.05, warm


def test_nav180_render_memo(tmp_path):
    from wayne_navigator import clear_lookup_render_cache, generate_chart

    clear_lookup_render_cache()
    db = get_db_path()
    a = str(tmp_path / "a.png")
    b = str(tmp_path / "b.png")
    p1 = generate_chart("2330", "台積電", db, a)
    assert p1 and os.path.isfile(p1) and os.path.getsize(p1) > 50000
    t0 = time.perf_counter()
    p2 = generate_chart("2330", "台積電", db, b)
    elapsed = time.perf_counter() - t0
    assert p2 and os.path.isfile(p2)
    assert elapsed < 0.25, elapsed


def test_chart_batch_two_phase_api():
    from chart_batch import (
        paint_volume_zones_serial,
        prepare_volume_zones_parallel,
        render_volume_zones_two_phase,
    )

    assert callable(prepare_volume_zones_parallel)
    assert callable(paint_volume_zones_serial)
    assert callable(render_volume_zones_two_phase)
    # 話筒壓撐名單改逐檔串流；two_phase API 仍保留給批次腳本
    bot = open("bot_servers.py", encoding="utf-8").read()
    assert "render_volume_zone_result" in bot
    assert "submit_mpl_paint" in bot


def test_vol_zone_uses_align_cache():
    import inspect

    from vol_zone_chart import official_work

    src = inspect.getsource(official_work)
    assert "align_ohlc_cached" in src
