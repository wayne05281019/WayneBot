# -*- coding: utf-8 -*-
"""圖文時間軸：第一段智原／貨櫃，第二段華碩／廣達，第三段台通／頎邦，第四段光聖／頎邦回證。"""
from biaoke_chrono import line_for, next_start, overview, slice_stop
from biaoke_charts import official_on
from biaoke_mind import format_methods_html, method_body
from biaoke_facts import names_in_ask


def test_current_slice_window():
    assert slice_stop() == "2024-05-09"
    assert next_start() == "2024-05-09"

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
    assert "時間戳" in ov
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


def test_twentieth_slice_fengda_109_124():
    body = method_body("圖文時間軸第二十段")
    assert "2024-04-01" in body
    assert "109" in body and "124" in body
    assert "不是日K" in body
    assert "116.5" in body
    assert "豐達科" in body or "3004" in body
    f = line_for("3004")
    assert "豐達科" in f
    assert "回測" in f
    assert "116.5" in f
    ov = overview()
    assert "109" in ov and "124" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twentyfirst_slice_quanta_282_battle():
    body = method_body("圖文時間軸第二十一段")
    assert "2024-04-01" in body
    assert "多方最低標準" in body
    assert "不是日K" in body
    assert "282.5" in body
    assert "多空廝殺" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "多方最低標準" in q or "多空廝殺" in q
    assert "282.5" in q
    ov = overview()
    assert "多方最低標準" in ov or "多空廝殺" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twentysecond_slice_quanta_298_holiday():
    body = method_body("圖文時間軸第二十二段")
    assert "2024-04-02" in body
    assert "挑戰前高" in body and "298" in body
    assert "不是日K" in body
    assert "292.5" in body
    assert "放假前" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "挑戰前高" in q or "放假前" in q
    assert "292.5" in q
    ov = overview()
    assert "挑戰前高" in ov or "放假前" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twentythird_slice_fengda_114_pressure():
    body = method_body("圖文時間軸第二十三段")
    assert "2024-04-02" in body
    assert "114-114.5" in body
    assert "不是日K" in body
    assert "114" in body
    assert "去年兩個高點" in body or "壓力" in body
    f = line_for("3004")
    assert "豐達科" in f
    assert "114-114.5" in f or "114" in f
    ov = overview()
    assert "114-114.5" in ov or "去年兩個高點" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twentyfourth_slice_ennoconn_350():
    body = method_body("圖文時間軸第二十四段")
    assert "2024-04-02" in body
    assert "365" in body and "350" in body
    assert "不是日K" in body
    assert "352" in body
    assert "守得住" in body
    e = line_for("6414")
    assert "樺漢" in e
    assert "350" in e
    assert "352" in e
    ov = overview()
    assert "350" in ov or "回測 365" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twentyfifth_slice_iei_6117():
    body = method_body("圖文時間軸第二十五段")
    assert "2024-04-09" in body
    assert "6117" in body
    assert "不是日K" in body
    assert "107" in body
    assert "建立所有部位" in body or "上車" in body
    y = line_for("6117")
    assert "迎廣" in y
    assert "107" in y
    assert "不是日K" in y
    ov = overview()
    assert "6117" in ov or "迎廣" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twentysixth_slice_tsmc_810():
    body = method_body("圖文時間軸第二十六段")
    assert "2024-04-09" in body
    assert "810" in body
    assert "不是日K" in body
    assert "816" in body
    assert "9XX" in body
    t = line_for("2330")
    assert "台積電" in t
    assert "810" in t
    assert "816" in t
    ov = overview()
    assert "810" in ov or "9XX" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov


def test_twentyseventh_slice_thunder_chenming_intraday():
    body = method_body("圖文時間軸第二十七段")
    assert "2024-04-09" in body
    assert "急殺買" in body
    assert "今天早盤應該是低點" in body
    assert "不是日K" in body
    assert "71.3" in body
    assert "70.4" in body
    assert "雷虎" in body
    assert "晟銘電" in body
    assert "3044" in body and "不對圖" in body
    tt = line_for("8033")
    assert "雷虎" in tt
    assert "71.3" in tt
    assert "不是日K" in tt
    cm = line_for("3013")
    assert "晟銘電" in cm
    assert "70.4" in cm
    assert "急殺買" in cm
    ov = overview()
    assert "急殺買" in ov or "早盤低點" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("急殺買")
    assert "雷虎" in html and "晟銘電" in html
    assert "不是日K" in html
    assert "71.3" in html and "70.4" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "急殺買")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "急殺買" in blob
    assert "71.3" in blob or "70.4" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    r09 = official_on(db, "8033", "20240409")
    assert r09 == {} or (
        abs(float(r09["low"]) - 68.5) < 0.01 and abs(float(r09["close"]) - 77) < 0.01
    )
    c09 = official_on(db, "3013", "20240409")
    assert c09 == {} or (
        abs(float(c09["low"]) - 67) < 0.01 and abs(float(c09["close"]) - 67) < 0.01
    )


def test_twentyeighth_slice_lasertek_pullback():
    body = method_body("圖文時間軸第二十八段")
    assert "2024-04-10" in body
    assert "剛好止漲回測" in body or "止漲回測" in body
    assert "先買 1/2" in body or "先買1/2" in body
    assert "不是日K" in body
    assert "58.1" in body
    assert "雷科" in body
    assert "志聖" in body
    assert "均豪" in body
    assert "5310" in body and "不對圖" in body
    lk = line_for("6207")
    assert "雷科" in lk
    assert "58.1" in lk
    assert "不是日K" in lk
    zs = line_for("2467")
    assert "志聖" in zs
    assert "135" in zs
    jh = line_for("5443")
    assert "均豪" in jh
    assert "69.1" in jh
    ov = overview()
    assert "止漲回測" in ov or "雷科" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("剛好止漲回測")
    assert "雷科" in html
    assert "不是日K" in html
    assert "58.1" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "剛好止漲回測")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "止漲回測" in blob
    assert "58.1" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    r10 = official_on(db, "6207", "20240410")
    assert r10 == {} or (
        abs(float(r10["low"]) - 56.4) < 0.01 and abs(float(r10["close"]) - 56.6) < 0.01
    )
    z10 = official_on(db, "2467", "20240410")
    assert z10 == {} or (
        abs(float(z10["low"]) - 130) < 0.01 and abs(float(z10["close"]) - 131.5) < 0.01
    )
    j10 = official_on(db, "5443", "20240410")
    assert j10 == {} or (
        abs(float(j10["low"]) - 67.5) < 0.01 and abs(float(j10["close"]) - 69) < 0.01
    )


