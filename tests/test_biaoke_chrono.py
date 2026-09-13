# -*- coding: utf-8 -*-
"""圖文時間軸：第一段智原／貨櫃，第二段華碩／廣達，第三段台通／頎邦，第四段光聖／頎邦回證。"""
from biaoke_chrono import line_for, next_start, overview, slice_stop
from biaoke_charts import official_on
from biaoke_mind import format_methods_html, method_body
from biaoke_facts import names_in_ask


def test_second_slice_stops_feb3_2024():
    body = method_body("圖文時間軸第二段")
    assert "2024-01-05" in body
    assert "華碩" in body
    assert "台指期不是華碩" in body or "不是華碩日K" in body
    assert "廣達" in body
    assert "456.5" in body or "454" in body


def test_third_slice_taitong_chipbond_still_there():
    body = method_body("圖文時間軸第三段")
    assert "2024-03-15" in body
    assert "台通" in body
    assert "頎邦" in body
    assert "不是台通" in body or "不是台通／頎邦" in body
    assert "29.1" in body
    t = line_for("8011")
    assert "鎖跌停" in t or "收 28" in t
    assert "不是台通日K" in t
    q = line_for("6147")
    assert "76" in q
    assert "73.5" in q


def test_fourth_slice_stops_mar19_2024():
    body = method_body("圖文時間軸第四段")
    assert "2024-03-18" in body
    assert "光聖" in body
    assert "盤中走勢" in body
    assert "不是日K" in body
    assert "125" in body
    assert "124" in body
    assert "121.5" in body
    g = line_for("6442")
    assert "光聖" in g
    assert "盤中走勢" in g
    assert "不是日K" in g
    assert "125" in g
    assert "124" in g
    assert "121.5" in g
    q = line_for("6147")
    assert "80.8" in q or "78.5" in q
    assert "盤中走勢" in q
    ov = overview()
    assert "光聖" in ov
    assert "盤中走勢" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_fifth_slice_stops_mar19_quanta_gap():
    body = method_body("圖文時間軸第五段")
    assert "2024-03-19" in body
    assert "廣達" in body
    assert "盤中走勢" in body
    assert "不是日K" in body
    assert "273" in body
    assert "19250" in body
    q = line_for("2382")
    assert "缺口" in q
    assert "盤中走勢" in q
    assert "不是日K" in q
    assert "273" in q
    assert "257" in q
    tx = line_for("TX")
    assert "19250" in tx
    assert "不數段" in tx
    ov = overview()
    assert "19250" in ov
    assert "鴻海" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_sixth_slice_honhai_chart_is_ennoconn():
    body = method_body("圖文時間軸第六段")
    assert "2024-03-20" in body
    assert "樺漢" in body
    assert "不是鴻海日K" in body
    assert "327" in body
    assert "331.5" in body
    h = line_for("2317")
    assert "鴻海" in h
    assert "不是鴻海日K" in h
    assert "327" in h
    e = line_for("6414")
    assert "樺漢" in e
    assert "盤中走勢" in e
    assert "327" in e
    assert "331.5" in e
    ov = overview()
    assert "樺漢" in ov
    assert "不是鴻海日K" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_seventh_slice_ennoconn_intraday_reversal():
    body = method_body("圖文時間軸第七段")
    assert "2024-03-21" in body
    assert "326" in body and "327" in body
    assert "先觀望" in body
    assert "可買" in body
    assert "不是日K" in body
    assert "1231" in body or "聯華" in body
    e = line_for("6414")
    assert "10:24" in e or "10:20" in e
    assert "12:37" in e or "12:31" in e
    assert "326.5" in e
    assert "334.5" in e
    assert "先觀望" in e
    ov = overview()
    assert "先觀望" in ov
    assert "改口" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_eighth_slice_ennoconn_327_hold():
    body = method_body("圖文時間軸第八段")
    assert "2024-03-22" in body
    assert "327" in body
    assert "不是日K" in body
    assert "329" in body
    e = line_for("6414")
    assert "12:20" in e or "12:15" in e
    assert "327" in e
    assert "323.5" in e or "324" in e
    ov = overview()
    assert "3/22" in ov or "2024-03-22" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_ninth_slice_last_boarding_is_ennoconn_not_honhai():
    body = method_body("圖文時間軸第九段")
    assert "2024-03-25" in body
    assert "最後上車" in body
    assert "不是鴻海日K" in body
    assert "348" in body
    assert "337" in body
    h = line_for("2317")
    assert "最後上車" in h
    assert "不是鴻海日K" in h
    assert "348" in h
    assert "145.5" in h
    e = line_for("6414")
    assert "最後上車" in e
    assert "盤中走勢" in e
    assert "348" in e
    assert "349" in e
    assert "337" in e
    ov = overview()
    assert "最後上車" in ov
    assert "不是鴻海日K" in ov
    assert "6416" in ov and "不對圖" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_tenth_slice_guangsheng_125_intraday():
    body = method_body("圖文時間軸第十段")
    assert "2024-03-26" in body
    assert "多空支撐" in body
    assert "不是日K" in body
    assert "139" in body
    assert "132" in body
    g = line_for("6442")
    assert "光聖" in g
    assert "盤中走勢" in g
    assert "不是日K" in g
    assert "125" in g
    assert "139" in g
    assert "132" in g
    assert "146" in g
    ov = overview()
    assert "3/26" in ov or "2024-03-26" in ov
    assert "多空支撐" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_eleventh_slice_guangsheng_144_resistance():
    body = method_body("圖文時間軸第十一段")
    assert "2024-03-28" in body
    assert "144" in body and "145" in body
    assert "不是日K" in body
    assert "137" in body
    assert "138" in body
    g = line_for("6442")
    assert "144" in g and "145" in g
    assert "盤中走勢" in g
    assert "137" in g
    assert "138" in g
    assert "141" in g
    ov = overview()
    assert "144" in ov and "145" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twelfth_slice_quanta_wash_282():
    body = method_body("圖文時間軸第十二段")
    assert "2024-03-28" in body
    assert "282" in body
    assert "不是日K" in body
    assert "262.5" in body
    assert "280" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "洗到" in q
    assert "282" in q
    assert "262.5" in q
    assert "280" in q
    ov = overview()
    assert "洗到" in ov and "282" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_thirteenth_slice_ennoconn_weekk_400():
    body = method_body("圖文時間軸第十三段")
    assert "2024-03-28" in body
    assert "必過" in body and "400" in body
    assert "不是日K" in body
    assert "不是周K" in body
    assert "349" in body
    assert "360" in body
    assert "375" in body
    e = line_for("6414")
    assert "樺漢" in e
    assert "最後上車" in e
    assert "必過" in e and "400" in e
    assert "不是日K" in e
    assert "不是周K" in e
    assert "349" in e
    assert "360" in e
    assert "375" in e
    ov = overview()
    assert "必過" in ov and "400" in ov
    assert "13:30" in ov or "不是周K" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_fourteenth_slice_quanta_not_honhai_300():
    body = method_body("圖文時間軸第十四段")
    assert "2024-03-28" in body
    assert "不可能像鴻海" in body
    assert "不是日K" in body
    assert "不是鴻海日K" in body
    assert "280" in body
    assert "300" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "不可能像鴻海" in q
    assert "不是鴻海日K" in q
    assert "280" in q
    assert "300" in q
    h = line_for("2317")
    assert "不是鴻海日K" in h
    assert "280" in h or "282" in h
    ov = overview()
    assert "站穩 300" in ov or "站穩300" in ov
    assert "不是鴻海日K" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_fifteenth_slice_quanta_retract_20pct():
    body = method_body("圖文時間軸第十五段")
    assert "2024-03-29" in body
    assert "非常強" in body
    assert "不是日K" in body
    assert "不是鴻海日K" in body
    assert "294.5" in body
    assert "20%" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "苦盡甘來" in q or "非常強" in q
    assert "294.5" in q
    assert "20%" in q
    assert "不是鴻海日K" in q
    h = line_for("2317")
    assert "不是鴻海日K" in h
    assert "294.5" in h or "150" in h
    ov = overview()
    assert "20%" in ov
    assert "非常強" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_sixteenth_slice_ennoconn_lower_wick():
    body = method_body("圖文時間軸第十六段")
    assert "2024-03-29" in body
    assert "長下引線" in body
    assert "不是日K" in body
    assert "356.5" in body
    assert "375" in body
    e = line_for("6414")
    assert "樺漢" in e
    assert "長下引線" in e
    assert "356.5" in e
    assert "375" in e
    assert "沒噴出" in e or "噴出" in e
    ov = overview()
    assert "長下引線" in ov
    assert "噴出" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_seventeenth_slice_quanta_hold_300():
    body = method_body("圖文時間軸第十七段")
    assert "2024-03-29" in body
    assert "站穩" in body and "300" in body
    assert "不是日K" in body
    assert "293.5" in body
    assert "賺了幾%" in body or "下車" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "波段" in q or "站穩" in q
    assert "293.5" in q
    assert "不是日K" in q
    ov = overview()
    assert "下星期上半週" in ov or "站穩 300" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_eighteenth_slice_guangsheng_half_year():
    body = method_body("圖文時間軸第十八段")
    assert "2024-03-29" in body
    assert "整理半年" in body
    assert "不是日K" in body
    assert "140.5" in body
    assert "161.5" in body
    g = line_for("6442")
    assert "光聖" in g
    assert "整理半年" in g
    assert "140.5" in g
    ov = overview()
    assert "整理半年" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_nineteenth_slice_quanta_289_291():
    assert slice_stop() == "2024-04-01"
    assert next_start() == "2024-04-01"
    body = method_body("圖文時間軸第十九段")
    assert "2024-04-01" in body
    assert "289.5" in body and "291" in body
    assert "不是日K" in body
    assert "290.5" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "多空分界" in q
    assert "290.5" in q
    assert "282.5" in q
    ov = overview()
    assert "289.5" in ov or "多空分界" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_taitong_chipbond_official_optional():
    db = "data/wayne_market.db"
    t15 = official_on(db, "8011", "20240315")
    assert t15 == {} or (
        abs(float(t15["close"]) - 28) < 0.01 and abs(float(t15["open"]) - 28) < 0.01
    )
    t14 = official_on(db, "8011", "20240314")
    assert t14 == {} or abs(float(t14["close"]) - 31.1) < 0.01
    c15 = official_on(db, "6147", "20240315")
    assert c15 == {} or abs(float(c15["close"]) - 76.5) < 0.01
    g18 = official_on(db, "6442", "20240318")
    assert g18 == {} or abs(float(g18["close"]) - 124) < 0.01
    g19 = official_on(db, "6442", "20240319")
    assert g19 == {} or abs(float(g19["close"]) - 121.5) < 0.01
    c19 = official_on(db, "6147", "20240319")
    assert c19 == {} or (
        abs(float(c19["high"]) - 80.8) < 0.01 and abs(float(c19["close"]) - 78.5) < 0.01
    )
    q19 = official_on(db, "2382", "20240319")
    assert q19 == {} or abs(float(q19["close"]) - 257) < 0.01
    q16 = official_on(db, "2382", "20240216")
    assert q16 == {} or abs(float(q16["close"]) - 248.5) < 0.01
    q28 = official_on(db, "2382", "20240328")
    assert q28 == {} or (
        abs(float(q28["high"]) - 280) < 0.01 and abs(float(q28["close"]) - 280) < 0.01
    )
    h28 = official_on(db, "2317", "20240328")
    assert h28 == {} or abs(float(h28["close"]) - 155.5) < 0.01
    h20 = official_on(db, "2317", "20240320")
    assert h20 == {} or abs(float(h20["close"]) - 138) < 0.01
    e20 = official_on(db, "6414", "20240320")
    assert e20 == {} or (
        abs(float(e20["high"]) - 338.5) < 0.01 and abs(float(e20["close"]) - 331.5) < 0.01
    )
    e21 = official_on(db, "6414", "20240321")
    assert e21 == {} or abs(float(e21["close"]) - 334.5) < 0.01
    e22 = official_on(db, "6414", "20240322")
    assert e22 == {} or abs(float(e22["close"]) - 329) < 0.01
    e25 = official_on(db, "6414", "20240325")
    assert e25 == {} or (
        abs(float(e25["high"]) - 349) < 0.01 and abs(float(e25["close"]) - 337) < 0.01
    )
    h25 = official_on(db, "2317", "20240325")
    assert h25 == {} or abs(float(h25["close"]) - 145.5) < 0.01
    g26 = official_on(db, "6442", "20240326")
    assert g26 == {} or (
        abs(float(g26["high"]) - 146) < 0.01 and abs(float(g26["close"]) - 132) < 0.01
    )
    g28 = official_on(db, "6442", "20240328")
    assert g28 == {} or (
        abs(float(g28["high"]) - 141) < 0.01 and abs(float(g28["close"]) - 138) < 0.01
    )
    e28 = official_on(db, "6414", "20240328")
    assert e28 == {} or (
        abs(float(e28["high"]) - 360) < 0.01 and abs(float(e28["close"]) - 349) < 0.01
    )
    e29 = official_on(db, "6414", "20240329")
    assert e29 == {} or (
        abs(float(e29["high"]) - 376) < 0.01 and abs(float(e29["close"]) - 375) < 0.01
    )
    q29 = official_on(db, "2382", "20240329")
    assert q29 == {} or (
        abs(float(q29["high"]) - 298) < 0.01 and abs(float(q29["close"]) - 293.5) < 0.01
    )
    h29 = official_on(db, "2317", "20240329")
    assert h29 == {} or abs(float(h29["close"]) - 150) < 0.01
    g29 = official_on(db, "6442", "20240329")
    assert g29 == {} or (
        abs(float(g29["high"]) - 142.5) < 0.01 and abs(float(g29["close"]) - 140.5) < 0.01
    )
    q01 = official_on(db, "2382", "20240401")
    assert q01 == {} or (
        abs(float(q01["low"]) - 281.5) < 0.01 and abs(float(q01["close"]) - 282.5) < 0.01
    )


