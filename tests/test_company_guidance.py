# -*- coding: utf-8 -*-
from company_guidance import (
    extract_guidance_from_text,
    format_guidance_note,
    guidance_step_g,
    parse_material_row,
)


def test_extract_qoq_and_year_growth():
    hits = extract_guidance_from_text("下一季營收較本季成長 12%。2026 年美元合併營收成長大約 44%。")
    kinds = {h["kind"] for h in hits}
    assert "next_q_qoq_pct" in kinds
    assert "year_rev_growth_pct" in kinds


def test_reject_no_forecast_disclaimer():
    blob = "媒體報導明年營收成長20%。本公司不作財務預測，以公開資訊觀測站為準。"
    assert extract_guidance_from_text(blob) == []


def test_guidance_step_g_only_qoq():
    assert guidance_step_g({"ok": True, "kind": "next_q_qoq_pct", "value": 10}) == 0.1
    assert guidance_step_g({"ok": True, "kind": "year_rev_growth_pct", "value": 44}) is None


def test_format_note():
    s = format_guidance_note(
        {"published_ymd": "20261118", "kind": "next_q_qoq_pct", "value": 8, "excerpt": "下一季成長8%"}
    )
    assert "11/18" in s and "QoQ" in s


def test_parse_material_ir_note():
    row = {
        "公司代號": "4106",
        "發言日期": "1151117",
        "主旨 ": "公告召開法人說明會",
        "說明": "4.法人說明會擇要訊息：115年前三季營運結果與營運近況說明\n5.其他",
    }
    out = parse_material_row(row, source="t187ap04_L")
    assert out and out[0]["kind"] == "ir_note"
