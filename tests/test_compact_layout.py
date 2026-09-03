# -*- coding: utf-8 -*-
"""海選卡、資金輪動：緊湊排版（對齊圖二美股晨報風格）。"""
from __future__ import annotations

import re

import pytest

from tests.conftest import require_production_db


def test_stock_card_volume_and_turnover_separate_lines():
    from screening_engine import _stock_card_html

    card = _stock_card_html(
        {
            "stock_id": "9925",
            "stock_name": "新保",
            "close": 40.05,
            "volume": 1047,
            "pct_change": 1.91,
            "q60r": 1.51,
            "turnover_k": 41800.0,
            "ma20": 39.98,
            "ma60": 40.49,
            "foreign_net": 316,
            "trust_net": 0,
            "dealer_net": -55,
            "profit": 1.9,
            "vol_rank_120": 7,
        },
        1,
        show_line_link=False,
    )
    assert "額　<code>41.8億</code>" in card
    assert "量　" in card
    assert "量比　" in card
    # 額與億同一行，不應裸寫 41.8 讓 億 掉到下一行
    assert re.search(r"額　<code>[\d.]+億</code>", card)
    assert "法人　外資" in card
    assert card.count("\n外資") == 0


def test_stock_card_chip_single_line():
    from screening_engine import _chip_html

    chips = _chip_html({"foreign_net": 8000, "trust_net": -200, "dealer_net": 0})
    assert "\n" not in chips
    assert "外資" in chips and "投信" in chips and "自營" in chips


@pytest.mark.production_db
def test_sector_rotation_uses_compact_kv():
    from money_flow import format_sector_rotation_html

    db = require_production_db()
    html = format_sector_rotation_html(db, "20260828")
    assert "單位：" in html
    assert "用途：" in html
    assert "單位　　" not in html
    assert "用途　　" not in html
    for line in html.split("\n"):
        if line.startswith("單位") or line.startswith("用途"):
            assert "：" in line
            assert not re.search(r"單位\s{3,}", line)
            assert not re.search(r"用途\s{3,}", line)


@pytest.mark.production_db
def test_flow_html_cover_uses_compact_kv():
    from money_flow import format_flow_html

    db = require_production_db()
    html = format_flow_html(db, yyyymmdd="20260828")
    assert "覆蓋：" in html or "單位：" in html
    assert "覆蓋　　" not in html
