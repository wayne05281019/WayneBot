# -*- coding: utf-8 -*-
"""平常話關鍵字 → 官方資料路徑（不編新聞、不編成本）。"""
from intent_router import (
    no_cost_honest_html,
    parse_intent,
    sell_honest_html,
    why_honest_html,
    why_hub_html,
)


def test_plain_speech_maps_to_official_paths():
    cases = {
        "為什麼跌": "why",
        "為甚麼漲": "why",
        "2330為什麼跌": "why",
        "台積電怎麼賣": "sell",
        "如何賣": "sell",
        "外資買超": "chips",
        "籌碼": "chips",
        "法人": "chips",
        "產業": "industry",
        "同業": "industry",
        "營收": "fund",
        "月營收": "fund",
        "大盤": "market",
        "加權指數": "market",
        "資金移動": "flow",
        "產業輪動": "flow",
        "今日海選名單": "screen",
        "黃金買點": "screen",
        "重點觀察": "screen",
        "我的持股": "portfolio",
        "自選股清單": "watch",
        "隔沖": "overnight",
        "當沖": "daytrade",
        "決策卡": "card",
        "刷新上一檔": "card",
        "連買區": "streak",
        "外資連買": "streak",
        "AI倉": "ai",
        "持倉": "portfolio",
        "持倉報告": "ai",
        "模擬持倉報告": "ai",
        "原因": "hub",
        "主力成本": "no_cost",
        "外資成本": "no_cost",
        "融資成本": "no_cost",
    }
    for text, kind in cases.items():
        hit = parse_intent(text)
        assert hit is not None, text
        assert hit.kind == kind, (text, hit)


def test_code_and_name_extracted():
    hit = parse_intent("2330為什麼跌")
    assert hit.kind == "why" and hit.code == "2330"
    hit = parse_intent("請問台積電怎麼賣")
    assert hit.kind == "sell" and hit.query == "台積電"
    hit = parse_intent("2330資金")
    assert hit.kind == "chips" and hit.code == "2330"
    hit = parse_intent("原因 2454")
    assert hit.kind == "why" and hit.code == "2454"
    hit = parse_intent("00631L為什麼跌")
    assert hit.kind == "why" and hit.code == "00631L"
    hit = parse_intent("00990A怎麼賣")
    assert hit.kind == "sell" and hit.code == "00990A"
    hit = parse_intent("00706l籌碼")
    assert hit.kind == "chips" and hit.code == "00706L"


def test_bare_stock_name_is_not_intent():
    assert parse_intent("台積電") is None
    assert parse_intent("2330") is None
    assert parse_intent("南亞") is None
    assert parse_intent("asdfgh") is None


def test_from_why_default_keeps_code():
    hit = parse_intent("2330", default_kind="why")
    assert hit.kind == "why" and hit.code == "2330"
    hit = parse_intent("台積電", default_kind="why")
    assert hit.kind == "why" and hit.query == "台積電"


def test_honest_copy_does_not_invent_news_or_cost():
    why = why_honest_html()
    assert "沒有" in why
    assert "新聞" in why
    assert "決策卡" in why
    sell = sell_honest_html()
    assert "20日高" in sell
    assert "不是買訊" in sell
    assert "不自動賣" in sell
    cost = no_cost_honest_html()
    assert "沒有" in cost
    assert "主力成本" in cost
    assert "三大法人不是主力" in cost
    hub = why_hub_html("2330")
    assert "三條槓" in hub
    assert "2330" in hub
    assert "不編新聞" in hub
    assert "語音" in hub
