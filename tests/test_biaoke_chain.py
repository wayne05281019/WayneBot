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
    assert "開口第一句" in SYSTEM or "判斷｜" in SYSTEM
    assert "09:23" not in SYSTEM
    assert "雍智" not in SYSTEM


def test_chain_six_neurons_in_order_for_emc():
    notes = format_chain_notes("", "台光電 7 月抄底為什麼能抱到明年")
    assert "神經元鏈" in notes
    assert notes.startswith("開口｜") or "開口｜" in notes[:80]
    assert "不是買訊" in notes.split("\n", 1)[0]
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
    assert "先看大盤巢穴會不會覆巢" not in think
    assert "再問產業趨勢還在不在" not in think
    assert "問的是 2383" in think


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
    from tests.conftest import has_production_db, production_db_path

    if not has_production_db():
        return
    db = production_db_path()
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
    from tests.conftest import require_production_db

    db = require_production_db()
    note = live_notes(db, "台光電怎麼看")
    assert "神經元鏈" in note
    assert "關鍵字命中" not in note
    assert "2383" in note
    assert "收" in note


def test_chain_real_quotes_when_db_present():
    from tests.conftest import require_production_db

    db = require_production_db()
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
    from tests.conftest import require_production_db

    db = require_production_db()
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
    from tests.conftest import has_production_db, production_db_path

    fired = fire_chain("", "台光電 7 月抄底為什麼能抱到明年")
    leader = next(s for s in fired["steps"] if s["id"] == "leader")
    assert "自己就是" in leader["text"]
    if not has_production_db():
        return
    db = production_db_path()
    fired = fire_chain(db, "台光電怎麼看")
    leader = next(s for s in fired["steps"] if s["id"] == "leader")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    assert "自己就是" in leader["text"]
    assert "留給第 4 顆" in leader["text"] or "不另對" in leader["text"]
    assert "4510" not in leader["text"]
    assert "收" in tape["text"]
    assert "壓" in tape["text"] or "撐" in tape["text"]
    follow = fire_chain(db, "智原怎麼看")
    if follow.get("sid") != "3035":
        return
    lead = next(s for s in follow["steps"] if s["id"] == "leader")
    assert "2454" in lead["text"] or "聯發科" in lead["text"]
    assert "爆量日" in lead["text"] or "收" in lead["text"]


def test_tape_does_not_repeat_hold_or_field():
    """第 4 顆只留官方量價／演算；長抱、半山腰、產業資金不重貼。"""
    from tests.conftest import require_production_db

    db = require_production_db()
    fired = fire_chain(db, "台光電怎麼看")
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    field = next(s for s in fired["steps"] if s["id"] == "field")
    assert "收" in tape["text"]
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
    assert "4/16" in mh["text"]
    assert "半山腰" in mh["text"] or "整理末端" in mh["text"] or "不是 4/16" in mh["text"]


def test_think_chains_45839_and_self_leader():
    """推論句要串巢穴官方 45839 和自己就是龍頭，不是只寫點位有了。"""
    from tests.conftest import require_production_db

    db = require_production_db()
    fired = fire_chain(db, "台光電怎麼看")
    think = fired["think"]
    assert "45839" in think
    assert "46506" in think
    assert "47578" in think
    assert "自己就是這族龍頭" in think
    assert "勿輕易調節" in think
    assert "3930" in think
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    close_m = __import__("re").search(r"收 ([0-9.]+)", tape["text"])
    if close_m:
        assert close_m.group(1) in think
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
    day = _pointed_calendar("", "20260916")
    assert "還在等 9/16" in day
    assert "已過" not in day
    assert "兩個9/16" in day or "只能上不能下" in day
    after = _pointed_calendar("", "20260917")
    assert "已過" in after
    assert "不准編新聞" in after or "不准編" in after
    assert "回撤" in after
    from tests.conftest import has_production_db, production_db_path

    if has_production_db():
        after = _pointed_calendar(production_db_path(), "20260917")
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


def test_thirtysecond_chain_unnamed_pullback():
    fired = fire_chain("", "找拉回上車時機")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "拉回上車" in blob or "漲停" in blob
    assert "不是日K" in blob
    assert "38.9" in blob or "40.25" in blob
    assert "佳能" in blob or "協易機" in blob


