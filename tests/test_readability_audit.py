# -*- coding: utf-8 -*-
"""全站可讀性審計：模擬新手／重度／不懂股，檢查 Telegram HTML 不撐寬、不錯行。"""
from __future__ import annotations

import os
import re
from typing import Callable, List, Tuple

import pytest

# 寬欄 pad 後常見：標籤後接 3+ 半形或 2+ 全形空白（非冒號格式）
_BAD_PAD = re.compile(r"^(產業|同業|單位|用途|覆蓋|期間|月營收|季報|基準日|已用槽|本金|日期|收盤|外資|投信)\s{3,}")
_BAD_PAD_FW = re.compile(r"^(產業|同業|單位|用途|日期|收盤|現價|漲跌)\u3000\u3000")


def _assert_readable(html: str, *, name: str) -> None:
    assert html, f"{name} empty"
    for line in html.split("\n"):
        if not line.strip():
            continue
        assert not _BAD_PAD.search(line), f"{name} wide pad: {line[:60]!r}"
        assert not _BAD_PAD_FW.search(line), f"{name} wide fw pad: {line[:60]!r}"
        # 額與億不應拆開（裸數字+下一行億）
        if "額" in line and "億" in line and "<code>" in line:
            assert re.search(r"<code>[^<]*億</code>", line), f"{name} split 億: {line!r}"


def _db():
    p = os.path.join(os.path.dirname(__file__), "..", "data", "wayne_market.db")
    if not os.path.isfile(p):
        pytest.skip("no market db")
    return p


def test_newbie_flow_sector_rotation_readable():
    from money_flow import format_sector_rotation_html

    html = format_sector_rotation_html(_db(), "20260828")
    _assert_readable(html, name="sector_rotation")


def test_newbie_flow_full_readable():
    from money_flow import format_flow_html

    html = format_flow_html(_db(), yyyymmdd="20260828")
    _assert_readable(html, name="flow")


def test_power_user_screen_card_readable():
    from screening_engine import _stock_card_html

    card = _stock_card_html(
        {
            "stock_id": "3711",
            "stock_name": "日月光投控",
            "close": 610,
            "volume": 26066,
            "pct_change": 4.45,
            "q60r": 1.09,
            "turnover_k": 15754400.0,
            "ma20": 603.5,
            "ma60": 615.5,
            "foreign_net": 7292,
            "trust_net": -555,
            "dealer_net": 900,
            "profit": 4.5,
            "vol_rank_120": 36,
            "sector_outflow": True,
            "sector_flow_label": "輪動出",
            "leave_l20": True,
        },
        2,
        show_line_link=False,
    )
    _assert_readable(card, name="screen_card")


def test_power_user_decision_card_text_readable():
    from wayne_navigator import generate_decision_card

    html = generate_decision_card("2330", _db(), lookback=20)
    _assert_readable(html, name="decision_card")


def test_holdings_readable():
    from portfolio_engine import PortfolioEngine

    eng = PortfolioEngine(_db())
    html = eng.format_holdings_html(
        [{"stock_code": "2330", "stock_name": "台積電", "shares": 1, "cost_price": 500}],
        quotes_map={"2330": {"close": 520, "pct_change": 1.2}},
    )
    _assert_readable(html, name="holdings")
    assert "現價：" in html or "成本：" in html


def test_industry_brief_readable():
    from industry_brief import format_industry_html

    html = format_industry_html("2330", _db())
    if "找不到" in html or "ETF" in html:
        pytest.skip("2330 industry skip")
    _assert_readable(html, name="industry")


def test_fundamentals_readable():
    from fundamentals import format_fundamentals_html

    html = format_fundamentals_html("2330", _db())
    if "尚無" in html:
        pytest.skip("no fundamentals")
    _assert_readable(html, name="fundamentals")
    assert "期間：" in html or "月營收：" in html


def test_ai_desk_readable():
    from ai_trader import format_ai_desk_html
    from portfolio_engine import PortfolioEngine

    eng = PortfolioEngine(_db())
    html = format_ai_desk_html(eng, "1001")
    _assert_readable(html, name="ai_desk")
    assert "總資產：" in html


def test_us_alert_still_good_baseline():
    from us_overnight import format_us_drop_alert

    snap = {
        "regime": "caution",
        "vix": 16.3,
        "vix_pct": 4.5,
        "vix_chg": 0.7,
        "dji_pct": -0.8,
        "dji_chg": -142.15,
        "spx_pct": -0.7,
        "spx_chg": -38.42,
        "ixic_pct": -1.0,
        "ixic_chg": -198.32,
        "sox_pct": -2.1,
        "sox_chg": -125.4,
        "us_phase": "regular",
        "us_session": "20260901",
    }
    html = format_us_drop_alert(snap)
    _assert_readable(html, name="us_alert")
    assert "道瓊" in html