def test_first_slice_official_bars_not_screenshot():
    db = "data/wayne_market.db"
    z19 = official_on(db, "3035", "20231219")
    assert z19 == {} or abs(float(z19["close"]) - 373.5) < 0.01
    z = line_for("3035")
    assert "智原" in z
    assert "396" in z
    assert "不要再操作智原" in z
    assert "373.5" in z
    assert "15182" in z
    w = line_for("2615")
    assert "突破頸線" in w
    assert "破底翻" in w
    assert "54.5" in w
    x = line_for("2605")
    assert "下飄旗" in x
    assert "一年半" in x
    assert "教學圖" in x
    assert "6239" in x and "不准把索引誤標" in x
    assert "27.95" in x
    assert line_for("2454") == ""
    assert "抱著波段賺更多" in overview() and "對不到" in overview()


def test_asus_quanta_chrono_vs_official():
    db = "data/wayne_market.db"
    a = line_for("2357")
    assert "華碩" in a
    assert "第二階段目標" in a
    assert "台指期" in a
    assert "不是華碩日K" in a or "不是華碩K" in a
    assert "456.5" in a
    assert "502" in a
    q = line_for("2382")
    assert "廣達" in q
    assert "回測頸線" in q
    assert "248" in q
    assert "253" in q
    assert "2/19" in q or "241.5" in q
    d26 = official_on(db, "2382", "20240126")
    assert d26 == {} or (
        abs(float(d26["open"]) - 248) < 0.01
        and abs(float(d26["close"]) - 242) < 0.01
        and int(d26["volume"]) == 29597
    )
    d02 = official_on(db, "2382", "20240202")
    assert d02 == {} or (
        abs(float(d02["open"]) - 249.5) < 0.01
        and abs(float(d02["close"]) - 253) < 0.01
        and int(d02["volume"]) == 41010
    )
    assert official_on(db, "2382", "20240203") == {}
    h = official_on(db, "2357", "20240105")
    assert h == {} or abs(float(h["close"]) - 454) < 0.01


