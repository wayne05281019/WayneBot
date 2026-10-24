# -*- coding: utf-8 -*-
"""查股四張圖盤中價／昨收／漲跌同源（上市／上櫃／興櫃）；現價＝昨收不准非零％。"""
from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from chip_tape import build_tape, load_tape_rows
from emerging_quotes import ensure_emerging_table
from live_quote import display_quote_from_card
from wayne_db import ensure_core_schema


def test_display_quote_forces_flat_when_close_equals_prev():
    dq = display_quote_from_card(
        {
            "close": 1402.0,
            "prev_close": 1402.0,
            "change_pct": -3.68,
            "is_live": True,
            "latest_date": "20261013",
            "quote_source": "emerging_quotes",
            "open": 1391.0,
            "high": 1450.0,
            "low": 1375.0,
            "volume": 10,
        }
    )
    assert dq is not None
    assert float(dq["close"]) == 1402.0
    assert float(dq["pct"]) == 0.0
    assert float(dq["change"]) == 0.0


def test_display_quote_recomputes_pct_from_close_prev():
    dq = display_quote_from_card(
        {
            "close": 1350.0,
            "prev_close": 1402.0,
            "change_pct": -99.0,  # 錯％不准蓋過 close−prev
            "is_live": True,
            "latest_date": "20261013",
            "quote_source": "emerging_quotes",
            "open": 1395.0,
            "high": 1400.0,
            "low": 1330.0,
            "volume": 20,
            "listing": "興櫃",
        }
    )
    assert dq is not None
    assert float(dq["close"]) == 1350.0
    assert float(dq["change"]) == -52.0
    assert abs(float(dq["pct"]) + 3.71) < 0.01
    assert dq["emerging"] is True


