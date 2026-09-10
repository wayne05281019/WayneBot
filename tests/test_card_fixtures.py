# -*- coding: utf-8 -*-
"""依使用者傳過的高低卡範本列（OCR 校準）— 海選驗收用。"""
import pytest

from decision_card_signals import (
    alert_tag,
    card_regime_label,
    card_row_leave_zero,
    compute_card_temperature,
    leave_zero_screen_ok,
    parse_profit_display,
    profit_left_zero_highlight,
    profit_pct_series,
)


def test_parse_profit_display():
    assert parse_profit_display("0.0%") == 0.0
    assert parse_profit_display("10.0%") == 10.0
    assert parse_profit_display("No") is None


def test_template_2420_8_28_not_leave_zero():
    """範本卡：獲利已 10.0% — 不是起漲（你回饋的誤收型）。"""
    ok, _ = leave_zero_screen_ok(9.5, 10.0)
    assert not ok


def test_template_profit_green_cell():
    """色票範本：0.9% 實綠；0.3% 即使前一天不是 0 也綠（作者致伸 9/3）。"""
    assert profit_left_zero_highlight(0.0, 0.9)
    hit, tag = card_row_leave_zero(0.0, 0.9)
    assert hit and "實綠" in tag
    ok, _ = leave_zero_screen_ok(0.0, 0.9)
    assert ok
    from wayne_navigator import _CARD, profit_cell_style

    assert profit_cell_style(0.3, 1.5, _CARD["white"])[0] == _CARD["lo_hit_fill"]


def test_template_not_green_after_step():
    """色票範本：昨 0.9% → 今 1.5% 白底，不算剛離零。"""
    assert not profit_left_zero_highlight(0.9, 1.5)
    hit, _ = card_row_leave_zero(0.9, 1.5)
    assert not hit


@pytest.mark.production_db
def test_profit_pct_series_per_day_not_global():
    """9925 範本：盤整期應出現多個 0.0% 列（逐日 cal60 + 未回推收盤）。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    tbl = NavigatorEngine(get_db_path()).get_decision_card("9925", lookback=40)["table"]
    zeros = sum(1 for _, r in tbl.iterrows() if float(r["profit_pct"]) <= 0.05)
    assert zeros >= 6, f"expected many 0.0% rows, got {zeros}"


@pytest.mark.production_db
def test_template_2530_leave_zero_row():
    """華建範本：8/31 獲利 0.0% → 起漲故事起點。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(get_db_path()).get_decision_card("2530", lookback=40)
    tbl = card["table"]
    row = tbl[tbl["date"].astype(str) == "20260831"]
    assert not row.empty
    assert float(row.iloc[0]["profit_pct"]) <= 0.05


@pytest.mark.production_db
def test_template_2633_8_11_profit_is_cal60_not_l20_floor():
    """高鐵 8/11：貼 20 日低仍用 60 曆日低算獲利（≈1.0%），不再強制 0.0%。"""
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    tbl = NavigatorEngine(get_db_path()).get_decision_card("2633", lookback=40)["table"]
    row = tbl[tbl["date"].astype(str) == "20260811"]
    assert not row.empty
    assert abs(float(row.iloc[0]["profit_pct"]) - 1.0) < 0.15


@pytest.mark.production_db
def test_2383_near_l20_profit_matches_cal60_carybot():
    """台光電獲利＝相對 60 曆日低 4100，貼 20 日低不歸零。

    盤中 5295 → 29.1% 是公式驗收（``format_profit_pct``）；16:30 後列上是官方收盤，
    不得再要求 MIS 5295 蓋掉今天。
    """
    from unittest.mock import patch

    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    rt = {
        "stock_id": "2383",
        "stock_name": "台光電",
        "open": 5390.0,
        "high": 5515.0,
        "low": 5255.0,
        "close": 5295.0,
        "volume": 1129,
        "pct_change": 0.09,
        "yesterday_close": 5290.0,
        "update_time": "11:46:00",
    }
    with patch("live_quote.fetch_lookup_quote", return_value=rt), patch(
        "live_quote.fetch_mis_quote", return_value=rt
    ), patch("live_quote.is_live_merge_window", return_value=True):
        card = NavigatorEngine(get_db_path()).get_decision_card("2383", merge_live=True)
    assert float(card["cal60_low"]) == 4100.0
    close = float(card["close"])
    expected = round((close / 4100.0 - 1) * 100.0, 1)
    assert abs(float(card["gain_pct"]) - expected) < 0.2
    assert float(card["gain_pct"]) > 20.0
    tbl = card["table"]
    assert float(tbl.iloc[0]["profit_pct"]) > 20.0


@pytest.mark.production_db
def test_profit_floor_max_cal60_and_l20():
    """profit_floor_at 仍取 max(cal60, l20)；僅內部用，不再驅動決策卡獲利欄。"""
    import sqlite3

    import pandas as pd
    from config import get_db_path
    from decision_card_signals import profit_floor_at

    db = get_db_path()
    conn = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT date, close FROM daily_quotes WHERE stock_id='2633' ORDER BY date", conn
    )
    conn.close()
    idx = df.index[df["date"].astype(str) == "20260811"][0]
    floor = profit_floor_at(df, idx)
    assert floor == 25.7


