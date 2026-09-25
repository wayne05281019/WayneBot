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


def test_hydrate_http_timeout_is_short():
    import inspect

    from ex_rights import _HYDRATE_HTTP_TIMEOUT, hydrate_official_ex_for_gaps, recent_ex_face

    assert _HYDRATE_HTTP_TIMEOUT <= 5.0
    src = inspect.getsource(hydrate_official_ex_for_gaps)
    assert "timeout=tout" in src
    assert "tpex" in src
    face_src = inspect.getsource(recent_ex_face)
    assert "rows[-5:]" in face_src
    assert "official_scale_events" in face_src


def test_heuristic_split_never_written_on_face(tmp_path):
    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_heuristic_event(db, "2383", "20260803", 1.15, kind="分割")
    bars = [
        {"date": "20260730", "open": 4005, "high": 4510, "low": 3930, "close": 4315},
        {"date": "20260803", "open": 5135, "high": 5195, "low": 4930, "close": 4980},
        {"date": "20260804", "open": 4995, "high": 5210, "low": 4875, "close": 5140},
        {"date": "20260805", "open": 5425, "high": 5425, "low": 5165, "close": 5245},
        {"date": "20260806", "open": 5200, "high": 5380, "low": 5105, "close": 5305},
    ]
    face = recent_ex_face("2383", db, "20260806", bars)
    assert "分割" not in (face["label"] or "")
    assert "分割" not in (face["note"] or "")


def test_official_div_date_and_amount_chi_hua_and_el(tmp_path):
    """奇鋐／台光電除息只認 TWT49U：日期＋權值+息值。"""
    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "3017",
                "ex_date": "20260819",
                "kind": "息",
                "close_before": 3035.0,
                "ref_price": 3014.11,
                "right_plus_div": 20.881604,
                "factor": 0.9931169686985173,
                "source": "TWT49U",
            },
            {
                "stock_id": "2383",
                "ex_date": "20260828",
                "kind": "息",
                "close_before": 5500.0,
                "ref_price": 5475.0,
                "right_plus_div": 25.0,
                "factor": 0.9954545454545455,
                "source": "TWT49U",
            },
        ],
    )
    chi = recent_ex_face(
        "3017",
        db,
        "20260819",
        [
            {"date": "20260818", "open": 3150, "close": 3035},
            {"date": "20260819", "open": 2915, "high": 3160, "low": 2900, "close": 3095},
        ],
    )
    assert chi["label"] == "08/19除息20.88元"
    assert "08/19除息20.88元" in chi["note"]
    assert "前收3,035" in chi["note"]
    assert "參考價3,014" in chi["note"]
    el = recent_ex_face(
        "2383",
        db,
        "20260828",
        [
            {"date": "20260827", "open": 5960, "close": 5500},
            {"date": "20260828", "open": 5480, "high": 5620, "low": 5425, "close": 5490},
        ],
    )
    assert el["label"] == "08/28除息25元"
    assert "分割" not in el["label"]
    assert "分割" not in el["note"]


def test_twt49u_kind_is_right_or_div_never_split():
    from ex_rights import _event_verb, _kind, parse_twse_row, scale_ex_verb

    fields = [
        "股票代號", "股票名稱", "資料日期", "權/息",
        "除權息前收盤價", "除權息參考價", "權值+息值",
    ]
    for raw, want_kind, want_verb in (("息", "息", "除息"), ("權", "權", "除權"), ("權息", "權息", "除權息")):
        row = ["3017", "奇鋐", "115年08月19日", raw, "3035", "3014.11", "20.881604"]
        item = parse_twse_row(fields, row)
        assert item["kind"] == want_kind
        assert item["source"] == "TWT49U"
        assert scale_ex_verb(item["kind"]) == want_verb
        assert "分割" not in scale_ex_verb(item["kind"])
    assert _kind("息") == "息"
    assert _kind("權") == "權"
    assert _event_verb("息") == "除息"
    assert _event_verb("權") == "除權"


def test_nearest_event_skips_heuristic_split(tmp_path):
    from ex_rights import nearest_event_label

    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_heuristic_event(db, "2383", "20260803", 1.15, kind="分割")
    upsert_events(
        db,
        [
            {
                "stock_id": "2383",
                "ex_date": "20260828",
                "kind": "息",
                "right_plus_div": 25.0,
                "source": "TWT49U",
            }
        ],
    )
    lab = nearest_event_label("2383", db, today="20260801")
    assert "分割" not in lab
    assert "除息" in lab
    only_h = nearest_event_label("2383", db, today="20260901")
    assert "分割" not in (only_h or "")


