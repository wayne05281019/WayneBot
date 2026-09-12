# -*- coding: utf-8 -*-
from biaoke_judge import format_judge_html, format_judge_notes, leader_of
from biaoke_mind import match_methods


def test_optical_followers_look_at_lianya():
    sid, name, why = leader_of("", "6442", "光聖")
    assert sid == "3081"
    assert name == "聯亞"
    assert "龍頭" in why


def test_wave_is_for_index_not_stock():
    hits = match_methods("波浪理論可以拿來看個股嗎")
    assert hits
    body = hits[0][1]
    assert "解大盤難度更高" in body or "很少用波浪" in body
    assert "不講死" in body or "一驗再驗" in body
    assert "提早規劃" in body


def test_judge_notes_are_materials_not_a_form():
    notes = format_judge_notes(
        {
            "sid": "6442",
            "name": "光聖",
            "in_corpus": True,
            "struct": {
                "date": "2026-09-11",
                "close": 100,
                "spike_date": "2026-08-01",
                "spike_high": 120,
                "spike_low": 90,
                "shrinking": True,
                "above_support": True,
            },
            "leader": {
                "sid": "3081",
                "name": "聯亞",
                "why": "同族跟漲先看龍頭",
                "struct": {"close": 2850, "shrinking": False, "above_support": True},
            },
            "pace": "這族要先看龍頭現在攻還是休息。",
        }
    )
    assert "材料" in notes
    assert "3081" in notes
    assert "聯亞" in notes
    assert "現況：" not in notes
    html = format_judge_html(
        {
            "sid": "6442",
            "name": "光聖",
            "in_corpus": True,
            "struct": {
                "date": "2026-09-11",
                "close": 100,
                "pct": 1.2,
                "spike_date": "2026-08-01",
                "spike_high": 120,
                "spike_low": 90,
                "stance": "量縮且收在爆大量日低點之上。",
            },
            "leader": {"sid": "3081", "name": "聯亞", "why": "同族跟漲先看龍頭"},
            "pace": "這族要先看龍頭。",
        }
    )
    assert "光聖" in html
    assert "聯亞" in html
    assert "爆大量日" in html
    assert "現況／量價" not in html