def test_alert_tag_rsv_no_false_k20_high_on_bias_only():
    """南亞型：月乖離高但 RSV 未過熱 → 不標 K20高。"""
    assert alert_tag(100.0, low60=90, high20=102, low20=95, bias_monthly=4.5, rsv=55.0) == "No"
    assert alert_tag(101.5, low60=90, high20=102, low20=95, bias_monthly=2.0, rsv=72.0) == "K20高"


def test_alert_tag_k20_high_near_95pct_winbond_like():
    """3105 9/2 型：收在 20 日高 95% 以上、RSV≥70 → K20高。"""
    assert alert_tag(469.5, low60=268, high20=492, low20=355, bias_monthly=16.6, rsv=83.6) == "K20高"
    assert alert_tag(440.0, low60=268, high20=492, low20=355, bias_monthly=9.0, rsv=62.0) == "No"


def test_display_alert_shows_hi_lo_when_blank():
    from decision_card_signals import display_alert_cell

    assert display_alert_cell("No", "10低") == "10低"
    assert display_alert_cell("K20高", "20高") == "20高"
    assert display_alert_cell("K20高", "No") == "K20高"
    assert display_alert_cell("60低", "10低") == "60低"
    assert display_alert_cell("No", "No") == "No"
    assert display_alert_cell("", "No") == "No"


def test_candle_up_taiwan_vs_prev_close():
    from decision_card_signals import candle_up_taiwan

    # 8/19 型：收>開但跌破昨收 → 綠
    assert not candle_up_taiwan(363.5, prev_close=374.5, open_=353.5)
    # 9/3 穩懋：開收皆跌 → 綠
    assert not candle_up_taiwan(446.5, prev_close=469.5, open_=478.0)
    # 平盤紅
    assert candle_up_taiwan(100.0, prev_close=100.0, open_=99.0)


def test_template_regime_narrow_range_is_consolidation():
    """2633/2530 範本：60日區間過小時標整理格局，不是多頭。"""
    assert card_regime_label(26.25, 26.0, 25.8, space_60=7) == "整理格局"
    assert card_regime_label(19.75, 19.4, 19.0, space_60=14) == "整理格局"


def test_template_temperature_cold_stock_scale():
    """9925 範本：冷股溫度應在個位數～十幾度，不是 50°C+。"""
    t = compute_card_temperature(39.3, 40.15, 39.3, -0.2, high60=41.5, low60=39.3)
    assert t < 15.0
    t_hot = compute_card_temperature(40.05, 40.15, 39.3, 0.5, high60=41.5, low60=39.3)
    assert t_hot < 20.0


def test_dumped_chop_below_ma60_uses_narrow_temp_scale():
    """中石化 8 月型：跌破季線、60 日下半盤整，不能沿用舊高寬尺到 40°C+。"""
    old = compute_card_temperature(7.82, 8.27, 7.37, 0.8, high60=10.4, low60=6.9)
    new = compute_card_temperature(
        7.82, 8.27, 7.37, 0.8, high60=10.4, low60=6.9, ma60=8.09
    )
    assert old >= 35.0
    assert new < 12.0
    assert new < old


def test_twenty_high_at_sixty_low_does_not_compress():
    """致伸 9/4 型：60 日低附近但已貼 20 高，仍走熱尺。"""
    t = compute_card_temperature(
        60.8, 60.9, 59.4, 1.1, high60=77.5, low60=59.4, ma60=65.55
    )
    assert t >= 60.0


def test_twenty_low_leave_zero_does_not_compress_to_zero():
    """華建 8/31 型：貼 20 低、獲利 0，窄尺本來就個位數，不要再壓成 0。"""
    t = compute_card_temperature(
        18.8, 19.9, 18.8, -3.0, high60=21.1, low60=18.45, ma60=19.55
    )
    assert 5.0 <= t <= 10.0


def test_below_ma60_not_twenty_high_compresses_even_if_p20_mid():
    """長榮 7/30 型：收在季線下、還沒貼 20 高，VAM 3.5，不能沿用 60 日舊高到 50°C+。"""
    hot = compute_card_temperature(201.0, 206.0, 185.5, 1.5, high60=237.0, low60=181.0)
    cold = compute_card_temperature(
        201.0, 206.0, 185.5, 1.5, high60=237.0, low60=181.0, ma60=205.86
    )
    assert hot >= 50.0
    assert cold < 16.0


def test_twenty_high_narrow_sixty_not_stuck_at_thirty():
    """萬海 8/13 型：已貼 20 高、60 日空間約 14%，VAM 56.8，不要卡在 30°C。"""
    t = compute_card_temperature(
        87.5, 87.5, 79.5, 3.0, high60=87.5, low60=76.7, ma60=82.55
    )
    assert 45.0 <= t <= 58.0