def test_twentyninth_slice_supermicro_chassis():
    body = method_body("圖文時間軸第二十九段")
    assert "2024-04-10" in body
    assert "美超微機殼" in body
    assert "收大黑K" in body
    assert "最佳上車時機" in body
    assert "不是日K" in body
    assert "103.5" in body
    assert "70" in body
    assert "迎廣" in body
    assert "晟銘電" in body
    y = line_for("6117")
    assert "迎廣" in y
    assert "103.5" in y
    assert "不是日K" in y
    cm = line_for("3013")
    assert "晟銘電" in cm
    assert "70" in cm
    ov = overview()
    assert "美超微" in ov or "最佳上車" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("最佳上車時機")
    assert "迎廣" in html and "晟銘電" in html
    assert "不是日K" in html
    assert "103.5" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "最佳上車時機")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "最佳上車" in blob
    assert "103.5" in blob or "70" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    y10 = official_on(db, "6117", "20240410")
    assert y10 == {} or (
        abs(float(y10["low"]) - 98.8) < 0.01 and abs(float(y10["close"]) - 98.8) < 0.01
    )
    c10 = official_on(db, "3013", "20240410")
    assert c10 == {} or (
        abs(float(c10["high"]) - 73.7) < 0.01 and abs(float(c10["close"]) - 73.7) < 0.01
    )


def test_thirtieth_slice_ask_who_leads():
    body = method_body("圖文時間軸第三十段")
    assert "2024-04-11" in body
    assert "會影響到迎廣走勢" in body
    assert "剛公佈的業績" in body
    assert "有哪位高手可解惑" in body
    assert "不是日K" in body
    assert "75.8" in body
    assert "100" in body
    assert "迎廣" in body
    assert "晟銘電" in body
    y = line_for("6117")
    assert "迎廣" in y
    assert "100" in y
    assert "不是日K" in y
    cm = line_for("3013")
    assert "晟銘電" in cm
    assert "75.8" in cm
    ov = overview()
    assert "解惑" in ov or "2-3 日" in ov or "2-3日" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("有哪位高手可解惑")
    assert "迎廣" in html and "晟銘電" in html
    assert "不是日K" in html
    assert "75.8" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "有哪位高手可解惑")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "解惑" in blob
    assert "75.8" in blob or "100" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    y11 = official_on(db, "6117", "20240411")
    assert y11 == {} or (
        abs(float(y11["low"]) - 95) < 0.01 and abs(float(y11["close"]) - 96) < 0.01
    )
    c11 = official_on(db, "3013", "20240411")
    assert c11 == {} or (
        abs(float(c11["high"]) - 80.1) < 0.01 and abs(float(c11["close"]) - 72.3) < 0.01
    )


def test_thirtyfirst_slice_tech_ma5_prefer_3013():
    body = method_body("圖文時間軸第三十一段")
    assert "2024-04-12" in body
    assert "支撐線沿著5日均線" in body or "支撐線沿著 5 日均線" in body
    assert "10日均線撐住" in body or "10 日均線撐住" in body
    assert "單純以技術面來說" in body
    assert "不是日K" in body
    assert "76.2" in body
    assert "97.6" in body
    assert "迎廣" in body
    assert "晟銘電" in body
    assert "雷虎" not in body
    y = line_for("6117")
    assert "迎廣" in y
    assert "97.6" in y
    assert "不是日K" in y
    cm = line_for("3013")
    assert "晟銘電" in cm
    assert "76.2" in cm
    ov = overview()
    assert "優先選 3013" in ov or "沿 5 日均線" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("單純以技術面來說")
    assert "迎廣" in html and "晟銘電" in html
    assert "不是日K" in html
    assert "76.2" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "單純以技術面來說")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "技術面" in blob
    assert "76.2" in blob or "97.6" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    y12 = official_on(db, "6117", "20240412")
    assert y12 == {} or (
        abs(float(y12["low"]) - 93.1) < 0.01 and abs(float(y12["close"]) - 93.1) < 0.01
    )
    c12 = official_on(db, "3013", "20240412")
    assert c12 == {} or (
        abs(float(c12["high"]) - 78.6) < 0.01 and abs(float(c12["close"]) - 74.3) < 0.01
    )


def test_thirtysecond_slice_canon_sehi_limit_up():
    body = method_body("圖文時間軸第三十二段")
    assert "2024-04-12" in body
    assert "讓佳能跑掉漲停" in body
    assert "第二選擇協易機" in body
    assert "找拉回上車時機" in body
    assert "不是日K" in body
    assert "38.9" in body
    assert "40.25" in body
    assert "佳能" in body
    assert "協易機" in body
    cn = line_for("2374")
    assert "佳能" in cn
    assert "38.9" in cn
    assert "不是日K" in cn
    se = line_for("4533")
    assert "協易機" in se
    assert "40.25" in se
    ov = overview()
    assert "讓佳能跑掉漲停" in ov or "找拉回" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("找拉回上車時機")
    assert "佳能" in html and "協易機" in html
    assert "不是日K" in html
    assert "38.9" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "找拉回上車時機")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "拉回上車" in blob or "漲停" in blob
    assert "38.9" in blob or "40.25" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    c12 = official_on(db, "2374", "20240412")
    assert c12 == {} or (
        abs(float(c12["high"]) - 38.9) < 0.01 and abs(float(c12["close"]) - 38.9) < 0.01
    )
    s12 = official_on(db, "4533", "20240412")
    assert s12 == {} or (
        abs(float(s12["high"]) - 40.25) < 0.01 and abs(float(s12["close"]) - 40.25) < 0.01
    )


