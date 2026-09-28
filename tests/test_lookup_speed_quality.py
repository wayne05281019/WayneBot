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
