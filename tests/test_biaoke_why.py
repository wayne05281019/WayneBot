# -*- coding: utf-8 -*-
"""飆客逐則自問自答：點位對官方 K，不准念稿、不准編起點。"""
from __future__ import annotations

from biaoke_archive import load_bundled_archive, load_bundled_club
from biaoke_mind import format_methods_html
from biaoke_why import is_why_query, lookup, why_counts


def test_why_index_covers_public_and_club():
    counts = why_counts()
    blob = load_bundled_archive()
    club = load_bundled_club()
    assert counts["n"] >= int(blob.get("n") or 0)
    assert counts["n_club"] >= int(club.get("n") or 0)
    assert counts["n_cards"] >= 1700 + 90
    assert counts["n_topics"] >= 10


def test_why_46506_is_tx_sep10_low():
    body = lookup("46506 怎麼來")
    assert "46506" in body
    assert "20260910" in body or "2026-09-10" in body
    assert "台指" in body
    assert "日盤" in body
    assert "不是加權" in body or "46573" in body
    assert "不數" in body or "沒 15" in body


def test_why_47578_is_twii_sep8_high():
    body = lookup("47578 怎麼來")
    assert "47578" in body
    assert "20260908" in body or "2026-09-08" in body or "9/8" in body
    assert "加權" in body
    assert "位階二" in body
    assert "48218" in body


def test_why_fifth_wave_not_pinned():
    body = lookup("第五波起頭在哪")
    assert "改口" in body
    assert "不准編" in body or "沒標" in body
    assert "2025-12-03" in body
    assert "2026-07-07" in body
    assert "起點" in body


def test_why_building_two_not_named():
    body = lookup("建築兩檔是哪兩檔")
    assert "沒點名" in body
    assert "漢唐" in body
    assert "聖暉" in body


def test_why_fuqiao_and_heat_leaders():
    fu = lookup("富喬為什麼有潛力")
    assert "上游材料" in fu
    assert "首選富喬" in fu or "富喬應該是首選" in fu
    heat = lookup("奇鋐、健策為什麼是長線主流")
    assert "次族群" in heat or "誰先過前高" in heat
    assert "3595" in heat or "創新高" in heat


def test_why_rejects_alien_voice():
    body = lookup("模糊的精確和和碩仁寶利息")
    assert "不是飆客" in body
    assert "和碩" not in body or "不拿來" in body


def test_methods_html_uses_why_chain():
    html = format_methods_html("46506 怎麼來")
    assert "台指" in html
    assert "20260910" in html or "2026-09-10" in html
    html2 = format_methods_html("台光電為何能這麼篤定")
    assert "2026-04-16" in html2
    assert "3930" in html2
    assert "不是把波浪套在 2383" in html2 or "產業趨勢" in html2
    assert is_why_query("下降軌怎麼畫")


def test_colloquial_questions_still_hit_chain():
    assert is_why_query("那檔還能不能抱")
    assert is_why_query("晚上那則在講什麼")
    body = lookup("晚上那則在講什麼")
    assert "46506" in body or "最近三篇" in body
    body2 = lookup("他最近在看什麼")
    assert "最近三篇" in body2 or "護城河" in body2 or "細微波" in body2


def test_live_notes_puts_why_chain_first():
    from biaoke_live import live_notes

    note = live_notes("", "46506 怎麼來")
    assert "判斷鏈" in note
    assert "台指" in note
    assert "20260910" in note or "2026-09-10" in note
    note2 = live_notes("", "建築兩檔是哪兩檔")
    assert "沒點名" in note2
    assert "漢唐" in note2