def test_methods_html_and_names():
    html = format_methods_html("智原那張圖為什麼貼")
    assert "圖文時間軸" in method_body("圖文時間軸第一段") or "abc" in html or "396" in html
    assert names_in_ask("萬海怎麼看")[0][0] == "2615"
    assert names_in_ask("智原怎麼看")[0][0] == "3035"
    assert names_in_ask("華碩怎麼看")[0][0] == "2357"
    assert names_in_ask("廣達怎麼看")[0][0] == "2382"
    assert names_in_ask("台通怎麼看")[0][0] == "8011"
    assert names_in_ask("頎邦怎麼看")[0][0] == "6147"
    assert names_in_ask("光聖怎麼看")[0][0] == "6442"
    assert names_in_ask("鴻海怎麼看")[0][0] == "2317"
    assert names_in_ask("樺漢怎麼看")[0][0] == "6414"
    flag = format_methods_html("下飄旗型整理多久")
    assert "不透漏" in flag
    assert "13日" not in flag
    asus = format_methods_html("華碩那張圖為什麼貼")
    assert "華碩" in asus and "台指期" in asus
    gs = format_methods_html("光聖那張圖為什麼貼")
    assert "光聖" in gs and "盤中" in gs
    assert "125" in gs
    gap = format_methods_html("廣達缺口那張圖為什麼貼")
    assert "廣達" in gap and "273" in gap
    assert "盤中" in gap or "不是日K" in gap
    hon = format_methods_html("鴻海那張圖為什麼貼")
    assert "樺漢" in hon and "不是鴻海日K" in hon
    assert "327" in hon
    watch = format_methods_html("樺漢326-327先觀望")
    assert "先觀望" in watch and "334.5" in watch
    hold327 = format_methods_html("327支撐線有沒有守住")
    assert "327" in hold327 and "329" in hold327
    last = format_methods_html("最後上車")
    assert "最後上車" in last and "不是鴻海日K" in last
    assert "348" in last and "337" in last
    gs125 = format_methods_html("多空支撐線")
    assert "光聖" in gs125 and "不是日K" in gs125
    assert "139" in gs125 and "132" in gs125
    gs144 = format_methods_html("144-145反壓區")
    assert "光聖" in gs144 and "不是日K" in gs144
    assert "137" in gs144 and "138" in gs144
    wash = format_methods_html("洗到282")
    assert "廣達" in wash and "不是日K" in wash
    assert "262.5" in wash and "280" in wash
    over400 = format_methods_html("必過400")
    assert "樺漢" in over400 and "不是日K" in over400
    assert "不是周K" in over400
    assert "349" in over400 and "360" in over400
    assert "375" in over400
    stand300 = format_methods_html("最晚四月下旬站穩300")
    assert "廣達" in stand300 and "不是日K" in stand300
    assert "不是鴻海日K" in stand300
    assert "280" in stand300 and "300" in stand300
    strong = format_methods_html("苦盡甘來")
    assert "廣達" in strong and "不是日K" in strong
    assert "不是鴻海日K" in strong
    assert "294.5" in strong and "20%" in strong
    wick = format_methods_html("長下引線")
    assert "樺漢" in wick and "不是日K" in wick
    assert "356.5" in wick and "375" in wick
    hold300 = format_methods_html("波段漲勢確認")
    assert "廣達" in hold300 and "不是日K" in hold300
    assert "293.5" in hold300 and "300" in hold300
    assert "下星期" in hold300
    half = format_methods_html("整理半年")
    assert "光聖" in half and "不是日K" in half
    assert "140.5" in half and "161.5" in half
    bound = format_methods_html("多空分界")
    assert "廣達" in bound and "不是日K" in bound
    assert "290.5" in bound and "289.5" in bound


