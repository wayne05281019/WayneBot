# -*- coding: utf-8 -*-
"""查股介紹／高低卡／籌碼：渲圖短快取＋JPEG 提質。"""
from __future__ import annotations

import inspect
import os
import time

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_lookup_jpeg_quality_floor():
    from bot_servers import _LOOKUP_JPEG_QUALITY
    from wayne_navigator import LOOKUP_JPEG_QUALITY, _savefig_lookup_png

    assert LOOKUP_JPEG_QUALITY >= 88
    assert _LOOKUP_JPEG_QUALITY >= 88
    src = inspect.getsource(_savefig_lookup_png)
    assert "LOOKUP_JPEG_QUALITY" in src
    assert "subsampling" in src
    assert "0" in src


def test_album_resize_uses_lanczos():
    from bot_servers import WayneTelegramBot

    cell = inspect.getsource(WayneTelegramBot._prepare_album_cell)
    photo = inspect.getsource(WayneTelegramBot._prepare_lookup_album_photo)
    assert "LANCZOS" in cell
    assert "LANCZOS" in photo
    assert "BILINEAR" not in cell
    assert "BILINEAR" not in photo


def test_decision_card_render_memo(tmp_path):
    from wayne_navigator import (
        NavigatorEngine,
        clear_lookup_render_cache,
        render_decision_card_png,
    )

    clear_lookup_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    assert isinstance(card, dict) and not card.get("error")
    a = str(tmp_path / "a.jpg")
    b = str(tmp_path / "b.jpg")
    p1 = render_decision_card_png(card, a)
    assert p1 and os.path.isfile(p1) and os.path.getsize(p1) > 80000
    t0 = time.perf_counter()
    p2 = render_decision_card_png(card, b)
    elapsed = time.perf_counter() - t0
    assert p2 and os.path.isfile(p2)
    assert elapsed < 0.15, elapsed


def test_glance_render_memo(tmp_path):
    from chip_tape import build_tape
    from wayne_navigator import (
        NavigatorEngine,
        clear_lookup_render_cache,
        render_first_glance_png,
    )

    clear_lookup_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
    tape = build_tape(db, "2330", merge_live=False) or {}
    a = str(tmp_path / "g1.jpg")
    b = str(tmp_path / "g2.jpg")
    p1 = render_first_glance_png("2330", card, tape, a, db, ohlc=ohlc)
    assert p1 and os.path.isfile(p1)
    t0 = time.perf_counter()
    p2 = render_first_glance_png("2330", card, tape, b, db, ohlc=ohlc)
    assert p2 and os.path.isfile(p2)
    assert time.perf_counter() - t0 < 0.15


def test_lookup_renders_use_independent_agg_figures():
    """介紹／高低卡用獨立 Agg Figure，才可真並行；不准再 @_mpl_serial 串起來。"""
    import wayne_navigator as wn

    card_src = inspect.getsource(wn.render_decision_card_png)
    glance_src = inspect.getsource(wn.render_first_glance_png)
    assert "_new_lookup_figure" in card_src
    assert "_new_lookup_figure" in glance_src
    assert "_close_lookup_figure" in card_src
    assert "_close_lookup_figure" in glance_src
    # 函式本體開頭不准再掛序列鎖（memo 先查、Agg 可並行）
    assert not card_src.strip().startswith("@_mpl_serial")
    assert not glance_src.strip().startswith("@_mpl_serial")
    helper = inspect.getsource(wn._new_lookup_figure)
    assert "FigureCanvasAgg" in helper
    assert "Figure(" in helper


def test_lookup_pair_parallel_not_slower_than_serial(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from chip_tape import build_tape
    from wayne_navigator import (
        NavigatorEngine,
        clear_lookup_render_cache,
        render_decision_card_png,
        render_first_glance_png,
    )

    clear_lookup_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
    tape = build_tape(db, "2330", merge_live=False) or {}

    clear_lookup_render_cache()
    t0 = time.perf_counter()
    render_first_glance_png("2330", card, tape, str(tmp_path / "sg.jpg"), db, ohlc=ohlc)
    render_decision_card_png(card, str(tmp_path / "sc.jpg"))
    serial = time.perf_counter() - t0

    clear_lookup_render_cache()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(2) as ex:
        a = ex.submit(
            render_first_glance_png,
            "2330",
            card,
            tape,
            str(tmp_path / "pg.jpg"),
            db,
            ohlc,
        )
        b = ex.submit(render_decision_card_png, card, str(tmp_path / "pc.jpg"))
        g, c = a.result(), b.result()
    parallel = time.perf_counter() - t0
    assert g and c and os.path.isfile(g) and os.path.isfile(c)
    assert os.path.getsize(g) > 80000 and os.path.getsize(c) > 80000
    # 允許誤差；真並行應不大於序列（GIL／字寬鎖下仍應 ≤ serial*1.15）
    assert parallel <= serial * 1.15 + 0.05, (serial, parallel)


def test_lookup_memo_survives_scratch_delete(tmp_path):
    """memo 存穩定副本；scratch 刪了暖路徑仍命中。"""
    from chip_tape import build_tape
    from wayne_navigator import (
        NavigatorEngine,
        clear_lookup_render_cache,
        render_decision_card_png,
        render_first_glance_png,
    )

    clear_lookup_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
    tape = build_tape(db, "2330", merge_live=False) or {}
    scratch_g = str(tmp_path / "scratch_g.jpg")
    scratch_c = str(tmp_path / "scratch_c.jpg")
    assert render_first_glance_png("2330", card, tape, scratch_g, db, ohlc=ohlc)
    assert render_decision_card_png(card, scratch_c)
    os.remove(scratch_g)
    os.remove(scratch_c)
    t0 = time.perf_counter()
    g2 = render_first_glance_png("2330", card, tape, str(tmp_path / "g2.jpg"), db, ohlc=ohlc)
    c2 = render_decision_card_png(card, str(tmp_path / "c2.jpg"))
    elapsed = time.perf_counter() - t0
    assert g2 and c2 and os.path.isfile(g2) and os.path.isfile(c2)
    assert elapsed < 0.2, elapsed
