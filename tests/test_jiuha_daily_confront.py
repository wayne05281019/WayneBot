# -*- coding: utf-8 -*-
from __future__ import annotations

from jiuha_observe import Bar

from scripts.jiuha_daily_confront import (
    _is_complete_bar,
    confront_level,
    detect_conditions,
    extract_lots,
)


def test_incomplete_bar_rejected():
    assert not _is_complete_bar(Bar("20261120", 1, 1, 1, 1, 100))
    assert _is_complete_bar(Bar("20261119", 40145, 40315, 38259, 38426, 1e7))


def test_detect_conditions():
    assert "margin_speed" in detect_conditions("融資跌得不夠快，去槓桿失敗")
    assert "shrink_up" in detect_conditions("漲 1500 點卻是縮量反彈")
    assert "false_break" in detect_conditions("頸線假突破真獵殺")


def test_confront_level_hit_miss():
    twii = {
        "20261112": Bar("20261112", 44180, 44525, 42943, 43091, 1.3e7),
        "20261113": Bar("20261113", 43719, 44489, 43534, 43675, 1.2e7),
    }
    sessions = ["20261112", "20261113"]
    hit = confront_level(44332, "20261112", twii, sessions)
    assert hit["verdict"] == "hit"
    miss = confront_level(50000, "20261112", twii, sessions)
    assert miss["verdict"] == "miss"
    # 不完整柱 → 無法驗證（次日也無）
    twii2 = {"20261120": Bar("20261120", 1, 1, 1, 1, 100)}
    unv = confront_level(36000, "20261120", twii2, ["20261120"])
    assert unv["verdict"] == "unverifiable"


def test_extract_lots_basic():
    lots = extract_lots("外資空單剩 89379 口附近")
    assert 89379.0 in lots