def test_thirtythird_slice_lasertek_stage2():
    body = method_body("圖文時間軸第三十三段")
    assert "2024-04-12" in body
    assert "雷科雖然被關" in body
    assert "第二階段型態目標價" in body
    assert "第三階段型態極限目標價" in body
    assert "不是日K" in body
    assert "截圖約 62" in body
    assert "64.6" in body
    assert "雷科" in body
    lk = line_for("6207")
    assert "雷科" in lk
    assert "截圖約 62" in lk
    assert "不是日K" in lk
    ov = overview()
    assert "第二階段型態目標價" in ov or "雖然被關" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("第三階段型態極限目標價")
    assert "雷科" in html
    assert "不是日K" in html
    assert "截圖約 62" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "第三階段型態極限目標價")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "極限目標價" in blob or "第二階段型態" in blob
    assert "截圖約 62" in blob or "64.5" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    b12 = official_on(db, "6207", "20240412")
    assert b12 == {} or (
        abs(float(b12["high"]) - 64.5) < 0.01 and abs(float(b12["close"]) - 62.4) < 0.01
    )


def test_thirtyfourth_slice_quanta_restore_k():
    body = method_body("圖文時間軸第三十四段")
    assert "2024-04-12" in body
    assert "抱到7-8月" in body
    assert "支撐線不是282" in body
    assert "還原權值K線" in body
    assert "不是日K" in body
    assert "截圖約 273" in body
    assert "廣達" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "截圖約 273" in q
    assert "不是日K" in q
    ov = overview()
    assert "還原權值K線" in ov or "支撐線不是282" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("還原權值K線")
    assert "廣達" in html
    assert "不是日K" in html
    assert "截圖約 273" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "還原權值K線")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "還原權值" in blob or "273" in blob
    assert "截圖約 273" in blob or "271" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    q12 = official_on(db, "2382", "20240412")
    assert q12 == {} or (
        abs(float(q12["low"]) - 271) < 0.01 and abs(float(q12["close"]) - 271) < 0.01
    )


def test_thirtyfifth_slice_thunder_k_structure():
    body = method_body("圖文時間軸第三十五段")
    assert "2024-04-12" in body
    assert "從K線量價結構" in body
    assert "上車最佳時機" in body
    assert "今天應該是上車" in body
    assert "不是日K" in body
    assert "截圖約 75" in body
    assert "雷虎" in body
    tt = line_for("8033")
    assert "雷虎" in tt
    assert "截圖約 75" in tt
    assert "不是日K" in tt
    ov = overview()
    assert "從K線量價結構" in ov or "上車最佳時機" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("從K線量價結構")
    assert "雷虎" in html
    assert "不是日K" in html
    assert "截圖約 75" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "從K線量價結構")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "從K線量價結構" in blob or "上車最佳" in blob
    assert "截圖約 75" in blob or "75.9" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    t12 = official_on(db, "8033", "20240412")
    assert t12 == {} or (
        abs(float(t12["high"]) - 77.4) < 0.01 and abs(float(t12["close"]) - 75.9) < 0.01
    )


def test_thirtysixth_slice_thunder_friday_entry_verified():
    body = method_body("圖文時間軸第三十六段")
    assert "2024-04-15" in body
    assert "上星期五中午我說的上車時間" in body
    assert "挑戰歷史高點85.2" in body
    assert "洗個1-3天" in body
    assert "不是日K" in body
    assert "截圖約 83.4" in body
    assert "雷虎" in body
    tt = line_for("8033")
    assert "雷虎" in tt
    assert "截圖約 83.4" in tt
    assert "不是日K" in tt
    ov = overview()
    assert "挑戰歷史高點85.2" in ov or "上星期五中午" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("挑戰歷史高點85.2")
    assert "雷虎" in html
    assert "不是日K" in html
    assert "截圖約 83.4" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "挑戰歷史高點85.2")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "挑戰歷史高點85.2" in blob or "上星期五中午" in blob
    assert "截圖約 83.4" in blob or "83.4" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    t15 = official_on(db, "8033", "20240415")
    assert t15 == {} or (
        abs(float(t15["high"]) - 83.4) < 0.01 and abs(float(t15["close"]) - 83.4) < 0.01
    )


def test_thirtyseventh_slice_lasertek_5ma_entry():
    body = method_body("圖文時間軸第三十七段")
    assert "2024-04-15" in body
    assert "回測5MA支撐線" in body
    assert "不用賣" in body
    assert "空手上車時間" in body
    assert "不是日K" in body
    assert "截圖約 61.4" in body
    assert "雷科" in body
    lk = line_for("6207")
    assert "雷科" in lk
    assert "截圖約 61.4" in lk
    assert "不是日K" in lk
    ov = overview()
    assert "回測5MA支撐線" in ov or "空手上車時間" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("回測5MA支撐線")
    assert "雷科" in html
    assert "不是日K" in html
    assert "截圖約 61.4" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "回測5MA支撐線")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "回測5MA支撐線" in blob or "空手上車" in blob
    assert "截圖約 61.4" in blob or "61.5" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    l15 = official_on(db, "6207", "20240415")
    assert l15 == {} or (
        abs(float(l15["low"]) - 59.0) < 0.01 and abs(float(l15["close"]) - 61.5) < 0.01
    )