def test_chain_zhiyuan_uses_chrono():
    from biaoke_chain import fire_chain

    fired = fire_chain("", "智原那張圖為什麼貼")
    assert fired["sid"] == "3035"
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    blob = tape["text"] + fired.get("think", "")
    assert "396" in blob or "不要再操作智原" in blob
    hold = next(s for s in fired["steps"] if s["id"] == "hold")
    assert "不要再操作智原" in hold["text"] or "不是 4/16" in hold["text"]


def test_chain_asus_quanta_uses_chrono():
    from biaoke_chain import fire_chain

    asus = fire_chain("", "華碩那張圖為什麼貼")
    assert asus["sid"] == "2357"
    blob = "".join(s.get("text") or "" for s in asus["steps"]) + asus.get("think", "")
    assert "第二階段" in blob or "台指期" in blob
    q = fire_chain("", "廣達頸線那張圖")
    assert q["sid"] == "2382"
    qblob = "".join(s.get("text") or "" for s in q["steps"]) + q.get("think", "")
    assert "頸線" in qblob or "248" in qblob


def test_chain_taitong_uses_chrono():
    from biaoke_chain import fire_chain

    t = fire_chain("", "台通那張圖為什麼貼")
    assert t["sid"] == "8011"
    blob = "".join(s.get("text") or "" for s in t["steps"]) + t.get("think", "")
    assert "29.1" in blob or "不是台通日K" in blob


