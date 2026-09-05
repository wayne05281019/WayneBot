# -*- coding: utf-8 -*-
from decision_card_signals import (
    card_daily_stance,
    double_green_breakout,
    format_profit_pct,
    is_profit_display_zero,
    leave_zero_screen_ok,
    profit_left_zero_highlight,
)


def test_profit_display_zero():
    assert is_profit_display_zero(0.0)
    assert is_profit_display_zero(0.04)
    assert not is_profit_display_zero(0.05)
    assert format_profit_pct(1.23) == "1.2%"


def test_profit_left_zero_matches_card_tests():
    # 對齊 test_profit_cell_uses_low_palette
    assert profit_left_zero_highlight(0.0, 0.9)
    assert not profit_left_zero_highlight(0.9, 1.5)


def test_double_green_breakout():
    assert double_green_breakout(0.0, "No", 1.2, "No")
    assert double_green_breakout(1.0, "60低", 2.0, "No")
    assert not double_green_breakout(1.0, "No", 2.0, "No")
    assert not double_green_breakout(0.0, "No", 0.0, "No")


def test_leave_zero_screen_caps_runners():
    ok, _ = leave_zero_screen_ok(0.0, 4.5)
    assert ok
    ok, reason = leave_zero_screen_ok(0.0, 5.2)
    assert not ok
    assert "5" in reason


def test_2383_carybot_profit_at_5295_vs_4100():
    """2026-09-04 Cary：收 5295、60曆日低 4100 → 獲利 29.1%，不得因貼20低歸零。"""
    pct = (5295.0 - 4100.0) / 4100.0 * 100.0
    assert abs(pct - 29.1) < 0.05
    assert format_profit_pct(pct) == "29.1%"
    assert not is_profit_display_zero(pct)


def test_card_query_stamp_live_includes_seconds():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from decision_card_signals import format_card_query_stamp

    dt = datetime(2026, 9, 4, 10, 15, 7, tzinfo=ZoneInfo("Asia/Taipei"))
    date_s, clock_s = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=dt
    )
    assert date_s == "2026/09/04"
    assert clock_s == "盤中 10:15"
    date_s, clock_s = format_card_query_stamp(
        is_live=True,
        latest_date="20260904",
        generated_at="2026-09-04 13:25:18",
    )
    assert clock_s == "盤中 13:25"
    date_s, clock_s = format_card_query_stamp(
        is_live=False, latest_date="20260904", generated_at=dt
    )
    assert date_s == "2026/09/04"
    assert clock_s == "13:30收盤"


