# -*- coding: utf-8 -*-
"""股東會／法說建檔：官方 OpenAPI 與說明欄日期句，不是關鍵字產品。"""
from __future__ import annotations

from company_events import (
    ingest_ir_from_material,
    ingest_shareholder_meetings,
    parse_ir_date_from_explanation,
    roc_compact_to_ymd,
)
from ex_rights import format_next_event_label, nearest_event_label, upsert_events
from wayne_db import ensure_core_schema


def test_roc_and_ir_date_parse():
    assert roc_compact_to_ymd("1151013") == "20261013"
    assert roc_compact_to_ymd("115/09/11") == "20260911"
    assert parse_ir_date_from_explanation(
        "12.召開法人說明會之日期：115/09/11\n地點：台北"
    ) == "20260911"
    assert parse_ir_date_from_explanation("法說會即將召開") is None
    assert parse_ir_date_from_explanation("召開股東常會") is None


def test_ingest_meeting_and_ir_then_nearest(tmp_path):
    db = str(tmp_path / "ev.db")
    ensure_core_schema(db)
    n = ingest_shareholder_meetings(
        [
            {
                "公司代號": "1101",
                "股東常(臨時)會": "臨時會",
                "開會日期": "1151013",
                "開會地點": "台北",
            },
            {
                "公司代號": "2330",
                "股東會種類": "常會",
                "股東會日期": "1150604",
                "開會地點": "新竹",
            },
        ],
        db,
    )
    assert n == 2
    n2 = ingest_ir_from_material(
        [
            {
                "公司代號": "2330",
                "主旨及說明": "召開法人說明會之日期：115/09/11",
            },
            {"公司代號": "9999", "主旨及說明": "董事會決議"},
        ],
        db,
    )
    assert n2 == 1
    assert nearest_event_label("1101", db, today="20260904") == "39天後臨時會"
    assert nearest_event_label("2330", db, today="20260904") == "7天後法說"
    assert nearest_event_label("9999", db, today="20260904") == ""
    assert format_next_event_label("法說", "20260911", "20260904") == "7天後法說"
    assert format_next_event_label("常會", "20260904", "20260904") == "今日股東會"


def test_nearest_picks_ex_rights_over_same_day_ir(tmp_path):
    db = str(tmp_path / "mix.db")
    ensure_core_schema(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "2454",
                "ex_date": "20260911",
                "kind": "息",
                "factor": 0.0,
                "source": "TWT48U",
            }
        ],
    )
    ingest_ir_from_material(
        [{"公司代號": "2454", "主旨及說明": "召開法人說明會之日期：115/09/11"}],
        db,
    )
    assert nearest_event_label("2454", db, today="20260904") == "7天後除息"


def test_keyword_only_material_does_not_create_ir(tmp_path):
    db = str(tmp_path / "kw.db")
    ensure_core_schema(db)
    n = ingest_ir_from_material(
        [{"公司代號": "2303", "主旨及說明": "本公司將參加法說會，詳見新聞稿"}],
        db,
    )
    assert n == 0
    assert nearest_event_label("2303", db, today="20260904") == ""
