# -*- coding: utf-8 -*-
"""介紹圖／高低卡先官方除息除權，不准等人自己看缺口。"""
from __future__ import annotations

import os

import pytest

from ex_rights import ensure_ex_rights_table, recent_ex_face, upsert_events, upsert_heuristic_event


def test_recent_ex_face_official_div_note(tmp_path):
    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "2542",
                "ex_date": "20260923",
                "kind": "息",
                "close_before": 45.45,
                "ref_price": 41.45,
                "right_plus_div": 4.0,
                "factor": 41.45 / 45.45,
                "source": "TWT49U",
            }
        ],
    )
    bars = [
        {"date": "20260922", "open": 46.8, "high": 46.8, "low": 45.4, "close": 45.45},
        {"date": "20260923", "open": 40.0, "high": 40.45, "low": 39.0, "close": 39.55},
        {"date": "20260924", "open": 38.9, "high": 39.5, "low": 38.8, "close": 39.5},
    ]
    face = recent_ex_face("2542", db, "20260924", bars)
    assert "09/23除息4元" in face["note"]
    assert "息差不是崩" in face["note"]
    assert "原柱" not in face["note"]
    assert "測壓" not in face["note"]
    assert face["label"] == "09/23除息4元"


def test_title_and_captions_use_ex_gap():
    from bot_servers import _decision_card_photo_caption, _glance_photo_caption
    from wayne_navigator import _title_event_text

    card = {
        "stock_id": "2542",
        "stock_name": "興富發",
        "ex_gap_note": "09/23除息4元（前收45.45、參考價41.45）。缺口是息差不是崩。",
        "ex_gap_label": "09/23除息4元",
        "next_event": "3天後法說",
        "sell_action": "",
    }
    assert _title_event_text(card) == "09/23除息4元"
    glance = _glance_photo_caption("當日K＋籌碼價量", card)
    assert glance.startswith("09/23除息4元")
    assert "當日K＋籌碼價量" in glance
    decision = _decision_card_photo_caption(card, "2542")
    assert "09/23除息4元" in decision
    assert "興富發" in decision


def test_heuristic_still_cannot_cover_official(tmp_path):
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "2542",
                "ex_date": "20260923",
                "kind": "息",
                "right_plus_div": 4.0,
                "close_before": 45.45,
                "ref_price": 41.45,
                "factor": 0.91,
                "source": "TWT49U",
            }
        ],
    )
    upsert_heuristic_event(db, "2542", "20260923", 0.87, kind="減資")
    bars = [
        {"date": "20260922", "open": 46.8, "close": 45.45},
        {"date": "20260923", "open": 40.0, "close": 39.55},
        {"date": "20260924", "open": 38.9, "close": 39.5},
    ]
    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    face = recent_ex_face("2542", db, "20260924", bars)
    assert "除息" in face["label"]
    assert "減資" not in face["label"]


@pytest.mark.production_db
def test_2542_zone_matches_twse_ex_div_bar():
    """大量區壓撐＝除息日官方高低，不准漂。"""
    import pytest

    from tests.conftest import require_production_db
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work

    db = require_production_db()
    work = official_work(load_official_ohlc("2542", db, 80))
    if work is None or len(work) < 5:
        pytest.skip("no 2542 bars")
    last = str(work["date"].iloc[-1])
    if last < "20260924":
        pytest.skip("need 9/24 close")
    ev = {
        "ex_date": "20260923",
        "kind": "息",
        "close_before": 45.45,
        "ref_price": 41.45,
        "right_plus_div": 4.0,
        "source": "TWT49U",
    }
    zone = find_volume_zone(work, ex_events=[ev])
    assert zone["date"] == "20260923"
    assert float(zone["high"]) == 40.45
    assert float(zone["low"]) == 39.0
    row = work.loc[work["date"] == "20260924"].iloc[-1]
    assert float(row["open"]) == 38.9
    assert float(row["high"]) == 39.5
    assert float(row["low"]) == 38.8
    assert float(row["close"]) == 39.5


@pytest.mark.production_db
def test_2542_card_does_not_call_ex_div_a_breakdown():
    import os

    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    from tests.conftest import require_production_db
    from wayne_navigator import NavigatorEngine

    db = require_production_db()
    card = NavigatorEngine(db).get_decision_card("2542", merge_live=False)
    assert card.get("ex_gap_label") == "09/23除息4元"
    assert "弱勢破底" not in (card.get("badges") or [])
    assert "已除權還原" not in (card.get("badges") or [])
    assert "已除息還原" in (card.get("badges") or [])
    assert "原柱" not in (card.get("ex_gap_note") or "")


def test_old_ex_div_not_pasted_on_later_week(tmp_path):
    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "2330",
                "ex_date": "20260916",
                "kind": "息",
                "right_plus_div": 7.0,
                "close_before": 2385,
                "ref_price": 2378,
                "factor": 0.997,
                "source": "TWT49U",
            }
        ],
    )
    bars = [
        {"date": "20260916", "open": 2375, "close": 2380},
        {"date": "20260917", "open": 2405, "close": 2425},
        {"date": "20260921", "open": 2445, "close": 2480},
        {"date": "20260922", "open": 2505, "close": 2460},
        {"date": "20260923", "open": 2475, "close": 2500},
        {"date": "20260924", "open": 2480, "close": 2475},
    ]
    face = recent_ex_face("2330", db, "20260924", bars)
    assert face["label"] == ""
    assert "除息" not in (face["note"] or "")


def test_latest_scale_ex_picks_newest_date_not_list_order():
    from ex_rights import latest_scale_ex

    events = [
        {
            "ex_date": "20260923",
            "kind": "息",
            "source": "TWT49U",
            "right_plus_div": 4.0,
        },
        {
            "ex_date": "20260424",
            "kind": "分割",
            "source": "heuristic_gap",
        },
    ]
    ev = latest_scale_ex(events, "20260924")
    assert ev["ex_date"] == "20260923"
    assert ev["kind"] == "息"
    mixed = list(events) + [
        {
            "ex_date": "20260923",
            "kind": "減資",
            "source": "heuristic_gap",
        }
    ]
    ev2 = latest_scale_ex(mixed, "20260924")
    assert ev2["kind"] == "息"
    assert ev2["source"] == "TWT49U"


def test_gap_up_without_ex_is_not_crash_copy(tmp_path):
    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    bars = [
        {"date": "20260917", "open": 179, "high": 180, "low": 178, "close": 179},
        {"date": "20260921", "open": 194.5, "high": 196, "low": 190, "close": 193},
        {"date": "20260922", "open": 192, "high": 193, "low": 190, "close": 191},
        {"date": "20260923", "open": 190, "high": 191, "low": 188, "close": 189},
        {"date": "20260924", "open": 188, "high": 189, "low": 186, "close": 187},
    ]
    face = recent_ex_face("3035", db, "20260924", bars)
    assert face["label"] == ""
    assert "不當崩" not in (face["note"] or "")
    assert "跳空超過五％" not in (face["note"] or "")


def test_regime_skips_breakdown_inside_ex_bar():
    from screening_engine import _regime_label

    item = {
        "close": 39.55,
        "ma20": 44.0,
        "ma60": 46.0,
        "low20": 43.0,
        "d20": -8.0,
        "ex_close_inside": True,
    }
    assert _regime_label(item) != "弱勢破底"
    assert _regime_label(item) != "貼近20日低"
    assert _regime_label({**item, "ex_close_inside": False}) == "弱勢破底"
