# -*- coding: utf-8 -*-
"""大盤／導航／飆大三圖：速度＋畫質＋排版（時間戳右上、不互壓）。"""
from __future__ import annotations

import inspect
import os
import tempfile
import time

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_index_kline_uses_linecollection_and_stamp_ur():
    import index_kline_chart as ik
    from index_kline_chart import render_index_kline_png

    src = inspect.getsource(render_index_kline_png)
    assert "LineCollection" in src
    assert "_lookup_render_memo_get" in src
    assert "0.985" in src  # 整圖右上時間戳
    assert "axhline(h60" in src or "linewidth=0.95" in src
    mod = inspect.getsource(ik)
    assert "from matplotlib.collections import LineCollection" in mod


def test_index_kline_memo_fast(tmp_path):
    from index_kline_chart import build_market_kline_chart
    from wayne_navigator import clear_lookup_render_cache

    clear_lookup_render_cache()
    db = get_db_path()
    a = str(tmp_path / "m1.jpg")
    b = str(tmp_path / "m2.jpg")
    p1 = build_market_kline_chart(a, days=180, db_path=db)
    assert p1 and os.path.isfile(p1) and os.path.getsize(p1) > 80_000
    t0 = time.perf_counter()
    p2 = build_market_kline_chart(b, days=180, db_path=db)
    elapsed = time.perf_counter() - t0
    assert p2 and os.path.isfile(p2)
    assert elapsed < 0.50, elapsed


def test_nav_buy_arrow_red_frame_and_jpeg():
    from wayne_navigator import (
        _NAV_BUY_ARROW_EDGE,
        _NAV_BUY_ARROW_H_MULT,
        _draw_nav_legend,
        _nav_arrow,
        draw_from_ohlc,
    )

    assert _NAV_BUY_ARROW_H_MULT >= 1.5
    assert _NAV_BUY_ARROW_EDGE.upper().startswith("#C")
    assert "edge" in inspect.signature(_nav_arrow).parameters
    leg = inspect.getsource(_draw_nav_legend)
    assert "買點↑首清楚／續淡" in leg or "買點↑藍▲紅框" in leg
    src = inspect.getsource(draw_from_ohlc)
    assert "_savefig_lookup_png" in src
    assert "0.985" in src


def test_nav180_jpeg_memo(tmp_path):
    from wayne_navigator import clear_lookup_render_cache, generate_chart

    clear_lookup_render_cache()
    db = get_db_path()
    a = str(tmp_path / "n1.jpg")
    b = str(tmp_path / "n2.jpg")
    p1 = generate_chart("2330", "台積電", db, a)
    assert p1 and os.path.isfile(p1) and os.path.getsize(p1) > 80_000
    t0 = time.perf_counter()
    p2 = generate_chart("2330", "台積電", db, b)
    elapsed = time.perf_counter() - t0
    assert p2 and os.path.isfile(p2)
    assert elapsed < 0.50, elapsed


def test_biaoke_broken_rail_and_dpi(tmp_path):
    from biaoke_brain import load_bars
    from biaoke_chart import (
        BIAOKE_CHART_DPI,
        analyze_structure,
        build_biaoke_structure_chart,
        render_biaoke_structure_png,
        _BARS,
    )
    from wayne_navigator import NAV_CHART_DPI, clear_lookup_render_cache

    assert 160 <= BIAOKE_CHART_DPI <= 220
    assert BIAOKE_CHART_DPI < NAV_CHART_DPI
    db = get_db_path()
    bars = load_bars(db, "2383", n=360)
    assert bars
    info = analyze_structure(bars[-_BARS:])
    # 9 個月窗滾動後 up_broken 可 True／False；鎖程式有分支＋能出圖，不准鎖死舊窗
    assert isinstance(info.get("up_broken"), bool)
    if info.get("up_broken") is True:
        assert (info.get("project") or {}).get("up_fut") in (None, 0) or not (
            info.get("project") or {}
        ).get("up_fut")
    else:
        assert info.get("up_pts") or (info.get("channel") or {}).get("kind")
    src = inspect.getsource(render_biaoke_structure_png)
    assert "不是買訊" in src
    assert "up_broken" in src
    clear_lookup_render_cache()
    out = str(tmp_path / "2383.jpg")
    r = build_biaoke_structure_chart(db, "2383", out, name="台光電")
    assert r.get("ok") and os.path.isfile(out)
    assert os.path.getsize(out) > 80_000
    # memo
    out2 = str(tmp_path / "2383b.jpg")
    t0 = time.perf_counter()
    r2 = build_biaoke_structure_chart(db, "2383", out2, name="台光電")
    elapsed = time.perf_counter() - t0
    assert r2.get("ok")
    assert elapsed < 0.60, elapsed
