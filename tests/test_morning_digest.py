# -*- coding: utf-8 -*-
"""06:30 早報彙整：提醒＋大盤＋加權研究合成、不再另寄加權。"""
from __future__ import annotations

from morning_digest import (
    apply_morning_opening_to_screening,
    build_morning_opening_html,
)


def test_build_morning_opening_merges_brief_and_outlook(monkeypatch):
    outlook = "＝＝大盤狀況＝＝\n<b>WayneBot 海選</b>\n美股　偏空"
    brief = "＝＝台灣加權指數研究＝＝\n收盤　46500"
    monkeypatch.setattr(
        "taiwan_market.format_taiwan_market_brief_html",
        lambda *_a, **_k: brief,
    )
    monkeypatch.setattr(
        "morning_digest._foreign_sell_observe_line",
        lambda *_a, **_k: (
            "<b>環境觀察｜觀察／預警（測試）</b>\n"
            "開盤前恐懼：現在關著\n確認：現在不算數\n冷靜：現在不算數"
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
    assert "環境觀察｜觀察／預警（測試）" in merged
    assert "確認：現在不算數" in merged
    assert "近窗" not in merged
    assert "今無" not in merged and "非買訊" not in merged
    assert "買進" not in merged


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
    assert out["payload"][1]["html"] == "桶"


def test_push_screening_morning_skips_separate_brief(monkeypatch):
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20261013"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": lambda _s, _x, chat_id=None: True})()
    sent = []
    runner.send_telegram_message = lambda text, chat_id=None: sent.append(text) or True
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
        lambda *_a, **_k: "＝＝台灣加權指數研究＝＝\n併入",
    )

    screening = {
        "status": "success",
        "payload": [{"mark_key": "market", "html": "大盤", "picks": []}],
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
