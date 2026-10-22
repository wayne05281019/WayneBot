# -*- coding: utf-8 -*-
"""06:30 早報 Option B：文字①環境＋夜盤＋加權精簡；文字②兩桶；附帶降級。"""
from __future__ import annotations

from morning_digest import (
    apply_morning_opening_to_screening,
    build_morning_opening_html,
    collapse_morning_pick_parts,
    _outlook_drop_short_nights,
)


def test_build_morning_opening_merges_brief_and_outlook(monkeypatch):
    outlook = (
        "＝＝大盤狀況＝＝\n"
        "<b>WayneBot 海選</b>\n"
        "美股　偏空\n"
        "台指期夜盤　26500\n"
        "比日盤收貴　0.30%\n"
        "電子期夜盤　2100\n"
        "比日盤收便宜　0.10%"
    )
    brief = (
        "＝＝台灣加權指數研究＝＝\n"
        "收盤　46500\n"
        "台指期夜盤　26580　開 26400　高 26600　低 26300　成交 12,000口\n"
        "電子期夜盤　2110　開 2100　高 2120　低 2090　成交 3,000口"
    )
    monkeypatch.setattr(
        "taiwan_market.format_taiwan_market_brief_html",
        lambda *_a, **_k: brief,
    )
    monkeypatch.setattr(
        "morning_digest._foreign_sell_observe_line",
        lambda *_a, **_k: (
            "<b>環境觀察｜觀察／預警（還在測試）</b>\n"
            "開盤前，市場不怕。\n今天沒有外資賣得更兇的股票。\n害怕還沒緩下來。"
        ),
    )
    screening = {
        "payload": [
            {"mark_key": "market", "html": outlook, "picks": []},
            {"mark_key": "leave_zero", "html": "海選桶", "picks": []},
        ]
    }
    merged = build_morning_opening_html(":memory:", "20261013", screening, us_snap=None)
    assert "大盤狀況" in merged
    assert "台灣加權指數研究" in merged
    assert "收盤" in merged
    assert "環境觀察｜觀察／預警（還在測試）" in merged
    assert "今天沒有外資賣得更兇的股票。" in merged
    assert "近窗" not in merged
    assert "今無" not in merged and "非買訊" not in merged
    assert "買進" not in merged
    # 夜盤只留詳細版；短版（僅收盤＋比日盤）已砍
    assert "成交 12,000口" in merged or "12,000口" in merged
    assert merged.count("台指期夜盤") == 1
    assert merged.count("電子期夜盤") == 1
    assert "對照說明" not in merged
    assert "同一盤勢隔日" not in merged


def test_outlook_drop_short_nights_keeps_detailed_brief():
    outlook = (
        "動作一句\n"
        "台指期夜盤　100\n"
        "比日盤收貴　1.00%\n"
        "比現貨貴　0.50%\n"
        "電子期夜盤　200\n"
        "比日盤收便宜　0.20%\n"
        "外資一句"
    )
    brief = "台指期夜盤　101　開 99　高 102　低 98　成交 1口\n電子期夜盤　201　開 200"
    out = _outlook_drop_short_nights(outlook, brief)
    assert "台指期夜盤" not in out
    assert "電子期夜盤" not in out
    assert "比日盤" not in out
    assert "比現貨" not in out
    assert "動作一句" in out
    assert "外資一句" in out


def test_apply_morning_opening_replaces_market_part():
    opening = "＝＝早報彙整＝＝\nA\nB"
    screening = {
        "payload": [
            {"mark_key": "market", "html": "舊大盤", "picks": []},
            {"mark_key": "leave_zero", "html": "桶", "picks": []},
        ],
        "message": "舊",
    }
    out = apply_morning_opening_to_screening(screening, opening)
    assert out["payload"][0]["html"] == opening
    assert out["payload"][0]["mark_label"] == "早報環境"


