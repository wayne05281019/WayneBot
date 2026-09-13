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
    assert "附圖索引" in SYSTEM
    assert "會改口" in SYSTEM
    assert "演算" in SYSTEM
    assert "不是預測保證" in SYSTEM or "不是保證" in SYSTEM
    assert "重讀" in SYSTEM


def test_chain_six_neurons_in_order_for_emc():
    notes = format_chain_notes("", "台光電 7 月抄底為什麼能抱到明年")
    assert "神經元鏈" in notes
    assert chain_order_ok(notes)
    fired = fire_chain("", "台光電 7 月抄底為什麼能抱到明年")
    assert fired["sid"] == "2383"
    ids = [s["id"] for s in fired["steps"]]
    assert ids == list(NEURON_IDS)
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "勿輕易調節" in hold["text"]
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "不數" in nest["text"] or "不數" in notes
    think = fired["think"]
    assert "巢穴" in think or "覆巢" in think or "大盤" in think
    assert "長抱" in think or "勿輕易調節" in hold["text"]


def test_chain_nanya_1303_is_not_nanya_tech():
    fired = fire_chain("", "南亞怎麼看")
    assert fired["sid"] == "1303"
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    doubt = next(s for s in fired["steps"] if s["id"] == "doubt")
    blob = hold["text"] + doubt["text"] + fired["think"]
    assert "2408" in hold["text"]
    assert "不是南亞科" in hold["text"] or "不是 4/16" in hold["text"]
    assert "217" in blob
    assert "出清" in blob
    assert "台塑" in hold["text"]
    assert "PCB" in hold["text"] or "AI 材料" in hold["text"]
    assert "適合上班族長期抱" in hold["text"]
    assert "對不到" in hold["text"]
    assert "上班族可積極" not in hold["text"]
    tech = fire_chain("", "南亞科怎麼看")
    assert tech["sid"] == "2408"
    tech_hold = next(s for s in tech["steps"] if s["id"] == "hold")
    assert "217" not in tech_hold["text"]
    office = fire_chain("", "南亞為什麼適合上班族長期抱")
    assert office["sid"] == "1303"
    office_hold = next(s for s in office["steps"] if s["id"] == "hold")
    assert "對不到" in office_hold["text"]
    assert "217" in office_hold["text"]
    notes = format_chain_notes("", "南亞怎麼看")
    assert chain_order_ok(notes)
    assert "1303" in notes


def test_chain_sep10_cooling_and_optical_break():
    cool = fire_chain("", "奇鋐散熱目前還強嗎")
    assert cool["sid"] == "3017"
    field = next(s for s in cool["steps"] if s["id"] == "field")
    assert "散熱" in field["text"]
    assert "強勢" in field["text"]
    optical = fire_chain("", "光通訊破線代表什麼")
    field_o = next(s for s in optical["steps"] if s["id"] == "field")
    blob = field_o["text"] + optical["think"]
    assert "7/30" in blob or "破線" in blob
    assert "下飄旗" in blob
    assert "不透漏" in blob
    flag = fire_chain("", "下飄旗型整理多久")
    ff = next(s for s in flag["steps"] if s["id"] == "field")
    assert "不透漏" in ff["text"]
    assert "旗型公式" in ff["text"]
    assert "13" not in ff["text"] or "不透漏" in ff["text"]


def test_chain_foresight_fancheng_and_formosa_group():
    fired = fire_chain("", "汎銓怎麼從兩百多到一千")
    assert fired["sid"] == "6830"
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    field = next(s for s in fired["steps"] if s["id"] == "field")
    blob = hold["text"] + field["text"] + fired["think"]
    assert "236" in blob
    assert "1000" in blob
    assert "很少人提" in blob
    assert "新聞變多" in hold["text"] or "新聞變多" in fired["think"]
    formosa = fire_chain("", "台塑四寶他怎麼講")
    hold_f = next(s for s in formosa["steps"] if s["id"] == "hold")
    blob_f = hold_f["text"] + formosa["think"]
    assert "四寶" in blob_f
    assert "對不到" in blob_f
    assert "台塑化" in blob_f or "南亞" in blob_f
    drone = fire_chain("", "中光電無人機為什麼能早看到後來又出清")
    assert drone["sid"] == "5371"
    dh = next(s for s in drone["steps"] if s["id"] == "hold")
    assert "半山腰" in dh["text"]
    assert "不要再碰" in dh["text"]


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


def test_chain_lianya_is_vane_not_april16_hold():
    fired = fire_chain("", "聯亞他還看好嗎")
    assert fired["sid"] == "3081"
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    blob = hold["text"] + fired["think"]
    assert "風向球" in blob
    assert "4/16" in blob
    assert "出清" in blob or "對跟錯" in blob
    assert "可抱到明年" not in hold["text"] or "不是 4/16" in hold["text"]