def _seed_em(db: str, *, last_date: str = "20261012", last_close: float = 1402.0):
    ensure_core_schema(db)
    ensure_emerging_table(db)
    conn = sqlite3.connect(db)
    days = [
        "20260929",
        "20260930",
        "20261001",
        "20261002",
        "20261003",
        "20261006",
        "20261007",
        "20261008",
        "20261009",
        "20261012",
    ]
    for i, d in enumerate(days):
        px = 1300.0 + i * 10
        if d == last_date:
            px = last_close
        conn.execute(
            """
            INSERT INTO emerging_quotes(
                date, stock_id, stock_name, market, open, high, low, close,
                volume, turnover_k, pct_change, avg_price, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                d,
                "3595",
                "山太士",
                "EM",
                px - 5,
                px + 20,
                px - 30,
                px,
                10.0 + i,
                px * 10,
                0.5,
                px,
                "csv",
            ),
        )
    conn.commit()
    conn.close()


def test_emerging_tape_merges_live_quote(tmp_path, monkeypatch):
    db = str(tmp_path / "em.db")
    _seed_em(db)
    live = {
        "stock_id": "3595",
        "open": 1395.0,
        "high": 1400.0,
        "low": 1330.0,
        "close": 1350.0,
        "volume": 25,
        "pct_change": -3.71,
        "change": -52.0,
        "yesterday_close": 1402.0,
        "update_time": "09:35:00",
        "is_realtime": True,
        "source": "yahoo",
        "emerging": True,
    }
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr("live_quote.taipei_today_str", lambda: "20261013")
    monkeypatch.setattr(
        "trading_calendar.is_tw_open_calendar_day", lambda d: True
    )
    rows = load_tape_rows(db, "3595", merge_live=True, live_quote=live)
    assert str(rows[-1]["date"]).replace("-", "") == "20261013"
    assert float(rows[-1]["close"]) == 1350.0
    assert float(rows[-1].get("yesterday_close") or 0) == 1402.0
    assert rows[-1].get("emerging") is True
    assert rows[-1].get("foreign_net") is None
    tape = build_tape(db, "3595", merge_live=True, live_quote=live) or {}
    assert float(tape["last"]["close"]) == 1350.0
    assert tape.get("emerging") is True
    assert tape.get("has_chips") is False


def test_glance_prefers_card_over_stale_tape():
    src = inspect.getsource(
        __import__("wayne_navigator", fromlist=["render_first_glance_png"]).render_first_glance_png
    )
    assert "display_quote_from_card" in src
    assert "match-card-076-fund-rev2line-v77-card-price" in src


def test_structure_lookup_passes_card_into_spot():
    from three_in_one_chart import (
        _lookup_structure_bars_and_spot,
        render_lookup_structure_result,
    )

    # spot 組裝抽到 _lookup_structure_bars_and_spot；render 仍傳 quote=spot
    helper = inspect.getsource(_lookup_structure_bars_and_spot)
    src = inspect.getsource(render_lookup_structure_result)
    assert "_spot_quote" in helper
    assert "card=card" in helper or "card=card" in src
    assert "quote=spot" in src


def test_structure_axis_close_uses_quote_not_last_bar_only():
    """右軸今收／現價必須跟決策卡 quote 同源；不准只吃官方 last_bar（上市上櫃也會分岔）。"""
    from biaoke_chart import _structure_render_memo_key, render_biaoke_structure_png

    src = inspect.getsource(render_biaoke_structure_png)
    memo_src = inspect.getsource(_structure_render_memo_key)
    assert 'quote.get("close")' in src or "quote.get('close')" in src
    assert 'close_tag = "現價"' in src or "close_tag = '現價'" in src
    assert "hdr-band-v78j-axis-card" in (src + memo_src)
    # 舊寫法：只認 last_bar.close 當今收＝回歸點
    assert 'text": f"今收 {_px_quote(last_c)}"' not in src


def test_volzone_header_uses_card_display_quote():
    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "display_quote_from_card" in src
    assert "hdr_quote" in src


def test_display_quote_listed_and_otc_same_shape():
    """上市／上櫃決策卡也走同一 display_quote；不准只修興櫃。"""
    for listing, qs in (("上市", "daily_quotes"), ("上櫃", "daily_quotes")):
        dq = display_quote_from_card(
            {
                "stock_id": "2330" if listing == "上市" else "3105",
                "close": 1000.0,
                "prev_close": 980.0,
                "change_pct": 99.0,
                "is_live": True,
                "latest_date": "20261013",
                "quote_source": qs,
                "listing": listing,
                "open": 990.0,
                "high": 1010.0,
                "low": 985.0,
                "volume": 1000,
            }
        )
        assert dq is not None
        assert float(dq["close"]) == 1000.0
        assert float(dq["prev"]) == 980.0
        assert float(dq["change"]) == 20.0
        assert abs(float(dq["pct"]) - 2.04) < 0.01
        assert dq["emerging"] is False


def test_spot_quote_uses_card_not_mis_for_emerging(monkeypatch):
    from biaoke_chart import _spot_quote

    card = {
        "stock_id": "3595",
        "close": 1350.0,
        "prev_close": 1402.0,
        "change_pct": -3.71,
        "is_live": True,
        "latest_date": "20261013",
        "query_date": "2026/10/13 (二)",
        "query_clock": "盤中 09:35",
        "quote_source": "emerging_quotes",
        "listing": "興櫃",
        "open": 1395.0,
        "high": 1400.0,
        "low": 1330.0,
        "volume": 25,
    }

    def _boom(*a, **k):
        raise AssertionError("有決策卡不准再打 MIS")

    monkeypatch.setattr("live_quote.fetch_mis_quote", _boom)
    q = _spot_quote(
        "3595",
        {"date": "20261012", "open": 1391, "high": 1450, "low": 1375, "close": 1402},
        {"close": 1391},
        "",
        card=card,
    )
    assert float(q["close"]) == 1350.0
    assert float(q["prev"]) == 1402.0
    assert abs(float(q["pct"]) + 3.71) < 0.01
    assert q["is_live"] is True
    assert str(q.get("date") or "").startswith("20261013")


def test_navigator_and_glance_sync_emerging_live(tmp_path, monkeypatch):
    """決策卡現價／昨收／％與 display_quote 同源；不准現價＝昨收却帶非零％。"""
    from wayne_navigator import NavigatorEngine

    db = str(tmp_path / "em2.db")
    # 庫內末日收刻意跟 live yesterday_close 不同，驗盤中昨收認報價源
    _seed_em(db, last_date="20261012", last_close=1507.42)
    live = {
        "stock_id": "3595",
        "open": 1395.0,
        "high": 1400.0,
        "low": 1330.0,
        "close": 1350.0,
        "volume": 25,
        "pct_change": -3.71,
        "change": -52.0,
        "yesterday_close": 1402.0,
        "update_time": "09:35:00",
        "is_realtime": True,
        "source": "yahoo",
        "emerging": True,
    }
    mid = datetime(2026, 10, 13, 9, 35, tzinfo=ZoneInfo("Asia/Taipei"))
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr("live_quote.taipei_today_str", lambda: "20261013")
    monkeypatch.setattr("config.taipei_now", lambda: mid)
    monkeypatch.setattr("decision_card_signals.taipei_now", lambda *a, **k: mid)
    monkeypatch.setattr(
        "trading_calendar.is_tw_open_calendar_day", lambda d: True
    )

    engine = NavigatorEngine(db)
    card = engine.get_decision_card("3595", merge_live=True, live_quote=live)
    assert not card.get("error"), card
    assert card.get("is_live") is True
    assert float(card.get("close") or 0) == 1350.0
    # 盤中昨收＝live yesterday_close，不准用庫內 1507.42
    assert float(card.get("prev_close") or 0) == 1402.0
    assert abs(float(card.get("change_pct") or 0) + 3.71) < 0.01
    dq = display_quote_from_card(card)
    assert dq and float(dq["close"]) == 1350.0
    assert float(dq["change"]) == -52.0
    assert abs(float(card["close"]) - float(dq["close"])) < 1e-9
    assert abs(float(card["prev_close"]) - float(dq["prev_close"])) < 1e-9
    # 模擬介紹圖舊 bug：tape 昨收蓋掉現價却沿用 live ％
    stale_close = 1402.0
    stale_pct = float(card.get("change_pct") or -3.71)
    fixed = display_quote_from_card(
        {**card, "close": stale_close, "prev_close": stale_close, "change_pct": stale_pct}
    )
    assert fixed and float(fixed["pct"]) == 0.0
