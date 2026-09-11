# -*- coding: utf-8 -*-
"""三遍交叉：原文指紋必須相同，再對規則抽取與官方日 K／附圖。"""
from __future__ import annotations

import sqlite3

import pytest

from biaoke_audit import (
    extract_pass,
    format_audit,
    is_audit_ask,
    numbers_in,
    repeat_inventory,
    run_three_passes,
)
from biaoke_claims import file_biaoke_claims, format_stock_claims


def test_repeat_inventory_fingerprint_stable():
    posts = [
        {
            "id": "158129800",
            "date": "2023-12-04",
            "time": "13:04",
            "kind": "post",
            "tags": ["智原"],
            "text": "智原這幾天支撐線370不跌破，就會開始進入推升另一波脈動！",
        },
        {
            "id": "184545002",
            "date": "2026-09-11",
            "time": "17:49",
            "kind": "post",
            "text": "今晚夜盤至少要穿越46506為今晚觀盤重點。附圖：https://image.cmoney.tw/attachment/abc.jpg",
        },
        {
            "id": "x:a1",
            "date": "2023-12-06",
            "time": "09:21",
            "kind": "reply",
            "parent": "x",
            "text": "有空單敢快回補，破底翻至少先看335",
        },
    ]
    rep = repeat_inventory(posts, times=3)
    assert rep["stable"] is True
    assert len(set(rep["fingerprints"])) == 1
    inv = rep["last"]
    assert inv["n_posts"] == 2
    assert inv["n_replies"] == 1
    assert inv["n_charts"] == 1
    assert any(h["stock_id"] == "3035" for r in inv["rows"] for h in r["mentions"])
    nums = [h["n"] for r in inv["rows"] for h in r["numbers"]]
    assert 370.0 in nums
    assert 46506.0 in nums
    assert 335.0 in nums


def test_unbound_number_without_stock_is_kept():
    hits = numbers_in("有空單敢快回補，破底翻至少先看335")
    assert any(abs(h["n"] - 335) < 0.01 for h in hits)
    ext = extract_pass(
        [{"id": "x", "text": "有空單敢快回補，破底翻至少先看335", "_sids": [], "_snames": []}]
    )
    assert ext["n_claims"] == 0


def test_three_passes_cross_official_bar(tmp_path):
    db = str(tmp_path / "a.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("20231204", "3035", "智原", "TW", 392, 393.5, 374.5, 380, 23573),
    )
    conn.execute(
        """
        CREATE TABLE biaoke_posts (
            id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT, parent TEXT,
            layer INTEGER, kind TEXT, tags TEXT, text TEXT, updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id,n,date,time,parent,layer,kind,tags,text,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "158129800",
            1,
            "2023-12-04",
            "13:04",
            "",
            0,
            "post",
            "[]",
            "智原這幾天支撐線370不跌破，就會開始進入推升另一波脈動！",
            "",
        ),
    )
    conn.commit()
    conn.close()
    from biaoke_desk import load_corpus_cache_clear

    load_corpus_cache_clear()
    result = run_three_passes(db, fetch_missing=False)
    assert result["stable"] is True
    assert len(set(result["fingerprints"])) == 1
    text = format_audit(db, result=result)
    assert "三遍交叉" in text
    assert "指紋全同" in text
    assert "不是買訊" in text
    assert "語料" not in text
    assert is_audit_ask("要做三次並交叉比對全部資料一字不漏")
    assert is_audit_ask("補齊找到所有所有的佐證資料圖文")
    assert is_audit_ask("改為一千種方式角度去比對")
    assert "一千角" in text or "三遍交叉" in text


def test_night_target_uses_tx_night_bar(tmp_path):
    db = str(tmp_path / "n.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE futures_daily (
            date TEXT, symbol TEXT, session TEXT, open REAL, high REAL,
            low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (date, symbol, session)
        )
        """
    )
    conn.execute(
        "INSERT INTO futures_daily(date,symbol,session,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("20260911", "TX", "night", 46306, 46574, 46041, 46503, 100),
    )
    conn.commit()
    conn.close()
    posts = [
        {
            "id": "184545002",
            "date": "2026-09-11",
            "time": "17:49",
            "kind": "post",
            "text": "今晚夜盤至少要穿越46506為今晚觀盤重點。",
            "_sids": ["TWII"],
            "_snames": ["台指"],
        }
    ]
    stats = file_biaoke_claims(db, [(posts, 0)])
    assert stats["targets"] >= 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT then_high, then_low, then_close, hit FROM biaoke_claims "
        "WHERE post_id='184545002' AND role='target' AND lo=46506"
    ).fetchone()
    conn.close()
    assert row is not None
    assert abs(float(row[0]) - 46574) < 0.1
    assert "當日高過到" in (row[3] or "")
    html = format_stock_claims(db, "TWII")
    assert "46506" in html
    assert "語料" not in html


