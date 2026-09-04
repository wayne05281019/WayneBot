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
    assert full == "直接減碼（最高價但非最高溫；作者如何賣，不是買訊）"
    assert "不同步（" not in full


def test_html_and_glance_wire_sell_notes():
    import inspect

    from wayne_navigator import (
        generate_decision_card,
        render_decision_card_png,
        render_first_glance_png,
    )

    html_src = inspect.getsource(generate_decision_card)
    assert "sell_note_lines" in html_src
    assert "協助判斷" in html_src
    png_src = inspect.getsource(render_first_glance_png)
    assert "sell_note_short" in png_src
    card_src = inspect.getsource(render_decision_card_png)
    assert "sell_note_short" in card_src
    assert "紀律" in card_src


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
    assert "不同步（" not in line
    assert sell_note_short(again) == "直接減碼（最高價但非最高溫）"


def _mini_card_for_png(**extra):
    table = pd.DataFrame(
        [
            {
                "date": "20260904",
                "close": 143.0,
                "獲利": "124.5%",
                "高低": "20高",
                "預警": "K20高",
                "溫度計": "81.1 °C",
                "升降": "升溫",
                "升降註": "",
                "月乖離": "+31.1%",
                "120日量": "第 8 名",
                "profit_pct": 124.5,
                "bias_monthly": 31.1,
                "vol_rank_120": 8,
                "temp_num": 81.1,
            }
        ]
    )
    card = {
        "stock_id": "3441",
        "stock_name": "聯一光",
        "latest_date": "20260904",
        "query_date": "2026/09/04",
        "query_clock": "",
        "close": 143.0,
        "change_pct": 10.0,
        "h10": 143.0,
        "dist_h10": 0.0,
        "h20": 143.0,
        "dist_h20": 0.0,
        "h60": 143.0,
        "dist_h60": 0.0,
        "l10": 90.0,
        "dist_l10": 58.9,
        "l20": 80.0,
        "dist_l20": 78.8,
        "l60": 63.7,
        "dist_l60": 124.5,
        "space_20": 79,
        "space_60": 124,
        "ma60s": 1.2,
        "qty60": 1000,
        "badges": ["多頭排列"],
        "stance": "今天不要追",
        "stance_kind": "avoid",
        "table": table,
    }
    card.update(extra)
    return card


def test_decision_card_png_draws_how_to_sell(tmp_path, monkeypatch):
    """決策卡第二行要畫如何賣，不能只出現在介紹圖。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from wayne_navigator import render_decision_card_png

    seen = []
    orig = matplotlib.axes.Axes.text

    def wrap(self, *args, **kwargs):
        if len(args) >= 3:
            seen.append(str(args[2]))
        if "s" in kwargs:
            seen.append(str(kwargs["s"]))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    card = _mini_card_for_png(
        sell_action="直接減碼",
        sell_why="不同步（最高價但非最高溫）",
    )
    out = tmp_path / "3441_sell.png"
    path = render_decision_card_png(card, str(out))
    assert path and out.is_file()
    joined = "\n".join(seen)
    assert "紀律　直接減碼（最高價但非最高溫）　不是買訊" in joined
    assert "紅箭頭只是觀察" not in joined


def test_decision_card_png_keeps_red_arrow_disclaimer_when_no_sell(tmp_path, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from wayne_navigator import render_decision_card_png

    seen = []
    orig = matplotlib.axes.Axes.text

    def wrap(self, *args, **kwargs):
        if len(args) >= 3:
            seen.append(str(args[2]))
        if "s" in kwargs:
            seen.append(str(kwargs["s"]))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    out = tmp_path / "no_sell.png"
    path = render_decision_card_png(_mini_card_for_png(), str(out))
    assert path and out.is_file()
    joined = "\n".join(seen)
    assert "紅箭頭只是觀察" in joined
    assert "紀律　" not in joined


@pytest.mark.production_db
def test_cary_2383_2408_3008_20260904_rows():
    """Cary 對卡殘差：台光電獲利不歸零、南亞科 9/3 最低溫、大立光 9/4 如何賣脫離。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    eng = NavigatorEngine(get_db_path())

    c2383 = eng.get_decision_card("2383", merge_live=False)
    assert str(c2383.get("latest_date")) == "20260904"
    assert float(c2383["cal60_low"]) == 4100.0
    assert abs(float(c2383["gain_pct"]) - 32.1) < 0.2
    t2383 = c2383["table"]
    r04 = t2383[t2383["date"].astype(str) == "20260904"].iloc[0]
    assert r04["獲利"] == "32.1%"
    r03 = t2383[t2383["date"].astype(str) == "20260903"].iloc[0]
    assert str(r03["升降"]) == "最低溫"

    c2408 = eng.get_decision_card("2408", merge_live=False)
    t2408 = c2408["table"]
    n03 = t2408[t2408["date"].astype(str) == "20260903"].iloc[0]
    assert str(n03["升降"]) == "最低溫"
    assert "價未新低" in str(n03.get("升降註") or "")
    assert float(c2408["gain_pct"]) > 40.0

    c3008 = eng.get_decision_card("3008", merge_live=False)
    assert str(c3008.get("latest_date")) == "20260904"
    assert c3008.get("sell_action") == "直接減碼"
    assert "不同步再脫離" in str(c3008.get("sell_why") or "")
    assert sell_note_short(c3008) == "直接減碼（不同步再脫離）"
