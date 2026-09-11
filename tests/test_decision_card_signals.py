# -*- coding: utf-8 -*-
import pytest

from decision_card_signals import (
    card_daily_stance,
    double_green_breakout,
    format_profit_pct,
    is_profit_display_zero,
    leave_zero_screen_ok,
    profit_display_leave_zero_band,
    profit_left_zero_highlight,
    stance_explain,
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
    assert profit_display_leave_zero_band(0.3)
    assert profit_display_leave_zero_band(0.7)
    assert profit_display_leave_zero_band(0.8)
    assert not profit_display_leave_zero_band(0.0)
    assert not profit_display_leave_zero_band(1.2)
    assert not profit_display_leave_zero_band(2.4)


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
    assert date_s == "2026/09/04（五）"
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
    assert date_s == "2026/09/04（五）"
    assert clock_s == "13:30收盤"


def test_card_query_stamp_after_close_is_fixed():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from decision_card_signals import format_card_query_stamp

    after = datetime(2026, 9, 4, 23, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    date_s, clock_s = format_card_query_stamp(
        is_live=False, latest_date="20260904", generated_at=after
    )
    assert date_s == "2026/09/04（五）"
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


def test_evening_lookup_stamp_is_close_not_wall_clock():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from decision_card_signals import format_card_query_stamp

    night = datetime(2026, 9, 8, 21, 40, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    _, clock_s = format_card_query_stamp(
        is_live=True, latest_date="20260908", generated_at=night
    )
    assert clock_s == "13:30收盤"
    _, clock_s = format_card_query_stamp(
        is_live=False, latest_date="20260908", generated_at=night
    )
    assert clock_s == "13:30收盤"


def test_stamp_and_dual_pill_do_not_reuse_live_clock_or_round_dots():
    import inspect

    from bot_servers import WayneTelegramBot
    from wayne_navigator import _pill, render_decision_card_png, render_first_glance_png

    glance = inspect.getsource(render_first_glance_png)
    card_png = inspect.getsource(render_decision_card_png)
    caption = inspect.getsource(WayneTelegramBot._send_decision_card_quick)
    assert 'or card.get("live_time")' not in glance
    assert 'or card.get("live_time")' not in caption
    assert "rounding_size=0.45" not in inspect.getsource(_pill)
    assert "dual_trend_half_boxes" in card_png
    show = inspect.getsource(WayneTelegramBot._show_picture_guide_page)
    assert "InputMediaAnimation" not in show
    assert "ensure_flip_gif" not in show
    """高檔／溫度≥80＝不要追；60低＋超跌＝觀察。不是下單、不抄紅箭頭。"""
    txt, kind = card_daily_stance(
        profit_pct=99.2, alert="No", hl="No", temp=72.4, badges=[]
    )
    assert kind == "avoid"
    assert "別追" in txt
    txt, kind = card_daily_stance(
        profit_pct=1.0,
        alert="60低",
        hl="60低",
        temp=12.0,
        bias=-12.0,
        badges=[],
    )
    assert kind == "watch"
    assert "看表" in txt
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
    assert "別追" in txt
    # 玉晶光型：創中長線新高且溫度≥80 → 今天別追高
    txt, kind = card_daily_stance(
        profit_pct=135.8,
        alert="K20高",
        hl="20高",
        temp=83.1,
        badges=["創480日新高", "溫度≥80注意"],
    )
    assert kind == "avoid"
    assert "別追" in txt
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
    assert "先等" in txt
    assert "別追" not in txt


def test_stance_explain_is_plain_speech():
    wait = stance_explain("wait")
    assert "20日表" in wait
    assert "紅箭頭不是買進訊號" in wait
    assert "按表操課" not in wait
    avoid = stance_explain("avoid")
    assert "追進去容易挨打" in avoid
    watch = stance_explain("watch")
    assert "先別急著買" in watch
    assert "低點訊號不是買訊" in watch
    sell = stance_explain("avoid", sell_note="現在價到高了、熱度沒跟上，先出一點、不要追")
    assert "不是叫你買" in sell
    assert "買訊" not in sell
    # 月K不寫進第二行，避免跟表上月乖離撞名。
    staged = stance_explain("wait", monthly_stage="月K還在往上")
    assert not staged.startswith("月K")
    assert "20日表" in staged


def test_stance_explain_follows_table_colors():
    """第二行對最新列／獲利／月乖離，不講月K、不在長線低喊減碼。"""
    from decision_card_signals import table_reads_as_low

    # 2383 型：獲利粉紅、空頭、月乖離綠、預警低
    card_2383 = {
        "gain_pct": 34.0,
        "space_20": 20,
        "bias_monthly": -3.2,
        "badges": ["空頭排列", "月K還在往上"],
        "table": [
            {
                "高低": "No",
                "預警": "K20低",
                "profit_pct": 34.0,
                "bias_monthly": -3.2,
            }
        ],
    }
    txt = stance_explain("wait", card=card_2383)
    assert "月K" not in txt
    assert "往上" not in txt
    assert "偏空" in txt
    assert "月線下" in txt
    assert "先等" in txt
    assert "34.0%" in txt
    assert "-3.2%" in txt
    assert not table_reads_as_low(card_2383)

    # 4915 9/7 型：近480日低、空間極窄、減碼句要關掉
    card_4915 = {
        "gain_pct": 1.3,
        "space_20": 3,
        "bias_monthly": 0.1,
        "badges": ["近480日低", "整理格局", "月K已走空"],
        "sell_action": "準備減碼",
        "sell_why": "先前同步再脫離",
        "table": [{"高低": "No", "預警": "No", "profit_pct": 1.3, "bias_monthly": 0.1}],
    }
    assert table_reads_as_low(card_4915)
    txt = stance_explain(
        "wait",
        sell_note="現在高點跟熱度都退了，先別追、也先別加碼。有持股就先出一點",
        card=card_4915,
    )
    assert "先出一點" not in txt
    assert "高點" not in txt
    assert "長線低" in txt
    assert "空間很小" in txt
    assert "低點訊號不是買訊" in txt

    # 康普型：貼低、獲利還在 0 附近 → 低點訊號不是買、先不要動作
    card_4739 = {
        "gain_pct": 0.1,
        "space_20": 6,
        "bias_monthly": -7.5,
        "badges": ["整理格局"],
        "table": [
            {
                "高低": "20低",
                "預警": "K20低",
                "profit_pct": 0.1,
                "bias_monthly": -7.5,
            }
        ],
    }
    txt = stance_explain("watch", card=card_4739)
    assert "低點訊號不是買訊" in txt
    assert "獲利還沒離開0" in txt
    assert "0.1%" in txt
    assert "先別急著買" in txt

    # 4915 9/4 型：同一段低，但今天格子是 20高 → 講高，不講壓低
    card_4915_hi = {
        "gain_pct": 2.4,
        "space_20": 3,
        "bias_monthly": 1.1,
        "badges": ["近480日低", "整理格局"],
        "table": [{"高低": "20高", "預警": "K20高", "profit_pct": 2.4, "bias_monthly": 1.1}],
    }
    assert not table_reads_as_low(card_4915_hi)
    txt = stance_explain("wait", card=card_4915_hi)
    assert "小區間的高" in txt
    assert "先別追" in txt
    assert "長線低" not in txt

    # 3105 型：漲多、月乖離正
    card_run = {
        "gain_pct": 68.1,
        "space_20": 39,
        "bias_monthly": 9.8,
        "badges": ["多頭格局"],
        "table": [{"高低": "No", "預警": "No", "profit_pct": 68.1, "bias_monthly": 9.8}],
    }
    txt = stance_explain("avoid", card=card_run)
    assert "拉很開" in txt
    assert "月線" in txt
    assert "別追" in txt
    assert "68.1%" in txt
    assert "+9.8%" in txt


def test_stance_explain_00631l_warming_not_cooling():
    """K20高＋升溫：第二行用五十句「在升」，不能抄降溫那句。"""
    import pandas as pd

    from sell_discipline import attach_sell, sell_note_short

    card = {
        "gain_pct": 29.7,
        "dist_h20": -2.8,
        "space_20": 12,
        "bias_monthly": 4.1,
        "stance": "今天先看表，先等",
        "stance_kind": "wait",
        "table": pd.DataFrame(
            [
                {
                    "date": "20260908",
                    "高低": "20高",
                    "預警": "K20高",
                    "升降": "最高溫",
                    "profit_pct": 31.0,
                },
                {
                    "date": "20260909",
                    "高低": "No",
                    "預警": "K20高",
                    "升降": "降溫",
                    "profit_pct": 28.0,
                },
                {
                    "date": "20260910",
                    "高低": "No",
                    "預警": "K20高",
                    "升降": "升溫",
                    "profit_pct": 29.7,
                },
            ]
        ),
    }
    attach_sell(card)
    note = stance_explain(
        str(card.get("stance_kind") or "wait"),
        sell_note=sell_note_short(card),
        card=card,
    )
    assert card.get("sell_action") == "準備減碼"
    assert "升" in note
    assert "已降" not in note
    assert "退了" not in note
    assert "先出一點" in note
    assert "已降" not in str(card.get("stance") or "")


def test_stance_explain_missing_bias_does_not_invent_monthly():
    """LINE／海選沒月乖離時，不准說貼著月線。"""
    txt = stance_explain("wait", card={"profit": 12.3, "close": 100.0}, surface="list")
    assert "貼著月線" not in txt
    assert "月線" not in txt
    assert "紅箭頭不是買進訊號" in txt
    assert "看下面這張" not in txt


def test_ma_matches_price_and_close_gap():
    from decision_card_signals import close_gap_broken, ma_matches_price

    assert ma_matches_price(100, 98)
    assert not ma_matches_price(67.1, 1004.1)
    assert not ma_matches_price(67.1, None)
    assert not close_gap_broken(None, 67.1)
    assert close_gap_broken(1490, 67.1)
    assert not close_gap_broken(100, 101)


def test_monthly_stage_from_ohlc_three_phases():
    from decision_card_signals import (
        MONTHLY_STAGE_DOWN,
        MONTHLY_STAGE_SIDE,
        MONTHLY_STAGE_UP,
        monthly_stage_from_ohlc,
    )

    def yyyymm(i: int) -> str:
        y, m = divmod(i, 12)
        return f"{2024 + y}{m + 1:02d}28"

    rising = [10.0 + i for i in range(18)]
    dates = [yyyymm(i) for i in range(18)]
    kind, label, short = monthly_stage_from_ohlc(dates, rising)
    assert kind == "up"
    assert label == MONTHLY_STAGE_UP
    assert short == "還在往上"

    falling = [40.0 - i for i in range(18)]
    kind, label, short = monthly_stage_from_ohlc(dates, falling)
    assert kind == "down"
    assert label == MONTHLY_STAGE_DOWN
    assert short == "已走空"

    # 均線仍往上但本月大跌 → 整理，不喊往上
    pullback = list(rising)
    pullback[-1] = pullback[-2] * 0.8
    kind, label, short = monthly_stage_from_ohlc(dates, pullback)
    assert kind == "side"
    assert label == MONTHLY_STAGE_SIDE
    assert short == "在整理"

    kind, label, short = monthly_stage_from_ohlc(["20260115"], [10])
    assert (kind, label, short) == ("", "", "")


@pytest.mark.production_db
def test_hot_names_monthly_stage_matches_chart_phase():
    """2383 月K還在往上、4915 已走空；不是買訊。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    eng = NavigatorEngine(get_db_path())
    up = eng.get_decision_card("2383", merge_live=False)
    assert up.get("monthly_stage_kind") == "up"
    assert up.get("monthly_stage") == "月K還在往上"
    down = eng.get_decision_card("4915", merge_live=False)
    assert down.get("monthly_stage_kind") == "down"
    assert down.get("monthly_stage") == "月K已走空"


@pytest.mark.production_db
def test_2383_4915_stance_note_matches_latest_row():
    """態度第二行對最新列顏色；月K只在徽章。"""
    from config import get_db_path
    from sell_discipline import attach_sell, sell_note_short
    from wayne_navigator import NavigatorEngine

    eng = NavigatorEngine(get_db_path())
    up = eng.get_decision_card("2383", merge_live=False)
    attach_sell(up)
    note = stance_explain(
        str(up.get("stance_kind") or "wait"),
        sell_note=sell_note_short(up),
        card=up,
    )
    assert "月K還在往上" in (up.get("badges") or [])
    assert "月K" not in note
    assert "往上" not in note
    assert "偏空" in note

    down = eng.get_decision_card("4915", merge_live=False)
    attach_sell(down)
    note = stance_explain(
        str(down.get("stance_kind") or "wait"),
        sell_note=sell_note_short(down),
        card=down,
    )
    last = down["table"].iloc[0]
    hi = str(last.get("高低") or "") in {"20高", "10高"} or str(last.get("預警") or "") == "K20高"
    if hi:
        assert "高" in note
        assert "長線低" not in note
    else:
        assert sell_note_short(down) == ""
        assert "先出一點" not in note
        assert "長線低" in note or "低附近" in note


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
        "badges": ["已除權還原", "60日量第 5 名", "120日第 14 名", "整理格局"],
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
    assert any(t == "整理格局" or t.startswith("整理格局") for t in seen)
    assert any("已除權還原" in t for t in seen)
    assert any("60日量第 5 名" in t for t in seen)
    assert not any("23:22" in t for t in seen)


def test_kotei_wait_label_matches_cary_months():
    from decision_card_signals import format_kotei_note, kotei_to_window_extreme, kotei_wait_label

    assert kotei_wait_label(5) == "再5個交易日"
    assert "約1個月" in kotei_wait_label(19)
    assert "約2個月" in kotei_wait_label(30)
    note = format_kotei_note(m20_low=19, m60_low=30)
    assert "月線還有19個交易日（約1個月）" in note
    assert "季線扣抵距低點還有30個交易日（約2個月）" in note
    assert "不是買訊" in note
    assert "還有再" not in format_kotei_note(m20_low=3, m60_low=29)
    assert "月線還有3個交易日" in format_kotei_note(m20_low=3, m60_low=29)
    far = format_kotei_note(m20_low=3, m60_low=29, gain_pct=26.6)
    assert "打底" not in far
    assert "均線把舊高低扣掉" in far
    near = format_kotei_note(m20_low=19, m60_low=30, gain_pct=2.0)
    assert "打底" in near
    hi = format_kotei_note(close=30, ma60=28, hl="20高", m60_high=5)
    assert "再5個交易日過高點" in hi
    assert "進場仍看表" in hi
    dates = [f"{20250101 + i}" for i in range(80)]
    closes = [10.0] * 80
    closes[-2] = 7.0
    got = kotei_to_window_extreme(dates, closes, 20, kind="low")
    assert got["ok"]
    assert got["remain"] == 19
    highs = [10.0] * 80
    highs[24] = 20.0
    got_h = kotei_to_window_extreme(dates, highs, 60, kind="high")
    assert got_h["ok"]
    assert got_h["remain"] == 5


@pytest.mark.production_db
def test_4739_kotei_matches_cary_sep10():
    """CaryBot 4739 2026-09-10：月線約一個月、季線約兩個月。"""
    from tests.conftest import require_production_db
    from wayne_navigator import NavigatorEngine

    db = require_production_db()
    card = NavigatorEngine(db).get_decision_card("4739", lookback=20, as_of="20260910")
    assert card.get("kotei_m20_low_days") == 19
    assert card.get("kotei_m60_low_days") == 30
    note = card.get("kotei_note") or ""
    assert "約1個月" in note
    assert "約2個月" in note
    assert "不是買訊" in note
    html = stance_explain(card.get("stance_kind") or "wait", card=card)
    assert "約2個月" in html
    assert "語料" not in html


@pytest.mark.production_db
def test_3630_kotei_five_days_to_high():
    """CaryBot 3630 2026-09-04：季線扣抵再過五天通過最高點。"""
    import sqlite3

    from decision_card_signals import kotei_to_window_extreme
    from tests.conftest import require_production_db

    db = require_production_db()
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT date, close, high FROM daily_quotes WHERE stock_id='3630' AND date<=? ORDER BY date",
        ("20260904",),
    ).fetchall()
    conn.close()
    dates = [r[0] for r in rows]
    highs = [r[2] for r in rows]
    got = kotei_to_window_extreme(dates, highs, 60, kind="high")
    assert got.get("ok")
    assert got["remain"] == 5
    assert str(got.get("extreme_date") or "").replace("-", "")[:8] == "20260617"