@pytest.mark.production_db
def test_production_three_passes_cover_origin_and_sep11():
    from biaoke_desk import load_corpus, load_corpus_cache_clear
    from tests.conftest import require_production_db

    db = require_production_db()
    load_corpus_cache_clear()
    blob = load_corpus(db)
    ids = {str(p.get("id") or "") for p in (blob.get("posts") or [])}
    assert int(blob.get("n") or 0) >= 1709
    assert "158129800" in ids
    assert "184526608" in ids
    assert "184545002" in ids
    result = run_three_passes(db, fetch_missing=False)
    assert result["stable"] is True
    assert (result.get("public") or {}).get("inventory", {}).get("n_posts") >= 1709
    assert int((result.get("angles") or {}).get("n") or 0) == 1000
    text = format_audit(db, result=result)
    assert "指紋全同" in text
    assert "一千角" in text
    assert "不是買訊" in text
    assert "語料" not in text


def test_one_thousand_angles_unique_names():
    from biaoke_angles import ANGLE_N, load_angle_context, run_angles, summarize_angles

    posts = [
        {
            "id": "158129800",
            "date": "2023-12-04",
            "time": "13:04",
            "kind": "post",
            "text": "智原這幾天支撐線370不跌破，就會開始進入推升另一波脈動！",
            "_sids": ["3035"],
            "_snames": ["智原"],
        },
        {
            "id": "184526608",
            "date": "2026-09-11",
            "time": "08:43",
            "kind": "post",
            "text": "9/3 45839低點有守住，右肩高有過前高，低不破前低。",
            "_sids": ["2408"],
            "_snames": ["南亞科"],
        },
        {
            "id": "184545002",
            "date": "2026-09-11",
            "time": "17:49",
            "kind": "post",
            "text": "今晚夜盤至少要穿越46506。15分走出5段。",
        },
        {
            "id": "184545002:r1",
            "date": "2026-09-11",
            "time": "18:10",
            "kind": "reply",
            "parent": "184545002",
            "layer": 1,
            "text": "飆大自己回：先看夜盤有沒有穿越。",
        },
        {
            "id": "184499206",
            "date": "2026-09-10",
            "time": "09:51",
            "kind": "post",
            "text": "下波至少測48218。",
        },
    ]
    ctx = load_angle_context(posts, stable=True)
    rows = run_angles(ctx)
    assert len(rows) == ANGLE_N == 1000
    names = [r["name"] for r in rows]
    assert len(set(names)) == 1000
    by = {r["name"]: r for r in rows}
    assert by["corpus_first_id"]["ok"] is True
    assert by["today_0843_45839"]["ok"] is True
    assert by["today_1749_46506"]["ok"] is True
    assert by["today_thread_replies_filed"]["ok"] is True
    st = summarize_angles(rows)
    assert st["n"] == 1000
    assert st["passed"] + st["failed"] == 1000
