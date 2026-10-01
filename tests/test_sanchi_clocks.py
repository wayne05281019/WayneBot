# -*- coding: utf-8 -*-
"""三尺時間文案：早報／查股／剛脫離零說清為何可不一致。"""
from __future__ import annotations

from sanchi_clocks import (
    SANCHI_LINE_LEAVE_ZERO,
    SANCHI_LINE_LOOKUP,
    SANCHI_LINE_MORNING,
    SANCHI_LINE_WHY,
    SANCHI_LINES,
    append_sanchi_to_caption,
    card_lights_buy_arrow,
    sanchi_note_html,
    sanchi_note_plain,
)


def _disp_w(text: str) -> int:
    return sum(2 if ord(ch) > 127 else 1 for ch in str(text or ""))


def test_sanchi_lines_fit_phone_bubble():
    # 氣泡約 18 全形＝36 半形寬；每行不得超
    for line in SANCHI_LINES:
        assert _disp_w(line) <= 36, (line, _disp_w(line))
    assert "昨收" in SANCHI_LINE_MORNING
    assert "1000" in SANCHI_LINE_MORNING
    assert "盤中" in SANCHI_LINE_LOOKUP
    assert "全市場" in SANCHI_LINE_LEAVE_ZERO
    assert "圖有箭≠早報必有" in SANCHI_LINE_WHY


def test_sanchi_html_and_plain():
    html = sanchi_note_html()
    plain = sanchi_note_plain()
    assert "<i>" in html and "</i>" in html
    assert SANCHI_LINE_MORNING in plain
    assert "leave_zero" not in html.lower()
    assert "golden_buy" not in plain


def test_append_only_when_buy_arrow():
    base = "穎崴"
    assert append_sanchi_to_caption(base, {"buy_verdict": "watch"}) == base
    assert append_sanchi_to_caption(base, {"buy_verdict": "no"}) == base
    assert append_sanchi_to_caption(base, {"entry_stage": "watch", "buy_verdict": "buy"}) == base
    lit = append_sanchi_to_caption(base, {"buy_verdict": "buy"})
    assert base in lit
    assert SANCHI_LINE_LOOKUP in lit
    assert SANCHI_LINE_MORNING in lit
    assert SANCHI_LINE_WHY in lit
    assert card_lights_buy_arrow({"relative_buy_kind": "just_left"}) is True
    assert card_lights_buy_arrow({"buy_verdict": "buy"}) is True
    assert card_lights_buy_arrow({}) is False


def test_morning_payload_includes_sanchi():
    from screening_engine import format_screening_payload

    payload = format_screening_payload(
        {
            "leave_zero": [
                {
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "close": 900.0,
                    "entry_stage": "buy",
                }
            ],
            "golden_buy": [],
        },
        "20260929",
        morning=True,
    )
    assert payload
    blob = "\n".join(str(p.get("html") or "") for p in payload)
    assert SANCHI_LINE_MORNING in blob
    assert SANCHI_LINE_WHY in blob


def test_manual_screen_also_gets_sanchi_on_first_bucket():
    from screening_engine import format_screening_payload

    payload = format_screening_payload(
        {"leave_zero": [], "golden_buy": []},
        "20260929",
        morning=False,
    )
    blob = "\n".join(str(p.get("html") or "") for p in payload)
    assert SANCHI_LINE_LOOKUP in blob