def test_chain_market_skips_stock_tape():
    fired = fire_chain("", "目前大盤是屬於哪個位階 以波浪來看的話")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    assert tape.get("skip") is True
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "覆巢" in nest["text"]
    assert "不數" in nest["text"] or "個股" in nest["text"]
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    live = fire_chain(db, "目前大盤是屬於哪個位階 以波浪來看的話")
    think = live["think"]
    assert "45839" in think
    assert "47578" in think
    assert live["sid"] == ""
    nest_live = next(s for s in live["steps"] if s["id"] == "nest")
    assert "9/16" in nest_live["text"]
    assert "還在等 9/16" in nest_live["text"]
    assert "9/16" in think


def test_live_notes_puts_chain_before_keyword_hits():
    from biaoke_desk import load_corpus_cache_clear

    load_corpus_cache_clear()
    note = live_notes("", "台光電 7 月抄底為什麼能抱到明年")
    assert "神經元鏈" in note
    if "方法" in note:
        assert note.find("神經元鏈") < note.find("方法")
    assert chain_order_ok(note)
    assert "3930" in note
    mtk = live_notes("", "聯發科他有看好嗎")
    assert "神經元鏈" in mtk
    assert "2454" in mtk


def test_chained_live_notes_skip_stale_keyword_hits():
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    note = live_notes(db, "台光電怎麼看")
    assert "神經元鏈" in note
    assert "關鍵字命中" not in note
    assert "4510" in note


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
    assert "45839" in nest["text"]
    assert "46184" in nest["text"] or "官方收" in nest["text"]
    assert "46506" in nest["text"]
    assert "47578" in nest["text"]
    assert "單靠" in nest["text"] or "還沒過" in nest["text"]
    assert "台積電官方" in nest["text"]
    assert "不數這檔段" in nest["text"]
    assert "費半" in nest["text"]
    assert "那指" in nest["text"]
    assert "不准編" in nest["text"] or "這路先當缺" in nest["text"] or "隔夜官方" in nest["text"]
    assert "9/16" in nest["text"]
    assert "Fed" in nest["text"] or "FED" in nest["text"]
    assert "不是看新聞" in nest["text"]
    assert "還在等 9/16" in nest["text"]
    assert "9/16" in fired["think"]


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
    assert "勿輕易調節" in emc_hold["text"]
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
    assert "產業趨勢還在不在" in rot
    assert "護城河" in rot
    assert "第五波" in rot
    assert "主力露餡" not in rot
    assert "F10 系列" not in rot


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


def test_tape_does_not_repeat_hold_or_field():
    """第 4 顆只留官方量價／演算；長抱、半山腰、產業資金不重貼。"""
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    fired = fire_chain(db, "台光電怎麼看")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    field = next(s for s in fired["steps"] if s["id"] == "field")
    assert "4510" in tape["text"]
    assert "3930" in tape["text"]
    assert "圖上演算" in tape["text"]
    assert "勿輕易調節" not in tape["text"]
    assert "長線龍頭" not in tape["text"]
    assert "流出前段" not in tape["text"]
    assert "勿輕易調節" in hold["text"]
    assert "流出前段" in field["text"] or "電子零組件" in field["text"]
    mtk = fire_chain(db, "聯發科怎麼看")
    mt = next(s for s in mtk["steps"] if s["id"] == "tape")
    mh = next(s for s in mtk["steps"] if s["id"] == "hold")
    assert "只做隔日沖" not in mt["text"]
    assert "半山腰" in mh["text"]
    assert "4/16" in mh["text"]


def test_think_chains_45839_and_self_leader():
    """推論句要串巢穴官方 45839 和自己就是龍頭，不是只寫點位有了。"""
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    fired = fire_chain(db, "台光電怎麼看")
    think = fired["think"]
    assert "45839" in think
    assert "46506" in think
    assert "47578" in think
    assert "自己就是這族龍頭" in think
    assert "勿輕易調節" in think
    assert "5365" in think
    assert "4510" in think
    assert "3930" in think
    doubt = next(s for s in fired["steps"] if s["id"] == "doubt")
    assert "費半" in doubt["text"]
    assert "台積電官方量價" in think or "台積電" in think
    assert "費半" in think
    mtk = fire_chain(db, "聯發科怎麼看")
    assert "自己就是這族龍頭" in mtk["think"]
    assert "4/16" in mtk["think"] or "半山腰" in mtk["think"]
    follow = fire_chain(db, "智原怎麼看")
    if follow.get("sid") == "3035":
        assert "聯發科" in follow["think"] or "2454" in follow["think"]
        assert "這族龍頭是" in follow["think"]
    assert "那指" in think
    assert "9/16" in think


