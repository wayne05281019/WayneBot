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
    sell_notes_for_stocks,
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
    assert 'str(a) == "紀律"' in png_src
    assert '"#AD1457"' in png_src
    card_src = inspect.getsource(render_decision_card_png)
    assert "sell_note_short" in card_src
    assert "紀律" in card_src
    assert "_fp(11.0 if sell_sub else 9.4)" in card_src
    from ai_trader import format_ai_desk_html
    from portfolio_engine import PortfolioEngine

    assert "sell_notes_for_stocks" in inspect.getsource(format_ai_desk_html)
    assert "sell_notes_for_stocks" in inspect.getsource(PortfolioEngine.format_holdings_html)


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
    joined = "\n".join(seen)
    assert "紀律　直接減碼（最高價但非最高溫）" in joined


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


@pytest.mark.production_db
def test_4915_20260904_sync_has_no_sell_caption():
    """致伸 9/4 最高價與最高溫同步：不是減碼標，決策卡圖說不可多寫紀律。"""
    from bot_servers import _photo_sell_caption
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(get_db_path()).get_decision_card("4915", merge_live=False)
    assert str(card.get("latest_date")) == "20260904"
    row = card["table"].iloc[0]
    assert str(row["高低"]) == "20高"
    assert str(row["升降"]) == "最高溫"
    assert card.get("sell_sync") is True
    assert card.get("sell_action") == ""
    assert sell_note_short(card) == ""
    assert _photo_sell_caption("高低決策卡", card, fallback="高低決策卡") == "高低決策卡"


def test_sell_notes_for_stocks_empty_inputs():
    assert sell_notes_for_stocks([], "/no/such.db") == {}
    assert sell_notes_for_stocks(["3703"], "") == {}


def test_ai_desk_html_wires_sell_note(monkeypatch, tmp_path):
    from wayne_db import ensure_core_schema
    from portfolio_engine import PortfolioEngine
    from ai_trader import ensure_ai_user, format_ai_desk_html

    path = str(tmp_path / "ai_sell.db")
    ensure_core_schema(path)
    eng = PortfolioEngine(path)
    uid = "1001"
    user = ensure_ai_user(eng, uid)
    bought = eng.buy(user, "20260904", "3703", "欣陸", 19.95, 8000, reason="起漲：獲利離零")
    assert bought.get("success") is True

    def fake_notes(ids, db_path, *, full=False):
        assert "3703" in [str(x) for x in ids]
        assert full is True
        return {"3703": "直接減碼（最高溫但非最高價；作者如何賣，不是買訊）"}

    monkeypatch.setattr("sell_discipline.sell_notes_for_stocks", fake_notes)
    html = format_ai_desk_html(eng, uid)
    assert "紀律：" in html
    assert "直接減碼（最高溫但非最高價；作者如何賣，不是買訊）" in html
    assert "不是買訊" in html


def test_holdings_html_wires_sell_note(monkeypatch, tmp_path):
    from wayne_db import ensure_core_schema
    from portfolio_engine import PortfolioEngine

    path = str(tmp_path / "hold_sell.db")
    ensure_core_schema(path)
    eng = PortfolioEngine(path)

    def fake_notes(ids, db_path, *, full=False):
        assert "3035" in [str(x) for x in ids]
        assert "4915" in [str(x) for x in ids]
        assert full is True
        return {"3035": "準備減碼（先前同步再脫離；作者如何賣，不是買訊）"}

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
    assert "準備減碼（先前同步再脫離；作者如何賣，不是買訊）" in html
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
    )
    assert notes["3703"].startswith("直接減碼（最高溫但非最高價")
    assert "不是買訊" in notes["3703"]
    assert notes["3035"].startswith("準備減碼（先前同步再脫離")
    assert notes["6526"].startswith("準備減碼（先前同步再脫離")
    assert "4915" not in notes
    assert "1303" not in notes
    assert "8234" not in notes

    eng = PortfolioEngine(db)
    html_cut = eng.format_holdings_html(
        [{"stock_code": "3703", "stock_name": "欣陸", "shares": 8, "cost_price": 19.95}],
        quotes_map={"3703": {"close": 20.0, "pct_change": 0.5}},
    )
    assert "紀律：" in html_cut
    assert "直接減碼（最高溫但非最高價" in html_cut
    html_sync = eng.format_holdings_html(
        [{"stock_code": "4915", "stock_name": "致伸", "shares": 1, "cost_price": 60.8}],
        quotes_map={"4915": {"close": 60.8, "pct_change": 0.3}},
    )
    assert "紀律" not in html_sync
    assert "減碼" not in html_sync
