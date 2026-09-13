# -*- coding: utf-8 -*-
"""圖文時間軸第一段：最早有附圖的公開文，對圖、官方沒柱就標缺。"""
from biaoke_chrono import line_for, next_start, overview, slice_stop
from biaoke_charts import official_on
from biaoke_mind import format_methods_html, method_body
from biaoke_facts import names_in_ask


def test_first_slice_stops_jan4_2024():
    assert slice_stop() == "2024-01-04"
    assert next_start() == "2024-01-05"
    body = method_body("圖文時間軸第一段")
    assert "2023-12-19" in body
    assert "2024-01-04" in body
    assert "2024-01-05" in body
    assert "官方庫日K從 2025-02-20" in body or "沒柱" in body


def test_zhiyuan_wanhai_xinxing_from_charts_not_invented_k():
    db = "data/wayne_market.db"
    assert official_on(db, "3035", "20231219") == {}
    assert official_on(db, "2615", "20231220") == {}
    assert official_on(db, "2605", "20231222") == {}
    z = line_for("3035")
    assert "智原" in z
    assert "396" in z
    assert "不要再操作智原" in z
    assert "沒日K" in z
    assert "不准編" in z
    w = line_for("2615")
    assert "突破頸線" in w
    assert "破底翻" in w
    x = line_for("2605")
    assert "下飄旗" in x
    assert "一年半" in x
    assert "教學圖" in x
    assert "6239" in x and "不准把索引誤標" in x
    assert line_for("2454") == ""
    assert "抱著波段賺更多" in overview() and "對不到" in overview()


def test_methods_html_and_names():
    html = format_methods_html("智原那張圖為什麼貼")
    assert "圖文時間軸" in method_body("圖文時間軸第一段") or "abc" in html or "396" in html
    assert names_in_ask("萬海怎麼看")[0][0] == "2615"
    assert names_in_ask("智原怎麼看")[0][0] == "3035"
    flag = format_methods_html("下飄旗型整理多久")
    assert "不透漏" in flag
    assert "13日" not in flag


def test_chain_zhiyuan_uses_chrono():
    from biaoke_chain import fire_chain

    fired = fire_chain("", "智原那張圖為什麼貼")
    assert fired["sid"] == "3035"
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    blob = tape["text"] + fired.get("think", "")
    assert "396" in blob or "不要再操作智原" in blob
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "不要再操作智原" in hold["text"] or "不是 4/16" in hold["text"]