def test_pointed_calendar_retracts_after_sep16():
    from biaoke_chain import _pointed_calendar

    before = _pointed_calendar("", "20260911")
    assert "還在等 9/16" in before
    assert "不是看新聞" in before
    after = _pointed_calendar("data/wayne_market.db", "20260916")
    assert "已過" in after
    assert "不准編新聞" in after or "不准編" in after
    assert "回撤" in after
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    assert "奇鋐" in after or "聯亞" in after or "新高檔官方日K" in after


def test_chain_rereads_his_views_without_keyword_ask():
    """怎麼看也要重讀他的說法，不是等關鍵字才貼。"""
    notes = format_chain_notes("", "台光電怎麼看")
    assert "神經元鏈" in notes
    assert "他的看法" in notes
    assert "個股先看產業趨勢" in notes
    assert "量先價行" in notes
    assert "四路對質" in notes
    assert "長抱主流" in notes
    assert "他點的日曆" in notes
    fired = fire_chain("", "台光電怎麼看")
    field = next(s for s in fired["steps"] if s["id"] == "field")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "產業趨勢還在不在" in field["text"]
    assert "護城河" in field["text"]
    if tape.get("ok"):
        assert "價穩量縮" in tape["text"] or "量先價行" in tape["text"] or "圖上演算" in tape["text"]
    assert "勿輕易調節" in hold["text"]
    assert "主力露餡" not in field["text"]


def test_hold_reads_only_this_uid_lot(tmp_path):
    """有持股只對這人倉；不改倉、不看別人倉。"""
    from wayne_db import add_to_portfolio, ensure_core_schema, get_user_portfolio

    db = str(tmp_path / "hold.db")
    ensure_core_schema(db)
    add_to_portfolio(db, "u-wayne", "2383", "台光電", 10, 3900)
    add_to_portfolio(db, "u-bro", "2454", "聯發科", 2, 4000)
    wayne = fire_chain(db, "台光電怎麼看", uid="u-wayne")
    bro = fire_chain(db, "台光電怎麼看", uid="u-bro")
    wh = next(s for s in wayne["steps"] if s["id"] == "hold")["text"]
    bh = next(s for s in bro["steps"] if s["id"] == "hold")["text"]
    assert "這人持股有這檔" in wh
    assert "這人持股有這檔" not in bh
    assert "不准改別人倉" in wh
    lots = get_user_portfolio(db, "u-wayne")
    assert lots and float(lots[0]["shares"]) == 10
    other = get_user_portfolio(db, "u-bro")
    assert other and str(other[0]["stock_code"]) == "2454"


def test_tape_and_hold_read_chart_index_for_emc():
    fired = fire_chain("", "台光電怎麼看")
    assert fired["sid"] == "2383"
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "他的附圖對官方日K" in tape["text"]
    assert "平台依賴度" in tape["text"] or "紅框" in tape["text"]
    assert "他的附圖（長抱／F10）" in hold["text"]
    notes = format_chain_notes("", "台光電怎麼看")
    assert "公開附圖對官方日K" in notes
    assert "社團附圖只對價" in notes
    mkt = fire_chain("", "目前大盤是屬於哪個位階 以波浪來看的話")
    tape_m = next(s for s in mkt["steps"] if s["id"] == "tape")
    assert tape_m.get("skip") is True
    assert "他的附圖對官方日K" not in str(tape_m.get("text") or "")


def test_twentyseventh_chain_unnamed_dump_buy():
    fired = fire_chain("", "急殺買")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "急殺買" in blob
    assert "不是日K" in blob
    assert "71.3" in blob or "70.4" in blob
    assert "雷虎" in blob or "晟銘電" in blob


def test_twentyeighth_chain_unnamed_pullback():
    fired = fire_chain("", "剛好止漲回測")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "止漲回測" in blob
    assert "不是日K" in blob
    assert "58.1" in blob
    assert "雷科" in blob


def test_twentyninth_chain_unnamed_best_entry():
    fired = fire_chain("", "最佳上車時機")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "最佳上車" in blob
    assert "不是日K" in blob
    assert "103.5" in blob or "70" in blob
    assert "迎廣" in blob or "晟銘電" in blob


def test_thirtieth_chain_unnamed_ask_who():
    fired = fire_chain("", "有哪位高手可解惑")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "解惑" in blob
    assert "不是日K" in blob
    assert "75.8" in blob or "100" in blob
    assert "迎廣" in blob or "晟銘電" in blob


def test_thirtyfirst_chain_unnamed_tech_ma5():
    fired = fire_chain("", "單純以技術面來說")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "技術面" in blob
    assert "不是日K" in blob
    assert "76.2" in blob or "97.6" in blob
    assert "迎廣" in blob or "晟銘電" in blob
