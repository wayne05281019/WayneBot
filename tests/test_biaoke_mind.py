# -*- coding: utf-8 -*-
"""飆大課綱：三百語料／一百判斷／三百官方 K。不是 700 顆按鈕。"""
from __future__ import annotations

import pytest

from biaoke_archive import load_bundled_archive
from biaoke_brain import DISCLAIMER, OFFTOPIC, answer_biaoke
from biaoke_desk import format_biaoke_welcome_html
from biaoke_mind import (
    corpus_curriculum,
    follow_up_ask,
    format_methods_html,
    k_curriculum,
    method_body,
    method_curriculum,
    views_for_neuron,
)


def test_neuron_views_reread_without_ask():
    nest = views_for_neuron("nest")
    titles = [t for t, _b in nest]
    assert "四路對質" in titles
    assert "波浪對大盤" in titles
    assert "右肩／45839" in titles
    assert "他點的日曆／國際局勢" in titles
    field = views_for_neuron("field")
    assert field and field[0][0] == "個股先看產業趨勢"
    assert any(t == "洞燭先機" for t, _b in field)
    assert "很少人提" in method_body("洞燭先機")
    assert "1000" in method_body("洞燭先機")
    assert "對不到「台塑四寶」" in method_body("洞燭先機") or "對不到" in method_body("洞燭先機")
    assert "下飄旗" in method_body("9/10 主戰場")
    assert "不透漏" in method_body("9/10 主戰場")
    assert "散熱" in method_body("9/10 主戰場")
    assert "價穩量縮" in method_body("量先價行")
    tape = views_for_neuron("tape")
    assert any(t == "量先價行" for t, _b in tape)


def test_methods_cover_industry_trend_hold_to_next_year():
    html = format_methods_html("技術分析最有用是什麼")
    assert "產業趨勢" in html
    assert "2026-04-16" in html
    assert "3930" in html
    html2 = answer_biaoke(":memory:", "台光電為何能這麼篤定")
    assert "這不是買訊" in html2
    assert "抱到明年" in html2 or "產業趨勢" in html2
    assert "不猜" not in html2
    assert "現況／量價" not in html2


def test_methods_cover_nanya_1303_not_office_worker_hold():
    html = format_methods_html("南亞為什麼適合上班族長期抱")
    assert "1303" in html
    assert "2408" in html
    assert "217" in html
    assert "對不到" in html
    assert "台塑" in html
    assert "PCB" in html or "AI 材料" in html
    tech = format_methods_html("南亞科他有看好嗎")
    assert "217" not in tech
    html2 = answer_biaoke(":memory:", "南亞怎麼看")
    assert "1303" in html2
    assert "這不是買訊" in html2
    assert "217" in html2


def test_methods_cover_long_hold_f10_and_mediatek():
    html = format_methods_html("F10 長抱跟台光電怎麼分")
    assert "2026-07-24" in html
    assert "勿輕易調節" in html
    assert "奇鋐" in html
    assert "F10" in html
    assert "平台依賴度" in html
    assert "鴻勁" in html
    mtk = format_methods_html("聯發科他有看好嗎")
    assert "2454" in mtk
    assert "IC 設計主線" in mtk
    assert "4/16" in mtk
    assert "不在" in mtk
    assert "尚未納入 F 系列" in mtk
    wave = format_methods_html("台光電抱著波段是不是賺更多")
    assert "勿輕易調節" in wave
    assert "抱著波段賺更多" in wave
    assert "對不到" in wave


def test_methods_cover_wash_three_days_and_right_shoulder():
    wash = format_methods_html("洗盤跟出貨怎麼分")
    assert "2024-07-08" in wash
    assert "破線翻" in wash
    assert "語料" not in wash
    three = format_methods_html("連三天不破點")
    assert "三日" in three
    assert "公開 1709" in three
    wave = format_methods_html("次級四浪是什麼")
    assert "萬潤" in wave or "廣達" in wave
    hold = format_methods_html("45839 有沒有守住")
    assert "45839" in hold
    assert "右肩" in hold
    assert "語料" not in hold
    html = answer_biaoke(":memory:", "洗盤跟出貨怎麼分")
    assert "這不是買訊" in html
    assert "語料" not in html


def test_methods_cover_unspoken_aux_stack():
    html = format_methods_html("他沒講出來的輔助判斷是什麼")
    assert "有緣人" in html or "100%" in html
    assert "台積電" in html
    assert "某金融商品" in html
    assert "不准寫死" in html
    assert "初步止訊號" in html or "還不到確認" in html


def test_welcome_says_compile_not_menu():
    html = format_biaoke_welcome_html()
    assert "在。" in html
    assert "問一檔" not in html
    assert "彙整" in DISCLAIMER


def test_method_curriculum_is_100_and_answers():
    asks = method_curriculum()
    assert len(asks) >= 100
    assert len(set(asks)) == len(asks)
    for q in asks:
        body = format_methods_html(q)
        assert body, q
        assert "海選" not in body or "不" in body
    html = answer_biaoke(":memory:", "量先價行怎麼看")
    assert "這不是買訊" in html
    assert "爆大量" in html
    html2 = answer_biaoke(":memory:", "大概何時止跌")
    assert "不猜日曆" in html2 or "費半" in html2
    assert "這不是買訊" in html2


