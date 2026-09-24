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


def test_why_fed_916_is_his_calendar_not_news():
    body = lookup("9/16 Fed 他在等什麼")
    assert "9/16" in body
    assert "Fed" in body or "FED" in body or "聯準會" in body
    assert "不是看新聞" in body
    assert "新史新高" in body or "再表態" in body
    assert "調節" in body
    assert "不准編" in body
    sept = lookup("九月16")
    assert "9/16" in sept or "Fed" in sept or "FED" in sept


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
    html3 = format_methods_html("Apple股王漲勢結束了嗎")
    assert "光學" in html3
    assert "2/3" in html3 or "降 2/3" in html3
    html2 = format_methods_html("台光電為何能這麼篤定")
    assert "2026-04-16" in html2
    assert "3930" in html2
    assert "不是把波浪套在 2383" in html2 or "產業趨勢" in html2
    assert is_why_query("下降軌怎麼畫")


def test_colloquial_questions_still_hit_chain():
    assert is_why_query("那檔還能不能抱")
    assert is_why_query("晚上那則在講什麼")
    body = lookup("晚上那則在講什麼")
    assert "46506" in body or "最近" in body
    body2 = lookup("他最近在看什麼")
    assert "最近" in body2 or "護城河" in body2 or "細微波" in body2


def test_why_sep14_important_comment_summary():
    body = lookup("創意應該是第一檔噴嗎")
    assert "ASIC" in body or "風向球" in body
    assert "43500" in body
    assert "頭肩底" in body
    assert "不是看壞" in body or "1～3 個月" in body or "1~3個月" in body
    assert "路人" in body
    pcb = lookup("PCB不要亂動")
    assert "光通訊" in pcb
    lgl = lookup("大立光算光通訊嗎")
    assert "InP" in lgl
    assert "不能算" in lgl or "不算" in lgl
    fu = lookup("富喬再度回到支撐區")
    assert "支撐" in fu
    retest = lookup("感覺夜盤不太妙")
    assert "測底" in retest
    assert "短線築底" in retest
    assert "21:50" in retest or "2026-09-14" in retest
    assert "引號" in retest or "引「" in retest
    assert "沒有不太妙" in retest


def test_why_sep15_escape_wave():
    body = lookup("今天強彈反而小心逃命波")
    assert "184601742" in body or "09:02" in body
    assert "逃命波" in body
    assert "不是已確認" in body
    assert "創意" in body
    assert "台達電" in body
    assert "證據" in body
    yong = lookup("雍智科已經整理完成")
    assert "雍智" in yong
    assert "精測" in yong
    assert "旺矽" in yong or "穎崴" in yong or "穎葳" in yong
    win = lookup("穩懋就是昨天跌破支撐立刻站回去")
    assert "3105" in win or "穩懋" in win
    assert "台達電" in win
    assert "420" in win or "444" in win
    inp = lookup("AI關鍵材料最重要就是InP")
    assert "InP" in inp
    assert "CCL" in inp
    flag = lookup("下飄旗型強力洗盤")
    assert "聯亞" in flag
    assert "100%" in flag or "保證" in flag
    assert "IET" in flag
    assert "4971" in flag or "IET-KY" in flag
    slow = lookup("目前大盤漲不動我反而覺得比較好")
    assert "開牌" in slow or "C-2" in slow
    assert "C-3" in slow
    assert "不是已確認" in slow
    jian = lookup("健策盡然跌停")
    assert "難操作" in jian or "跌停" in jian
    assert "5820" in jian or "盤中" in jian
    broken = lookup("健策多頭結構已經被破壞")
    assert "14:52" in broken
    assert "奇鋐" in broken
    assert "不好的訊號" in broken
    pull = lookup("該抽出")
    assert "C-2" in pull and "C-3" in pull
    assert "不是已確認" in pull
    fu = lookup("初升段走完")
    assert "富喬" in fu
    assert "2整理" in fu or "2 整理" in fu
    night = lookup("46767")
    assert "46767" in night
    assert "築底" in night or "下降壓" in night
    assert "碎形" in night or "關鍵K" in night
    shang = lookup("上詮屬CPO")
    assert "3363" in shang or "上詮" in shang
    assert "InP" in shang
    assert "聯亞" in shang
    kbar = lookup("健策爆大量跌破平台")
    assert "5310" in kbar or "2469" in kbar
    assert "轉折" in kbar or "籌碼" in kbar
    c5 = lookup("C-5低點確認了嗎")
    assert "45398" in c5
    assert "如果句" in c5
    assert "頭肩底" in c5
    assert "10月中" in c5
    assert "不是買訊" in c5


