# -*- coding: utf-8 -*-
"""大盤位階只跟飆大自己點過的標籤走。"""
import inspect
import os

from biaoke_chain import fire_chain
from biaoke_digest import format_latest_focus
from biaoke_wave import (
    EYES,
    build_twii_degree_chart,
    degree_hits,
    format_wave_now,
    is_wave_question,
    last_two,
)
from biaoke_why import is_why_query, lookup
from bot_servers import WayneTelegramBot


def test_wave_question_no_ticker():
    assert is_wave_question("現在波浪位階")
    assert is_wave_question("目前大盤是屬於哪個位階 以波浪來看的話")
    assert is_wave_question("他技術線圖看到什麼")
    assert not is_wave_question("台光電怎麼看")
    assert not is_wave_question("46506 怎麼來")


def test_degree_hits_are_his_labels_only():
    hits = degree_hits("")
    tags = {h["tag"] for h in hits}
    assert "A波低" in tags
    assert "位階二" in tags
    assert "第五波測底" in tags
    assert "修正末端" in tags
    last, prev = last_two("")
    assert last is not None
    assert last["tag"] == "第五波測底"
    assert "測底" in (last.get("quote") or "")
    assert "感覺夜盤不太妙" not in (last.get("quote") or "")
    assert prev is not None
    assert prev["tag"] in {"修正末端", "頭肩底", "C-1", "位階二"}
    blob = " ".join(h.get("quote") or "" for h in hits)
    assert "蔡森" not in blob


def test_format_wave_now_compares_and_turning():
    text = format_wave_now("")
    assert "第五波測底" in text
    assert "位階二" in text or "修正末端" in text
    assert "A 波低" in text or "A波低" in text or "7/29" in text
    assert "精準" in text or "細微波" in text
    assert "不數" in text
    assert "不是買訊" in text
    assert "位階不講死" in text
    assert "17000" not in text
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    live = format_wave_now(db)
    assert "45839" in live
    assert "47578" in live
    assert "39385" in live or "39384" in live
    assert "45398" in live or "低於 45839" in live


def test_why_wave_now_and_eyes():
    assert is_why_query("現在波浪位階")
    body = lookup("現在波浪位階")
    assert "位階二" in body
    assert "測底" in body or "修正末端" in body
    assert "不數" in body or "5／9" in body
    eyes = lookup("他技術線圖看到什麼")
    assert "KD" in eyes or "均線" in eyes
    assert "台積電" in eyes
    assert "7/29" in eyes or "A 波低" in eyes
    turn = lookup("看大盤轉折最準")
    assert "精準" in turn or "細微波" in turn
    assert "7/29" in turn
    assert EYES


def test_blank_focus_leads_with_degree():
    html = format_latest_focus("")
    assert "現在位階" in html
    assert "第五波測底" in html or "測底" in html
    assert "位階不講死" in html
    assert "產業趨勢" in html
    assert "現在波浪位階" in html
    assert "位階他不講死" not in html
    assert len(html) < 2800


def test_nest_includes_his_degree():
    fired = fire_chain("", "目前大盤是屬於哪個位階 以波浪來看的話")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "第五波測底" in nest["text"] or "現在位階" in nest["text"]
    assert "不數" in nest["text"]
    think = fired["think"]
    assert "現在位階" in think or "第五波測底" in think
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    assert tape.get("skip") is True


def test_twii_degree_chart_when_db_present(tmp_path):
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    dest = str(tmp_path / "twii-degree.png")
    built = build_twii_degree_chart(db, dest)
    assert built.get("ok")
    assert os.path.isfile(built.get("path") or "")
    assert os.path.getsize(built["path"]) > 12_000
    cap = built.get("caption") or ""
    assert "不是15分" in cap or "不是 15" in cap
    assert "不是買訊" in cap
    src = inspect.getsource(WayneTelegramBot._send_biaoke_structure_chart)
    assert "is_wave_question" in src
    assert "_send_biaoke_twii_degree_chart" in src
    origin = inspect.getsource(WayneTelegramBot._send_biaoke_origin_charts)
    assert "is_wave_question" in origin
    assert "TWII" in origin