def test_collapse_morning_pick_parts_merges_two_buckets():
    screening = {
        "payload": [
            {"mark_key": "market", "html": "環境", "picks": []},
            {
                "mark_key": "leave_zero",
                "html": "＝＝黃金買點＝＝\n2330",
                "picks": [("2330", "台積電")],
            },
            {
                "mark_key": "ma60_lower",
                "html": "＝＝紅箭確認＝＝\n2317",
                "picks": [("2317", "鴻海")],
            },
        ]
    }
    out = collapse_morning_pick_parts(screening)
    keys = [p["mark_key"] for p in out["payload"]]
    assert keys == ["market", "morning_picks"]
    blob = out["payload"][1]["html"]
    assert "黃金買點" in blob
    assert "紅箭確認" in blob
    assert "早報＝昨收" in blob
    assert "查股藍▲" not in blob
    assert "圖上有箭" not in blob
    picks = out["payload"][1]["picks"]
    assert ("2330", "台積電") in picks
    assert ("2317", "鴻海") in picks


def test_apply_morning_opening_collapses_to_two_text_parts():
    opening = "＝＝早報環境＝＝\n美股"
    screening = {
        "payload": [
            {"mark_key": "market", "html": "舊", "picks": []},
            {"mark_key": "leave_zero", "html": "＝＝黃金買點＝＝\nA", "picks": []},
            {"mark_key": "ma60_lower", "html": "＝＝紅箭確認＝＝\nB", "picks": []},
        ],
        "message": "舊",
    }
    out = apply_morning_opening_to_screening(screening, opening)
    assert len(out["payload"]) == 2
    assert out["payload"][0]["mark_key"] == "market"
    assert out["payload"][1]["mark_key"] == "morning_picks"


def test_build_morning_opening_passes_for_morning_flag(monkeypatch):
    seen = {}

    def _brief(*_a, **k):
        seen.update(k)
        return "＝＝台灣加權指數研究＝＝\n收盤　1\n台指期夜盤　細節口"

    monkeypatch.setattr("taiwan_market.format_taiwan_market_brief_html", _brief)
    monkeypatch.setattr("morning_digest._foreign_sell_observe_line", lambda *_a, **_k: "")
    monkeypatch.setattr("morning_digest._prev_day_margin_line", lambda *_a, **_k: "")
    screening = {
        "payload": [{"mark_key": "market", "html": "＝＝大盤狀況＝＝\n動作", "picks": []}]
    }
    build_morning_opening_html(":memory:", "20261013", screening)
    assert seen.get("for_morning") is True


def test_push_screening_morning_skips_separate_brief(monkeypatch):
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20261013"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": lambda _s, _x, chat_id=None: True})()
    sent = []
    runner.send_telegram_message = lambda text, chat_id=None: sent.append(text) or True
    runner._format_watch_radar_section = lambda uid="": "RADAR-SHOULD-NOT"
    runner._run_ai_desk = lambda *a, **k: {}
    runner._family_chat_ids = lambda: ["9001"]
    runner._mark_pipeline = lambda *a, **k: None
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
    monkeypatch.setattr(
        "morning_digest.build_morning_opening_html",
        lambda *_a, **_k: "＝＝台灣加權指數研究＝＝\n併入",
    )

    screening = {
        "status": "success",
        "payload": [
            {"mark_key": "market", "html": "大盤", "picks": []},
            {"mark_key": "leave_zero", "html": "黃金", "picks": []},
            {"mark_key": "ma60_lower", "html": "紅箭", "picks": []},
        ],
        "message": "x",
        "results": {},
    }
    assert runner._push_screening(
        screening,
        as_of="20261010",
        morning_digest=True,
        pipeline_run_date="screen-20261010",
    )
    assert not any("加權指數研究" in t for t in sent)
    assert not any("資金輪動" in t for t in sent)
    assert not any("月營收" in t for t in sent)
    assert not any("RADAR" in t for t in sent)


