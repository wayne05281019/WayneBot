# -*- coding: utf-8 -*-
"""次級四浪分級：EPS／股性桶。"""
from __future__ import annotations

from focus_wave4_desk import Wave4Row, _assign_bucket, _chip_label, format_wave4_desk_html


def test_chip_label_foreign_dominant():
    assert _chip_label(5000, 100, -50, chip_asof="20261103").startswith("外資")


def test_chip_label_missing_not_fake_retail():
    assert _chip_label(0, 0, 0) == "籌碼未齊"


def test_assign_intervene_needs_eps_and_chain():
    row = Wave4Row(
        stock_id="2383",
        stock_name="台光電",
        market="TW",
        close=3660,
        room_to_w4_pct=24.7,
        bottom_near_year_ago_bars=3,
        score=120,
        eps_last=15.0,
        eps_profit=True,
        taught_tags=["PCB"],
        chip_label="外資偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "intervene"
    assert "實質" in why or "AI" in why


def test_quality_below_w4_low_still_intervene():
    """台光電型：未過四浪低也不排除。"""
    row = Wave4Row(
        stock_id="2383",
        stock_name="台光電",
        market="TW",
        close=3660,
        wave3_low=3690,
        wave4=4565,
        room_to_w4_pct=24.7,
        above_w4_low=False,
        bottom_near_year_ago_bars=3,
        score=120,
        eps_last=15.0,
        eps_profit=True,
        taught_tags=["PCB"],
        chip_label="外資偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "intervene"
    assert "不准排除" in why or "8000" in why


def test_passive_is_rebound_sprint():
    """被動元件＝搶反彈短衝，不當成長線值得介入。"""
    row = Wave4Row(
        stock_id="2327",
        stock_name="國巨",
        market="TW",
        close=800,
        room_to_w4_pct=30.0,
        above_w4_low=True,
        bottom_near_year_ago_bars=1,
        score=90,
        eps_last=14.0,
        eps_profit=True,
        taught_tags=["被動元件"],
        industry_chain="電子上游-被動元件",
        chip_label="外資偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "sprint"
    assert "搶反彈" in why


def test_assign_sprint_when_no_eps():
    row = Wave4Row(
        stock_id="9999",
        stock_name="dummy",
        market="TW",
        close=10,
        room_to_w4_pct=30,
        bottom_near_year_ago_bars=0,
        score=80,
        eps_last=-1.0,
        eps_profit=False,
        taught_tags=[],
        chip_label="偏散戶／雜訊",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "sprint"
    assert "短衝" in why


def test_format_html_has_buckets():
    html = format_wave4_desk_html(
        {
            "ok": True,
            "asof": "20261126",
            "n_hits": 2,
            "n_intervene": 1,
            "n_sprint": 1,
            "n_watch": 0,
            "intervene": [
                {
                    "stock_id": "2383",
                    "stock_name": "台光電",
                    "room_to_w4_pct": 24.7,
                    "chip_label": "外資偏愛",
                    "eps_last": 15.0,
                    "taught_tags": ["PCB"],
                }
            ],
            "sprint": [
                {
                    "stock_id": "1111",
                    "stock_name": "dummy",
                    "room_to_w4_pct": 40.0,
                    "chip_label": "偏散戶／雜訊",
                    "eps_last": None,
                    "taught_tags": [],
                }
            ],
        }
    )
    assert "次級四浪" in html
    assert "值得介入" in html
    assert "短衝" in html
    assert "非買訊" in html
    assert "四浪高" in html
    assert "搶反彈" in html or "被動元件" in html