def test_thirtyeighth_slice_lock_sold_sehi():
    body = method_body("圖文時間軸第三十八段")
    assert "2024-04-15" in body
    assert "這兩檔列入鎖股" in body
    assert "協易機爆大量" in body
    assert "已經賣了" in body
    assert "不是日K" in body
    assert "截圖約 40.1" in body
    assert "截圖約 39.65" in body
    assert "截圖約 119" in body
    assert "佳能" in body and "協易機" in body and "漢科" in body
    cn = line_for("2374")
    assert "佳能" in cn
    assert "截圖約 40.1" in cn
    assert "不是日K" in cn
    se = line_for("4533")
    assert "協易機" in se
    assert "截圖約 39.65" in se
    hk = line_for("3402")
    assert "漢科" in hk
    assert "截圖約 119" in hk
    ov = overview()
    assert "這兩檔列入鎖股" in ov or "協易機爆大量" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("這兩檔列入鎖股")
    assert "佳能" in html and "漢科" in html
    assert "不是日K" in html
    assert "截圖約 40.1" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "這兩檔列入鎖股")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "這兩檔列入鎖股" in blob or "協易機爆大量" in blob
    assert "截圖約 40.1" in blob or "37.65" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    c15 = official_on(db, "2374", "20240415")
    assert c15 == {} or (
        abs(float(c15["high"]) - 41.1) < 0.01 and abs(float(c15["close"]) - 37.65) < 0.01
    )
    s15 = official_on(db, "4533", "20240415")
    assert s15 == {} or (
        abs(float(s15["high"]) - 42.5) < 0.01 and abs(float(s15["close"]) - 38.85) < 0.01
    )
    h15 = official_on(db, "3402", "20240415")
    assert h15 == {} or (
        abs(float(h15["high"]) - 126.0) < 0.01 and abs(float(h15["close"]) - 121.5) < 0.01
    )


def test_thirtyninth_slice_canon_374_half():
    body = method_body("圖文時間軸第三十九段")
    assert "2024-04-16" in body
    assert "早盤在37.4" in body
    assert "今日10點之前多空交界區" in body
    assert "先買一半" in body
    assert "不是日K" in body
    assert "截圖約 38.6" in body
    assert "佳能" in body
    cn = line_for("2374")
    assert "佳能" in cn
    assert "截圖約 38.6" in cn
    assert "不是日K" in cn
    ov = overview()
    assert "早盤在37.4" in ov or "多空交界區" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("早盤在37.4")
    assert "佳能" in html
    assert "不是日K" in html
    assert "截圖約 38.6" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "早盤在37.4")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "早盤在37.4" in blob or "先買一半" in blob
    assert "截圖約 38.6" in blob or "38.45" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    c16 = official_on(db, "2374", "20240416")
    assert c16 == {} or (
        abs(float(c16["low"]) - 36.3) < 0.01 and abs(float(c16["close"]) - 38.45) < 0.01
    )


def test_fortieth_slice_hank_117_third():
    body = method_body("圖文時間軸第四十段")
    assert "2024-04-16" in body
    assert "先掛117-117.5" in body
    assert "兩個價位" in body
    assert "先買1/3" in body
    assert "先買一半" not in body
    assert "不是日K" in body
    assert "截圖約 118" in body
    assert "漢科" in body
    hk = line_for("3402")
    assert "漢科" in hk
    assert "截圖約 118" in hk
    assert "不是日K" in hk
    assert "先掛117-117.5" in hk
    ov = overview()
    assert "先掛117-117.5" in ov or "先買1/3" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("先掛117-117.5")
    assert "漢科" in html
    assert "不是日K" in html
    assert "截圖約 118" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "先掛117-117.5")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "先掛117-117.5" in blob or "先買1/3" in blob
    assert "截圖約 118" in blob or "115.0" in blob or "115" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    h16 = official_on(db, "3402", "20240416")
    assert h16 == {} or (
        abs(float(h16["low"]) - 113.0) < 0.01 and abs(float(h16["close"]) - 115.0) < 0.01
    )


def test_fortyfirst_slice_leike_neck_565():
    body = method_body("圖文時間軸第四十一段")
    assert "2024-04-16" in body
    assert "打到頸線56.5" in body
    assert "第一次不太可能直接跌破" in body
    assert "三日之內必需重新站上" in body
    assert "不是日K" in body
    assert "截圖約 57.5" in body
    assert "雷科" in body
    assert "先買1/3" not in body
    lk = line_for("6207")
    assert "雷科" in lk
    assert "截圖約 57.5" in lk
    assert "不是日K" in lk
    assert "打到頸線56.5" in lk
    ov = overview()
    assert "打到頸線56.5" in ov or "第一次不太可能直接跌破" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("打到頸線56.5")
    assert "雷科" in html
    assert "不是日K" in html
    assert "截圖約 57.5" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "打到頸線56.5")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "打到頸線56.5" in blob or "第一次不太可能直接跌破" in blob
    assert "截圖約 57.5" in blob or "58.6" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    k16 = official_on(db, "6207", "20240416")
    assert k16 == {} or (
        abs(float(k16["low"]) - 56.2) < 0.01 and abs(float(k16["close"]) - 58.6) < 0.01
    )


def test_fortysecond_slice_index_19650_not_wrong_charts():
    body = method_body("圖文時間軸第四十二段")
    assert "2024-04-16" in body
    assert "直探19650" in body
    assert "19650會測兩次" in body or "測兩次" in body
    assert "不數段" in body
    assert "不是加權" in body or "不是加權日K" in body or "加權指數" in body
    assert "不對圖" in body
    assert "佳能" in body and "0050" in body
    assert "截圖約 786" in body
    twii = line_for("TWII")
    assert "直探19650" in twii
    assert "加權指數" in twii
    assert "不數段" in twii
    assert "直探19650" not in line_for("TX")
    tsmc = line_for("2330")
    assert "截圖約 786" in tsmc
    assert "不是日K" in tsmc
    ov = overview()
    assert "直探19650" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("直探19650")
    assert "19650" in html
    assert "不數段" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "直探19650")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "直探19650" in blob or "19650會測兩次" in blob
    assert "不數段" in blob
    db = "data/wayne_market.db"
    t16 = official_on(db, "2330", "20240416")
    assert t16 == {} or (
        abs(float(t16["low"]) - 785) < 0.01 and abs(float(t16["close"]) - 788) < 0.01
    )


