# -*- coding: utf-8 -*-
"""飆客貫通：點位家族、產業輪動、同一檔從第一次點名串到最近。"""
from __future__ import annotations

from biaoke_mind import format_methods_html
from biaoke_weave import is_weave_query, weave_counts, weave_lookup
from biaoke_why import lookup


def test_weave_covers_named_stocks():
    counts = weave_counts()
    assert counts["n_stocks"] >= 20
    assert counts["n_masters"] >= 10


def test_weave_system_is_one_operating_system():
    body = lookup("把他全部貫通")
    assert "產業趨勢" in body
    assert "細微波" in body
    assert "量先價行" in body
    assert "買跌不買漲" in body
    assert "散熱" in body
    assert "48218" in body
    assert is_weave_query("把他全部貫通")


def test_weave_index_levels_are_one_structure():
    body = lookup("這些點位怎麼連")
    for x in ("39385", "48218", "45839", "47578", "46506"):
        assert x in body, x
    assert "位階二" in body
    assert "不是五個孤立" in body or "同一組結構" in body


def test_weave_emc_connects_family_not_isolated():
    body = lookup("台光電")
    assert "2026-04-16" in body or "可抱到明年" in body
    assert "聯亞" in body
    assert "3930" in body or "7/29" in body or "7/30" in body
    assert "建築" in body
    assert "沒點名" in body


def test_weave_rotation_timeline():
    body = lookup("現在主流資金輪動")
    assert "散熱" in body
    assert "記憶體" in body
    assert "聯亞" in body or "風向球" in body


def test_methods_html_weaves_through_line():
    html = format_methods_html("把他全部貫通")
    assert "產業趨勢" in html
    assert "量先價行" in html
    note = weave_lookup("台光電")
    assert "護城河" in note or "買跌" in note


def test_weave_keeps_wrong_and_right():
    body = lookup("他改口過什麼")
    assert "40000" in body or "不破 40000" in body
    assert "39385" in body
    assert "及時修正" in body


def test_weave_leader_follow():
    body = lookup("龍頭怎麼跟漲")
    assert "聯亞" in body
    assert "奇鋐" in body
    assert "風向球" in body or "誰先過前高" in body


def test_weave_opening_verified():
    body = lookup("開口之後對不對")
    assert "記憶體" in body
    assert "20 日" in body or "20日" in body
    assert "背離" in body


def test_weave_stock_picks_subject_not_incidental():
    body = lookup("台光電")
    assert "同族一起判" in body or "金像電" in body
    assert "後續對" in body or "護城河" in body
    assert "3-4浪" not in body
    assert "3-4 浪" not in body
    note = weave_lookup("台光電")
    assert "滿足" in note or "350" in note or "護城河" in note


def test_weave_lianya_flip_kept():
    body = lookup("聯亞改口過沒")
    assert "出清" in body
    assert "風向球" in body


def test_weave_same_night_is_one_judgment():
    body = lookup("9/11那晚怎麼串")
    assert "46506" in body or "45839" in body
    assert "聯亞" in body
    assert "同一晚" in body or "同一條判斷" in body
