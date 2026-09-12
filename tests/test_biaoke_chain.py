# -*- coding: utf-8 -*-
"""飆大神經元鏈：六顆按他的推論順序，不是關鍵字拼盤。"""
import os

from biaoke_chain import (
    NEURON_IDS,
    chain_order_ok,
    fire_chain,
    format_chain_notes,
)
from biaoke_live import SYSTEM, live_notes


def test_system_requires_neuron_chain():
    assert "神經元必須串" in SYSTEM
    assert "優先於舊文" in SYSTEM
    assert "大盤巢穴" in SYSTEM
    assert "長抱還是進出" in SYSTEM
    assert "圖是第④顆" in SYSTEM or "第④顆" in SYSTEM
    assert "演算" in SYSTEM
    assert "不是預測保證" in SYSTEM or "不是保證" in SYSTEM


def test_chain_six_neurons_in_order_for_emc():
    notes = format_chain_notes("", "台光電 7 月抄底為什麼能抱到明年")
    assert "神經元鏈" in notes
    assert chain_order_ok(notes)
    fired = fire_chain("", "台光電 7 月抄底為什麼能抱到明年")
    assert fired["sid"] == "2383"
    ids = [s["id"] for s in fired["steps"]]
    assert ids == list(NEURON_IDS)
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "勿輕易調整" in hold["text"]
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "不數" in nest["text"] or "不數" in notes
    think = fired["think"]
    assert "巢穴" in think or "覆巢" in think or "大盤" in think
    assert "長抱" in think or "勿輕易調整" in hold["text"]


def test_chain_mediatek_is_not_april16_hold():
    fired = fire_chain("", "聯發科他有看好嗎")
    assert fired["sid"] == "2454"
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    blob = hold["text"] + fired["think"]
    assert "4/16" in blob or "不是" in blob
    assert "IC 設計" in blob or "尚未納入" in blob or "不在" in blob
    notes = format_chain_notes("", "聯發科他有看好嗎")
    assert chain_order_ok(notes)
    assert "演算" in notes


def test_chain_market_skips_stock_tape():
    fired = fire_chain("", "目前大盤是屬於哪個位階 以波浪來看的話")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    assert tape.get("skip") is True
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "覆巢" in nest["text"]
    assert "不數" in nest["text"] or "個股" in nest["text"]


def test_live_notes_puts_chain_before_keyword_hits():
    from biaoke_desk import load_corpus_cache_clear

    load_corpus_cache_clear()
    note = live_notes("", "台光電 7 月抄底為什麼能抱到明年")
    assert "神經元鏈" in note
    assert note.find("神經元鏈") < note.find("方法")
    assert chain_order_ok(note)
    assert "3930" in note
    mtk = live_notes("", "聯發科他有看好嗎")
    assert "神經元鏈" in mtk
    assert "2454" in mtk


def test_chain_real_quotes_when_db_present():
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    fired = fire_chain(db, "台光電怎麼看")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    if not tape.get("ok"):
        return
    assert "4510" in tape["text"] or "壓" in tape["text"]
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "官方加權" in nest["text"]
    assert "圖上演算" in tape["text"]
    assert "不是保證" in tape["text"] or "演算" in fired["think"]


def test_field_does_not_repeat_hold_neuron():
    """產業是第 2 顆，長抱／F10／聯發科名單是第 5 顆，不要兩顆貼同一段。"""
    fired = fire_chain("", "聯發科他有看好嗎")
    field = next(s for s in fired["steps"] if s["id"] == "field")
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "主力露餡" not in field["text"]
    assert "F10 系列" not in field["text"]
    assert "4/16" in hold["text"] or "尚未納入" in hold["text"]
    emc = fire_chain("", "台光電 7 月抄底為什麼能抱到明年")
    emc_field = next(s for s in emc["steps"] if s["id"] == "field")
    emc_hold = next(s for s in emc["steps"] if s["id"] == "hold")
    assert "產業趨勢" in emc_field["text"]
    assert "勿輕易調整" in emc_hold["text"]
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    live = fire_chain(db, "聯發科怎麼看")
    live_field = next(s for s in live["steps"] if s["id"] == "field")
    live_hold = next(s for s in live["steps"] if s["id"] == "hold")
    assert "主力露餡" not in live_field["text"]
    assert "半導體" in live_field["text"] or "產業" in live_field["text"]
    assert "4/16" in live_hold["text"]
    emc_live = fire_chain(db, "台光電怎麼看")
    rot = next(s for s in emc_live["steps"] if s["id"] == "field")["text"]
    assert rot.count("電子零組件業") <= 1


def test_self_leader_defers_ohlc_to_tape():
    """自己就是龍頭時，第 3 顆不重貼第 4 顆的官方高低。"""
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        fired = fire_chain("", "台光電 7 月抄底為什麼能抱到明年")
        leader = next(s for s in fired["steps"] if s["id"] == "leader")
        assert "自己就是" in leader["text"]
        return
    fired = fire_chain(db, "台光電怎麼看")
    leader = next(s for s in fired["steps"] if s["id"] == "leader")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    assert "自己就是" in leader["text"]
    assert "留給第 4 顆" in leader["text"] or "不另對" in leader["text"]
    assert "4510" not in leader["text"]
    assert "4510" in tape["text"]
    follow = fire_chain(db, "智原怎麼看")
    if follow.get("sid") != "3035":
        return
    lead = next(s for s in follow["steps"] if s["id"] == "leader")
    assert "2454" in lead["text"] or "聯發科" in lead["text"]
    assert "爆量日" in lead["text"] or "收" in lead["text"]