def test_fortythird_slice_gap_neck_not_stock_charts():
    body = method_body("圖文時間軸第四十三段")
    assert "2024-04-17" in body
    assert "19500~19650" in body
    assert "缺口至頸線" in body
    assert "244" in body and "245" in body
    assert "不數段" in body
    assert "不對圖" in body
    tx = line_for("TX")
    assert "19500~19650" not in tx
    twii = line_for("TWII")
    assert "19500~19650" in twii
    assert "加權指數" in twii
    otc = line_for("OTC")
    assert "244" in otc
    ov = overview()
    assert "19500~19650" in ov
    html = format_methods_html("19500~19650")
    assert "19500~19650" in html
    assert "不數段" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "19500~19650")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "19500~19650" in blob
    assert "不數段" in blob


def test_fortyfourth_slice_honso_limitup_leike_645():
    body = method_body("圖文時間軸第四十四段")
    assert "2024-04-17" in body
    assert "我沒有弘塑" in body
    assert "漲停過前高" in body
    assert "也會過前高 64.5" in body
    assert "不是日K" in body
    assert "截圖約 1110" in body
    assert "截圖約 61.5" in body
    assert "弘塑" in body and "雷科" in body
    hs = line_for("3131")
    assert "弘塑" in hs
    assert "截圖約 1110" in hs
    assert "不是日K" in hs
    assert "我沒有弘塑" in hs or "沒有弘塑" in hs
    lk = line_for("6207")
    assert "也會過前高 64.5" in lk
    assert "截圖約 61.5" in lk
    assert "不是日K" in lk
    ov = overview()
    assert "弘塑漲停過前高" in ov or "也會過前高 64.5" in ov
    assert "抱著波段賺更多" in ov and "對不到" in ov
    html = format_methods_html("我沒有弘塑")
    assert "弘塑" in html
    assert "不是日K" in html
    assert "截圖約 1110" in html
    html2 = format_methods_html("也會過前高64.5")
    assert "雷科" in html2
    assert "64.5" in html2
    from biaoke_chain import fire_chain

    fired = fire_chain("", "也會過前高64.5")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "也會過前高" in blob
    assert "截圖約 61.5" in blob or "61.4" in blob or "截圖約 1110" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    h17 = official_on(db, "3131", "20240417")
    assert h17 == {} or (
        abs(float(h17["high"]) - 1110) < 0.01 and abs(float(h17["close"]) - 1110) < 0.01
    )
    k17 = official_on(db, "6207", "20240417")
    assert k17 == {} or (
        abs(float(k17["high"]) - 62.4) < 0.01 and abs(float(k17["close"]) - 61.4) < 0.01
    )


def test_fortyfifth_slice_tx_night_19650_twii_19844():
    body = method_body("圖文時間軸第四十五段")
    assert "2024-04-18" in body
    assert "台指期夜盤" in body
    assert "最多打到19650" in body
    assert "19844" in body
    assert "不數段" in body
    assert "不對圖" in body
    assert "截圖約 804" in body
    tx = line_for("TX")
    assert "最多打到19650" in tx
    assert "台指期夜盤" in tx
    assert "直探19650" not in tx
    assert "19500~19650" not in tx
    twii = line_for("TWII")
    assert "19844" in twii
    assert "加權指數" in twii or "加權" in twii
    assert "直探19650" in twii
    ov = overview()
    assert "台指期夜盤" in ov
    assert "19844" in ov
    html = format_methods_html("台指期夜盤")
    assert "最多打到19650" in html
    assert "19844" in html
    assert "不數段" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "最多打到19650")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "最多打到19650" in blob
    assert "不數段" in blob
    db = "data/wayne_market.db"
    t17 = official_on(db, "2330", "20240417")
    assert t17 == {} or (
        abs(float(t17["high"]) - 808) < 0.01 and abs(float(t17["close"]) - 804) < 0.01
    )


def test_fortysixth_slice_huang_peishuo_18752():
    body = method_body("圖文時間軸第四十六段")
    assert "2024-04-19" in body
    assert "黃培碩" in body
    assert "18752-19012" in body
    assert "不數段" in body
    assert "加權日K" in body or "加權日線" in body
    assert "17500" in body
    twii = line_for("TWII")
    assert "18752-19012" in twii
    assert "黃培碩" in twii
    ov = overview()
    assert "黃培碩" in ov
    assert "18752-19012" in ov
    html = format_methods_html("黃培碩")
    assert "18752-19012" in html
    assert "不數段" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "18752-19012")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "18752-19012" in blob
    assert "不數段" in blob


def test_fortyseventh_slice_old_ai_wistron_intraday():
    body = method_body("圖文時間軸第四十七段")
    assert "2024-04-21" in body
    assert "兩階段跌幅滿足" in body
    assert "成本230不會再買" in body
    assert "優先佈局金像電" in body
    assert "滿足是350" in body
    assert "小時線站上119" in body
    assert "不數段" in body
    assert "不准發明細微波" in body
    assert "不是日K" in body
    assert "截圖約 115" in body
    assert "不對圖" in body
    w = line_for("3231")
    assert "緯創" in w
    assert "小時線站上119" in w
    assert "截圖約 115" in w
    assert "不是日K" in w
    q = line_for("2382")
    assert "成本230不會再買" in q
    assert "不對圖" in q
    g = line_for("2368")
    assert "優先佈局金像電" in g
    assert "不對圖" in g
    e = line_for("2383")
    assert "滿足是350" in e
    assert "不對圖" in e
    ov = overview()
    assert "小時線站上119" in ov
    assert "優先佈局金像電" in ov
    html = format_methods_html("小時線站上119")
    assert "緯創" in html
    assert "截圖約 115" in html
    assert "不數段" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "小時線站上119")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "小時線站上119" in blob
    assert "不數段" in blob
    db = "data/wayne_market.db"
    w19 = official_on(db, "3231", "20240419")
    assert w19 == {} or (
        abs(float(w19["high"]) - 119) < 0.01 and abs(float(w19["close"]) - 115) < 0.01
        and abs(float(w19["low"]) - 111) < 0.01
    )
    w22 = official_on(db, "3231", "20240422")
    assert w22 == {} or (
        abs(float(w22["low"]) - 108.5) < 0.01 and abs(float(w22["close"]) - 108.5) < 0.01
    )
    q19 = official_on(db, "2382", "20240419")
    assert q19 == {} or (
        abs(float(q19["low"]) - 237) < 0.01 and abs(float(q19["close"]) - 241.5) < 0.01
    )
    g19 = official_on(db, "2368", "20240419")
    assert g19 == {} or (
        abs(float(g19["low"]) - 190.5) < 0.01 and abs(float(g19["close"]) - 196) < 0.01
    )
    e22 = official_on(db, "2383", "20240422")
    assert e22 == {} or (
        abs(float(e22["low"]) - 350.5) < 0.01 and abs(float(e22["close"]) - 350.5) < 0.01
    )


