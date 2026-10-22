# -*- coding: utf-8 -*-
"""出圖加速低風險：字型預熱／memo 先查再 paint／大盤附圖進度／ensure TTL。"""
from __future__ import annotations

import inspect
import os
import time

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_prewarm_card_fonts_warms_common_sizes():
    from wayne_navigator import prewarm_card_fonts

    src = inspect.getsource(prewarm_card_fonts)
    assert "_fp(sz" in src or "_fp(sz," in src
    assert "bold" in src
    # 可重複呼叫；第二次應直接 return
    prewarm_card_fonts()
    prewarm_card_fonts()


def test_try_decision_card_memo_hits_without_paint(tmp_path):
    from wayne_navigator import (
        NavigatorEngine,
        clear_lookup_render_cache,
        render_decision_card_png,
        try_decision_card_memo,
    )

    clear_lookup_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    assert isinstance(card, dict) and not card.get("error")
    a = str(tmp_path / "a.jpg")
    assert render_decision_card_png(card, a)
    b = str(tmp_path / "b.jpg")
    t0 = time.perf_counter()
    hit = try_decision_card_memo(card, b)
    elapsed = time.perf_counter() - t0
    assert hit and os.path.isfile(hit)
    assert elapsed < 0.15, elapsed


def test_try_glance_memo_hits_without_paint(tmp_path):
    from chip_tape import build_tape
    from wayne_navigator import (
        NavigatorEngine,
        clear_lookup_render_cache,
        render_first_glance_png,
        try_glance_memo,
    )

    clear_lookup_render_cache()
    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2330", lookback=20, merge_live=False)
    ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
    tape = build_tape(db, "2330", merge_live=False) or {}
    a = str(tmp_path / "g1.jpg")
    assert render_first_glance_png("2330", card, tape, a, db, ohlc=ohlc)
    b = str(tmp_path / "g2.jpg")
    t0 = time.perf_counter()
    hit = try_glance_memo("2330", card, tape, b, db)
    assert hit and os.path.isfile(hit)
    assert time.perf_counter() - t0 < 0.35


def test_lookup_card_glance_try_memo_before_paint_queue():
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "try_decision_card_memo" in src
    assert "try_glance_memo" in src
    assert "try_lookup_vol_memo" in src
    # memo 命中路徑要在 submit_mpl_paint 之前（暖路徑不佔佇列）
    card_warm = src.find("try_decision_card_memo")
    card_paint = src.find("render_decision_card_png(card, card_path_f)")
    assert 0 < card_warm < card_paint


def test_market_session_cards_keep_progress_bubble():
    from bot_servers import WayneTelegramBot

    page = inspect.getsource(WayneTelegramBot._send_market_page)
    sess = inspect.getsource(WayneTelegramBot._send_market_session_cards)
    assert "wait_h=wait_h" in page
    assert "美股・台指・恐懼貪婪" in page
    assert "美股走勢圖" in sess
    # 附圖段：先 session_cards（帶 wait_h）再 _end_wait，不准文字一出就消泡泡
    anchor = page.find("美股・台指・恐懼貪婪")
    assert anchor > 0
    assert page.find("_send_market_session_cards", anchor) < page.find(
        "await _end_wait()", anchor
    )


def test_ensure_vol_ttl_at_least_five_minutes():
    import vol_zone_chart as vz

    assert float(vz._ENSURE_VOL_TTL_SEC) >= 300.0
    src = inspect.getsource(vz.ensure_official_volume_window)
    # 缺月 force_refetch 用 IN 一批查，不准逐日 SELECT
    assert "IN (" in src or "IN(" in src


def test_schedule_fuse_absorb_still_staggered():
    """16:30 融合 vs 盤後彙整已錯開；不准為加速把 absorb 拉回 16:30。"""
    import biaoke_absorb as ba
    import main as main_mod

    absorb_src = inspect.getsource(ba)
    assert "17:40" in absorb_src
    assert "16:30" in absorb_src  # 註解避撞
    slots = inspect.getsource(main_mod.start_daily_scheduler)
    assert '(16, 30, "fuse")' in slots
    assert '(6, 30, "morning")' in slots  # 06:30 必寄不動