def test_thirtythird_chain_unnamed_stage2():
    fired = fire_chain("", "第三階段型態極限目標價")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "極限目標價" in blob or "第二階段型態" in blob
    assert "不是日K" in blob
    assert "截圖約 62" in blob or "64.5" in blob
    assert "雷科" in blob


def test_thirtyfourth_chain_unnamed_restore_k():
    fired = fire_chain("", "還原權值K線")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "還原權值" in blob or "273" in blob
    assert "不是日K" in blob
    assert "截圖約 273" in blob or "271" in blob
    assert "廣達" in blob


def test_thirtyfifth_chain_unnamed_k_structure():
    fired = fire_chain("", "從K線量價結構")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "從K線量價結構" in blob or "上車最佳" in blob
    assert "不是日K" in blob
    assert "截圖約 75" in blob or "75.9" in blob
    assert "雷虎" in blob


def test_thirtysixth_chain_unnamed_hist_high():
    fired = fire_chain("", "挑戰歷史高點85.2")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "挑戰歷史高點85.2" in blob or "上星期五中午" in blob
    assert "不是日K" in blob
    assert "截圖約 83.4" in blob or "83.4" in blob
    assert "雷虎" in blob


def test_thirtyseventh_chain_unnamed_5ma():
    fired = fire_chain("", "回測5MA支撐線")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "回測5MA支撐線" in blob or "空手上車" in blob
    assert "不是日K" in blob
    assert "截圖約 61.4" in blob or "61.5" in blob
    assert "雷科" in blob


def test_thirtyeighth_chain_unnamed_lock():
    fired = fire_chain("", "這兩檔列入鎖股")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "這兩檔列入鎖股" in blob or "協易機爆大量" in blob
    assert "不是日K" in blob
    assert "截圖約 40.1" in blob or "37.65" in blob
    assert "佳能" in blob and "漢科" in blob


def test_thirtyninth_chain_unnamed_374():
    fired = fire_chain("", "早盤在37.4")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "早盤在37.4" in blob or "先買一半" in blob
    assert "不是日K" in blob
    assert "截圖約 38.6" in blob or "38.45" in blob
    assert "佳能" in blob


def test_fortieth_chain_unnamed_117():
    fired = fire_chain("", "先掛117-117.5")
    assert fired.get("named") is False
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "先掛117-117.5" in blob or "先買1/3" in blob
    assert "不是日K" in blob
    assert "截圖約 118" in blob or "115.0" in blob or "115" in blob
    assert "漢科" in blob


def test_fortyfirst_chain_unnamed_neck_565():
    fired = fire_chain("", "打到頸線56.5")
    assert fired.get("named") is False
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "打到頸線56.5" in blob or "第一次不太可能直接跌破" in blob
    assert "不是日K" in blob
    assert "截圖約 57.5" in blob or "58.6" in blob
    assert "雷科" in blob
    assert "先買1/3" not in blob


def test_fortysecond_chain_unnamed_19650():
    fired = fire_chain("", "直探19650")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "直探19650" in blob or "19650會測兩次" in blob
    assert "不數段" in blob
    assert "截圖約 786" in blob or "788" in blob
    assert "不對圖" in blob


def test_fortythird_chain_unnamed_gap_neck():
    fired = fire_chain("", "19500~19650")
    assert fired.get("named") is False
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "19500~19650" in blob
    assert "不數段" in blob
    assert "不對圖" in blob


def test_fortyfourth_chain_unnamed_honso_leike():
    fired = fire_chain("", "也會過前高64.5")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "也會過前高" in blob
    assert "不是日K" in blob
    assert "截圖約 61.5" in blob or "61.4" in blob or "截圖約 1110" in blob
    assert "雷科" in blob
    hon = fire_chain("", "我沒有弘塑")
    hblob = "".join(s.get("text") or "" for s in hon["steps"]) + hon.get("think", "")
    assert "弘塑" in hblob
    assert "不是日K" in hblob or "1110" in hblob


def test_fortyfifth_chain_unnamed_tx_night_19650():
    fired = fire_chain("", "最多打到19650")
    assert fired.get("named") is False
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "最多打到19650" in blob
    assert "不數段" in blob
    assert "不對圖" in blob
    night = fire_chain("", "破19844")
    nblob = "".join(s.get("text") or "" for s in night["steps"]) + night.get("think", "")
    assert "19844" in nblob


