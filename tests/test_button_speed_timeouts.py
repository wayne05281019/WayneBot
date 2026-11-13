# -*- coding: utf-8 -*-
"""全系統按鍵速度：逾時／快取／剛脫離零不准對全市場打 MIS。"""
from __future__ import annotations

import inspect
import time
from unittest.mock import patch

import pytest

from bot_servers import (
    WayneTelegramBot,
    _DONGZHU_TIMEOUT,
    _FLOW_HTML_TIMEOUT,
    _LEAVE_ZERO_TIMEOUT,
    _MARKET_ANALYZE_TIMEOUT,
    _MARKET_CNN_TIMEOUT,
    _MARKET_MIS_TIMEOUT,
    _MARKET_PAGE_TIMEOUT,
    _MARKET_US_REFRESH_TIMEOUT,
    _TRADE_BUCKET_TIMEOUT,
    _WINRATE_RESOLVE_TIMEOUT,
    _WINRATE_WAIT_MAX_S,
)


def test_button_timeouts_are_not_too_tight():
    assert _FLOW_HTML_TIMEOUT >= 25.0
    assert _MARKET_PAGE_TIMEOUT >= 60.0
    assert _MARKET_US_REFRESH_TIMEOUT <= 20.0
    assert _MARKET_CNN_TIMEOUT <= 12.0
    assert _MARKET_ANALYZE_TIMEOUT <= 40.0
    assert _MARKET_MIS_TIMEOUT <= 10.0
    assert _DONGZHU_TIMEOUT >= 40.0
    assert _TRADE_BUCKET_TIMEOUT >= 60.0
    assert _LEAVE_ZERO_TIMEOUT >= 90.0
    # 勝率按鈕當場重掃藍▲：不准 120s 假逾時（話筒 1:59 警告）
    assert _WINRATE_RESOLVE_TIMEOUT >= 240.0
    assert _WINRATE_WAIT_MAX_S >= _WINRATE_RESOLVE_TIMEOUT
    wr = inspect.getsource(WayneTelegramBot._run_winrate_buypoint)
    assert "_WINRATE_RESOLVE_TIMEOUT" in wr
    assert "overtime_keep=True" in wr
    assert "名單重建逾時" in wr
    src = inspect.getsource(WayneTelegramBot.run_polling)
    assert ".read_timeout(60.0)" in src or ".read_timeout(60)" in src
    page = inspect.getsource(WayneTelegramBot._send_market_page)
    # 美股／CNN 必須有子逾時，不准拖死整頁；教具改走波浪位階（v34）
    assert "_MARKET_US_REFRESH_TIMEOUT" in page
    assert "_MARKET_CNN_TIMEOUT" in page
    assert "_send_market_wave_charts" not in page
    assert "波浪位階" in page
    wave = inspect.getsource(WayneTelegramBot.wave_status_cmd)
    assert "_send_market_wave_charts" in wave
    assert "_wave_locks" in wave
    assert "上一組波浪位階還在出圖" in wave


def test_leave_zero_pick_defers_mis_to_candidates_only():
    from screening_engine import ScreeningEngine

    src = inspect.getsource(ScreeningEngine._screen_leave_zero_from_profit)
    assert "官方柱已過剛離零閘" in src
    head, _sep, _tail = src.partition("for sid in codes:")
    assert "fetch_mis_batch" not in head
    assert "fetch_mis_batch" in src


def test_leave_zero_pick_cache_and_flow_dongzhu_helpers():
    from biaoke_field_scan import clear_dongzhu_picks_cache
    from money_flow import clear_flow_html_cache
    from screening_engine import clear_leave_zero_pick_cache

    clear_leave_zero_pick_cache()
    clear_flow_html_cache()
    clear_dongzhu_picks_cache()


@pytest.mark.production_db
def test_leave_zero_pick_warm_cache_and_no_full_market_mis():
    from config import get_db_path
    from screening_engine import ScreeningEngine, clear_leave_zero_pick_cache

    clear_leave_zero_pick_cache()
    eng = ScreeningEngine(get_db_path())
    mis_calls: list = []

    def _fake_mis(codes, db_path, timeout=12.0):
        mis_calls.append(list(codes))
        return {}

    with patch("midday_review.fetch_mis_batch", side_effect=_fake_mis):
        with patch("live_quote.is_live_merge_window", return_value=True):
            t0 = time.perf_counter()
            rows = eng.screen_leave_zero_pick(pick="0")
            cold = time.perf_counter() - t0
            assert isinstance(rows, list)
            for pack in mis_calls:
                assert len(pack) <= 64, f"MIS 打太多檔：{len(pack)}"
            assert cold < 90.0, f"剛脫離零冷掃描過慢 {cold:.1f}s"

    clear_leave_zero_pick_cache()
    with patch("live_quote.is_live_merge_window", return_value=False):
        t0 = time.perf_counter()
        rows = eng.screen_leave_zero_pick(pick="0")
        cold = time.perf_counter() - t0
        t0 = time.perf_counter()
        rows2 = eng.screen_leave_zero_pick(pick="0")
        warm = time.perf_counter() - t0
    assert isinstance(rows, list)
    assert [r.get("code") for r in rows2] == [r.get("code") for r in rows]
    assert cold < 90.0, f"剛脫離零非盤中冷掃描過慢 {cold:.1f}s"
    assert warm < 0.05, f"剛脫離零 memo 應 <50ms，實際 {warm:.3f}s（cold {cold:.3f}s）"


@pytest.mark.production_db
def test_flow_html_memo_hit():
    from config import get_db_path
    from money_flow import clear_flow_html_cache, format_flow_html

    clear_flow_html_cache()
    db = get_db_path()
    t0 = time.perf_counter()
    html = format_flow_html(db, user_id="bench")
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    html2 = format_flow_html(db, user_id="bench")
    warm = time.perf_counter() - t0
    assert html and html2 == html
    assert cold < 8.0, f"資金頁冷 {cold:.2f}s"
    assert warm < 0.05, f"資金頁 memo {warm:.3f}s"
