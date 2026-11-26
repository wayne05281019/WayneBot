# -*- coding: utf-8 -*-
"""次級四浪分級：EPS／股性桶。"""
from __future__ import annotations

from focus_wave4_desk import (
    Wave4Row,
    _assign_bucket,
    _chip_label,
    apply_live_close,
    format_wave4_desk_html,
    format_wave4_hub_html,
    format_wave4_one_html,
    format_wave4_page_html,
    intervene_page,
)


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


def test_hub_two_paths():
    html = format_wave4_hub_html()
    assert "打代號" in html
    assert "實質十檔" in html
    assert "現價" in html
    assert "非買訊" in html


def test_guangsheng_horizon_sid_is_6442_not_1815():
    """資料正確性：光聖＝6442；1815是富喬，不准掛錯遠距。"""
    from focus_wave4_desk import QUALITY_HORIZON_ZH

    assert "6442" in QUALITY_HORIZON_ZH
    assert "光聖" in QUALITY_HORIZON_ZH["6442"]
    assert "1815" not in QUALITY_HORIZON_ZH


def test_intervene_page_ten_and_live_room():
    payload = {
        "asof": "20261126",
        "n_intervene": 12,
        "intervene": [
            {
                "stock_id": f"{i:04d}",
                "stock_name": f"n{i}",
                "room_to_w4_pct": 20.0,
                "wave4": 120.0,
                "wave3_low": 90.0,
                "close": 100.0,
                "eps_last": 1.0,
                "eps_profit": True,
                "taught_tags": ["PCB"],
                "above_w4_low": True,
                "bucket": "intervene",
                "why_zh": "舊收盤文案",
                "chip_label": "外資偏愛",
            }
            for i in range(12)
        ],
    }
    rows, pages, has_next = intervene_page(payload, 0)
    assert len(rows) == 10
    assert pages == 2
    assert has_next
    page_html = format_wave4_page_html(payload, rows, page=0, pages=2, live=True)
    assert "實質十檔" in page_html
    assert "現價" in page_html
    live = apply_live_close(rows[0], 110.0)
    assert live["live_px"] is True
    assert abs(live["room_to_w4_pct"] - (120 - 110) / 110 * 100) < 0.05
    one = format_wave4_one_html(live, live=True)
    assert "四浪高" in one and "非買訊" in one


def test_live_past_w4_refreshes_bucket_not_stale_intervene():
    """條件錯回歸：現價已過四浪高，不准還掛收盤時的值得介入舊文案。"""
    row = {
        "stock_id": "2383",
        "stock_name": "台光電",
        "market": "TW",
        "close": 3660.0,
        "wave4": 4565.0,
        "wave3_low": 3690.0,
        "room_to_w4_pct": 24.7,
        "above_w4_low": False,
        "bottom_near_year_ago_bars": 3,
        "score": 120,
        "eps_last": 15.0,
        "eps_profit": True,
        "taught_tags": ["PCB"],
        "chip_label": "外資偏愛",
        "bucket": "intervene",
        "why_zh": "舊收盤→實質＋鏈",
    }
    live = apply_live_close(row, 5000.0)
    assert live["room_to_w4_pct"] < 0
    assert live["above_w4_low"] is True
    assert live["bucket"] != "intervene"
    assert "已過四浪" in (live.get("why_zh") or "") or live["bucket"] == "watch"
    html = format_wave4_one_html(live, live=True)
    assert "已過／觸及次級四浪高" in html
    assert "值得介入" not in html.split("分級：")[-1].split("｜")[0]