def test_chain_sep15_night_five_tools_rewire():
    nest = fire_chain("", "46767 怎麼看")
    assert not nest.get("sid")
    nest_t = next(s for s in nest["steps"] if s["id"] == "nest")["text"]
    think = nest["think"]
    assert "46767" in nest_t or "46767" in think
    assert "碎形" in nest_t or "關鍵K" in nest_t or "碎形" in think
    from tests.conftest import has_production_db, production_db_path

    if not has_production_db():
        return
    nest_db = fire_chain(production_db_path(), "46767 怎麼看")
    assert not nest_db.get("sid")
    think = nest["think"]
    assert "46767" in nest_t or "46767" in think
    assert "碎形" in nest_t or "關鍵K" in nest_t or "碎形" in think
    jian = fire_chain(production_db_path(), "健策怎麼看")
    assert jian["sid"] == "3653"
    field = next(s for s in jian["steps"] if s["id"] == "field")
    tape = next(s for s in jian["steps"] if s["id"] == "tape")
    hold = next(s for s in jian["steps"] if s["id"] == "hold")
    blob = field["text"] + tape["text"] + hold["text"] + jian["think"]
    assert "5310" in blob or "2469" in blob
    assert "轉折" in blob or "平台" in blob
    shang = fire_chain(production_db_path(), "上詮怎麼看")
    assert shang["sid"] == "3363"
    lead = next(s for s in shang["steps"] if s["id"] == "leader")
    field_s = next(s for s in shang["steps"] if s["id"] == "field")
    blob_s = lead["text"] + field_s["text"] + shang["think"]
    assert "上詮" in blob_s
    assert "CPO" in blob_s or "FAU" in blob_s
    assert "這族龍頭是 3081" not in shang["think"]
    gs = fire_chain(production_db_path(), "光聖怎麼看")
    assert gs["sid"] == "6442"
    assert "這族龍頭是 3081" not in gs["think"]
    assert "3363" in gs["think"] or "上詮" in next(s for s in gs["steps"] if s["id"] == "leader")["text"]


def test_five_cross_gives_different_insight_per_stock():
    """五件交叉：同一套巢穴，個股啟發不准一樣。"""
    from biaoke_chain import _view_line

    jian = fire_chain("", "健策怎麼看")
    emc = fire_chain("", "台光電怎麼看")
    chi = fire_chain("", "奇鋐怎麼看")
    shang = fire_chain("", "上詮怎麼看")
    asic = fire_chain("", "創意怎麼看")
    mkt = fire_chain("", "46767 怎麼看")
    jf = jian.get("five") or jian["think"]
    ef = emc.get("five") or emc["think"]
    cf = chi.get("five") or chi["think"]
    sf = shang.get("five") or shang["think"]
    af = asic.get("five") or asic["think"]
    mf = mkt.get("five") or mkt["think"]
    assert "輪動不是覆巢" in jf
    assert "形態真破" in jf or "假跌破" in jf
    assert "強勢整理" in ef or "續抱" in ef or "沒破線" in ef
    assert "輪動不是覆巢" not in ef
    assert "C-3如果句不准改寫成長抱出清" in ef
    assert "跟漲先當轉弱" in cf
    assert "不是C波出清" in cf
    assert "碎形窗" in cf or "只能上不能下" in cf
    assert "2天漲1000" not in (chi.get("five") or "")
    assert "頸線" in sf or "底部" in sf
    assert "還沒轉折K" in sf
    assert "止漲整理K" in af
    assert "如果句" in mf
    assert "已確認末端" in mf
    assert "36000" in mf
    assert "5%" in mf or "微乎其微" in mf
    assert "沒表態" in mf or "高檔震盪" in mf
    assert "不是9/16日盤" in mf or "周四" in mf
    assert "兩個9/16" in mf or "三個9/16" in mf or "Fed" in mf
    assert "C-5" in mf
    assert "45398" in mf
    assert "頭肩底至少3周" in mf or "鏡射" in mf
    assert "不是主升段" in mf or "不是買訊" in mf
    assert "不到46767" in mf or "一定C-3" in mf
    clips = [_view_line(n) for n in NEURON_IDS]
    assert len({c for c in clips if c}) == 6
    assert not all("46767" in c for c in clips)


