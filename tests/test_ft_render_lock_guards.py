# -*- coding: utf-8 -*-
"""FreeType／Agg 出圖鎖閘：低級互踩不准再溜回 main。

不需 production_db，進 smoke-no-db。對齊 #491／後續：
量字與存檔必進同一把 mpl_render；不准再分 _FT_LOCK。
勝率整頁冷路徑不准 ThreadPool 重疊 paint。
"""
from __future__ import annotations

import inspect

import pytest


def test_savefig_lookup_png_holds_mpl_render():
    from wayne_navigator import _MPL_RENDER_LOCK, _savefig_lookup_png

    src = inspect.getsource(_savefig_lookup_png)
    assert "with mpl_render()" in src
    assert "fig.savefig" in src
    assert type(_MPL_RENDER_LOCK).__name__ == "RLock"


def test_glyph_width_shares_mpl_render_not_separate_ft_lock():
    """#491 只鎖 savefig 不夠：_glyph_w_pt 若另把 _FT_LOCK，與 draw 並行會 Abort。"""
    import wayne_navigator as wn

    assert not hasattr(wn, "_FT_LOCK")
    src = inspect.getsource(wn._glyph_w_pt)
    assert "with mpl_render()" in src
    assert "_FT_LOCK" not in src
    warm = inspect.getsource(wn.prewarm_card_fonts)
    assert "with mpl_render()" in warm
    assert "_FT_LOCK" not in warm


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


def test_lookup_bot_awaits_card_before_glance():
    """查股介紹圖不准跟高低卡 gather 搶同一把鎖的 wait_for 時計。"""
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "card_item = await card_render_task" in src
    assert "glance_item = await _render_ready" in src
    # 舊寫法：gather(glance, card) 會讓後者排隊時間算進逾時
    assert "asyncio.gather(\n                _render_ready(\n                    \"glance\"" not in src


def test_mpl_render_is_reentrant():
    """chips／導航外層已鎖時，_savefig／量字再進不准死鎖。"""
    from wayne_navigator import mpl_render, _glyph_w_pt

    with mpl_render():
        with mpl_render():
            assert _glyph_w_pt("測試", 12.0, 700) >= 0