def test_push_screening_morning_keeps_session_cards(monkeypatch):
    """圖必留且先於文字：美股／電子盤／恐懼貪婪走 _push_morning_session_cards。"""
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20261013"
    runner.chat_id = "9001"
    order = []

    def _send_report(_s, _x, chat_id=None):
        order.append(("text", chat_id))
        return True

    runner.bot = type(
        "B",
        (),
        {
            "send_screening_report": _send_report,
            "send_market_session_cards_to_chat": lambda *a, **k: None,
        },
    )()
    runner.send_telegram_message = lambda *a, **k: True
    runner._format_watch_radar_section = lambda uid="": ""
    runner._run_ai_desk = lambda *a, **k: {}
    runner._family_chat_ids = lambda: ["9001"]
    runner._mark_pipeline = lambda *a, **k: None
    monkeypatch.setattr("money_flow.format_sector_rotation_html", lambda *_a, **_k: "")
    monkeypatch.setattr("fundamentals.format_hot_revenue_html", lambda *_a, **_k: "")
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False})
    monkeypatch.setattr("screen_review.score_screen_picks", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.score_ai_fills", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.adapt_bucket_weights", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "morning_digest.build_morning_opening_html",
        lambda *_a, **_k: "環境",
    )
    monkeypatch.setattr(
        "main_runner.MainRunner._push_morning_session_cards",
        lambda self, cid, us_snap=None: order.append(("cards", cid)),
    )
    screening = {
        "status": "success",
        "payload": [{"mark_key": "market", "html": "大盤", "picks": []}],
        "message": "x",
        "results": {},
    }
    assert runner._push_screening(
        screening, as_of="20261010", morning_digest=True, pipeline_run_date="screen-20261010"
    )
    assert order == [("cards", "9001"), ("text", "9001")]


def test_push_screening_morning_cards_before_text_both_family(monkeypatch):
    """兩人白名單：每人同一輪先圖後文，不交叉亂序。"""
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20261013"
    runner.chat_id = "9001"
    order = []

    def _send_report(_s, _x, chat_id=None):
        order.append(("text", chat_id))
        return True

    runner.bot = type("B", (), {"send_screening_report": _send_report})()
    runner.send_telegram_message = lambda *a, **k: True
    runner._format_watch_radar_section = lambda uid="": ""
    runner._run_ai_desk = lambda *a, **k: {}
    runner._family_chat_ids = lambda: ["9001", "8772209416"]
    runner._mark_pipeline = lambda *a, **k: None
    monkeypatch.setattr("money_flow.format_sector_rotation_html", lambda *_a, **_k: "")
    monkeypatch.setattr("fundamentals.format_hot_revenue_html", lambda *_a, **_k: "")
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False})
    monkeypatch.setattr("screen_review.score_screen_picks", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.score_ai_fills", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.adapt_bucket_weights", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "morning_digest.build_morning_opening_html",
        lambda *_a, **_k: "環境",
    )
    monkeypatch.setattr(
        "main_runner.MainRunner._push_morning_session_cards",
        lambda self, cid, us_snap=None: order.append(("cards", cid)),
    )
    screening = {
        "status": "success",
        "payload": [{"mark_key": "market", "html": "大盤", "picks": []}],
        "message": "x",
        "results": {},
    }
    assert runner._push_screening(
        screening, as_of="20261010", morning_digest=True, pipeline_run_date="screen-20261010"
    )
    assert order == [
        ("cards", "9001"),
        ("text", "9001"),
        ("cards", "8772209416"),
        ("text", "8772209416"),
    ]


def test_push_screening_non_morning_skips_session_cards(monkeypatch):
    """非早報路徑不寄大盤附圖。"""
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20261013"
    runner.chat_id = "9001"
    cards = []
    runner.bot = type(
        "B",
        (),
        {"send_screening_report": lambda _s, _x, chat_id=None: True},
    )()
    runner.send_telegram_message = lambda *a, **k: True
    runner._format_watch_radar_section = lambda uid="": ""
    runner._run_ai_desk = lambda *a, **k: {}
    runner._family_chat_ids = lambda: ["9001"]
    runner._mark_pipeline = lambda *a, **k: None
    monkeypatch.setattr("money_flow.format_sector_rotation_html", lambda *_a, **_k: "")
    monkeypatch.setattr("fundamentals.format_hot_revenue_html", lambda *_a, **_k: "")
    monkeypatch.setattr("taiwan_market.format_taiwan_market_brief_html", lambda *_a, **_k: "")
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False})
    monkeypatch.setattr("screen_review.score_screen_picks", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.score_ai_fills", lambda *_a, **_k: None)
    monkeypatch.setattr("screen_review.adapt_bucket_weights", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "main_runner.MainRunner._push_morning_session_cards",
        lambda self, cid, us_snap=None: cards.append(cid),
    )
    screening = {
        "status": "success",
        "payload": [{"mark_key": "market", "html": "大盤", "picks": []}],
        "message": "x",
        "results": {},
    }
    assert runner._push_screening(screening, as_of="20261010", morning_digest=False)
    assert cards == []
