# -*- coding: utf-8 -*-
"""as_of／導航假柱地毯：不准未齊日／未收當官方基準。"""
from __future__ import annotations

import inspect


def test_nav_draw_skips_invent_and_load_caps_asof():
    from wayne_navigator import _load_ohlc, draw_from_ohlc

    src = inspect.getsource(draw_from_ohlc)
    assert "load_confirmed_absent_dates" in src
    assert "skip_invent_dates" in src
    load_src = inspect.getsource(_load_ohlc)
    assert "db_as_of_trading_date" in load_src


def test_resolve_screen_as_of_no_fuse_fallback_without_complete():
    from trading_calendar import resolve_screen_as_of

    src = inspect.getsource(resolve_screen_as_of)
    assert "return fuse_end_trading_date" not in src
    assert "return None" in src


def test_get_latest_trading_date_requires_sides_complete():
    from screening_engine import ScreeningEngine

    src = inspect.getsource(ScreeningEngine.get_latest_trading_date)
    assert "sides_complete" in src
    assert 'SELECT MAX(date)' not in src
    assert 'datetime.now().strftime("%Y%m%d")' not in src


def test_watch_as_of_complete_only():
    from wayne_db import resolve_watch_view_as_of, watchlist_join_pnl

    src = inspect.getsource(resolve_watch_view_as_of)
    assert "complete or want" not in src
    assert 'as_of = complete or ""' in src or "as_of = complete or ''" in src
    join = inspect.getsource(watchlist_join_pnl)
    assert "watch_display_cap(now)" not in join


def test_emerging_as_of_not_ahead_of_listed_incomplete():
    from wayne_navigator import NavigatorEngine

    src = inspect.getsource(NavigatorEngine.get_decision_card)
    assert "is_official_daily_bar" in src
    assert "listed_as_of" in src


def test_market_as_of_no_fuse_alone():
    from taiwan_market import resolve_market_as_of

    src = inspect.getsource(resolve_market_as_of)
    assert "fuse_end_trading_date" not in src
    assert "complete or cap" not in src
