# -*- coding: utf-8 -*-
"""早報附註：加權研究／資金輪動／月營收分開、手機寬、數字不拆。"""
from __future__ import annotations

import re

from tg_layout import DASH_LINE, _html_plain, pack_phone_bits


def _plain(s: str) -> str:
    return _html_plain(s)


def test_pack_phone_bits_keeps_short_and_splits_at_sep():
    one = pack_phone_bits("日　+0.32%", "5日　+1.20%")
    assert len(one) == 1
    long = pack_phone_bits(
        "日　+0.32%",
        "5日　+1.20%",
        "20日　+3.40%",
        width=18,
    )
    assert len(long) >= 2
    blob = "\n".join(long)
    assert "+0.32%" in blob and "+1.20%" in blob and "+3.40%" in blob
    assert not any(ln.endswith("+") for ln in long)


def test_taiwan_market_brief_uses_dashed_phone_lines(monkeypatch):
    from taiwan_market import format_taiwan_market_brief_html

    snap = {
        "ok": True,
        "close": 46551.12,
        "ma5": 46200.0,
        "ma20": 45800.0,
        "ma60": 44000.0,
        "chg1_pct": 0.32,
        "chg5_pct": 1.2,
        "chg20_pct": 3.4,
        "vs_ma20_pct": 1.2,
        "vs_high52_pct": -4.5,
        "breadth_above_ma20": 55.5,
        "sample_n": 900,
        "sector_flow_net": 12345,
        "regime": "neutral",
        "regime_label": "震盪",
        "confidence": 40,
        "regime_plus": "range",
        "regime_plus_label": "區間",
        "falling_risk": 20,
        "risk_zone": "normal",
        "futures": {"close": 26500, "date": "20260919", "open_interest": 0},
        "futures_night": {"close": 26580, "date": "20260919"},
        "backtest": [
            {"regime": "neutral", "bucket": "黃金買點", "n": 20, "avg_next_pct": 0.8, "hit_rate": 0.6},
            {"regime": "neutral", "bucket": "重點觀察", "n": 20, "avg_next_pct": 0.2, "hit_rate": 0.5},
        ],
    }
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: snap)
    html = format_taiwan_market_brief_html(":memory:", "20260919")
    assert "＝＝台灣加權指數研究＝＝" in html
    assert "📊" not in html
    assert DASH_LINE in html
    assert "收盤　" in html
    assert "同一盤勢隔日" in html
    assert "黃金買點　隔日+0.8%（勝60%）" in html
    assert "重點觀察　隔日+0.2%（勝50%）" in html
    assert "箱型震盪：偏選股，不賭方向。" in html
    assert sum(1 for ln in html.split("\n") if ln.startswith("盤勢　")) == 1
    joined = html.replace("\n", "")
    assert "（勝60%）" in joined
    for ln in html.split("\n"):
        if DASH_LINE in ln or ln.startswith("＝＝"):
            continue
        plain = _plain(ln)
        if "隔日" in plain and "（勝" in plain:
            assert re.search(r"隔日[+\-]\d+\.\d+%（勝\d+%）", plain), ln
            continue
        if "<b>" in ln:
            continue
        assert not plain.endswith("勝"), ln


def test_hot_revenue_dashed_two_line_rows(monkeypatch):
    from fundamentals import format_hot_revenue_html

    monkeypatch.setattr(
        "fundamentals.hot_revenue_names",
        lambda *_a, **_k: [
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "yoy_pct": 25.5,
                "mom_pct": 3.2,
                "yyyymm": "202608",
            }
        ],
    )
    html = format_hot_revenue_html(":memory:")
    assert "＝＝月營收轉強＝＝" in html
    assert DASH_LINE in html
    assert "年增≥20%　且月增≥0" in html
    assert "<code>2330</code> 台積電" in html
    assert "年增 +25.5%　月增 +3.2%" in html
    assert "🔥" not in html
    title_lines = [ln for ln in html.split("\n") if "月營收轉強" in ln]
    assert title_lines
    assert all(len(_plain(ln)) <= 18 for ln in title_lines)


def test_push_screening_sends_extras_as_separate_messages(monkeypatch):
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20260921"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": lambda _s, _x, chat_id=None: True})()
    sent = []
    runner.send_telegram_message = lambda text, chat_id=None: sent.append((chat_id, text)) or True
    runner._format_watch_radar_section = lambda uid="": f"RADAR-{uid}"
    runner._run_ai_desk = lambda *a, **k: {}
    runner._family_chat_ids = lambda: ["9001"]
    monkeypatch.setattr(
        "taiwan_market.format_taiwan_market_brief_html",
        lambda *_a, **_k: "＝＝台灣加權指數研究＝＝\n收盤　1",
    )
    monkeypatch.setattr(
        "money_flow.format_sector_rotation_html",
        lambda *_a, **_k: "盤後資金輪動\n單位：張",
    )
    monkeypatch.setattr(
        "fundamentals.format_hot_revenue_html",
        lambda *_a, **_k: "＝＝月營收轉強＝＝\n年增",
    )
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False})
    monkeypatch.setattr("screen_review.score_screen_picks", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.score_ai_fills", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.adapt_bucket_weights", lambda *_a, **_k: None)

    runner._push_screening(
        {"status": "success", "payload": [{"html": "海選"}], "message": "海選本文", "results": {}},
        as_of="20260919",
    )
    texts = [t for _cid, t in sent]
    assert "＝＝台灣加權指數研究＝＝\n收盤　1" in texts
    assert "盤後資金輪動\n單位：張" in texts
    assert "＝＝月營收轉強＝＝\n年增" in texts
    assert "RADAR-9001" in texts
    mashed = [t for t in texts if "台灣加權指數研究" in t and "月營收轉強" in t]
    assert mashed == []
    mashed_radar = [t for t in texts if "台灣加權指數研究" in t and "RADAR-9001" in t]
    assert mashed_radar == []
