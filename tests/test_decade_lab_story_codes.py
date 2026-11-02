# -*- coding: utf-8 -*-
"""序D 故事碼純函式。"""
from __future__ import annotations

from decade_lab_story_codes import classify_barek_stories


def _b(date, o, h, l, c, v):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_dry_continue_down_hits():
    # 前段放量，末日無量下跌
    bars = [_b(f"2026010{i}", 100, 101, 99, 100, 1000) for i in range(1, 6)]
    bars.append(_b("20260106", 100, 100, 95, 96, 200))  # 量遠低於中位
    r = classify_barek_stories(bars)
    assert r["ok"] is True
    assert r["codes"]["dry_continue_down"]["hit"] is True


def test_break_low_no_climax():
    bars = [_b(f"2026010{i}", 100, 102, 98, 100, 500) for i in range(1, 6)]
    bars.append(_b("20260106", 99, 99, 90, 91, 400))  # 破低但非爆量
    r = classify_barek_stories(bars)
    assert r["codes"]["break_low_no_climax"]["hit"] is True


def test_gap_and_two_bar_confirm_down():
    base = [_b(f"2026010{i}", 100, 105, 100, 103, 800) for i in range(1, 5)]
    # 兩根收破 base 低 100
    base.append(_b("20260105", 99, 99, 95, 96, 700))
    base.append(_b("20260106", 96, 96, 94, 94, 700))
    r = classify_barek_stories(base)
    assert r["codes"]["two_bar_confirm"]["hit"] is True
    assert r["codes"]["two_bar_confirm"]["side"] == "down"


def test_insufficient_bars():
    r = classify_barek_stories([_b("20260101", 1, 1, 1, 1, 1)])
    assert r["ok"] is False
