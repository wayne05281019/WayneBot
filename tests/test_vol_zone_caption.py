# -*- coding: utf-8 -*-
"""第三張大量區圖說：位置句只陳述，不改如何賣。"""
from __future__ import annotations

from vol_zone_chart import (
    VOL_ZONE_CAPTION_HEAD,
    vol_zone_photo_caption,
    vol_zone_position_line,
)

_NO_HOLD_SELL = ("持有", "出售", "減碼", "先出", "不急", "該買", "該賣", "抱著", "持續")


def _card_heat(trend: str) -> dict:
    return {"table": [{"date": "20260924", "升降": trend}]}


def test_in_band_test_press_volume_thin_heat_up():
    zone = {"high": 210, "low": 195.5, "volume": 30000}
    last = {"high": 210, "low": 199.5, "close": 206.5, "volume": 8000}
    line = vol_zone_position_line(zone, last, _card_heat("升溫"))
    assert "現價在帶內" in line
    assert "測壓未過" in line
    assert "量縮對爆大量日" in line
    assert "溫度升" in line
    for w in _NO_HOLD_SELL:
        assert w not in line


def test_close_above_press_volume_real():
    zone = {"high": 210, "low": 195.5, "volume": 10000}
    last = {"high": 216, "low": 208, "close": 214, "volume": 9000}
    line = vol_zone_position_line(zone, last, _card_heat("最高溫"))
    assert line.startswith("收過壓")
    assert "量對爆大量日仍真" in line
    assert "溫度最高溫" in line
    assert "測壓未過" not in line
    assert "跌破撐" not in line


def test_broke_support_no_heat():
    zone = {"high": 210, "low": 195.5, "volume": 10000}
    last = {"high": 194, "low": 188, "close": 190, "volume": 4000}
    line = vol_zone_position_line(zone, last, None)
    assert "跌破撐" in line
    assert "現價在帶內" not in line
    assert "溫度" not in line


def test_photo_caption_keeps_head_and_drops_sell_words():
    cap = vol_zone_photo_caption(
        zone={"high": 210, "low": 195.5, "volume": 30000},
        last={"high": 207.5, "low": 199.5, "close": 206.5, "volume": 8000},
        card=_card_heat("升溫"),
    )
    assert cap.startswith(VOL_ZONE_CAPTION_HEAD)
    assert "現價在帶內" in cap
    assert "非買訊" in cap
    for w in _NO_HOLD_SELL:
        assert w not in cap.split("\n", 1)[-1]


def test_lookup_sell_caption_unchanged_on_card():
    from bot_servers import _decision_card_photo_caption, _glance_photo_caption

    card = {
        "stock_id": "3035",
        "stock_name": "智原",
        "sell_action": "直接減碼",
        "sell_why": "不同步（最高價但非最高溫）",
        "table": [{"date": "20260924", "高低": "20高", "升降": "升溫", "預警": ""}],
    }
    glance = _glance_photo_caption("當日K＋籌碼價量", card)
    decision = _decision_card_photo_caption(card, "3035")
    assert "Ai建議" in glance or "Ai建議" in decision
    vz = vol_zone_photo_caption(
        zone={"high": 210, "low": 195.5, "volume": 30000},
        last={"high": 207.5, "close": 206.5, "volume": 8000},
        card=card,
    )
    assert "Ai建議" not in vz
    assert "如何賣" not in vz
