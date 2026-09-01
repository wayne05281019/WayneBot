from wayne_navigator import (
    _price_at_window_low,
    compute_temp_trend_labels,
    temp_trend_cell_style,
    temp_trend_note_cell_style,
    _CARD,
)


def test_price_at_window_low():
    closes = [3700, 3790, 3765, 3735]
    assert _price_at_window_low(0, closes, 0)
    assert not _price_at_window_low(3, closes, 0)


def test_temp_compress_mediatek_like_pattern():
    """溫度連創窗內低、股價橫盤略彈 → 溫度壓縮＋價未新低（2454 8/20~8/25 型）。"""
    temps = [25.2, 24.5, 23.0, 23.0, 22.9, 23.5]
    closes = [3700, 3790, 3765, 3765, 3735, 3925]
    labels, notes = compute_temp_trend_labels(temps, closes=closes, window=6)
    assert labels[4] == "溫度壓縮"
    assert notes[4] == "價未新低"
    assert labels[1] in ("最低溫", "降溫", "溫度壓縮")


def test_temp_compress_styles_high_contrast():
    bg, fg = temp_trend_cell_style("溫度壓縮", _CARD["white"])
    nbg, nfg = temp_trend_note_cell_style("價未新低", _CARD["white"])
    assert bg == _CARD["temp_compress_bg"]
    assert fg == _CARD["temp_compress_fg"]
    assert nbg == _CARD["price_not_low_bg"]
    assert nfg == _CARD["price_not_low_fg"]