def test_five_cross_daily_break_does_not_wipe_stock_keyk():
    """日K破45839 仍要跟夜盤築底、個股關鍵K交叉，不准一刀切出清。"""
    from biaoke_chain import _five_cross

    nest = (
        "官方收 45511 已低於他自己點的 9/3 低 45839，覆巢先當有事。"
        "夜盤築底是好事。C-2 轉 C-3 未確認。"
    )
    jian = _five_cross(
        [
            {"id": "nest", "text": nest},
            {"id": "field", "text": "散熱轉弱由健策轉折K確認。爆大量跌破平台＝轉折K"},
            {"id": "leader", "text": "這族龍頭是 3017 奇鋐"},
            {"id": "tape", "text": "健策爆大量跌破平台，確認出現轉折"},
            {"id": "hold", "text": "籌碼交換至少 2 周"},
            {"id": "doubt", "text": ""},
        ],
        "3653",
        "健策",
    )
    emc = _five_cross(
        [
            {"id": "nest", "text": nest},
            {"id": "field", "text": "台光電護城河最高"},
            {"id": "leader", "text": "自己就是這族龍頭"},
            {"id": "tape", "text": "收 4510 站上撐"},
            {"id": "hold", "text": "切勿輕易調節"},
            {"id": "doubt", "text": ""},
        ],
        "2383",
        "台光電",
    )
    assert "輪動不是覆巢" in jian
    assert "45839" in jian
    assert "續抱" in emc
    assert "輪動不是覆巢" not in emc
    assert jian != emc


def test_five_cross_wash_is_not_turn_and_36000_not_43500():
    """破線站回＝洗盤；爆大量才是轉折K。36000≠43500。"""
    from biaoke_chain import _five_cross

    nest = "夜盤築底是好事。C-2 轉 C-3 未確認。官方夜盤高還沒過他自己點的 46506。46767。"
    wash = _five_cross(
        [
            {"id": "nest", "text": nest},
            {"id": "field", "text": "前兩天破線，今天開始重新站回支撐。證據還不足。"},
            {"id": "leader", "text": "自己就是長線龍頭"},
            {"id": "tape", "text": "重新站回支撐"},
            {"id": "hold", "text": "切勿輕易調節"},
            {"id": "doubt", "text": ""},
        ],
        "2308",
        "台達電",
    )
    assert "洗盤" in wash
    assert "不是轉折K" in wash
    assert "長抱另論" in wash
    turn = _five_cross(
        [
            {"id": "nest", "text": nest},
            {"id": "field", "text": "散熱轉弱由健策轉折K確認"},
            {"id": "leader", "text": ""},
            {"id": "tape", "text": "健策爆大量跌破平台，確認出現轉折"},
            {"id": "hold", "text": ""},
            {"id": "doubt", "text": ""},
        ],
        "3653",
        "健策",
    )
    assert "輪動不是覆巢" in turn
    assert "洗盤" not in turn
    mkt = _five_cross(
        [
            {"id": "nest", "text": nest + "36000是9波擴延。某商品量價說43500非常難。"},
            {"id": "field", "text": ""},
            {"id": "leader", "text": ""},
            {"id": "tape", "text": ""},
            {"id": "hold", "text": ""},
            {"id": "doubt", "text": ""},
        ],
        "",
        "",
    )
    assert "36000" in mkt
    assert "43500" in mkt
    assert "46767" in mkt
    assert "混" in mkt
    asic = fire_chain("", "創意怎麼看")
    af = asic.get("five") or asic["think"]
    assert "止漲整理K" in af
    assert "43500危機沒解除" in af or "連續漲勢" in af
    emc = fire_chain("", "台光電怎麼看")
    ef = emc.get("five") or emc["think"]
    assert "強勢整理" in ef
    assert "轉折K" not in ef or "不是轉折K" in ef
    assert "光聖" in ef or "時間換空間" in ef
    iet = fire_chain("", "IET怎麼看")
    if iet.get("sid") == "4971":
        it = iet.get("five") or iet["think"]
        assert "洗盤" in it
        assert "轉折K" not in it or "不是轉折K" in it
    chi = fire_chain("", "奇鋐怎麼看")
    cf = chi.get("five") or chi["think"]
    hold_c = next(s for s in chi["steps"] if s["id"] == "hold")["text"]
    assert "碎形窗" in cf or "只能上不能下" in cf
    assert "2天漲1000" not in hold_c.split("他的說法")[0]
    jian = fire_chain("", "健策怎麼看")
    jf = jian.get("five") or jian["think"]
    assert "2周" in jf or "2 周" in jf
    yong = fire_chain("", "雍智怎麼看")
    yf = yong.get("five") or yong["think"]
    assert "整理完成" in yf or "時間問題" in yf
    assert "轉折K" not in yf or "不是轉折K" in yf
    probe = fire_chain("", "精測怎麼看")
    pf = probe.get("five") or probe["think"]
    assert "洗盤" in pf
    wei = fire_chain("", "穎崴怎麼看")
    wf = wei.get("five") or wei["think"]
    assert "時間問題" in wf
    assert "出清" in wf
    yao = fire_chain("", "台燿怎麼看")
    yao_f = yao.get("five") or yao["think"]
    assert "台光電表態" in yao_f or "等台光電" in yao_f