def test_fortyeighth_slice_old_ai_quanta_wiwynn_ennoconn():
    body = method_body("圖文時間軸第四十八段")
    assert "2024-04-26" in body
    assert "6669我比較看好" in body
    assert "機殼8210持續看好" in body
    assert "先以跌深反談" in body
    assert "不是日K" in body
    assert "截圖約 297" in body
    assert "截圖約 263.5" in body
    assert "截圖約 2380" in body
    assert "不對圖" in body
    q = line_for("2382")
    assert "漲勢確認" in q
    assert "截圖約 263.5" in q
    assert "不是日K" in q
    w = line_for("6669")
    assert "緯穎" in w
    assert "比較看好" in w
    assert "截圖約 2380" in w
    e = line_for("8210")
    assert "勤誠" in e
    assert "持續看好" in e
    assert "截圖約 297" in e
    emc = line_for("2383")
    assert "跌深反談" in emc
    assert "不對圖" in emc
    ov = overview()
    assert "6669" in ov
    assert "8210" in ov
    html = format_methods_html("6669我比較看好")
    assert "緯穎" in html
    assert "截圖約 2380" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "6669我比較看好")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "6669我比較看好" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    q26 = official_on(db, "2382", "20240426")
    assert q26 == {} or (
        abs(float(q26["high"]) - 269) < 0.01 and abs(float(q26["close"]) - 257.5) < 0.01
    )
    y26 = official_on(db, "6669", "20240426")
    assert y26 == {} or (
        abs(float(y26["high"]) - 2410) < 0.01 and abs(float(y26["close"]) - 2325) < 0.01
    )
    c26 = official_on(db, "8210", "20240426")
    assert c26 == {} or (
        abs(float(c26["high"]) - 303) < 0.01 and abs(float(c26["close"]) - 288.5) < 0.01
    )
    e26 = official_on(db, "2383", "20240426")
    assert e26 == {} or (
        abs(float(e26["low"]) - 390) < 0.01 and abs(float(e26["close"]) - 397) < 0.01
    )


def test_fortyninth_slice_ennoconn_289_head_shoulders():
    body = method_body("圖文時間軸第四十九段")
    assert "2024-04-26" in body
    assert "站上289以上" in body
    assert "過前高323" in body
    assert "不是日K" in body
    assert "截圖約 289.5" in body
    assert "勤誠" in body
    e = line_for("8210")
    assert "勤誠" in e
    assert "站上289" in e
    assert "截圖約 289.5" in e
    assert "不是日K" in e
    ov = overview()
    assert "過前高323" in ov
    assert "289.5" in ov
    html = format_methods_html("站上289以上")
    assert "勤誠" in html
    assert "截圖約 289.5" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "站上289以上")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "站上289以上" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    c26 = official_on(db, "8210", "20240426")
    assert c26 == {} or (
        abs(float(c26["high"]) - 303) < 0.01 and abs(float(c26["close"]) - 288.5) < 0.01
    )
    c27 = official_on(db, "8210", "20240527")
    assert c27 == {} or (
        abs(float(c27["high"]) - 341) < 0.01 and abs(float(c27["close"]) - 341) < 0.01
    )


def test_fiftieth_slice_gigalight_intraday_buy():
    body = method_body("圖文時間軸第五十段")
    assert "2024-05-02" in body
    assert "行進中上車短線買點" in body
    assert "二月份有操作這檔股票" in body
    assert "不是日K" in body
    assert "截圖約 50.1" in body
    assert "光環" in body
    g = line_for("3234")
    assert "光環" in g
    assert "行進中上車短線買點" in g
    assert "截圖約 50.1" in g
    assert "不是日K" in g
    ov = overview()
    assert "行進中上車短線買點" in ov
    assert "光環" in ov
    html = format_methods_html("行進中上車短線買點")
    assert "光環" in html
    assert "截圖約 50.1" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "行進中上車短線買點")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "行進中上車短線買點" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    g02 = official_on(db, "3234", "20240502")
    assert g02 == {} or (
        abs(float(g02["high"]) - 50.9) < 0.01 and abs(float(g02["close"]) - 50.6) < 0.01
        and abs(float(g02["low"]) - 46.85) < 0.01
    )


def test_fiftyfirst_slice_gigalight_disposed_switch_gs():
    body = method_body("圖文時間軸第五十一段")
    assert "2024-05-03" in body
    assert "3234被處置" in body
    assert "不是假突破的6442" in body
    assert "不是日K" in body
    assert "截圖約 48.55" in body
    assert "截圖約 165.5" in body
    g = line_for("3234")
    assert "被處置" in g
    assert "截圖約 48.55" in g
    assert "不是日K" in g
    gs = line_for("6442")
    assert "光聖" in gs
    assert "不是假突破" in gs
    assert "截圖約 165.5" in gs
    ov = overview()
    assert "3234被處置" in ov
    html = format_methods_html("3234被處置")
    assert "光環" in html and "光聖" in html
    assert "截圖約 48.55" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "3234被處置")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "3234被處置" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    g03 = official_on(db, "3234", "20240503")
    assert g03 == {} or (
        abs(float(g03["low"]) - 47.25) < 0.01 and abs(float(g03["close"]) - 47.7) < 0.01
    )
    s03 = official_on(db, "6442", "20240503")
    assert s03 == {} or (
        abs(float(s03["high"]) - 172) < 0.01 and abs(float(s03["close"]) - 161) < 0.01
    )