def test_card_query_stamp_after_close_is_fixed():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from decision_card_signals import format_card_query_stamp

    after = datetime(2026, 9, 4, 23, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    date_s, clock_s = format_card_query_stamp(
        is_live=False, latest_date="20260904", generated_at=after
    )
    assert date_s == "2026/09/04"
    assert clock_s == "13:30收盤"
    date_s, clock_s = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at="2026-09-04 13:30:00"
    )
    assert clock_s == "13:30收盤"
    weekend = datetime(2026, 9, 5, 16, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    _, clock_s = format_card_query_stamp(
        is_live=False, latest_date="20260904", generated_at=weekend
    )
    assert clock_s == "13:30收盤"
    open_bell = datetime(2026, 9, 4, 9, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    _, clock_s = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=open_bell
    )
    assert clock_s == "盤中 09:00"
    preopen = datetime(2026, 9, 4, 8, 50, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    _, clock_s = format_card_query_stamp(
        is_live=True, latest_date="20260904", generated_at=preopen
    )
    assert clock_s == "13:30收盤"


def test_card_daily_stance_is_table_not_arrow():
    """高檔／溫度≥80＝不要追；60低＋超跌＝觀察。不是下單、不抄紅箭頭。"""
    txt, kind = card_daily_stance(
        profit_pct=99.2, alert="No", hl="No", temp=72.4, badges=[]
    )
    assert kind == "avoid"
    assert "不宜追" in txt
    txt, kind = card_daily_stance(
        profit_pct=1.0,
        alert="60低",
        hl="60低",
        temp=12.0,
        bias=-12.0,
        badges=[],
    )
    assert kind == "watch"
    assert "觀察" in txt
    txt, kind = card_daily_stance(
        profit_pct=32.1, alert="K20低", hl="No", temp=17.3, badges=["空頭整理"]
    )
    assert kind == "wait"
    txt, kind = card_daily_stance(
        profit_pct=10.0,
        alert="K20高",
        hl="20高",
        temp=83.0,
        trend_note="價溫背離",
        badges=["價溫背離少追"],
    )
    assert kind == "avoid"
    assert "不要追" in txt
    # 玉晶光型：創中長線新高且溫度≥80 → 今天不要追
    txt, kind = card_daily_stance(
        profit_pct=135.8,
        alert="K20高",
        hl="20高",
        temp=83.1,
        badges=["創480日新高", "溫度≥80注意"],
    )
    assert kind == "avoid"
    assert "不要追" in txt
    # 華票型：紅箭頭／20高＋最高溫不是買訊，也不當低點觀察
    txt, kind = card_daily_stance(
        profit_pct=5.6,
        alert="K20高",
        hl="20高",
        temp=31.0,
        badges=["創20日新高"],
    )
    assert kind == "wait"
    assert "買" not in txt
    assert "觀察" not in txt


def test_4915_sep4_leave_zero_is_wait_not_buy():
    """9/4 致伸：雙綠脫離可進起漲；貼 20 高、溫度未滿 80＝等待，不是買訊。"""
    ok, reason = leave_zero_screen_ok(0.3, 2.4, yest_alert="60低", today_alert="K20高")
    assert ok
    assert "雙綠" in reason
    txt, kind = card_daily_stance(
        profit_pct=2.4, alert="K20高", hl="20高", temp=69.3, badges=[]
    )
    assert kind == "wait"
    assert "等待" in txt
    assert "不要追" not in txt


def test_live_decision_card_png_draws_query_clock(tmp_path, monkeypatch):
    import os

    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.axes
    import pandas as pd

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
    table = pd.DataFrame(
        [
            {
                "date": "20260904",
                "close": 100.0,
                "獲利": "1.0%",
                "高低": "No",
                "預警": "No",
                "溫度計": "20.0 °C",
                "升降": "升溫",
                "升降註": "",
                "月乖離": "+0.5%",
                "120日量": "第 80 名",
                "profit_pct": 1.0,
                "bias_monthly": 0.5,
                "vol_rank_120": 80,
                "temp_num": 20.0,
            }
        ]
    )
    card = {
        "stock_id": "2330",
        "stock_name": "台積電",
        "industry": "半導體業",
        "latest_date": "20260904",
        "is_live": True,
        "generated_at": "2026-09-04 10:15:07",
        "query_date": "2026/09/04",
        "query_clock": "盤中 10:15",
        "close": 100.0,
        "change_pct": 1.0,
        "prev_close": 99.0,
        "open": 99.5,
        "high": 101.0,
        "low": 99.0,
        "h10": 101.0,
        "dist_h10": -1.0,
        "h20": 102.0,
        "dist_h20": -2.0,
        "h60": 110.0,
        "dist_h60": -9.1,
        "l10": 95.0,
        "dist_l10": 5.3,
        "l20": 90.0,
        "dist_l20": 11.1,
        "l60": 80.0,
        "dist_l60": 25.0,
        "space_20": 13,
        "space_60": 37,
        "ma60s": 0.1,
        "qty60": 1000,
        "badges": ["盤中 10:15"],
        "stance": "等待・按表操課",
        "stance_kind": "wait",
        "table": table,
    }
    out = tmp_path / "live_stamp.png"
    path = render_decision_card_png(card, str(out))
    assert path and out.is_file()
    assert any("盤中 10:15" in t for t in seen)
    assert any("2026/09/04" in t for t in seen)
    assert any("半導體業" in t for t in seen)


def test_closed_cards_draw_industry_and_fixed_close_clock(tmp_path, monkeypatch):
    import os

    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.axes
    import pandas as pd

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
                "date": "20260904",
                "close": 18.3,
                "獲利": "1.1%",
                "高低": "No",
                "預警": "No",
                "溫度計": "20.0 °C",
                "升降": "升溫",
                "升降註": "",
                "月乖離": "+0.5%",
                "120日量": "第 80 名",
                "profit_pct": 1.1,
                "bias_monthly": 0.5,
                "vol_rank_120": 80,
                "temp_num": 20.0,
            }
        ]
    )
    card = {
        "stock_id": "5276",
        "stock_name": "達輝-KY",
        "industry": "其他業",
        "latest_date": "20260904",
        "is_live": False,
        "generated_at": "2026-09-05 23:22:00",
        "query_date": "2026/09/04",
        "query_clock": "13:30收盤",
        "next_event": "",
        "close": 18.3,
        "change_pct": 1.1,
        "prev_close": 18.1,
        "open": 18.2,
        "high": 18.4,
        "low": 18.1,
        "h10": 19.0,
        "dist_h10": -3.7,
        "h20": 19.2,
        "dist_h20": -4.7,
        "h60": 20.0,
        "dist_h60": -8.5,
        "l10": 17.0,
        "dist_l10": 7.6,
        "l20": 16.5,
        "dist_l20": 10.9,
        "l60": 15.0,
        "dist_l60": 22.0,
        "space_20": 10,
        "space_60": 20,
        "ma60s": 0.1,
        "qty60": 100,
        "badges": ["整理格局"],
        "stance": "等待・按表操課",
        "stance_kind": "wait",
        "table": table,
    }
    card_path = tmp_path / "closed_stamp_card.png"
    glance_path = tmp_path / "closed_stamp_glance.png"
    assert render_decision_card_png(card, str(card_path))
    assert any("13:30收盤" in t for t in seen)
    assert any("其他業" in t for t in seen)
    assert not any("23:22" in t for t in seen)
    seen.clear()
    tape = {"last": {}, "move": {}, "volume": {}, "foreign": {}, "trust": {}, "dealer": {}, "three": {}, "inst_pct": 0}
    assert render_first_glance_png("5276", card, tape, str(glance_path))
    assert any("13:30收盤" in t for t in seen)
    assert any("其他業" in t for t in seen)
    assert any("整理格局" in t for t in seen)
    assert not any("23:22" in t for t in seen)