def test_why_sunday_pcb_1245_is_sep1_high():
    body = lookup("金像電 1245")
    assert "184841864" in body
    assert "1245" in body
    assert "20260901" in body
    assert "4635" in body
    assert "不是點名南電" in body or "族群對照" in body
    assert "不是買訊" in body
    assert "5／9" in body or "5/9" in body
    abf = lookup("ABF三雄")
    assert "族群對照" in abf or "不是點名南電" in abf
    assert "8046" in abf
    dead = lookup("ABF目前是死水嗎")
    assert "一攤死水" in dead
    assert "爆量長紅" in dead
    assert "下殺取量" in dead
    assert "不是點名南電" in dead
    assert "週日沒官方柱" in dead
    vol = lookup("他怎麼只看量價就知道多空")
    assert "量價結構" in vol
    assert "均線" in vol
    assert "KD" in vol
    assert "MACD" in vol
    assert "分點" in vol
    assert "防守點" in vol


def test_why_volume_fake_structure():
    body = lookup("量假結構是什麼")
    assert "打成" in body
    assert "量價結構" in body
    assert "主力意圖" in body
    assert "長上影" in body
    assert "不進海選" in body
    assert "打成" in lookup("懂量價結構")


def test_live_notes_puts_why_chain_first():
    from biaoke_live import live_notes

    note = live_notes("", "46506 怎麼來")
    assert "判斷鏈" in note
    assert "台指" in note
    assert "20260910" in note or "2026-09-10" in note
    note2 = live_notes("", "建築兩檔是哪兩檔")
    assert "沒點名" in note2
    assert "漢唐" in note2


def test_why_46746_is_tx_sep2_15m_high():
    body = lookup("46746 怎麼來")
    assert "46746" in body
    assert "08:45" in body or "0845" in body
    assert "45415" in body
    assert "46250" in body
    assert "不數" in body
    assert "46407" in body


def test_why_qincheng_60m_has_official_high_low():
    body = lookup("勤誠量價背離他出清過嗎")
    assert "479" in body
    assert "460" in body
    assert "473" in body
    assert "60 分" in body or "60分" in body
    assert "海選" in body
    html = format_methods_html("勤誠 6/19 60分")
    assert "479" in html
    assert "不是買訊" not in html
    assert "這不是買訊" not in html


def test_why_hi_test_dark_horses_are_6683_and_6830():
    body = lookup("高階測試黑馬是哪兩檔")
    assert "6683" in body
    assert "6830" in body
    assert "雍智" in body
    assert "漢唐" not in body
    html = format_methods_html("高階測試兩檔黑馬")
    assert "6683" in html
    assert "汎銓" in html or "泛銓" in html
    assert "不是買訊" not in html


def test_why_broker_points_not_his_method():
    body = lookup("要天天看券商分點嗎")
    assert "社團內化" in body
    assert "量價" in body
    assert "分點" in body
    assert "神探" not in body
    assert "月刊" not in body


def test_why_unspoken_aux_stack():
    body = lookup("他沒講出來的輔助判斷是什麼")
    assert "100%" in body or "有緣人" in body
    assert "台積電" in body
    assert "某金融商品" in body
    assert "不准寫死" in body
    assert "初步止訊號" in body or "還不到確認" in body
    assert is_why_query("有緣人那則在講什麼")


def test_why_sep23_asic_thread_vs_official_bars():
    body = lookup("目前台股最強主流是ASIC")
    assert "184902216" in body
    assert "創意" in body
    assert "聯發科" in body
    assert "8385" in body
    assert "5185" in body
    assert "48157" in body
    assert "波浪理論" in body or "不准套個股" in body
    assert "不是買訊" in body
    assert "5／9" in body or "不數" in body
    fser = lookup("新F系列名單")
    assert "台積電" in fser
    assert "台燿" in fser
    assert "1440" in fser
    assert "1460" in fser
    jian = lookup("健策量價結構告訴我整理完成了")
    assert "6410" in jian
    assert "3653" in jian
    cpo = lookup("CPO現在的主角是大立光")
    assert "上詮" in cpo
    assert "6190" in cpo or "6470" in cpo
    kin = lookup("金像電量價結構就是告訴我已經整理完成")
    assert "1140" in kin
    assert "1245" in kin
    hold = lookup("不太可能整理超過2個月")
    assert "2～3" in hold or "2~3" in hold
    assert "不是買訊" in hold


