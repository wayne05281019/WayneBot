# -*- coding: utf-8 -*-
from biaoke_judge import format_judge_html, format_judge_notes, leader_of
from biaoke_mind import match_methods


def test_optical_followers_look_at_lianya():
    sid, name, why = leader_of("", "6442", "光聖")
    assert sid == "3081"
    assert name == "聯亞"
    assert "龍頭" in why


def test_zhiyuan_follows_mediatek():
    sid, name, why = leader_of("", "3035", "智原")
    assert sid == "2454"
    assert name == "聯發科"


def test_catchup_lags_when_leader_already_broke():
    from biaoke_judge import _catchup

    text = _catchup(
        {
            "sid": "3035",
            "above_support": True,
            "broke_resistance": False,
            "shrinking": True,
        },
        {
            "sid": "2454",
            "name": "聯發科",
            "struct": {
                "above_support": True,
                "broke_resistance": True,
                "shrinking": False,
            },
            "cal60": {"pct": 40},
        },
        {"pct": 10},
    )
    assert "聯發科" in text
    assert "補漲" in text
    assert "波浪" in text
    assert "保證" not in text or "不是保證" in text


def test_catchup_abandons_when_below_spike_low():
    from biaoke_judge import _catchup

    text = _catchup(
        {"sid": "3035", "above_support": False, "broke_resistance": False},
        {
            "sid": "2454",
            "name": "聯發科",
            "struct": {"above_support": True, "broke_resistance": True},
        },
        {},
    )
    assert "放棄" in text
    assert "補漲幾成" in text


def test_wave_is_for_index_not_stock():
    hits = match_methods("波浪理論可以拿來看個股嗎")
    assert hits
    body = hits[0][1]
    assert "解大盤難度更高" in body or "很少用波浪" in body
    assert "不講死" in body or "一驗再驗" in body
    assert "提早規劃" in body


def test_industry_trend_explains_emc_july_hold():
    hits = match_methods("台光電 7 月抄底為什麼能抱到明年")
    assert hits
    title, body = hits[0]
    assert title == "個股先看產業趨勢"
    assert "技術分析最有用是大盤" in body
    assert "2026-04-16" in body
    assert "3930" in body
    assert "不是把波浪套在 2383" in body
    assert "護城河" in body or "2027" in body
    assert "不猜" not in body
    why = match_methods("為什麼能這麼篤定")
    assert why and "產業趨勢" in why[0][1]


def test_emc_is_pcb_leader_and_long_hold():
    sid, name, why = leader_of("", "2383", "台光電")
    assert sid == "2383"
    assert name == "台光電"
    assert "龍頭" in why
    notes = format_judge_notes(
        {
            "sid": "2383",
            "name": "台光電",
            "in_corpus": True,
            "long_hold": True,
            "struct": {
                "date": "2026-09-11",
                "close": 5295,
                "spike_date": "2026-08-01",
                "spike_high": 5400,
                "spike_low": 4800,
                "shrinking": False,
                "above_support": True,
                "broke_resistance": True,
            },
            "hold": "台光電在他 4/16 長線龍頭名單：產業趨勢還在就不是天天管；買點是大盤大跌窗口，不是把波浪套在這檔日 K。錨是 7/6 買跌不買漲，官方日 K 7/29 低 3985、7/30 低 3930。",
            "pace": "量價已過爆大量日高，但這檔他當長線龍頭，不是半山腰隔日沖那一類。",
        }
    )
    assert "材料" in notes
    assert "3930" in notes
    assert "產業趨勢" in notes
    assert "半山腰隔日沖那一類" in notes
    assert "現況：" not in notes
    html = format_judge_html(
        {
            "sid": "2383",
            "name": "台光電",
            "in_corpus": True,
            "hold": "台光電在他 4/16 長線龍頭名單：產業趨勢還在就不是天天管。",
            "pace": "不是半山腰隔日沖那一類。",
            "struct": {
                "date": "2026-09-11",
                "close": 5295,
                "pct": 1.2,
                "spike_date": "2026-08-01",
                "spike_high": 5400,
                "spike_low": 4800,
                "stance": "量縮且收在爆大量日低點之上。",
            },
        }
    )
    assert "台光電" in html
    assert "天天管" in html
    assert "不猜" not in html
    assert "現況／量價" not in html


