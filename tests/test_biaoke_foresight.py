# -*- coding: utf-8 -*-
"""洞燭先機：先掃 1709＋官方日K，再進神經元。不是逐檔發明。"""
from biaoke_foresight import METHOD_BODY, doubt_line, field_line, hold_line
from biaoke_mind import format_methods_html, method_body
from biaoke_facts import names_in_ask


def test_how_is_pattern_not_one_stock():
    body = method_body("洞燭先機")
    assert "很少人提" in body
    assert "次族群第一名" in body
    assert "236" in body
    assert "1000" in body
    assert "台塑四寶" in body
    assert "對不到" in body
    assert METHOD_BODY.startswith("洞燭先機")


def test_fancheng_official_236_to_1000():
    hold = hold_line("6830")
    assert "236" in hold
    assert "1000" in hold
    assert "885" in hold
    assert "很少人提" in hold
    assert field_line("6830")
    assert "1000" in doubt_line("6830")


def test_formosa_group_not_sibao_in_corpus():
    html = format_methods_html("台塑四寶他怎麼講")
    assert "對不到" in html
    assert "台塑化" in html or "南亞" in html
    assert "四寶" in html
    assert names_in_ask("台塑怎麼看")[0][0] == "1301"
    assert names_in_ask("台塑化怎麼看")[0][0] == "6505"
    assert "四寶" in hold_line("1301") or "對不到" in hold_line("1301")


def test_nanya_and_drone_are_cases_not_new_neurons():
    assert "217" in hold_line("1303")
    assert "對不到" in hold_line("1303")
    assert "不要再碰" in hold_line("5371")
    assert "272" in hold_line("8033")
    assert hold_line("2383") == ""


def test_sep10_battlefield_quotes_flag_without_formula():
    from biaoke_foresight import battle_line
    from biaoke_mind import format_methods_html, method_body

    body = method_body("9/10 主戰場")
    assert "散熱" in body and "強勢" in body
    assert "7/30" in body and "9/1" in body
    assert "下飄旗" in body
    assert "不透漏" in body
    assert "旗型公式" in body
    html = format_methods_html("下飄旗型整理多久")
    assert "不透漏" in html
    assert "13日" not in html
    assert "等幅" not in html
    assert battle_line("3017")
    assert "散熱" in battle_line("3017")
    assert "破線" in battle_line("3081")
    assert "不透漏" in battle_line("3081")
