# -*- coding: utf-8 -*-
"""大量區改獨立 Agg Figure（不吃 pyplot 全域）；與介紹／高低卡同刻三線程不准搶 FreeType。"""
from __future__ import annotations

import inspect
import os
import time

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_volzone_paint_uses_independent_agg_figure():
    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "_new_lookup_figure" in src
    assert "_close_lookup_figure" in src
    assert "plt.figure" not in src
    assert "plt.subplots" not in src
    assert "plt.close" not in src


def test_volzone_agg_render_still_works(tmp_path):
    from vol_zone_chart import render_volume_zone_result
    from wayne_navigator import NavigatorEngine, clear_lookup_render_cache

    clear_lookup_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    assert isinstance(card, dict) and not card.get("error")
    out = str(tmp_path / "v.jpg")
    t0 = time.perf_counter()
    path, cap = render_volume_zone_result(
        "2330",
        card.get("name") or "台積電",
        db,
        out,
        card=card,
        with_nav_signals=True,
    )
    elapsed = time.perf_counter() - t0
    assert path and os.path.isfile(path) and os.path.getsize(path) > 20000
    assert cap
    assert elapsed < 8.0, f"大量區 Agg 冷渲過慢 {elapsed:.2f}s"