def test_chain_guangsheng_uses_chrono():
    from biaoke_chain import fire_chain

    t = fire_chain("", "光聖那張圖為什麼貼")
    assert t["sid"] == "6442"
    blob = "".join(s.get("text") or "" for s in t["steps"]) + t.get("think", "")
    assert "125" in blob
    assert "盤中走勢" in blob or "不是日K" in blob


def test_chain_quanta_gap_uses_chrono():
    from biaoke_chain import fire_chain

    t = fire_chain("", "廣達缺口那張圖為什麼貼")
    assert t["sid"] == "2382"
    blob = "".join(s.get("text") or "" for s in t["steps"]) + t.get("think", "")
    assert "273" in blob or "缺口" in blob
    assert "盤中走勢" in blob or "不是日K" in blob


def test_chain_honhai_chart_is_ennoconn():
    from biaoke_chain import fire_chain

    t = fire_chain("", "鴻海那張圖為什麼貼")
    assert t["sid"] == "2317"
    blob = "".join(s.get("text") or "" for s in t["steps"]) + t.get("think", "")
    assert "不是鴻海日K" in blob
    assert "327" in blob
    e = fire_chain("", "樺漢那張圖為什麼貼")
    assert e["sid"] == "6414"
    eblob = "".join(s.get("text") or "" for s in e["steps"]) + e.get("think", "")
    assert "327" in eblob
    assert "盤中走勢" in eblob or "331.5" in eblob
    w = fire_chain("", "樺漢326-327先觀望")
    assert w["sid"] == "6414"
    wblob = "".join(s.get("text") or "" for s in w["steps"]) + w.get("think", "")
    assert "先觀望" in wblob
    assert "334.5" in wblob or "326.5" in wblob
    h327 = fire_chain("", "樺漢327支撐線有沒有守住")
    assert h327["sid"] == "6414"
    hblob = "".join(s.get("text") or "" for s in h327["steps"]) + h327.get("think", "")
    assert "327" in hblob
    assert "329" in hblob or "12:15" in hblob or "12:20" in hblob
    last = fire_chain("", "樺漢最後上車")
    assert last["sid"] == "6414"
    lblob = "".join(s.get("text") or "" for s in last["steps"]) + last.get("think", "")
    assert "最後上車" in lblob
    assert "不是鴻海日K" in lblob or "348" in lblob
    gs125 = fire_chain("", "光聖多空支撐線")
    assert gs125["sid"] == "6442"
    gblob = "".join(s.get("text") or "" for s in gs125["steps"]) + gs125.get("think", "")
    assert "125" in gblob
    assert "132" in gblob or "今天收盤不重要" in gblob or "139" in gblob
    gs144 = fire_chain("", "光聖144-145反壓區")
    assert gs144["sid"] == "6442"
    g144 = "".join(s.get("text") or "" for s in gs144["steps"]) + gs144.get("think", "")
    assert "144" in g144 and "145" in g144
    assert "138" in g144 or "137" in g144 or "不是日K" in g144
    wash = fire_chain("", "洗到282")
    wblob = "".join(s.get("text") or "" for s in wash["steps"]) + wash.get("think", "")
    assert "282" in wblob
    assert "洗到" in wblob
    over400 = fire_chain("", "樺漢必過400")
    assert over400["sid"] == "6414"
    o400 = "".join(s.get("text") or "" for s in over400["steps"]) + over400.get("think", "")
    assert "必過" in o400
    assert "400" in o400
    stand = fire_chain("", "最晚四月下旬站穩300")
    sblob = "".join(s.get("text") or "" for s in stand["steps"]) + stand.get("think", "")
    assert "不可能像鴻海" in sblob
    assert "不是鴻海日K" in sblob
    assert "280" in sblob
    assert "300" in sblob
    strong = fire_chain("", "苦盡甘來")
    gblob = "".join(s.get("text") or "" for s in strong["steps"]) + strong.get("think", "")
    assert "非常強" in gblob
    assert "不是鴻海日K" in gblob
    assert "294.5" in gblob
    assert "20%" in gblob
    wick = fire_chain("", "長下引線紅K")
    wblob = "".join(s.get("text") or "" for s in wick["steps"]) + wick.get("think", "")
    assert "長下引線" in wblob
    assert "356.5" in wblob
    assert "375" in wblob
    hold300 = fire_chain("", "波段漲勢確認")
    h300 = "".join(s.get("text") or "" for s in hold300["steps"]) + hold300.get("think", "")
    assert "站穩" in h300
    assert "293.5" in h300
    assert "300" in h300
    half = fire_chain("", "整理半年")
    hblob = "".join(s.get("text") or "" for s in half["steps"]) + half.get("think", "")
    assert "整理半年" in hblob
    assert "140.5" in hblob
    assert "161.5" in hblob
    bound = fire_chain("", "多空分界")
    bblob = "".join(s.get("text") or "" for s in bound["steps"]) + bound.get("think", "")
    assert "289.5" in bblob
    assert "290.5" in bblob
    assert "291" in bblob