def test_corpus_curriculum_has_300_from_1709():
    blob = load_bundled_archive()
    asks = corpus_curriculum(blob.get("posts") or [], limit=300)
    assert len(asks) >= 300
    sample = [a for a in asks if "勤誠" in a or "智原" in a or "散熱" in a]
    assert sample


def test_follow_up_uses_history_per_turn():
    hist = [{"ask": "勤誠", "answer": "庫裡有勤誠"}]
    assert "勤誠" in follow_up_ask("那怎麼看", hist)
    assert "勤誠" in follow_up_ask("所以呢", hist)
    assert follow_up_ask("藝舍-KY", hist) == "藝舍-KY"


def test_twentyseventh_methods_thunder_chenming():
    html = format_methods_html("今天早盤應該是低點")
    assert "雷虎" in html and "晟銘電" in html
    assert "不是日K" in html
    assert "71.3" in html and "70.4" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第二十七段" for t, _b in tape)


def test_twentyeighth_methods_lasertek_pullback():
    html = format_methods_html("剛好止漲回測")
    assert "雷科" in html
    assert "不是日K" in html
    assert "58.1" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第二十八段" for t, _b in tape)


def test_twentyninth_methods_supermicro_chassis():
    html = format_methods_html("收大黑K")
    assert "晟銘電" in html and "迎廣" in html
    assert "不是日K" in html
    assert "70" in html and "103.5" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第二十九段" for t, _b in tape)


def test_thirtieth_methods_ask_who_leads():
    html = format_methods_html("剛公佈的業績")
    assert "晟銘電" in html and "迎廣" in html
    assert "不是日K" in html
    assert "75.8" in html and "100" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十段" for t, _b in tape)


def test_thirtyfirst_methods_tech_ma5():
    html = format_methods_html("單純以技術面來說")
    assert "晟銘電" in html and "迎廣" in html
    assert "不是日K" in html
    assert "76.2" in html and "97.6" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十一段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十一段" for t, _b in hold)


def test_thirtysecond_methods_canon_sehi():
    html = format_methods_html("找拉回上車時機")
    assert "佳能" in html and "協易機" in html
    assert "不是日K" in html
    assert "38.9" in html and "40.25" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十二段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十二段" for t, _b in hold)


def test_thirtythird_methods_lasertek_stage2():
    html = format_methods_html("第三階段型態極限目標價")
    assert "雷科" in html
    assert "不是日K" in html
    assert "截圖約 62" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十三段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十三段" for t, _b in hold)


def test_thirtyfourth_methods_quanta_restore_k():
    html = format_methods_html("還原權值K線")
    assert "廣達" in html
    assert "不是日K" in html
    assert "截圖約 273" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十四段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十四段" for t, _b in hold)


def test_thirtyfifth_methods_thunder_k_structure():
    html = format_methods_html("從K線量價結構")
    assert "雷虎" in html
    assert "不是日K" in html
    assert "截圖約 75" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十五段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十五段" for t, _b in hold)


def test_thirtysixth_methods_thunder_friday_entry():
    html = format_methods_html("挑戰歷史高點85.2")
    assert "雷虎" in html
    assert "不是日K" in html
    assert "截圖約 83.4" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十六段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十六段" for t, _b in hold)


def test_thirtyseventh_methods_lasertek_5ma():
    html = format_methods_html("回測5MA支撐線")
    assert "雷科" in html
    assert "不是日K" in html
    assert "截圖約 61.4" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十七段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十七段" for t, _b in hold)


def test_thirtyeighth_methods_lock_sold():
    html = format_methods_html("這兩檔列入鎖股")
    assert "佳能" in html and "漢科" in html
    assert "不是日K" in html
    assert "截圖約 40.1" in html
    tape = views_for_neuron("tape")
    assert any(t == "圖文時間軸第三十八段" for t, _b in tape)
    hold = views_for_neuron("hold")
    assert any(t == "圖文時間軸第三十八段" for t, _b in hold)


def test_offtopic_still_refused():
    assert answer_biaoke(":memory:", "今晚吃什麼") == OFFTOPIC
    assert "買訊" not in OFFTOPIC


def test_compile_mentions_this_brain():
    assert "彙整" in DISCLAIMER


@pytest.mark.production_db
def test_k_curriculum_300_unnamed_on_production_db():
    from tests.conftest import require_production_db

    db = require_production_db()
    import sqlite3

    blob = load_bundled_archive()
    named = []
    for p in blob.get("posts") or []:
        named.extend(p.get("tags") or [])
        named.append(p.get("text") or "")
    conn = sqlite3.connect(db)
    rows = conn.execute(
        """
        SELECT stock_id, stock_name FROM daily_quotes
        WHERE date=(SELECT MAX(date) FROM daily_quotes)
        ORDER BY volume DESC
        """
    ).fetchall()
    conn.close()
    cases = k_curriculum(named, rows, limit=300)
    assert len(cases) >= 300
    from biaoke_brain import overlay_stock, volume_first_price, load_bars

    sid, name = cases[0]
    bars = load_bars(db, sid)
    st = volume_first_price(bars)
    html = overlay_stock({"stock_id": sid, "stock_name": name}, st, in_corpus=False)
    assert "資料庫從頭到尾沒點名" in html
    assert "買訊" not in html or "不是" in html

