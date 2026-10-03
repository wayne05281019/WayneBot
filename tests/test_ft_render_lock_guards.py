# -*- coding: utf-8 -*-
"""FreeType／Agg 出圖鎖閘：低級互踩不准再溜回 main。

不需 production_db，進 smoke-no-db。對齊 #491：存檔必進 mpl_render；
勝率整頁冷路徑不准 ThreadPool 重疊 paint。
"""
from __future__ import annotations

import inspect
import threading

import pytest


def test_savefig_lookup_png_holds_mpl_render():
    from wayne_navigator import _MPL_RENDER_LOCK, _savefig_lookup_png

    src = inspect.getsource(_savefig_lookup_png)
    assert "with mpl_render()" in src
    assert "fig.savefig" in src
    assert type(_MPL_RENDER_LOCK).__name__ == "RLock"


def test_winrate_page_pairs_paint_not_threaded():
    """#489 曾讓壓區∥高低卡執行緒重疊搶 FreeType；冷路徑必須串行 paint。"""
    from winrate_buypoint import render_page_pairs, warm_winrate_cards

    page_src = inspect.getsource(render_page_pairs)
    assert "ThreadPoolExecutor" not in page_src
    assert "card_pool" not in page_src
    assert "render_volume_zone_result" in page_src
    assert "render_decision_card_png" in page_src
    # 預熱卡資料仍可平行（只算卡、不存檔）
    warm_src = inspect.getsource(warm_winrate_cards)
    assert "ThreadPoolExecutor" in warm_src
    assert "render_decision_card_png" not in warm_src
    assert "savefig" not in warm_src


def test_volzone_and_lookup_cards_share_ft_gate():
    from vol_zone_chart import render_volume_zone_result
    from wayne_navigator import render_decision_card_png, render_first_glance_png

    vz = inspect.getsource(render_volume_zone_result)
    assert "with mpl_render()" in vz
    assert vz.find("prepare_volume_zone") < vz.find("with mpl_render()")

    card = inspect.getsource(render_decision_card_png)
    glance = inspect.getsource(render_first_glance_png)
    assert "_savefig_lookup_png" in card
    assert "_savefig_lookup_png" in glance


def test_mpl_render_is_reentrant():
    """chips／導航外層已鎖時，_savefig 再進不准死鎖。"""
    from wayne_navigator import mpl_render

    with mpl_render():
        with mpl_render():
            assert True
