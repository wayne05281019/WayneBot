# -*- coding: utf-8 -*-
"""FreeType／Agg 出圖鎖閘：低級互踩不准再溜回 main。

不需 production_db，進 smoke-no-db。對齊 #491／#492／全面出圖：
量字與存檔必進同一把 mpl_render；不准再分 _FT_LOCK。
真正 savefig 走單一 paint worker；壓撐三張不准三線並行 wait_for。
勝率／壓撐名單外層不准整頁 submit（會獨占 worker 堵住查股）。
勝率冷路徑不准 ThreadPool 重疊 paint。
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


def test_single_mpl_paint_worker():
    """全進程只准一條 paint worker，雙人／多鈕同時按也不准並行踩 FreeType。"""
    import wayne_navigator as wn

    assert hasattr(wn, "submit_mpl_paint")
    assert hasattr(wn, "run_mpl_paint")
    assert wn._MPL_PAINT_EXECUTOR._max_workers == 1


def test_run_mpl_paint_nested_no_deadlock():
    """勝率／壓撐名單在 worker 內再跑 run_mpl_paint 不准卡死。"""
    from wayne_navigator import run_mpl_paint

    def inner():
        return 7

    def outer():
        return run_mpl_paint(inner) + 1

    assert run_mpl_paint(outer) == 8


def test_winrate_page_pairs_paint_not_threaded():
    """#489 曾讓壓區∥高低卡執行緒重疊搶 FreeType；冷路徑必須串行 paint。"""
    from winrate_buypoint import render_page_pairs, warm_winrate_cards

    page_src = inspect.getsource(render_page_pairs)
    assert "ThreadPoolExecutor" not in page_src
    assert "card_pool" not in page_src
    assert "run_mpl_paint" in page_src
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
    assert "glance_item = await glance_task" in src
    assert "submit_mpl_paint" in src
    # 舊寫法：gather(glance, card) 會讓後者排隊時間算進逾時
    assert "asyncio.gather(\n                _render_ready(\n                    \"glance\"" not in src
    assert src.find("glance_task = asyncio.create_task") < src.find(
        "card_item = await card_render_task"
    )


def test_pressure_trio_paints_serial_not_parallel_wait_for():
    """壓撐點股三張：不准 vz∥card∥chips create_task；要串行＋單一 paint worker。"""
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_pressure_stock_trio)
    assert "submit_mpl_paint" in src
    assert "create_task(asyncio.to_thread(_vz))" not in src
    assert "create_task(asyncio.to_thread(_card_png))" not in src
    assert "create_task(asyncio.to_thread(_chips))" not in src
    # 逾時不准比查股短到把等鎖誤判成失敗
    assert "timeout=40.0" not in src
    assert "timeout=25.0" not in src
    assert "_LOOKUP_PNG_TIMEOUT" in src


def test_bot_chart_entries_use_submit_mpl_paint():
    """真正 savefig 必走 submit／run_mpl_paint；多檔必須逐檔送。

    壓撐名單：逐檔 submit_mpl_paint(render_volume_zone_result)。
    勝率買點：逐檔 to_thread(render_stock_pair)，內層 run_mpl_paint。
    查股／三張／大盤／飆大／籌碼：外層 submit_mpl_paint。
    """
    from bot_servers import WayneTelegramBot

    # 外層必進 paint worker（單張／少數圖）
    direct = {
        "_send_pressure_stock_trio": "壓撐三張",
        "_send_card_to_locked": "查股",
        "_send_decision_card_quick": "決策卡",
        "_send_navigation_chart": "導航圖",
        "_send_market_kline": "大盤日K",
        "_send_biaoke_structure_chart": "飆大結構",
        "_send_biaoke_twii_degree_chart": "飆大加權",
        "_render_biaoke_advice_chart": "飆大建議圖按檔渲",
        "_send_chips_to": "籌碼",
    }
    for meth, label in direct.items():
        assert hasattr(WayneTelegramBot, meth), label
        src = inspect.getsource(getattr(WayneTelegramBot, meth))
        assert "submit_mpl_paint" in src, f"{label} ({meth}) 未走 submit_mpl_paint"

    # 壓撐名單／勝率：逐檔送；不准整頁 two_phase／render_page_pairs
    pressure = inspect.getsource(WayneTelegramBot._run_pressure_support)
    assert "submit_mpl_paint(" in pressure
    assert "render_volume_zones_two_phase" not in pressure
    assert "asyncio.to_thread" in pressure or "wrap_future" in pressure

    wr = inspect.getsource(WayneTelegramBot._run_winrate_buypoint)
    assert "asyncio.to_thread" in wr
    assert "submit_mpl_paint(" not in wr
    assert "render_stock_pair" in wr
    assert "render_page_pairs(" not in wr


def test_page_prep_outside_worker_does_not_block_lookup_paint():
    """勝率／壓撐整頁若外層 submit，查股 paint 會卡在算卡後面；算卡必須在 worker 外。"""
    import threading
    import time

    from wayne_navigator import run_mpl_paint, submit_mpl_paint

    events: list[tuple[float, str]] = []
    lock = threading.Lock()

    def log(msg: str) -> None:
        with lock:
            events.append((time.perf_counter(), msg))

    def page_scoped() -> None:
        log("prep")
        time.sleep(0.4)
        run_mpl_paint(lambda: (log("wr_paint"), None))

    def lookup() -> None:
        def _p():
            log("lk_paint")
            return "ok"

        submit_mpl_paint(_p).result()

    t0 = time.perf_counter()
    th = threading.Thread(target=page_scoped)
    th.start()
    time.sleep(0.05)
    lookup()
    th.join()
    named = {m: t - t0 for t, m in events}
    assert "lk_paint" in named and "wr_paint" in named
    # 查股 paint 必須在長 prep 結束前就能進 worker
    assert named["lk_paint"] < 0.35, named


def test_chart_batch_paint_uses_single_worker():
    from chart_batch import paint_nav_charts_serial, paint_volume_zones_serial

    src = inspect.getsource(paint_volume_zones_serial)
    assert "run_mpl_paint" in src
    assert "ThreadPoolExecutor" not in src
    nav = inspect.getsource(paint_nav_charts_serial)
    assert "run_mpl_paint" in nav
    assert "ThreadPoolExecutor" not in nav


def test_mpl_render_is_reentrant():
    """chips／導航外層已鎖時，_savefig／量字再進不准死鎖。"""
    from wayne_navigator import mpl_render, _glyph_w_pt

    with mpl_render():
        with mpl_render():
            assert _glyph_w_pt("測試", 12.0, 700) >= 0
