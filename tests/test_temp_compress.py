from wayne_navigator import (
    _price_at_window_high,
    _price_at_window_low,
    compute_temp_trend_labels,
    temp_cell_style,
    temp_trend_cell_style,
    temp_trend_note_cell_style,
    _CARD,
)
from decision_card_signals import TEMP_ATH_WATCH


def test_price_at_window_low():
    closes = [3700, 3790, 3765, 3735]
    assert _price_at_window_low(0, closes, 0)
    assert not _price_at_window_low(3, closes, 0)


def test_price_at_window_high():
    closes = [660, 700, 640, 7810]
    assert not _price_at_window_high(2, closes, 0)
    assert _price_at_window_high(3, closes, 0)


def test_temp_compress_mediatek_like_pattern():
    """溫度連創窗內低、股價橫盤略彈 → 最低溫＋價未新低（對齊 Cary 主標）。"""
    temps = [25.2, 24.5, 23.0, 23.0, 22.9, 23.5]
    closes = [3700, 3790, 3765, 3765, 3735, 3925]
    labels, notes = compute_temp_trend_labels(temps, closes=closes, window=6)
    assert labels[4] == "最低溫"
    assert notes[4] == "價未新低"
    assert labels[1] in ("最低溫", "降溫")


def test_price_temp_divergence_largan_like():
    """大立光 9/2 型：價創窗內高、溫度已從最高溫回頭 → 降溫＋價溫背離。"""
    temps = [80.1, 85.0, 92.2, 90.4]
    closes = [7200, 7500, 7700, 7810]
    labels, notes = compute_temp_trend_labels(temps, closes=closes, window=4)
    assert labels[-1] == "降溫"
    assert notes[-1] == "價溫背離"
    assert labels[-2] == "最高溫"
    nbg, nfg = temp_trend_note_cell_style("價溫背離", _CARD["white"])
    assert nbg == _CARD["temp_hot_bg"]
    assert nfg == _CARD["temp_hot_fg"]


def test_temp_cell_style_marks_80_watch():
    assert TEMP_ATH_WATCH == 80.0
    bg, fg = temp_cell_style(80.0, _CARD["white"])
    assert bg == _CARD["pill_hi"]
    assert fg == _CARD["white"]
    cool_bg, _ = temp_cell_style(49.2, _CARD["white"])
    assert cool_bg != _CARD["pill_hi"]
    mint_bg, mint_fg = temp_cell_style(36.0, _CARD["white"])
    assert mint_bg == _CARD["lo_fill"]
    assert mint_fg == _CARD["lo_ink"]
    assert mint_bg != _CARD["temp_hot_bg"]


def test_temp_compress_styles_high_contrast():
    bg, fg = temp_trend_cell_style("溫度壓縮", _CARD["white"])
    nbg, nfg = temp_trend_note_cell_style("價未新低", _CARD["white"])
    assert bg == _CARD["temp_compress_bg"]
    assert fg == _CARD["temp_compress_fg"]
    assert nbg == _CARD["price_not_low_bg"]
    assert nfg == _CARD["price_not_low_fg"]
