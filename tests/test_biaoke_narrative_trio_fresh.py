# -*- coding: utf-8 -*-
"""飆大文敘＋三窗點位：最新主文／近兩則自回重點必須進庫→文敘或標籤。

根因鎖：尾端 24 則閒聊不准擠掉早上點位自回；31700／31500／防線句要進題旨。
非買訊。Asia/Taipei。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def _seed_two_threads(tmp_path):
    from biaoke_desk import upsert_biaoke_posts

    db = str(tmp_path / "fresh.db")
    rows = [
        {
            "id": "189472259",
            "date": "2026-11-21",
            "time": "15:19",
            "kind": "post",
            "tags": [],
            "text": (
                "1.大盤唯一錯誤就是這次反彈小時線5波推升，還能回檔超過0.618。"
                "底部出現5波推升直接A轉破底。"
            ),
        },
        {
            "id": "189472259:r1",
            "parent": "189472259",
            "date": "2026-11-21",
            "time": "16:00",
            "kind": "reply",
            "layer": 1,
            "tags": [],
            "text": "前一串自回：還在看下降壓力線清洗籌碼。",
        },
        {
            "id": "189488822",
            "date": "2026-11-23",
            "time": "08:53",
            "kind": "post",
            "tags": [],
            "text": (
                "台指期開盤點位市場黑手企圖心明顯想守多頭最後一道防線\n"
                "1.\t台指期開盤點位市場黑手就是讓最後一組5-5脈動 1 4重疊，"
                "至少先破壞持續下跌走9波擴延下跌脈動，持續觀察。\n"
                "2. 跌破35000就是長線多頭格局被破壞。"
                "穿刺33000多點就是多頭最後防線。"
            ),
        },
    ]
    # 早上點位自回（必須進文敘，不准被尾端閒聊擠掉）
    morning = [
        ("09:35", "外資 政府操盤黑手都知道33000~35000就是多頭最後防線。"),
        ("09:38", "穿刺 三天站回都還好，真正崩盤是31700之下"),
        ("09:49", "所以我說除非發生系統性風險 就是通殺，以台股而言收盤31500之下就是系統性風險確認"),
        ("11:16", "最重要是大盤3天內一定收盤要站上35700以上，否則拖越久對未來多頭越不利"),
        ("17:15", "今晚 費半不能有效穿刺 8336 或8498(B波假突破)"),
    ]
    for i, (hm, text) in enumerate(morning, 1):
        rows.append(
            {
                "id": f"189488822:c-level-{i}",
                "parent": "189488822",
                "date": "2026-11-23",
                "time": hm,
                "kind": "reply",
                "layer": 1,
                "tags": [],
                "text": text,
            }
        )
    # 尾端閒聊 30 則（舊邏輯會把早上點位裁掉）
    for i in range(30):
        rows.append(
            {
                "id": f"189488822:c-chat-{i}",
                "parent": "189488822",
                "date": "2026-11-23",
                "time": f"18:{i:02d}",
                "kind": "reply",
                "layer": 1,
                "tags": [],
                "text": f"謝謝關心{i}，今天天氣不錯聊天。",
            }
        )
    upsert_biaoke_posts(db, rows)
    return db


def test_pick_focus_keeps_morning_levels_over_chat_tail(tmp_path, monkeypatch):
    from biaoke_digest import format_latest_focus
    import biaoke_digest as bd

    monkeypatch.setattr(
        bd,
        "taipei_now",
        lambda: datetime(2026, 11, 23, 18, 40, tzinfo=TAIPEI),
    )
    db = _seed_two_threads(tmp_path)
    html = format_latest_focus(db)
    assert "35000" in html
    assert "33000" in html
    assert "31700" in html
    assert "31500" in html
    assert "35700" in html
    assert "8336" in html or "8498" in html
    # 閒聊不准蓋掉點位欄
    assert "天氣不錯" not in html or "31700" in html


def test_cross_day_prior_thread_reply_not_dropped(tmp_path, monkeypatch):
    """前一則主文日的自回不准因 day < 最新主文日整段丢掉。"""
    from biaoke_digest import format_latest_focus
    import biaoke_digest as bd

    monkeypatch.setattr(
        bd,
        "taipei_now",
        lambda: datetime(2026, 11, 23, 12, 0, tzinfo=TAIPEI),
    )
    db = _seed_two_threads(tmp_path)
    html = format_latest_focus(db)
    # 最新主文在；前一串大盤自回也應有機會進（點位優先）
    assert "台指期" in html or "35000" in html
    assert "下降壓力" in html or "5波推升" in html or "唯一錯誤" in html


def test_reply_level_delta_and_pred_levels_today():
    from biaoke_level_learn import _reply_level_delta, _thesis_pred_levels

    assert _reply_level_delta("真正崩盤是31700之下")
    assert _reply_level_delta("收盤31500之下就是系統性風險確認")
    assert _reply_level_delta("33000~35000就是多頭最後防線")
    blob = (
        "跌破35000｜33000~35000多頭最後防線｜崩盤是31700之下｜"
        "收盤31500之下系統性風險｜站上35700｜費半不能有效穿刺 8336 或8498(B波假突破)｜"
        "目前我看到的大盤要修正到35000~35500之間，真正的低點會在35000~35500之間"
    )
    pred = _thesis_pred_levels(blob)
    roles = {str(r.get("role")): float(r.get("level")) for r in (pred.get("tw") or [])}
    assert abs(roles.get("崩盤觀察", 0) - 31700.0) < 0.6
    assert abs(roles.get("系統風險", 0) - 31500.0) < 0.6
    assert abs(roles.get("站回觀察", 0) - 35700.0) < 0.6
    assert abs(roles.get("極限穿刺", 0) - 33000.0) < 0.6
    sox = {round(float(r.get("level")), 1) for r in (pred.get("sox") or [])}
    assert 8336.0 in sox
    assert 8498.0 in sox


def test_latest_snip_merges_level_self_replies(tmp_path):
    from biaoke_desk import upsert_biaoke_posts
    from biaoke_level_learn import _latest_biaoke_index_snip, ensure_tables

    db = _seed_two_threads(tmp_path)
    # 較早長篇題旨（分數可能更高）不准壓掉今日主文串
    upsert_biaoke_posts(
        db,
        [
            {
                "id": "189000001",
                "date": "2026-11-20",
                "time": "21:00",
                "kind": "post",
                "tags": [],
                "text": (
                    "目前我看到的大盤要修正到35000~35500之間。"
                    "1.大盤止跌還沒到目前走5-5-3，真正的低點會在35000~35500之間。"
                    "2.波浪理論是動態修正。3.35000~35500就如去年4月17300。"
                    "4.盤中穿刺33000左右。5.3天內站回35700。"
                ),
            }
        ],
    )
    ensure_tables(db)
    snip = _latest_biaoke_index_snip(
        db,
        "20261123",
        now=datetime(2026, 11, 23, 18, 40, tzinfo=TAIPEI),
    )
    assert isinstance(snip, str) and snip
    assert "189488822" in snip or "台指期開盤" in snip or "最後一道防線" in snip
    assert "35000" in snip
    assert "31700" in snip
    assert "31500" in snip
    assert "35700" in snip
    assert "8336" in snip or "8498" in snip


def test_build_live_pack_labels_include_today_levels(tmp_path):
    from biaoke_level_learn import _build_live_pack, ensure_tables

    db = _seed_two_threads(tmp_path)
    ensure_tables(db)
    # 加權末日＝他文日，避免題旨 as_of 卡舊
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quotes("
        "stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO quotes VALUES (?,?,?,?,?,?,?)",
        ("^TWII", "2026-11-23", 35000, 37100, 35400, 36800, 1e7),
    )
    conn.commit()
    conn.close()
    pack = _build_live_pack(
        db, now=datetime(2026, 11, 23, 18, 40, tzinfo=TAIPEI)
    ) or {}
    roles = {
        str(r.get("role")): float(r.get("level"))
        for r in ((pack.get("pred_levels") or {}).get("tw") or [])
    }
    assert abs(roles.get("崩盤觀察", 0) - 31700.0) < 0.6
    assert abs(roles.get("系統風險", 0) - 31500.0) < 0.6
    wait = str(pack.get("wait_struct") or "")
    assert "31700" in wait or "31500" in wait or "35700" in wait


def test_board_meta_freshness_sees_defense_reply(tmp_path):
    from phone_narrative_freshness import latest_biaoke_board_meta, assess_narrative_freshness

    db = _seed_two_threads(tmp_path)
    meta = latest_biaoke_board_meta(db)
    assert meta.get("ymd") == "20261123"
    fresh = assess_narrative_freshness(
        db, now=datetime(2026, 11, 23, 18, 40, tzinfo=TAIPEI)
    )
    assert fresh.get("board_ymd") == "20261123"
