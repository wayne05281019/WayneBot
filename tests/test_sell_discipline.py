# -*- coding: utf-8 -*-
"""作者如何賣：最高價 vs 最高溫。只測紀律標，不當買訊。"""
from __future__ import annotations

from sell_discipline import classify_how_to_sell, sell_note_lines


def test_lianyi_desync_hi_price_not_hi_temp():
    """聯一光 9/4 型：最高價但非最高溫 → 直接減碼。"""
    hl = ["No"] * 8 + ["20高"]
    temp = ["升溫"] * 8 + ["降溫"]
    flags = classify_how_to_sell(hl, temp)
    assert flags["sell_action"] == "直接減碼"
    assert flags["hi_price"] is True
    assert flags["hi_temp"] is False
    assert "不同步" in flags["sell_why"]
    lines = sell_note_lines(flags)
    assert lines and lines[0].startswith("直接減碼")
    assert "買訊" in lines[0]


def test_wanhai_desync_after_sync():
    """萬海 8/24 同步、8/25 最高價＋降溫 → 直接減碼。"""
    hl = ["No"] * 6 + ["20高", "20高"]
    temp = ["升溫"] * 6 + ["最高溫", "降溫"]
    flags = classify_how_to_sell(hl, temp)
    assert flags["sell_action"] == "直接減碼"
    assert flags["hi_price"] is True
    assert flags["hi_temp"] is False


def test_sync_then_leave_is_prepare():
    """先前同步再脫離 → 準備減碼。"""
    hl = ["No"] * 5 + ["20高", "No"]
    temp = ["升溫"] * 5 + ["最高溫", "降溫"]
    flags = classify_how_to_sell(hl, temp)
    assert flags["sell_action"] == "準備減碼"
    assert "同步再脫離" in flags["sell_why"]
    assert flags["hi_price"] is False


def test_desync_then_leave_is_cut():
    """不同步再脫離 → 直接減碼。"""
    hl = ["No"] * 5 + ["20高", "No"]
    temp = ["升溫"] * 5 + ["降溫", "降溫"]
    flags = classify_how_to_sell(hl, temp)
    assert flags["sell_action"] == "直接減碼"
    assert "不同步再脫離" in flags["sell_why"]


def test_sync_today_has_no_sell_tag():
    hl = ["20高"]
    temp = ["最高溫"]
    flags = classify_how_to_sell(hl, temp)
    assert flags["sell_action"] == ""
    assert flags["sell_sync"] is True
    assert sell_note_lines(flags) == []


def test_never_high_is_silent():
    hl = ["20低", "10低", "No"]
    temp = ["最低溫", "升溫", "降溫"]
    flags = classify_how_to_sell(hl, temp)
    assert flags["sell_action"] == ""
    assert sell_note_lines(flags) == []


def test_leave_older_than_linger_clears():
    hl = ["20高"] + ["No"] * 5
    temp = ["最高溫"] + ["降溫"] * 5
    flags = classify_how_to_sell(hl, temp, linger=3)
    assert flags["sell_action"] == ""
