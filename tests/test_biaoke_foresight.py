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
    assert "S+++" in hold_line("2383")
    assert "3930" in hold_line("2383")
    assert "勿輕易調節" in hold_line("2383")
    assert "4/16" in hold_line("2383")


def test_f4_f10_from_public_chart_not_club_quote():
    """F4／F10 以 1709 附圖＋官方日K 為準；旺矽是 6223。"""
    assert "S+++" in hold_line("2330")
    assert "A+/S-候選" in hold_line("3017") or "S-候選" in hold_line("3017")
    assert "回測" in hold_line("3017")
    assert "7194" in hold_line("3017") or "2490" in hold_line("3017")
    assert "6223" in hold_line("6223")
    assert "6230" in hold_line("6223")
    assert "尼得科" in hold_line("6223")
    assert hold_line("6230") == ""
    assert "出清" in hold_line("6515")
    assert "S+++" in hold_line("2383")
    assert "1265" in hold_line("2383")
    assert "護城河" in field_line("2383") or "CCL" in hold_line("2383")
    assert "4/16" in hold_line("2368")
    assert "不在" in hold_line("2368")
    assert "A-" in hold_line("8210")
    assert "S" in hold_line("2059")
    assert "7769" in hold_line("7769")
    assert "設備" in hold_line("7769")
    html = format_methods_html("F10 是哪幾檔")
    assert "台積電" in html and "川湖" in html and "勤誠" in html
    assert "鴻勁" in html
    assert "尚未納入 F 系列" in html or "還不在 F 系列" in html
    body = method_body("長抱主流／F4→F10／聯發科")
    assert "平台依賴度" in body
    assert "7769" in body


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
    assert "次級四浪" in battle_line("3081")
    assert "強力洗盤" in battle_line("3081")
    assert "穩懋" in battle_line("3105")
    assert "台達電" in battle_line("3105")
    assert "跌停" in battle_line("3653")
    assert "8/21" in battle_line("3017")
    assert "中線多頭" in battle_line("2408")
    assert "光學" in battle_line("3008")
    assert "InP" in battle_line("3008")
    assert "支撐" in battle_line("1815")
    assert "不要亂動" in battle_line("2383")
    assert "ASIC" in battle_line("3443")
    assert "43500" in battle_line("3443")
    assert "43500" in battle_line("3017")


def test_longhold_chain_why_not_f10_or_mediatek():
    from biaoke_foresight import LONGHOLD_SIDS, longhold_why
    from biaoke_chain import fire_chain
    from biaoke_mind import method_body

    why = longhold_why("")
    assert "倒了就是 AI 時代結束" in why
    assert "賣設備" in why
    assert "CoWoS" in why
    assert "台積電" in why and "台達電" in why and "旺矽" in why
    assert "聯發科 2454 不在 4/16" in why
    assert "建築兩檔" in why and "沒點名" in why
    assert "抱著波段賺更多" in why and "對不到" in why
    assert "39385" in why
    assert "3930" in why
    assert LONGHOLD_SIDS == ("2330", "2308", "2383", "6223", "6515", "3017")
    assert longhold_why("2454") == ""
    assert longhold_why("2404") == ""
    assert "倒了就是 AI 時代結束" in hold_line("2383")
    assert "僅次台積電" in hold_line("2383")
    assert "賣設備不行長抱" in hold_line("7769")
    assert "過路費" in hold_line("6223")
    body = method_body("能長抱的產業鏈")
    assert "倒了就是 AI 時代結束" in body
    assert "2454" in body
    fired = fire_chain("", "為什麼這些能長抱")
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert hold.get("skip") is not True
    assert "倒了就是 AI 時代結束" in hold["text"]
    assert "賣設備" in hold["text"]
    mtk = fire_chain("", "聯發科他有看好嗎")
    mh = next(s for s in mtk["steps"] if s["id"] == "hold")
    assert "不是 4/16" in mh["text"] or "不在" in mh["text"]
    assert "可抱到明年" not in mh["text"] or "不是 4/16" in mh["text"]


def test_scan_adds_mediatek_and_lianya_only_when_k_matches():
    """1709 全盤再掃：聯發科／聯亞對上日K才進表；4/22 沒點發哥；不是 4/16。"""
    from biaoke_foresight import case_for, longhold_why, names
    from biaoke_chain import fire_chain
    from biaoke_mind import format_methods_html, method_body
    from biaoke_judge import _hold_note

    assert "聯發科" in names()
    assert "聯亞" in names()
    mtk = hold_line("2454")
    assert "不是 4/16" in mtk
    assert "當天沒點發哥" in mtk or "沒點發哥" in mtk
    assert "創意" in mtk and "力旺" in mtk and "世芯" in mtk
    assert "2295" in mtk
    assert "1895" in mtk
    assert "3630" in mtk
    assert "3875" in mtk
    assert "尚未納入" in mtk or "不敢將發哥列入" in mtk
    assert "可抱到明年" in mtk and "不是 4/16" in mtk
    assert longhold_why("2454") == ""
    assert case_for("3529") is None
    assert case_for("3661") is None
    vane = hold_line("3081")
    assert "風向球" in vane
    assert "不是 4/16" in vane
    assert "出清" in vane
    assert "2010" in vane
    assert "2850" in vane
    assert "沒鎖住" in vane
    assert "建築兩檔" in vane and "沒點名" in vane
    assert "可抱到明年" not in vane or "不是 4/16" in vane
    assert "抱著波段賺更多" not in vane
    body = method_body("洞燭先機")
    assert "當天沒點發哥" in body or "沒點發哥" in body
    assert "矽光子風向球" in body
    html = format_methods_html("聯發科他有看好嗎")
    assert "沒點發哥" in html
    assert "4/16" in html
    note = _hold_note("2454", True)
    assert "沒點發哥" in note
    assert "尚未納入 F 系列" in note or "不敢將發哥列入" in note
    assert "台積電" in note
    fired = fire_chain("", "聯發科他有看好嗎")
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "沒點發哥" in hold["text"]
    assert "不是 4/16" in hold["text"] or "不在" in hold["text"]
    ly = fire_chain("", "聯亞他還看好嗎")
    lh = next(s for s in ly["steps"] if s["id"] == "hold")
    assert "風向球" in lh["text"]
    assert "出清" in lh["text"]
    assert "沒鎖住" in lh["text"] or "對跟錯" in lh["text"]