def test_chain_c5_if_not_main_up_and_45398_not_sid():
    fired = fire_chain("", "45398 怎麼看")
    assert not fired.get("sid")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")["text"]
    five = fired.get("five") or fired["think"]
    think = fired["think"]
    blob = nest + five + think
    assert "45398" in blob
    assert "C-5" in blob
    assert "如果句" in blob
    assert "頭肩底" in blob
    assert "10月中" in blob or "不是買訊" in blob
    assert "未收" in blob or "不當官方" in blob
    c5 = fire_chain("", "C-5低點確認了嗎")
    assert not c5.get("sid")
    c5b = (c5.get("five") or "") + c5["think"]
    assert "不是已確認C-5" in c5b or "如果句" in c5b
    assert "主升段" in c5b or "10月中" in c5b


def test_nest_skips_incomplete_index_bar(tmp_path, monkeypatch):
    import sqlite3

    from taiwan_market import ensure_index_daily_table

    db = str(tmp_path / "c5-cap.db")
    ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO index_daily(date,symbol,open,high,low,close,volume,pct_change,updated_at) "
        "VALUES ('20260915','TWII',45800,46010,45492,45511,1,0,'t')"
    )
    conn.execute(
        "INSERT INTO index_daily(date,symbol,open,high,low,close,volume,pct_change,updated_at) "
        "VALUES ('20260916','TWII',45500,45700,45200,45600,1,0,'t')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20260915"
    )
    from biaoke_chain import _NEST_OFFICIAL

    _NEST_OFFICIAL.clear()
    fired = fire_chain(db, "C-5低點怎麼看")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")["text"]
    assert "20260916" not in nest.replace("-", "")
    assert "45200" not in nest
    assert "45511" in nest or "45492" in nest
    assert "45398" in nest
    assert "如果句" in nest


def test_five_lead_is_first_sentence_with_if_and_unclosed():
    from biaoke_chain import attach_five_lead, format_five_lead, split_lead_detail
    from biaoke_brain import OFFTOPIC, answer_biaoke

    mkt = fire_chain("", "45398 怎麼看")
    lead = mkt.get("lead") or format_five_lead(mkt)
    assert "如果句" in lead
    assert "未收" in lead
    assert "不是買訊" in lead
    assert "C-5" in lead or "45398" in lead
    notes = format_chain_notes("", "45398 怎麼看")
    assert notes.startswith("開口｜")
    html = attach_five_lead("後面細節。", "", "45398 怎麼看")
    assert html.startswith(lead[:12]) or "如果句" in html[:80]
    assert html.index("如果句") < html.index("後面細節")
    lead, detail = split_lead_detail(html)
    assert "不是買訊" in lead
    assert "〔" in lead
    assert "後面細節" in detail
    assert "後面細節" not in lead
    raw, empty = split_lead_detail("沒有開口句的整則")
    assert raw == "沒有開口句的整則"
    assert empty == ""
    emc = fire_chain("", "台光電怎麼看")
    el = emc.get("lead") or ""
    assert "問的是 2383" in el
    assert "不數浪" in el
    assert "不是買訊" in el
    assert "他還在等自己點過的" not in el
    assert "如果句" not in el
    assert "未收" not in el
    assert answer_biaoke(":memory:", "你好") == "在，你說。"
    assert answer_biaoke(":memory:", "今晚吃什麼") == OFFTOPIC
    from biaoke_digest import format_latest_focus

    focus = format_latest_focus("")
    assert "如果句" in focus or "未收" in focus
    assert "不是買訊" in focus