def test_fiftysecond_slice_quanta_intraday_not_weekly():
    body = method_body("圖文時間軸第五十二段")
    assert "2024-05-03" in body
    assert "2382的後勢擔憂" in body
    assert "60分鐘線是頭肩底" in body
    assert "週線頭肩頂" in body
    assert "不是日K" in body
    assert "不是60分" in body or "不是週線" in body
    assert "截圖約 256.5" in body
    assert "不數段" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "後勢擔憂" in q or "60分鐘線是頭肩底" in q
    assert "截圖約 256.5" in q
    assert "不是日K" in q
    assert "2330" in q and "不對圖" in q
    ov = overview()
    assert "2382的後勢擔憂" in ov or "很多人對2382" in ov
    assert "256.5" in ov
    html = format_methods_html("2382的後勢擔憂")
    assert "廣達" in html
    assert "截圖約 256.5" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "最保守會反彈那個價區")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "最保守會反彈那個價區" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    q03 = official_on(db, "2382", "20240503")
    assert q03 == {} or (
        abs(float(q03["high"]) - 266) < 0.01
        and abs(float(q03["low"]) - 256.5) < 0.01
        and abs(float(q03["close"]) - 256.5) < 0.01
    )
    q02 = official_on(db, "2382", "20240502")
    assert q02 == {} or abs(float(q02["close"]) - 261) < 0.01


def test_fiftythird_slice_quanta_min_target_intraday():
    body = method_body("圖文時間軸第五十三段")
    assert "2024-05-06" in body
    assert "型態最少滿足價區到了" in body
    assert "不是日K" in body
    assert "截圖約 272.5" in body
    assert "不數段" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "型態最少滿足價區到了" in q
    assert "截圖約 272.5" in q
    assert "不是日K" in q
    ov = overview()
    assert "型態最少滿足價區到了" in ov
    assert "272.5" in ov
    html = format_methods_html("型態最少滿足價區到了")
    assert "廣達" in html
    assert "截圖約 272.5" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "型態最少滿足價區到了")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "型態最少滿足價區到了" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    q06 = official_on(db, "2382", "20240506")
    assert q06 == {} or (
        abs(float(q06["high"]) - 273) < 0.01
        and abs(float(q06["low"]) - 262) < 0.01
        and abs(float(q06["close"]) - 262) < 0.01
    )


def test_fiftyfourth_slice_emc_right_shoulder_intraday():
    body = method_body("圖文時間軸第五十四段")
    assert "2024-05-07" in body
    assert "今天在做型態右肩" in body
    assert "蔡森" in body
    assert "8-10根K" in body
    assert "不是日K" in body
    assert "截圖約 412.5" in body
    assert "不數段" in body
    e = line_for("2383")
    assert "台光電" in e
    assert "今天在做型態右肩" in e
    assert "截圖約 412.5" in e
    assert "不是日K" in e
    ov = overview()
    assert "今天在做型態右肩" in ov
    assert "412.5" in ov
    html = format_methods_html("型態大師蔡森")
    assert "台光電" in html
    assert "截圖約 412.5" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "型態大師蔡森")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "型態大師蔡森" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    e07 = official_on(db, "2383", "20240507")
    assert e07 == {} or (
        abs(float(e07["low"]) - 409) < 0.01 and abs(float(e07["close"]) - 420) < 0.01
    )


def test_fiftyfifth_slice_alchip_no_bottom_fish():
    body = method_body("圖文時間軸第五十五段")
    assert "2024-05-08" in body
    assert "抄底3661" in body
    assert "2150" in body
    assert "不是日K" in body
    assert "截圖約 2760" in body
    assert "不數段" in body
    s = line_for("3661")
    assert "世芯" in s
    assert "抄底3661" in s
    assert "截圖約 2760" in s
    assert "不是日K" in s
    ov = overview()
    assert "抄底3661" in ov
    assert "2760" in ov
    html = format_methods_html("跌幅型態滿足價位在2150")
    assert "世芯" in html
    assert "截圖約 2760" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "跌幅型態滿足價位在2150")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "2150" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    a07 = official_on(db, "3661", "20240507")
    assert a07 == {} or (
        abs(float(a07["low"]) - 2725) < 0.01 and abs(float(a07["close"]) - 2760) < 0.01
    )


def test_fiftysixth_slice_quanta_early_280_not_others():
    body = method_body("圖文時間軸第五十六段")
    assert "2024-05-08" in body
    assert "鼎天、廣明" in body
    assert "提早上280" in body
    assert "不是日K" in body
    assert "截圖約 274.5" in body
    q = line_for("2382")
    assert "廣達" in q
    assert "提早上280" in q
    assert "截圖約 274.5" in q
    assert "不是日K" in q
    d = line_for("3306")
    assert "鼎天" in d
    assert "不對圖" in d
    assert "圖不是鼎天" in d or "不是鼎天" in d
    g = line_for("6188")
    assert "廣明" in g
    assert "不對圖" in g
    ov = overview()
    assert "鼎天、廣明" in ov
    assert "274.5" in ov
    html = format_methods_html("鼎天、廣明")
    assert "廣達" in html
    assert "截圖約 274.5" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "鼎天、廣明")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "鼎天、廣明" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    q08 = official_on(db, "2382", "20240508")
    assert q08 == {} or (
        abs(float(q08["high"]) - 277.5) < 0.01 and abs(float(q08["close"]) - 273.5) < 0.01
    )