def test_judge_notes_are_materials_not_a_form():
    notes = format_judge_notes(
        {
            "sid": "6442",
            "name": "光聖",
            "in_corpus": True,
            "struct": {
                "date": "2026-09-11",
                "close": 100,
                "spike_date": "2026-08-01",
                "spike_high": 120,
                "spike_low": 90,
                "shrinking": True,
                "above_support": True,
            },
            "leader": {
                "sid": "3081",
                "name": "聯亞",
                "why": "同族跟漲先看龍頭",
                "struct": {"close": 2850, "shrinking": False, "above_support": True},
            },
            "pace": "這族要先看龍頭現在攻還是休息。",
        }
    )
    assert "材料" in notes
    assert "3081" in notes
    assert "聯亞" in notes
    assert "現況：" not in notes
    html = format_judge_html(
        {
            "sid": "6442",
            "name": "光聖",
            "in_corpus": True,
            "struct": {
                "date": "2026-09-11",
                "close": 100,
                "pct": 1.2,
                "spike_date": "2026-08-01",
                "spike_high": 120,
                "spike_low": 90,
                "stance": "量縮且收在爆大量日低點之上。",
            },
            "leader": {"sid": "3081", "name": "聯亞", "why": "同族跟漲先看龍頭"},
            "pace": "這族要先看龍頭。",
        }
    )
    assert "光聖" in html
    assert "聯亞" in html
    assert "爆大量日" in html
    assert "現況／量價" not in html


def test_audit_cannot_be_firm_when_layers_missing():
    from biaoke_judge import audit_certainty, format_judge_html

    miss = audit_certainty(
        {
            "sid": "3035",
            "name": "智原",
            "in_corpus": False,
            "struct": {
                "sid": "3035",
                "above_support": True,
                "broke_resistance": False,
                "shrinking": False,
            },
            "leader": {"sid": "2454", "name": "聯發科", "struct": {}},
        }
    )
    assert miss["firm"] is False
    assert "不能篤定" in miss["verdict"] or "不能" in miss["verdict"]
    assert "自問" in miss["verdict"]
    html = format_judge_html(
        {
            "sid": "3035",
            "name": "智原",
            "in_corpus": False,
            "audit": miss,
            "leader": {"sid": "2454", "name": "聯發科", "why": "同族跟漲先看龍頭"},
            "struct": {
                "date": "2026-09-10",
                "close": 136,
                "pct": 1.49,
                "spike_date": "2026-09-08",
                "spike_high": 148,
                "spike_low": 138,
                "stance": "站上撐了但量還沒縮。",
            },
        }
    )
    assert html.startswith("自問")
    assert "智原" in html
    assert "聯發科" in html

    firm = audit_certainty(
        {
            "sid": "2383",
            "name": "台光電",
            "in_corpus": True,
            "long_hold": True,
            "rotation": "三大法人這天剛輪進PCB",
            "struct": {
                "sid": "2383",
                "above_support": True,
                "shrinking": True,
                "broke_resistance": False,
            },
            "leader": {
                "sid": "2383",
                "name": "台光電",
                "struct": {"above_support": True, "shrinking": True},
            },
        }
    )
    assert firm["firm"] is True
    assert "能" in firm["verdict"]
    assert "買訊" in firm["verdict"]


def test_hold_note_splits_long_hold_f10_and_mediatek():
    from biaoke_judge import _hold_note

    emc = _hold_note("2383", True)
    assert "勿輕易調整" in emc
    assert "4/16" in emc
    assert "3930" in emc
    delta = _hold_note("2308", True)
    assert "勿輕易調整" in delta
    qin = _hold_note("3017", True)
    assert "F10" in qin
    assert "回測" in qin
    mtk = _hold_note("2454", True)
    assert "4/22" in mtk or "IC 設計" in mtk
    assert "不是 4/16" in mtk or "不在" in mtk
    assert "尚未納入 F 系列" in mtk
    assert "台積電" in mtk
