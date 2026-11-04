# -*- coding: utf-8 -*-
"""查股編碼壓力：多檔同時產決策卡／介紹圖，偉權＋哥哥路徑不互搶。"""
from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from config import get_db_path
from wayne_navigator import NavigatorEngine, clear_lookup_render_cache, render_stock_pack

pytestmark = pytest.mark.production_db

# 近日已對檔以外：龍頭／熱門／中等／冷門
TIER_CODES = ("3037", "2303", "5471", "3115")


def test_four_tier_cards_parallel_under_deadline():
    """四檔決策卡並行：先暖一次消冷啟／SQLite 頁快取，再測並行牆鐘。

    根因（flaky）：冷啟並行時單檔可到 2s＋、四檔搶讀偶發 >4s；不是互搶死鎖。
    不變式：暖後並行牆鐘須明顯快過四檔串行合計（真並行），且每檔有真收。
    """
    eng = NavigatorEngine(get_db_path())
    # 暖：消第一次開庫／頁快取；不計入並行牆鐘
    for sid in TIER_CODES:
        warm = eng.get_decision_card(sid, merge_live=False)
        assert not warm.get("error"), f"{sid} {warm.get('error')}"
        assert float(warm.get("close") or 0) > 0

    def one(sid: str):
        t0 = time.perf_counter()
        card = eng.get_decision_card(sid, merge_live=False)
        return sid, card, time.perf_counter() - t0

    # 串行基準（同暖狀態）
    serial_sum = 0.0
    for sid in TIER_CODES:
        _sid, card, dt = one(sid)
        assert not card.get("error")
        serial_sum += dt

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(one, sid) for sid in TIER_CODES]
        rows = [f.result() for f in as_completed(futs)]
    wall = time.perf_counter() - t0
    assert len(rows) == 4
    for sid, card, dt in rows:
        assert not card.get("error"), f"{sid} {card.get('error')}"
        assert float(card.get("close") or 0) > 0
        print(f"card {sid} {dt:.3f}s close={card.get('close')} pct={card.get('gain_pct')}")
    print(f"four_tier_cards_parallel wall={wall:.3f}s serial_sum={serial_sum:.3f}s")
    # 暖後並行應快過串行合計；留 15% 公差給排程抖動。硬頂防死鎖／長卡。
    assert wall < serial_sum * 0.85 + 0.05, (wall, serial_sum)
    assert wall < 2.5, f"四檔決策卡並行太慢 {wall:.2f}s"


def test_four_tier_png_packs_parallel():
    """四檔介紹＋高低卡並行提交：單 paint worker 下牆鐘≈串行合計，不准死鎖／缺圖。

    根因（flaky）：舊預算 wall<45 假設真並行出圖；FreeType／Agg 已鎖成單一
    paint worker（#493／#491），四檔冷渲各自十數秒時合計必破 45。
    不變式：四檔都出真 JPEG；牆鐘 < 單檔冷渲上限×4＋CI 負載裕度。
    """
    clear_lookup_render_cache()
    tmp = tempfile.mkdtemp(prefix="wayne_stress_")

    def one(sid: str):
        charts = os.path.join(tmp, sid)
        os.makedirs(charts, exist_ok=True)
        t0 = time.perf_counter()
        pack = render_stock_pack(sid, get_db_path(), charts)
        return sid, pack, time.perf_counter() - t0

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [f.result() for f in as_completed([pool.submit(one, sid) for sid in TIER_CODES])]
    wall = time.perf_counter() - t0
    per = []
    for sid, pack, dt in rows:
        assert not pack.get("error"), f"{sid} {pack.get('error')}"
        for key in ("glance",):
            path = pack.get(key) or ""
            assert path and os.path.isfile(path) and os.path.getsize(path) > 2000, f"{sid} {key}"
        cards = pack.get("cards") or []
        assert cards and os.path.isfile(cards[0]) and os.path.getsize(cards[0]) > 2000, sid
        per.append(dt)
        print(f"pack {sid} {dt:.3f}s")
    print(f"four_tier_png_packs_parallel wall={wall:.3f}s per={per}")
    # 單 worker：牆鐘逼近最慢那檔的排隊總長；硬頂＝單檔 40s×4＋20s CI 裕度
    assert wall < 180.0, f"四檔出圖並行死鎖或過慢 {wall:.2f}s"
    assert max(per) < 120.0, f"單檔出圖過慢 {max(per):.2f}s"
