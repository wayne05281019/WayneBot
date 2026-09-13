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
    assert slice_stop() == "2024-03-19"
    assert next_start() == "2024-03-19"
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
    assert "廣達缺口" in ov
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
    flag = format_methods_html("下飄旗型整理多久")
    assert "不透漏" in flag
    assert "13日" not in flag
    asus = format_methods_html("華碩那張圖為什麼貼")
    assert "華碩" in asus and "台指期" in asus
    gs = format_methods_html("光聖那張圖為什麼貼")
    assert "光聖" in gs and "盤中" in gs
    assert "125" in gs


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
