# -*- coding: utf-8 -*-
"""海選／興櫃／連買／大盤：呈現對齊（不改買訊／選股）。"""
from __future__ import annotations

import re

from tg_layout import _disp_w, _html_plain


def test_stock_card_two_char_labels_align():
    from screening_engine import _stock_card_html

    card = _stock_card_html(
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 980.0,
            "pct_change": 1.2,
            "volume": 12345,
            "q60r": 1.1,
            "turnover_k": 1_200_000.0,
            "ma20": 950.0,
            "ma60": 900.0,
            "foreign_net": 100,
            "trust_net": 50,
            "dealer_net": -10,
            "profit": 5.0,
            "vol_rank_120": 7,
            "quote_date": "20260904",
            "entry_stage": "buy",
            "entry_stage_label": "買點",
        },
        1,
        show_line_link=False,
        bucket_label="買點",
    )
    plain = _html_plain(card)
    labs = ("格局", "收盤", "量能", "金額", "均線", "法人", "獲利", "量榜")
    for lab in labs:
        assert any(ln.startswith(lab) for ln in plain.split("\n")), lab
    assert "120量" not in plain
    # 兩字標籤＋全形空白後值欄起點一致
    starts = []
    for ln in plain.split("\n"):
        if any(ln.startswith(lab) for lab in labs):
            assert "　" in ln[:6]
            starts.append(_disp_w(ln.split("　", 1)[0]))
    assert starts
    assert max(starts) == min(starts) == 4


def test_emerging_payload_uses_same_card_labels():
    from screening_engine import EMERGING_PUSH_SPECS, format_screening_payload

    payload = format_screening_payload(
        {
            "leave_zero": [
                {
                    "stock_id": "1260",
                    "stock_name": "富味鄉",
                    "close": 40.0,
                    "pct_change": 0.5,
                    "volume": 100,
                    "q60r": 1.0,
                    "market": "EM",
                    "quote_source": "emerging",
                    "entry_stage": "watch",
                    "entry_stage_label": "還在零",
                }
            ]
        },
        "20260904",
        title="WayneBot 興櫃海選",
        specs=EMERGING_PUSH_SPECS,
    )
    blob = "\n".join(p["html"] for p in payload)
    assert "興櫃海選" in blob
    assert "格局　" in blob
    assert "收盤　" in blob
    assert "量能　" in blob
    assert "120量" not in blob


def test_streak_row_labels_align_units():
    from buy_streak import KIND_BOTH, KIND_FOREIGN, StreakRow, format_row_lines

    row = StreakRow(
        stock_id="2330",
        name="台積電",
        market="TW",
        days=6,
        foreign_lots=750,
        trust_lots=0,
        volume_lots=13000,
    )
    lines = format_row_lines(row, KIND_FOREIGN)
    assert lines[0].startswith("連買") and "750張" in lines[0]
    assert lines[1].startswith("佔比") and f"{row.foreign_pct}%" in lines[1]
    assert _disp_w(lines[0].split("　", 1)[0]) == 4
    assert _disp_w(lines[1].split("　", 1)[0]) == 4

    both = StreakRow(
        stock_id="2317",
        name="鴻海",
        market="TW",
        days=3,
        foreign_lots=60,
        trust_lots=90,
        volume_lots=1000,
    )
    bl = format_row_lines(both, KIND_BOTH)
    assert [ln.split("　", 1)[0] for ln in bl] == ["皆買", "張數", "佔比"]
    assert all(_disp_w(ln.split("　", 1)[0]) == 4 for ln in bl)


def test_outlook_kv_aligns_buy_sell_and_cash():
    from taiwan_market import _outlook_kv, _us_cash_close_lines, format_screen_market_outlook_html

    assert _outlook_kv("買多", "<code>1口</code>", width=4).startswith("買多　")
    us_lines = _us_cash_close_lines(
        {
            "dji_pct": -0.1,
            "spx_pct": -0.2,
            "ixic_pct": -0.3,
            "sox_pct": -0.4,
        },
        style="outlook",
    )
    plains = [_html_plain(x) for x in us_lines]
    assert all("　" in p for p in plains)
    # 標籤欄對齊到 width=8（短標會補空白）
    widths = [_disp_w(p.split("　", 1)[0]) for p in plains]
    assert min(widths) >= 4

    html = format_screen_market_outlook_html(
        ":memory:",
        "20260904",
        snap={
            "ok": True,
            "as_of": "20260904",
            "close": 100.0,
            "chg1_pct": 0.1,
            "vs_ma20_pct": 0.0,
            "regime": "neutral",
            "falling_risk": 10,
            "tx_foreign_oi": {
                "date": "20260904",
                "oi_long": 1,
                "oi_short": 2,
                "oi_net": -1,
            },
        },
        us_snap={"ok": True, "regime": "ok", "ixic_pct": 0.1, "sox_pct": 0.1},
        flow_maps={
            "just_rotated": {},
            "just_rotated_rows": [],
            "inflow_rows": [],
            "outflow_rows": [],
        },
    )
    plain = _html_plain(html)
    assert re.search(r"(?m)^買多　", plain)
    assert re.search(r"(?m)^買空　", plain)
