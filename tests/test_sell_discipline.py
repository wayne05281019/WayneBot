# -*- coding: utf-8 -*-
"""作者如何賣：最高價 vs 最高溫。只測紀律標，不當買訊。"""
from __future__ import annotations

import pandas as pd
import pytest

from sell_discipline import (
    FACE_NOTES,
    NOTE_DESYNC_LEFT,
    NOTE_HI_PRICE,
    NOTE_HI_TEMP,
    NOTE_SYNC_LEFT,
    apply_face_stance,
    attach_sell,
    card_discipline_face,
    classify_how_to_sell,
    latest_table_row,
    sell_note_lines,
    sell_note_short,
    sell_notes_for_stocks,
    stance_title_from_face,
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
    assert lines and lines[0].startswith(NOTE_HI_PRICE)
    assert "不是叫你買" in lines[0]


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
    note = sell_note_short(flags)
    assert note == NOTE_SYNC_LEFT
    assert "先別追" in note
    assert "先出一點" in note
    assert "到過" not in note
    assert "都過了" not in note
    assert "可以先想" not in note


def test_all_sell_notes_say_what_to_do_now():
    cases = [
        ("準備減碼", "先前同步再脫離", NOTE_SYNC_LEFT, "都退了"),
        ("直接減碼", "不同步（最高價但非最高溫）", NOTE_HI_PRICE, "熱度沒跟上"),
        ("直接減碼", "不同步（最高溫但非最高價）", NOTE_HI_TEMP, "價沒過前高"),
        ("直接減碼", "不同步再脫離", NOTE_DESYNC_LEFT, "都沒了"),
    ]
    for act, why, expect, mark in cases:
        note = sell_note_short({"sell_action": act, "sell_why": why})
        assert note == expect, why
        assert "先出一點" in note or "先別追" in note
        assert mark in note
        assert note.startswith("現在")
        assert "可以先" not in note
        assert "到過" not in note
        assert "減碼" not in note


def test_discipline_bank_has_at_least_fifty_faces():
    assert len(FACE_NOTES) >= 50
    assert len(set(FACE_NOTES.values())) >= 50
    for note in FACE_NOTES.values():
        assert "減碼" not in note
        assert "買訊" not in note
        assert "先" in note or "少追" in note or "不要追" in note


def test_warming_near_high_does_not_say_heat_left():
    """2382 9/9 型：K20高、升溫、距20日高 −1.6%。不能寫熱度退了。"""
    card = {
        "sell_action": "準備減碼",
        "sell_why": "先前同步再脫離",
        "gain_pct": 22.6,
        "dist_h20": -1.6,
        "temp_c": "61.1 °C",
        "table": [
            {
                "date": "20260909",
                "高低": "No",
                "預警": "K20高",
                "升降": "升溫",
                "升降註": "",
                "溫度計": "61.1 °C",
                "profit_pct": 22.6,
            }
        ],
    }
    face = card_discipline_face(card)
    assert face["pos"] == "near_hi"
    assert face["heat"] == "up"
    note = sell_note_short(card)
    assert "退了" not in note
    assert "都沒了" not in note
    assert "升" in note
    assert "20日高" in note
    assert "別追" in note
    assert "先出一點" in note


def _etf_near_high_card(table, *, trend="升溫", **extra):
    card = {
        "sell_action": "準備減碼",
        "sell_why": "先前同步再脫離",
        "gain_pct": 29.7,
        "dist_h20": -2.8,
        "temp_c": "57.8 °C",
        "stance": "今天先看表，先等",
        "stance_kind": "wait",
        "table": table,
    }
    card.update(extra)
    return card


def test_flat_heat_near_high_does_not_say_gone():
    """升降＝No：熱度沒再走，不能寫都沒了／已降。"""
    card = _etf_near_high_card(
        [
            {
                "date": "20260910",
                "高低": "No",
                "預警": "K20高",
                "升降": "No",
                "profit_pct": 17.3,
            }
        ],
        gain_pct=17.3,
        sell_action="直接減碼",
        sell_why="不同步再脫離",
    )
    face = card_discipline_face(card)
    assert face["heat"] == "flat"
    note = sell_note_short(card)
    assert "沒再走" in note
    assert "都沒了" not in note
    assert "已降" not in note
    assert "退了" not in note
    title, _ = stance_title_from_face(card)
    assert "已降" not in title


def test_run_face_says_already_up_when_gain_large():
    """獲利大的未來卡：降溫／貼20高／升溫脫離都要寫已經漲多。"""
    cool = {
        "sell_action": "準備減碼",
        "sell_why": "先前同步再脫離",
        "gain_pct": 46.8,
        "dist_h20": -1.2,
        "table": [{"date": "20260909", "高低": "No", "預警": "K20高", "升降": "降溫", "profit_pct": 46.8}],
    }
    face = card_discipline_face(cool)
    assert face["why"] == "sync_left_run"
    note = sell_note_short(cool)
    assert "漲多" in note
    assert "已降" in note
    assert "在升" not in note

    hi20 = {
        "sell_action": "直接減碼",
        "sell_why": "不同步（最高價但非最高溫）",
        "gain_pct": 20.4,
        "table": [{"date": "20260909", "高低": "20高", "預警": "K20高", "升降": "No", "profit_pct": 20.4}],
    }
    assert card_discipline_face(hi20)["why"] == "hi_price_run"
    assert "漲多" in sell_note_short(hi20)
    assert "沒再走" in sell_note_short(hi20)

    back = {
        "sell_action": "直接減碼",
        "sell_why": "不同步再脫離",
        "gain_pct": 35.4,
        "dist_h20": -1.0,
        "table": [{"date": "20260909", "高低": "No", "預警": "K20高", "升降": "升溫", "profit_pct": 35.4}],
    }
    assert card_discipline_face(back)["why"] == "desync_left_run"
    note2 = sell_note_short(back)
    assert "漲多" in note2
    assert "升" in note2
    assert "已降" not in note2


def test_small_gain_does_not_use_run_face():
    card = {
        "sell_action": "準備減碼",
        "sell_why": "先前同步再脫離",
        "gain_pct": 12.0,
        "dist_h20": -1.2,
        "table": [{"date": "20260909", "高低": "No", "預警": "K20高", "升降": "降溫", "profit_pct": 12.0}],
    }
    assert card_discipline_face(card)["why"] == "sync_left"
    note = sell_note_short(card)
    assert "漲多" not in note
    assert "已降" in note


def test_00631l_warming_near_high_uses_rising_face():
    """00631L 型：最新列 K20高＋升溫＋獲利大。五十句寫在升，態度標題不寫已降。"""
    today = {
        "date": "20260910",
        "高低": "No",
        "預警": "K20高",
        "升降": "升溫",
        "升降註": "",
        "溫度計": "57.8 °C",
        "profit_pct": 29.7,
    }
    yest = {
        "date": "20260909",
        "高低": "No",
        "預警": "K20高",
        "升降": "降溫",
        "升降註": "",
        "溫度計": "69.7 °C",
        "profit_pct": 28.0,
    }
    newest_first = pd.DataFrame([today, yest])
    oldest_first = pd.DataFrame([yest, today])
    for tbl in (newest_first, oldest_first, [today, yest], [yest, today]):
        card = _etf_near_high_card(tbl)
        row = latest_table_row(card)
        assert str(row.get("date")) == "20260910"
        assert str(row.get("升降")) == "升溫"
        face = card_discipline_face(card)
        assert face["pos"] == "near_hi"
        assert face["heat"] == "up"
        assert face["why"] == "sync_left_run"
        note = sell_note_short(card)
        assert "升" in note
        assert "已降" not in note
        assert "退了" not in note
        assert "都沒了" not in note
        assert "20日高" in note
        assert "先出一點" in note
        title, kind = stance_title_from_face(card)
        assert kind == "avoid"
        assert "已降" not in title
        assert "別追" in title
        apply_face_stance(card)
        assert card["stance"] == title
        assert "已降" not in card["stance"]


def test_cooling_near_high_title_says_heat_dropped():
    card = _etf_near_high_card(
        [
            {
                "date": "20260910",
                "高低": "No",
                "預警": "K20高",
                "升降": "降溫",
                "profit_pct": 29.7,
            }
        ]
    )
    note = sell_note_short(card)
    assert "已降" in note or "在降" in note
    assert "在升" not in note
    title, kind = stance_title_from_face(card)
    assert kind == "avoid"
    assert "已降" in title


def test_attach_sell_overwrites_stance_from_face():
    tbl = pd.DataFrame(
        {
            "date": ["20260909", "20260910"],
            "高低": ["20高", "No"],
            "預警": ["K20高", "K20高"],
            "升降": ["最高溫", "升溫"],
        }
    )
    card = {
        "table": tbl,
        "gain_pct": 29.7,
        "dist_h20": -2.8,
        "stance": "今天先看表，先等",
        "stance_kind": "wait",
    }
    attach_sell(card)
    assert card["sell_action"] == "準備減碼"
    assert "同步再脫離" in card["sell_why"]
    assert "已降" not in card["stance"]
    assert "別追" in card["stance"]
    assert "升" in sell_note_short(card)


def test_decision_card_png_00631l_warming_not_cooling(tmp_path, monkeypatch):
    """決策卡今日態度＋紀律：升溫靠近20日高，畫面不能出現熱度已降。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from wayne_navigator import render_decision_card_png, render_first_glance_png

    seen = []
    orig = matplotlib.axes.Axes.text

    def wrap(self, *args, **kwargs):
        if len(args) >= 3:
            seen.append(str(args[2]))
        if "s" in kwargs:
            seen.append(str(kwargs["s"]))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    table = pd.DataFrame(
        [
            {
                "date": "20260910",
                "close": 24.5,
                "獲利": "29.7%",
                "高低": "No",
                "預警": "K20高",
                "溫度計": "57.8 °C",
                "升降": "升溫",
                "升降註": "",
                "月乖離": "+4.1%",
                "120日量": "第 40 名",
                "profit_pct": 29.7,
                "bias_monthly": 4.1,
                "vol_rank_120": 40,
                "temp_num": 57.8,
            },
            {
                "date": "20260909",
                "close": 24.1,
                "獲利": "28.0%",
                "高低": "No",
                "預警": "K20高",
                "溫度計": "69.7 °C",
                "升降": "降溫",
                "升降註": "",
                "月乖離": "+3.8%",
                "120日量": "第 42 名",
                "profit_pct": 28.0,
                "bias_monthly": 3.8,
                "vol_rank_120": 42,
                "temp_num": 69.7,
            },
            {
                "date": "20260908",
                "close": 24.8,
                "獲利": "31.0%",
                "高低": "20高",
                "預警": "K20高",
                "溫度計": "72.0 °C",
                "升降": "最高溫",
                "升降註": "",
                "月乖離": "+5.0%",
                "120日量": "第 38 名",
                "profit_pct": 31.0,
                "bias_monthly": 5.0,
                "vol_rank_120": 38,
                "temp_num": 72.0,
            },
        ]
    )
    card = _mini_card_for_png(
        table=table,
        sell_action="準備減碼",
        sell_why="先前同步再脫離",
        gain_pct=29.7,
        dist_h20=-2.8,
        temp_c="57.8 °C",
        stance="今天先看表，先等",
        stance_kind="wait",
        stock_id="00631L",
        stock_name="元大台灣50正2",
        latest_date="20260910",
        query_date="2026/09/10",
        close=24.5,
    )
    out = tmp_path / "00631L_warm.png"
    path = render_decision_card_png(card, str(out))
    assert path and out.is_file()
    joined = "\n".join(seen)
    assert "已降" not in joined
    assert "退了" not in joined
    assert "升" in joined
    assert "別追" in joined
    assert "今日態度" in joined

    seen.clear()
    glance = tmp_path / "00631L_glance.png"
    tape = {
        "last": {},
        "move": {},
        "volume": {},
        "foreign": {},
        "trust": {},
        "dealer": {},
        "three": {},
        "inst_pct": 0,
        "conflict": "",
    }
    gpath = render_first_glance_png("00631L", card, tape, str(glance))
    assert gpath and glance.is_file()
    joined_g = "\n".join(seen)
    assert "已降" not in joined_g
    assert "退了" not in joined_g
    assert "升" in joined_g


def test_cooling_leave_still_says_heat_left():
    card = {
        "sell_action": "準備減碼",
        "sell_why": "先前同步再脫離",
        "gain_pct": 18.1,
        "dist_h20": -2.8,
        "table": [{"高低": "No", "預警": "No", "升降": "降溫", "溫度計": "53.5 °C"}],
    }
    assert sell_note_short(card) == NOTE_SYNC_LEFT


def test_discipline_box_drops_conflicting_pink():
    from sell_discipline import discipline_box_notes

    left = {"sell_action": "準備減碼", "sell_why": "先前同步再脫離"}
    assert discipline_box_notes(left, "已經連 3 天貼在高檔，先不要追。有持股考慮先出") == [NOTE_SYNC_LEFT]
    hi = {"sell_action": "直接減碼", "sell_why": "不同步（最高價但非最高溫）"}
    assert discipline_box_notes(hi, "剛貼到高檔，先看、先別追") == [NOTE_HI_PRICE]
    quiet = {"sell_action": "", "sell_why": ""}
    assert discipline_box_notes(quiet, "已經連 3 天貼在高檔，先不要追。有持股考慮先出") == [
        "已經連 3 天貼在高檔，先不要追。有持股考慮先出"
    ]


def test_pink_warning_note_tells_what_to_do():
    from wayne_navigator import pink_warning_note

    assert pink_warning_note({"k20_high_streak": 3}) == "已經連 3 天貼在高檔，先不要追。有持股考慮先出"
    assert pink_warning_note({"k20_high_streak": 1}) == "剛貼到高檔，先看、先別追"
    assert pink_warning_note({"k20_high_streak": 0}) == ""
    assert "粉紅預警" not in pink_warning_note({"k20_high_streak": 4})


def test_glance_png_sync_leave_uses_plain_peak_heat(tmp_path, monkeypatch):
    """介紹圖紀律列：現況＋怎麼做，不要「到過…都過了」。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from wayne_navigator import render_first_glance_png

    seen = []
    orig = matplotlib.axes.Axes.text

    def wrap(self, *args, **kwargs):
        text = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        seen.append(text)
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    table = pd.DataFrame(
        [
            {"date": "20260903", "高低": "20高", "升降": "最高溫"},
            {"date": "20260904", "高低": "No", "升降": "降溫"},
        ]
    )
    card = _mini_card_for_png(table=table, sell_action="", sell_why="", dist_h20=-5.2)
    tape = {
        "last": {},
        "move": {},
        "volume": {},
        "foreign": {},
        "trust": {},
        "dealer": {},
        "three": {},
        "inst_pct": 0,
        "conflict": "",
    }
    out = tmp_path / "sync_leave_glance.png"
    path = render_first_glance_png("3035", card, tape, str(out))
    assert path and out.is_file()
    joined = "\n".join(seen)
    assert "高點跟熱度都退了" in joined
    assert "先別追" in joined
    assert "先出一點" in joined
    assert "到過" not in joined
    assert "都過了" not in joined
    assert "可以先想" not in joined
    assert not any(t.startswith("在") and "退了" in t for t in seen)


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
    assert sell_note_short(flags) == NOTE_HI_PRICE
    assert "買訊" not in sell_note_short(flags)
    assert "作者" not in sell_note_short(flags)
    full = sell_note_lines(flags)[0]
    assert full == f"{NOTE_HI_PRICE}。不是叫你買。"
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
    assert "monthly_stage" in html_src
    png_src = inspect.getsource(render_first_glance_png)
    assert "sell_note_short" in png_src
    assert '"紀律"' in png_src
    assert '"#AD1457"' in png_src
    card_src = inspect.getsource(render_decision_card_png)
    assert "sell_note_short" in card_src
    assert "apply_face_stance" in card_src
    assert "stance_explain" in card_src
    assert "今日態度" in card_src
    assert "monthly_stage" in card_src
    from sell_discipline import attach_sell as attach_fn

    assert "apply_face_stance" in inspect.getsource(attach_fn)
    from ai_trader import format_ai_desk_html, format_ai_desk_pages
    from portfolio_engine import PortfolioEngine

    assert "sell_notes_for_stocks" in inspect.getsource(format_ai_desk_pages)
    assert "月K" in inspect.getsource(format_ai_desk_pages)
    assert "format_ai_desk_pages" in inspect.getsource(format_ai_desk_html)
    assert "sell_notes_for_stocks" in inspect.getsource(PortfolioEngine.format_holdings_html)
    assert "月K" in inspect.getsource(PortfolioEngine.format_holdings_html)


@pytest.mark.production_db
def test_3441_20260904_how_to_sell_survives_table_reattach():
    """聯一光 9/4：作者公開最高價但非最高溫；查股 HTML 會再 attach 一次，不能被新→舊表洗掉。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(get_db_path()).get_decision_card(
        "3441", merge_live=False, as_of="20260904"
    )
    assert str(card.get("latest_date")) == "20260904"
    assert card.get("sell_action") == "直接減碼"
    again = {"table": card["table"]}
    attach_sell(again)
    assert again["sell_action"] == "直接減碼"
    line = sell_note_lines(again)[0]
    assert "先出一點" in line
    assert "不要追" in line
    assert "不是叫你買" in line
    assert "不同步（" not in line
    assert "先出一點" in sell_note_short(again)
    assert "不要追" in sell_note_short(again)
    assert "退了" not in sell_note_short(again)


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
    joined = "\n".join(seen)
    assert any("先出一點" in t and "不要追" in t and "不是叫你買" in t for t in seen)
    assert not any("熱度都退了" in t for t in seen)
    assert "紅箭頭不是買進訊號" not in joined
    assert "按表操課" not in joined


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
    path = render_decision_card_png(
        _mini_card_for_png(stance="今天先看表，先等", stance_kind="wait"),
        str(out),
    )
    assert path and out.is_file()
    joined = "\n".join(seen)
    # mini 卡是 20高／獲利很大：第二行對表講高檔，不是套紅箭頭那句。
    assert "表貼在高檔" in joined
    assert "紅箭頭不是買進訊號" not in joined
    assert "紀律　" not in joined


def test_glance_png_sell_stays_readable_with_long_fund(tmp_path, monkeypatch):
    """季報長句不可把介紹圖紀律列壓成 8pt。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from wayne_navigator import render_first_glance_png

    monkeypatch.setattr(
        "fundamentals.glance_fundamentals_plain",
        lambda *_a, **_k: [
            (
                "季報",
                "2026Q2　營收 999.9億　毛利 111.1億　毛利率 12.3%　營益率 8.7%　EPS 12.34",
            )
        ],
    )
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
        dist_l120=80.0,
        dist_l240=90.0,
        dist_l480=100.0,
        vol_rank=30,
        vol_rank_60=20,
        vol_rank_480=10,
        temp_c="81.1 °C",
        prev_close=130.0,
        open=134.0,
        high=143.0,
        low=129.5,
        k20_high_streak=0,
    )
    tape = {
        "last": {},
        "move": {},
        "volume": {},
        "foreign": {},
        "trust": {},
        "dealer": {},
        "three": {},
        "inst_pct": 0,
    }
    out = tmp_path / "glance_sell.png"
    path = render_first_glance_png("3441", card, tape, str(out))
    assert path and out.is_file()
    assert "紀律" in seen
    assert any("先出一點" in s and "不要追" in s for s in seen)
    assert not any("熱度都退了" in s for s in seen)
    assert not any(s.startswith("紀律　") for s in seen)


