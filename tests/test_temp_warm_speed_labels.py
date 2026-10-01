# -*- coding: utf-8 -*-
"""升降欄：升溫急／升溫快（日對日 °C），顯示用、不是買訊。"""
from wayne_navigator import (
    TEMP_WARM_EPS,
    TEMP_WARM_FAST_DELTA,
    TEMP_WARM_SHARP_DELTA,
    _CARD,
    compute_temp_trend_labels,
    temp_trend_cell_style,
)


def test_temp_warm_thresholds_locked():
    assert TEMP_WARM_EPS == 0.25
    assert TEMP_WARM_FAST_DELTA == 5.0
    assert TEMP_WARM_SHARP_DELTA == 12.0


def test_warm_sharp_priority_below_window_peak():
    """創窗內最高溫時仍寫最高溫，不改叫升溫急（即使 Δ 很大）。"""
    temps = [10.0, 40.0]
    labels, notes = compute_temp_trend_labels(temps, window=2)
    assert labels[1] == "最高溫"
    assert notes[1] == ""


def test_warm_fast_when_not_window_peak():
    # 先衝高再回、再中幅／急升 → 未再創窗內最高，走升溫快／急
    temps = [40.0, 80.0, 55.0, 61.0, 74.0]
    labels, _notes = compute_temp_trend_labels(temps, window=5)
    assert labels[1] == "最高溫"
    assert labels[2] == "降溫急"  # 80→55 = -25
    assert labels[3] == "升溫快"  # 55→61 = +6
    assert labels[4] == "升溫急"  # 61→74 = +13，仍低於窗內 80


def test_warm_plain_below_fast_not_at_peak():
    temps = [40.0, 60.0, 50.0, 52.0]
    labels, _ = compute_temp_trend_labels(temps, window=4)
    assert labels[1] == "最高溫"
    assert labels[2] == "降溫快"  # -10
    assert labels[3] == "升溫"  # +2


def test_temp_trend_styles_for_speed_labels():
    sharp_bg, sharp_fg = temp_trend_cell_style("升溫急", _CARD["white"])
    fast_bg, _ = temp_trend_cell_style("升溫快", _CARD["white"])
    warm_bg, _ = temp_trend_cell_style("升溫", _CARD["white"])
    cool_sharp_bg, _ = temp_trend_cell_style("降溫急", _CARD["white"])
    assert sharp_bg == "#EC407A"
    assert sharp_fg == _CARD["white"]
    assert fast_bg == "#F48FB1"
    assert warm_bg == "#F8BBD0"
    assert cool_sharp_bg == "#2E7D32"
    assert sharp_bg != warm_bg != fast_bg


def test_temp_trend_heat_bucket_maps_speed_labels():
    """態度／大量區 caption：急／快與普通同一桶；不准當買訊。"""
    from wayne_navigator import temp_trend_heat_bucket
    from sell_discipline import attach_sell, card_discipline_face
    from vol_zone_chart import _heat_key

    assert temp_trend_heat_bucket("升溫急") == "up"
    assert temp_trend_heat_bucket("升溫快") == "up"
    assert temp_trend_heat_bucket("升溫") == "up"
    assert temp_trend_heat_bucket("降溫急") == "down"
    assert temp_trend_heat_bucket("降溫快") == "down"
    assert temp_trend_heat_bucket("降溫") == "down"
    assert temp_trend_heat_bucket("最高溫") == "peak"
    assert temp_trend_heat_bucket("最低溫") == "floor"
    assert temp_trend_heat_bucket("No") == "flat"
    assert temp_trend_heat_bucket("升溫", note="價溫背離") == "diverge"

    for lab, expect in (
        ("升溫急", "up"),
        ("升溫快", "up"),
        ("降溫急", "down"),
        ("降溫快", "down"),
    ):
        card = {
            "table": [
                {
                    "高低": "No",
                    "預警": "No",
                    "升降": lab,
                    "升降註": "",
                    "profit_pct": 12.0,
                    "temp_num": 40.0,
                }
            ],
            "gain_pct": 12.0,
        }
        attach_sell(card)
        assert card_discipline_face(card)["heat"] == expect
        assert _heat_key(card) == expect