def test_phone_ex_verb_never_invents_split_or_cut():
    from ex_rights import _event_verb, _kind, format_next_event_label, phone_ex_verb

    assert _kind("分割") == ""
    assert _kind("減資") == ""
    assert _kind("") == ""
    assert _event_verb("分割") == ""
    assert _event_verb("減資") == ""
    assert _event_verb("啟發式") == ""
    assert phone_ex_verb("分割") == ""
    assert phone_ex_verb("減資") == ""
    assert phone_ex_verb("啟發式") == ""
    assert phone_ex_verb("息") == "除息"
    assert phone_ex_verb("權") == "除權"
    assert phone_ex_verb("權息") == "除權息"
    assert format_next_event_label("分割", "20260925", "20260924") == ""
    assert format_next_event_label("減資", "20260925", "20260924") == ""
    assert format_next_event_label("啟發式", "20260925", "20260924") == ""


def test_tpex_row_kind_is_right_or_div_never_split():
    from ex_rights import parse_tpex_row, phone_ex_verb, scale_ex_verb

    fields = [
        "代號", "名稱", "除權息日期", "權/息",
        "除權息前收盤價", "除權息參考價", "權值+息值",
    ]
    row = ["6488", "環球晶", "115年08月05日", "息", "500", "495", "5"]
    item = parse_tpex_row(fields, row)
    assert item["stock_id"] == "6488"
    assert item["market"] == "TWO"
    assert item["source"] == "tpex_exDailyQ"
    assert item["kind"] == "息"
    assert scale_ex_verb(item["kind"]) == "除息"
    assert phone_ex_verb(item["kind"]) == "除息"


def test_empty_source_ex_rights_never_shown(tmp_path):
    from ex_rights import nearest_event_label

    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "1101",
                "ex_date": "20260930",
                "kind": "息",
                "source": "",
            }
        ],
    )
    assert nearest_event_label("1101", db, today="20260924") == ""


def test_listed_otc_emerging_heuristic_never_on_face(tmp_path):
    """上市／上櫃／興櫃：啟發式分割不准上圖上字。"""
    os.environ["WAYNE_SKIP_EX_FETCH"] = "1"
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    bars = [
        {"date": "20260730", "open": 100, "high": 110, "low": 95, "close": 108},
        {"date": "20260803", "open": 160, "high": 165, "low": 150, "close": 158},
        {"date": "20260804", "open": 157, "high": 162, "low": 150, "close": 160},
        {"date": "20260805", "open": 161, "high": 163, "low": 155, "close": 156},
        {"date": "20260806", "open": 155, "high": 158, "low": 150, "close": 152},
    ]
    for sid in ("2330", "6488", "1260"):
        upsert_events(
            db,
            [
                {
                    "stock_id": sid,
                    "ex_date": "20260803",
                    "kind": "分割",
                    "factor": 1.5,
                    "source": "heuristic_gap",
                }
            ],
        )
        face = recent_ex_face(sid, db, "20260806", bars)
        blob = f"{face.get('label') or ''} {face.get('note') or ''}"
        assert "分割" not in blob
        assert "除權" not in blob
        assert "除息" not in blob
        assert face["label"] == ""


def test_heuristic_upsert_kind_is_not_split(tmp_path):
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_heuristic_event(db, "2383", "20260803", 1.15, kind="分割")
    import sqlite3

    kind, src = sqlite3.connect(db).execute(
        "SELECT kind, source FROM ex_rights WHERE stock_id='2383'"
    ).fetchone()
    assert kind == "啟發式"
    assert src == "heuristic_gap"


def test_vol_zone_on_ex_ignores_heuristic_split():
    from vol_zone_chart import vol_zone_photo_caption

    zone = {"date": "20260803", "high": 165, "low": 150, "volume": 1000}
    last = {"date": "20260803", "close": 158, "high": 165, "low": 150, "volume": 1000}
    bars = [
        {"date": "20260730", "open": 100, "high": 110, "low": 95, "close": 108, "volume": 800},
        {"date": "20260803", "open": 160, "high": 165, "low": 150, "close": 158, "volume": 1000},
    ]
    cap = vol_zone_photo_caption(
        zone=zone,
        last=last,
        bars=bars,
        ex_events=[{"ex_date": "20260803", "kind": "分割", "source": "heuristic_gap"}],
    )
    assert "分割" not in cap
    assert "除息" not in cap
    assert "除權" not in cap