@pytest.mark.production_db
def test_cary_2383_2408_3008_20260904_rows():
    """Cary 對卡殘差：台光電獲利不歸零、南亞科 9/3 最低溫、大立光 9/4 如何賣脫離。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    eng = NavigatorEngine(get_db_path())

    c2383 = eng.get_decision_card("2383", merge_live=False, as_of="20260904")
    assert str(c2383.get("latest_date")) == "20260904"
    assert float(c2383["cal60_low"]) == 4100.0
    assert abs(float(c2383["gain_pct"]) - 32.1) < 0.2
    t2383 = c2383["table"]
    r04 = t2383[t2383["date"].astype(str) == "20260904"].iloc[0]
    assert r04["獲利"] == "32.1%"
    r03 = t2383[t2383["date"].astype(str) == "20260903"].iloc[0]
    assert str(r03["升降"]) == "最低溫"

    c2408 = eng.get_decision_card("2408", merge_live=False, as_of="20260904")
    t2408 = c2408["table"]
    n03 = t2408[t2408["date"].astype(str) == "20260903"].iloc[0]
    assert str(n03["升降"]) == "最低溫"
    assert "價未新低" in str(n03.get("升降註") or "")
    assert float(c2408["gain_pct"]) > 40.0

    c3008 = eng.get_decision_card("3008", merge_live=False, as_of="20260904")
    assert str(c3008.get("latest_date")) == "20260904"
    assert c3008.get("sell_action") == "直接減碼"
    assert "不同步再脫離" in str(c3008.get("sell_why") or "")
    note3008 = sell_note_short(c3008)
    assert "先出一點" in note3008
    assert "退了" not in note3008
    assert "都沒了" not in note3008
    assert "升" in note3008


@pytest.mark.production_db
def test_4915_20260904_sync_has_no_sell_caption():
    """致伸 9/4 最高價與最高溫同步：不是減碼標，決策卡圖說不可多寫紀律。"""
    from bot_servers import _photo_sell_caption
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(get_db_path()).get_decision_card(
        "4915", merge_live=False, as_of="20260904"
    )
    assert str(card.get("latest_date")) == "20260904"
    row = card["table"].iloc[0]
    assert str(row["高低"]) == "20高"
    assert str(row["升降"]) == "最高溫"
    assert card.get("sell_sync") is True
    assert card.get("sell_action") == ""
    assert sell_note_short(card) == ""
    assert _photo_sell_caption("高低決策卡", card, fallback="高低決策卡") == "高低決策卡"


def test_sell_note_short_skips_when_table_reads_low():
    """近480日低且今天不是20高：減碼句不上卡。"""
    card = {
        "sell_action": "準備減碼",
        "sell_why": "先前同步再脫離",
        "gain_pct": 1.3,
        "space_20": 3,
        "bias_monthly": 0.1,
        "badges": ["近480日低"],
        "table": [{"高低": "No", "預警": "No"}],
    }
    assert sell_note_short(card) == ""
    assert sell_note_lines(card) == []
    hot = {
        "sell_action": "直接減碼",
        "sell_why": "不同步（最高價但非最高溫）",
        "gain_pct": 11.8,
        "space_20": 5,
        "badges": ["創20日新高"],
        "table": [{"高低": "20高", "預警": "K20高"}],
    }
    assert sell_note_short(hot) == NOTE_HI_PRICE
    assert sell_notes_for_stocks([], "/no/such.db") == {}
    assert sell_notes_for_stocks(["3703"], "") == {}


def test_ai_desk_html_wires_sell_note(monkeypatch, tmp_path):
    from wayne_db import ensure_core_schema
    from portfolio_engine import PortfolioEngine
    from ai_trader import ensure_ai_user, format_ai_desk_html, format_ai_desk_pages

    path = str(tmp_path / "ai_sell.db")
    ensure_core_schema(path)
    eng = PortfolioEngine(path)
    uid = "1001"
    user = ensure_ai_user(eng, uid)
    bought = eng.buy(user, "20260904", "3703", "欣陸", 19.95, 8000, reason="黃金買點：獲利離零")
    assert bought.get("success") is True

    def fake_notes(ids, db_path, *, full=False, as_of=None, readings=None):
        assert "3703" in [str(x) for x in ids]
        assert full is True
        if readings is not None:
            readings["3703"] = {
                "monthly_stage": "月K還在往上",
                "monthly_stage_short": "還在往上",
            }
        return {"3703": f"{NOTE_HI_TEMP}。不是叫你買。"}

    monkeypatch.setattr("sell_discipline.sell_notes_for_stocks", fake_notes)
    html = format_ai_desk_html(eng, uid)
    pages = format_ai_desk_pages(eng, uid)
    assert len(pages) >= 2
    assert "紀律：" in html
    assert "月K　還在往上" in html
    assert "先出一點" in html
    assert "不是叫你買" in html
    assert "<b>第 1 槽</b>" in html
    assert "<b>槽位</b>" in html
    assert "○" in html
    assert any("第 1 槽" in p for p in pages)
    assert not any("總資產" in p and "第 1 槽" in p for p in pages)


def test_holdings_html_wires_sell_note(monkeypatch, tmp_path):
    from wayne_db import ensure_core_schema
    from portfolio_engine import PortfolioEngine

    path = str(tmp_path / "hold_sell.db")
    ensure_core_schema(path)
    eng = PortfolioEngine(path)

    def fake_notes(ids, db_path, *, full=False, as_of=None, readings=None):
        assert "3035" in [str(x) for x in ids]
        assert "4915" in [str(x) for x in ids]
        assert full is True
        if readings is not None:
            readings["3035"] = {
                "monthly_stage": "月K已走空",
                "monthly_stage_short": "已走空",
            }
        return {"3035": f"{NOTE_SYNC_LEFT}。不是叫你買。"}

    monkeypatch.setattr("sell_discipline.sell_notes_for_stocks", fake_notes)
    html = eng.format_holdings_html(
        [
            {"stock_code": "3035", "stock_name": "智原", "shares": 1, "cost_price": 100},
            {"stock_code": "4915", "stock_name": "致伸", "shares": 1, "cost_price": 60},
        ],
        quotes_map={
            "3035": {"close": 110, "pct_change": 1.0},
            "4915": {"close": 60.8, "pct_change": 0.5},
        },
    )
    assert f"{NOTE_SYNC_LEFT}。不是叫你買。" in html
    assert "月K" in html.split("智原")[-1].split("致伸")[0]
    assert "已走空" in html
    assert html.split("致伸")[-1].count("紀律") == 0


@pytest.mark.production_db
def test_holdings_and_notes_match_20260904_flags():
    """手記 3035／6526 準備減碼、AI 3703 直接減碼；致伸同步不標。"""
    from config import get_db_path
    from portfolio_engine import PortfolioEngine

    db = get_db_path()
    notes = sell_notes_for_stocks(
        ["3703", "3035", "6526", "4915", "1303", "8234"],
        db,
        full=True,
        as_of="20260904",
    )
    assert "先出一點" in notes["3703"]
    assert "不要追高" in notes["3703"]
    assert "不是叫你買" in notes["3703"]
    assert "退了" in notes["3035"]
    assert "漲多" in notes["3035"]
    assert "先別追" in notes["3035"]
    assert "不是叫你買" in notes["3035"]
    assert "退了" not in notes["6526"]
    assert "升" in notes["6526"]
    assert "先別追" in notes["6526"]
    assert "4915" not in notes
    assert "1303" not in notes
    assert "8234" not in notes

    from wayne_navigator import NavigatorEngine

    live = NavigatorEngine(db).get_decision_card("3703", merge_live=False)
    if str(live.get("latest_date")) != "20260904":
        return

    eng = PortfolioEngine(db)
    html_cut = eng.format_holdings_html(
        [{"stock_code": "3703", "stock_name": "欣陸", "shares": 8, "cost_price": 19.95}],
        quotes_map={"3703": {"close": 20.0, "pct_change": 0.5}},
    )
    assert "紀律：" in html_cut
    assert "先出一點" in html_cut
    assert "不要追高" in html_cut
    html_sync = eng.format_holdings_html(
        [{"stock_code": "4915", "stock_name": "致伸", "shares": 1, "cost_price": 60.8}],
        quotes_map={"4915": {"close": 60.8, "pct_change": 0.3}},
    )
    assert "紀律" not in html_sync
    assert "減碼" not in html_sync