def test_why_sep24_slow_up_vs_sep23_official_bars():
    body = lookup("目前大盤看起來是走緩步上攻")
    assert "184931175" in body
    assert "證據不夠" in body
    assert "九組" in body
    assert "不准當已確認" in body or "如果句" in body
    assert "5／9" in body or "不數" in body
    assert "48157" in body
    assert "48024" in body
    assert "不是買訊" in body
    assert "未收" not in body or "還沒這列" in body
    jian = lookup("健策是真突破")
    assert "3653" in jian
    assert "6410" in jian
    assert "滾量" in jian or "all in" in jian
    chi = lookup("為何奇鋐下週要進入主升段")
    assert "3017" in chi
    assert "3595" in chi
    assert "2649" in chi or "3470" in chi
    assert "待驗證" in chi
    assert "不是買訊" in chi
    jian2 = lookup("健策是真突破")
    assert "6095" in jian2
    assert "6410" in jian2
    yao = lookup("不太可能像聯發科一樣直接噴")
    assert "1275" in yao
    assert "1730" in yao or "1485" in yao
    xin = lookup("全新並沒有這麼快")
    assert "28618" in xin
    assert "3310" in xin
    ccl = lookup("聯茂跳空漲停")
    assert "90%" in ccl or "90" in ccl
    assert "還沒這列" in ccl
    assert "台光電" in ccl
    assert "台燿" in ccl
    yao = lookup("不太可能像聯發科一樣直接噴")
    assert "台燿" in yao
    assert "前高" in yao
    xin = lookup("全新並沒有這麼快")
    assert "全新" in xin
    assert "ASIC" in xin or "散熱" in xin
    fake = lookup("跌到47000以下都是最後假跌破")
    assert "47000" in fake
    assert "44000" in fake
    four = lookup("四檔股票 2~3成")
    assert "中秋" in four
    assert "不是買訊" in four


def test_why_accuracy_question_does_not_wait_for_reminder():
    body = lookup("這次對質結果準確度如何")
    assert "還沒到能講的那天" in body
    assert "高低卡" in body
    assert "不是買訊" in body
    assert "5／9" in body or "不數" in body


def test_catchup_has_sep23_main_not_passerby():
    import json
    from pathlib import Path

    blob = json.loads(
        Path("docs/expert_notes/飆客/catchup.json").read_text(encoding="utf-8")
    )
    ids = [str(p.get("id") or "") for p in blob.get("posts") or []]
    assert "184902216" in ids
    assert "184902216:c184902216-244" in ids
    assert "184902216:c184902216-238" in ids
    assert "184902216:c184902216-69-5" not in ids
    main = next(p for p in blob["posts"] if p["id"] == "184902216")
    assert "ASIC" in main["text"]
    assert main["layer"] == 0
    assert "步步大" not in "".join(
        str(p.get("text") or "") for p in blob["posts"] if str(p.get("id") or "").startswith("184902216")
    )


def test_catchup_has_sep24_main_not_passerby():
    import json
    from pathlib import Path

    blob = json.loads(
        Path("docs/expert_notes/飆客/catchup.json").read_text(encoding="utf-8")
    )
    ids = [str(p.get("id") or "") for p in blob.get("posts") or []]
    assert "184931175" in ids
    assert "184931175:c184931175-117" in ids
    assert "184931175:c184931175-148" in ids
    assert "184931175:c184931175-228-1" in ids
    assert "184931175:c184931175-226-1" in ids
    assert "184902216:c184902216-266" in ids
    assert "184902216:c184902216-69-5" not in ids
    main = next(p for p in blob["posts"] if p["id"] == "184931175")
    assert "緩步上攻" in main["text"]
    assert "九組推升" in main["text"]
    assert main["layer"] == 0
    thread = [
        str(p.get("text") or "")
        for p in blob["posts"]
        if str(p.get("id") or "").startswith("184931175")
    ]
    joined = "".join(thread)
    assert "47000" in joined
    assert "聯茂" in joined
    assert len(thread) >= 38
    assert "建策噴了 直接飆大跪了" not in joined
    assert "令媛復健" not in joined