def test_overlays_do_not_change_five_cross_branches():
    """官方結構／對質／回測／法人只 overlay，不准改五件交叉分支。"""
    from biaoke_chain import (
        _bt_if_clause,
        _field,
        _rail_from_brief,
        format_five_lead,
    )

    jian = fire_chain("", "健策怎麼看")
    emc = fire_chain("", "台光電怎麼看")
    mkt = fire_chain("", "45398 怎麼看")
    assert "輪動不是覆巢" in (jian.get("five") or "")
    assert "強勢整理" in (emc.get("five") or "") or "沒破線" in (emc.get("five") or "")
    assert "官方結構" not in (jian.get("five") or "")
    assert "五件回測 overlay" not in (emc.get("five") or "")
    assert "C-5" in (mkt.get("five") or "")
    cal = _bt_if_clause()
    assert "不改這次五件判斷" in cal
    assert "形態" in cal
    assert "%" not in cal
    doubt = next(s for s in emc["steps"] if s["id"] == "doubt")
    assert "不改這次五件判斷" in doubt["text"]
    rail = _rail_from_brief(
        {
            "sid": "2383",
            "struct": {"close": 4000, "spike_low": 3930, "spike_high": 4510},
            "structure": {"down_now": 4100, "up_now": 3800},
        }
    )
    assert rail.startswith("官方結構：")
    assert "收在爆大量撐 3930 上" in rail
    assert "下降壓 4100還壓著" in rail
    assert "上升撐 3800收在上" in rail
    lead = format_five_lead(
        {
            "five": emc["five"],
            "steps": emc["steps"],
            "think": emc.get("think") or "",
            "rail": rail,
        }
    )
    assert "強勢整理" in lead or "沒破線" in lead or "續抱" in lead
    assert "官方結構" in lead
    assert "不是買訊" in lead
    field = _field(
        "台光電怎麼看",
        {"sid": "2383", "name": "台光電", "rotation": "電子零組件業在流出前段"},
    )
    assert field["text"].startswith("個股最重要是產業趨勢還在不在")
    assert "官方法人 overlay：電子零組件業在流出前段" in field["text"]
    assert "不改他的產業句" in field["text"]
    from tests.conftest import has_production_db, production_db_path

    db = production_db_path()
    if has_production_db():
        live = fire_chain(db, "台光電怎麼看")
        live_lead = live.get("lead") or ""
        live_field = next(s for s in live["steps"] if s["id"] == "field")["text"]
        live_doubt = next(s for s in live["steps"] if s["id"] == "doubt")["text"]
        assert "強勢整理" in (live.get("five") or "") or "沒破線" in (live.get("five") or "")
        assert "官方結構" in live_lead or "官方結構" in next(
            s for s in live["steps"] if s["id"] == "tape"
        )["text"]
        assert "電子零組件" in live_field or "產業" in live_field
        if "官方法人 overlay：" in live_field:
            assert "不改他的產業句" in live_field
        assert "不改這次五件判斷" in live_doubt


def test_mouth_is_one_judgment_drawers_not_six_texts():
    notes = format_chain_notes("", "台光電怎麼看")
    assert "判斷｜" in notes
    assert "抽屜" in notes
    assert "神經元鏈" in notes
    assert chain_order_ok(notes)
    assert "他還在等自己點過的" not in notes
    fired = fire_chain("", "台光電怎麼看")
    assert "問的是 2383" in (fired.get("judge") or "")
    assert "不數浪" in (fired.get("judge") or "")
    mkt = format_chain_notes("", "目前大盤是屬於哪個位階 以波浪來看的話")
    assert "判斷｜" in mkt
    assert "這句沒點檔" in mkt or "大盤" in mkt
