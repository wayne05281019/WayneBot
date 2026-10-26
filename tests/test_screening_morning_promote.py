# -*- coding: utf-8 -*-
"""WB-16：evening 有桶、morning 沒列 → 早報升寫 morning，12:45／畫面桶才看得到。"""
from __future__ import annotations


def test_screen_session_has_face_vs_silent_only(tmp_path):
    from screen_sessions import (
        save_screen_session,
        screen_session_has_data,
        screen_session_has_face_data,
        screen_session_has_session_data,
    )

    db = str(tmp_path / "face.db")
    save_screen_session(
        db,
        "20261022",
        "evening",
        {
            "select_01": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 100.0}
            ],
        },
    )
    assert screen_session_has_data(db, "20261022")
    assert screen_session_has_session_data(db, "20261022", "evening")
    assert not screen_session_has_session_data(db, "20261022", "morning")
    assert not screen_session_has_face_data(db, "20261022")

    save_screen_session(
        db,
        "20261022",
        "evening",
        {
            "leave_zero": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 100.0}
            ],
            "select_01": [
                {"stock_id": "2317", "stock_name": "鴻海", "close": 200.0}
            ],
        },
    )
    assert screen_session_has_face_data(db, "20261022", "evening")


def test_ensure_morning_promotes_evening_face_buckets(tmp_path, monkeypatch):
    from midday_review import load_midday_bucket_rows
    from screen_sessions import (
        load_bucket_rows,
        save_screen_session,
        screen_session_has_session_data,
    )
    from screening_engine import ensure_morning_session_from_cache

    db = str(tmp_path / "promote.db")
    save_screen_session(
        db,
        "20261022",
        "evening",
        {
            "leave_zero": [
                {
                    "stock_id": "3665",
                    "stock_name": "貿聯-KY",
                    "close": 500.0,
                    "entry_price": 490.0,
                }
            ],
            "ma60_lower": [
                {
                    "stock_id": "1314",
                    "stock_name": "中石化",
                    "close": 8.5,
                }
            ],
            "golden_buy": [
                {
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "close": 1000.0,
                }
            ],
            "select_01": [
                {"stock_id": "2317", "stock_name": "鴻海", "close": 200.0}
            ],
        },
    )
    assert not screen_session_has_session_data(db, "20261022", "morning")
    # 升寫前：12:45 只讀 morning → 空（桶算了沒顯示）
    assert load_midday_bucket_rows(db, "20261022") == []

    monkeypatch.setattr(
        "screening_engine._postprocess_screen",
        lambda *_a, **_k: {},
    )
    out = ensure_morning_session_from_cache(db, "20261022", apply_us=True, light=True)
    assert out is not None
    assert out.get("as_of") == "20261022"
    assert screen_session_has_session_data(db, "20261022", "morning")
    assert {r["stock_id"] for r in load_bucket_rows(db, "leave_zero", "20261022", session="morning")} == {
        "3665"
    }
    assert {r["stock_id"] for r in load_bucket_rows(db, "ma60_lower", "20261022", session="morning")} == {
        "1314"
    }
    # 靜默桶也跟著升寫（仍不上話筒 SCREEN_PUSH）
    assert {r["stock_id"] for r in load_bucket_rows(db, "select_01", "20261022", session="morning")} == {
        "2317"
    }
    mid = load_midday_bucket_rows(db, "20261022")
    assert {r["stock_id"] for r in mid} == {"3665", "2330"}
    keys = [p.get("mark_key") for p in (out.get("payload") or [])]
    assert "leave_zero" in keys
    assert "ma60_lower" in keys
    assert "select_01" not in keys  # 不上話筒


def test_screening_surviving_oom_promotes_evening(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from screen_sessions import save_screen_session, screen_session_has_session_data

    db = str(tmp_path / "oom.db")
    save_screen_session(
        db,
        "20261022",
        "evening",
        {
            "leave_zero": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 100.0}
            ],
        },
    )
    monkeypatch.setattr(
        "screening_engine._postprocess_screen",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "screening_engine._resolve_screen_as_of_ymd",
        lambda *_a, **_k: "20261022",
    )
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = db
    out = runner._screening_surviving_oom("20261022", session="morning", apply_us=True)
    assert out is not None
    assert screen_session_has_session_data(db, "20261022", "morning")
    assert (out.get("results") or {}).get("leave_zero")


def test_review_buckets_include_half_year_high():
    from screen_buckets import REVIEW_BUCKETS

    keys = [k for k, _ in REVIEW_BUCKETS]
    assert "half_year_high" in keys
    assert keys.index("half_year_high") > keys.index("select_01")
