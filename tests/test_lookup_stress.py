# -*- coding: utf-8 -*-
"""查股編碼壓力：多檔同時產決策卡／三張圖，偉權＋哥哥路徑不互搶。"""
from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from config import get_db_path
from wayne_navigator import NavigatorEngine, render_stock_pack

pytestmark = pytest.mark.production_db

# 近日已對檔以外：龍頭／熱門／中等／冷門
TIER_CODES = ("3037", "2303", "5471", "3115")


def test_four_tier_cards_parallel_under_deadline():
    eng = NavigatorEngine(get_db_path())

    def one(sid: str):
        t0 = time.perf_counter()
        card = eng.get_decision_card(sid, merge_live=False)
        return sid, card, time.perf_counter() - t0

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
    print(f"four_tier_cards_parallel wall={wall:.3f}s")
    # 向量化前單檔約 0.3s、四檔串行 >1s；並行牆鐘應明顯低於 4s
    assert wall < 4.0, f"四檔決策卡並行太慢 {wall:.2f}s"


def test_four_tier_png_packs_parallel():
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
    for sid, pack, dt in rows:
        assert not pack.get("error"), f"{sid} {pack.get('error')}"
        for key in ("glance", "chart"):
            path = pack.get(key) or ""
            assert path and os.path.isfile(path) and os.path.getsize(path) > 2000, f"{sid} {key}"
        cards = pack.get("cards") or []
        assert cards and os.path.isfile(cards[0]) and os.path.getsize(cards[0]) > 2000, sid
        print(f"pack {sid} {dt:.3f}s")
    print(f"four_tier_png_packs_parallel wall={wall:.3f}s")
    assert wall < 45.0, f"四檔三張圖並行太慢 {wall:.2f}s"
