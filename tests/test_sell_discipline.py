# -*- coding: utf-8 -*-
"""作者如何賣：最高價 vs 最高溫。只測紀律標，不當買訊。"""
from __future__ import annotations

import pandas as pd
import pytest

from sell_discipline import (
    attach_sell,
    classify_how_to_sell,
    sell_note_lines,
    sell_note_short,
)


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


def test_attach_sell_reads_newest_first_table_as_chrono():
    """決策卡 table 是新→舊；不可把最舊列當成今天。"""
    tbl = pd.DataFrame(
        {
            "date": ["20260904", "20260903", "20260902"],
            "高低": ["20高", "No", "No"],
            "升降": ["升溫", "降溫", "降溫"],
        }
    )
    card = {"table": tbl}
    attach_sell(card)
    assert card["sell_action"] == "直接減碼"
    assert "最高價但非最高溫" in card["sell_why"]


def test_attach_sell_oldest_first_table_same_result():
    tbl = pd.DataFrame(
        {
            "date": ["20260902", "20260903", "20260904"],
            "高低": ["No", "No", "20高"],
            "升降": ["降溫", "降溫", "升溫"],
        }
    )
    card = {"table": tbl}
    attach_sell(card)
    assert card["sell_action"] == "直接減碼"


def test_sell_note_short_drops_disclaimer():
    flags = {
        "sell_action": "直接減碼",
        "sell_why": "不同步（最高價但非最高溫）",
    }
    assert sell_note_short(flags) == "直接減碼（最高價但非最高溫）"
    assert "買訊" not in sell_note_short(flags)
    assert "作者" not in sell_note_short(flags)
    full = sell_note_lines(flags)[0]
    assert "作者如何賣" in full
    assert "不是買訊" in full


def test_html_and_glance_wire_sell_notes():
    import inspect

    from wayne_navigator import generate_decision_card, render_first_glance_png

    html_src = inspect.getsource(generate_decision_card)
    assert "sell_note_lines" in html_src
    assert "協助判斷" in html_src
    png_src = inspect.getsource(render_first_glance_png)
    assert "sell_note_short" in png_src


@pytest.mark.production_db
def test_3441_20260904_how_to_sell_survives_table_reattach():
    """聯一光 9/4：作者公開最高價但非最高溫；查股 HTML 會再 attach 一次，不能被新→舊表洗掉。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(get_db_path()).get_decision_card("3441", merge_live=False)
    assert str(card.get("latest_date")) == "20260904"
    assert card.get("sell_action") == "直接減碼"
    again = {"table": card["table"]}
    attach_sell(again)
    assert again["sell_action"] == "直接減碼"
    line = sell_note_lines(again)[0]
    assert "直接減碼" in line
    assert "不是買訊" in line
    assert sell_note_short(again) == "直接減碼（最高價但非最高溫）"