def test_fiftyseventh_slice_asus_intraday_not_271_bar():
    body = method_body("圖文時間軸第五十七段")
    assert "2024-05-09" in body
    assert "2357直接過271" in body
    assert "不是日K" in body
    assert "截圖約 478" in body
    assert "不准發明" in body
    a = line_for("2357")
    assert "華碩" in a
    assert "截圖約 478" in a
    assert "不是日K" in a
    ov = overview()
    assert "2357直接過271" in ov
    assert "478" in ov
    html = format_methods_html("先買進1/2，明天回測持續買進")
    assert "華碩" in html
    assert "截圖約 478" in html
    assert "不是日K" in html
    from biaoke_chain import fire_chain

    fired = fire_chain("", "先買進1/2，明天回測持續買進")
    blob = "".join(s.get("text") or "" for s in fired["steps"]) + fired.get("think", "")
    assert "先買進1/2" in blob
    assert "不是日K" in blob
    db = "data/wayne_market.db"
    a09 = official_on(db, "2357", "20240509")
    assert a09 == {} or (
        abs(float(a09["high"]) - 483) < 0.01 and abs(float(a09["close"]) - 475) < 0.01
    )



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
    f29 = official_on(db, "3004", "20240329")
    assert f29 == {} or (
        abs(float(f29["low"]) - 109.5) < 0.01 and abs(float(f29["close"]) - 113) < 0.01
    )
    f01 = official_on(db, "3004", "20240401")
    assert f01 == {} or (
        abs(float(f01["high"]) - 118) < 0.01 and abs(float(f01["close"]) - 116) < 0.01
    )
    q02 = official_on(db, "2382", "20240402")
    assert q02 == {} or (
        abs(float(q02["high"]) - 299) < 0.01 and abs(float(q02["close"]) - 298) < 0.01
    )
    f02 = official_on(db, "3004", "20240402")
    assert f02 == {} or (
        abs(float(f02["low"]) - 112.5) < 0.01 and abs(float(f02["close"]) - 115.5) < 0.01
    )
    e02 = official_on(db, "6414", "20240402")
    assert e02 == {} or (
        abs(float(e02["low"]) - 345) < 0.01 and abs(float(e02["close"]) - 345.5) < 0.01
    )
    y09 = official_on(db, "6117", "20240409")
    assert y09 == {} or (
        abs(float(y09["high"]) - 108) < 0.01 and abs(float(y09["close"]) - 108) < 0.01
    )
    t09 = official_on(db, "2330", "20240409")
    assert t09 == {} or (
        abs(float(t09["high"]) - 820) < 0.01 and abs(float(t09["close"]) - 819) < 0.01
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
    assert names_in_ask("緯創怎麼看")[0][0] == "3231"
    assert names_in_ask("緯穎怎麼看")[0][0] == "6669"
    assert names_in_ask("勤誠怎麼看")[0][0] == "8210"
    assert names_in_ask("光環怎麼看")[0][0] == "3234"
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
    fd = format_methods_html("回測109")
    assert "豐達科" in fd and "不是日K" in fd
    assert "116.5" in fd and "124" in fd
    battle = format_methods_html("多空廝殺激烈")
    assert "廣達" in battle and "不是日K" in battle
    assert "282.5" in battle and "多方最低標準" in battle
    hol = format_methods_html("挑戰前高298")
    assert "廣達" in hol and "不是日K" in hol
    assert "292.5" in hol and "放假前" in hol
    fd114 = format_methods_html("回測114-114.5")
    assert "豐達科" in fd114 and "不是日K" in fd114
    assert "114-114.5" in fd114
    hold350 = format_methods_html("350應該守得住")
    assert "樺漢" in hold350 and "不是日K" in hold350
    assert "352" in hold350 and "350" in hold350
    iei = format_methods_html("建立所有部位持股")
    assert "迎廣" in iei and "不是日K" in iei
    assert "107" in iei and "6117" in iei
    tsmc = format_methods_html("目標價9XX")
    assert "台積電" in tsmc and "不是日K" in tsmc
    assert "816" in tsmc and "810" in tsmc


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
    assert "盤中" in lblob or "327" in lblob or "350" in lblob
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
    fd = fire_chain("", "回測109")
    fblob = "".join(s.get("text") or "" for s in fd["steps"]) + fd.get("think", "")
    assert "109" in fblob
    assert "116.5" in fblob
    assert "124" in fblob
    battle = fire_chain("", "多空廝殺激烈")
    b21 = "".join(s.get("text") or "" for s in battle["steps"]) + battle.get("think", "")
    assert "多方最低標準" in b21
    assert "282.5" in b21
    assert "多空廝殺" in b21
    hol = fire_chain("", "挑戰前高298")
    h22 = "".join(s.get("text") or "" for s in hol["steps"]) + hol.get("think", "")
    assert "挑戰前高" in h22
    assert "292.5" in h22
    assert "放假前" in h22
    fd114 = fire_chain("", "去年兩個高點壓力線")
    f23 = "".join(s.get("text") or "" for s in fd114["steps"]) + fd114.get("think", "")
    assert "114-114.5" in f23
    assert "去年兩個高點" in f23 or "壓力" in f23
    hold350 = fire_chain("", "350應該守得住")
    e24 = "".join(s.get("text") or "" for s in hold350["steps"]) + hold350.get("think", "")
    assert "350" in e24
    assert "352" in e24
    assert "守得住" in e24
    iei = fire_chain("", "建立所有部位持股")
    y25 = "".join(s.get("text") or "" for s in iei["steps"]) + iei.get("think", "")
    assert "6117" in y25
    assert "107" in y25
    assert "迎廣" in y25
    tsmc = fire_chain("", "目標價9XX")
    t26 = "".join(s.get("text") or "" for s in tsmc["steps"]) + tsmc.get("think", "")
    assert "810" in t26
    assert "816" in t26
    assert "9XX" in t26
