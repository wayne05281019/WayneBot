# -*- coding: utf-8 -*-
"""新文進六顆神經元：捕獲就分類，開火讀最近句，不改 SYSTEM。"""
import inspect
import sqlite3

from biaoke_chain import fire_chain
from biaoke_ingest import _after_ingest_analyze
from biaoke_neurons import classify_spoken, latest_bundle, record_neuron_events


def test_classify_c2_goes_to_nest():
    hits = classify_spoken("今天強彈反而提高警惕，小心逃命波C-2，不是已確認。")
    nids = {h["neuron"] for h in hits}
    assert "nest" in nids
    assert "doubt" in nids
    assert any(h["sid"] in ("", "TWII") for h in hits if h["neuron"] == "nest")


def test_classify_wenmao_standback_goes_to_tape():
    hits = classify_spoken("穩懋昨天跌破支撐立刻站回，近期會比台達電強")
    tape = [h for h in hits if h["neuron"] == "tape"]
    assert any(h["sid"] == "3105" for h in tape)
    quoted = classify_spoken('"健策要跌停了" 沒有，大盤還好')
    assert all(h.get("sid") != "3653" for h in quoted)


def test_record_and_fire_reads_latest(tmp_path):
    db = str(tmp_path / "n.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260915", "3105", "穩懋", 447.5, 476.0, 445.5, 454.0, 35312, 2.25),
    )
    conn.commit()
    conn.close()
    n = record_neuron_events(
        db,
        [
            {
                "id": "r1",
                "date": "2026-09-15",
                "time": "09:45",
                "kind": "reply",
                "text": "穩懋昨天跌破支撐立刻站回，近期會比台達電強",
            },
            {
                "id": "p1",
                "date": "2026-09-15",
                "time": "09:02",
                "kind": "post",
                "text": "今天強彈反而提高警惕，小心逃命波C-2，不是已確認。",
            },
        ],
    )
    assert n >= 2
    bundle = latest_bundle(db, "3105")
    assert "站回" in (bundle.get("tape") or "")
    assert "逃命波" in (bundle.get("nest") or "") or "C-2" in (bundle.get("nest") or "")
    fired = fire_chain(db, "穩懋怎麼看")
    assert fired["sid"] == "3105"
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "他自己最新" in tape["text"]
    assert "站回" in tape["text"]
    assert "他自己最新" in nest["text"]
    assert "C-2" in nest["text"] or "逃命波" in nest["text"]
    think = fired["think"]
    assert "站回" in think or "逃命波" in think or "C-2" in think
    assert "這族龍頭是 他自己最新" not in think


def test_ingest_hooks_neurons_immediately():
    src = inspect.getsource(_after_ingest_analyze)
    assert "record_neuron_events" in src
    assert "record_events" in src
    ingest_src = inspect.getsource(__import__("biaoke_ingest").ingest_public_posts)
    assert "backfill_recent_neurons" in ingest_src


def test_bystander_kind_not_filed(tmp_path):
    db = str(tmp_path / "b.db")
    n = record_neuron_events(
        db,
        [
            {
                "id": "x",
                "date": "2026-09-15",
                "time": "10:00",
                "kind": "bystander",
                "text": "小心逃命波C-2",
            }
        ],
    )
    assert n == 0
    assert latest_bundle(db, "") == {}


def test_classify_night_gold_uses_five_tools_not_keywords():
    nest = classify_spoken(
        "目前這兩天大盤(夜盤)在築底是好事，接下來看星期四或星期五反彈點位(夜盤)至少要46767。"
    )
    assert {h["neuron"] for h in nest} >= {"nest"}
    assert any(h["sid"] in ("", "TWII") for h in nest if h["neuron"] == "nest")
    tape = classify_spoken("後來收盤看到健策爆大量跌破平台，確認出現轉折，多頭結構被破壞的量價結構")
    assert any(h["neuron"] == "tape" and h["sid"] == "3653" for h in tape)
    hold = classify_spoken("我只要看到出現止漲整理K棒是一定會調節的。至於今天抽出的資金轉到創意，說實話，風險也很大。")
    nids = {h["neuron"] for h in hold}
    assert "hold" in nids
    assert "doubt" in nids or "field" in nids
    field = classify_spoken("上詮屬CPO／FAU，而聯亞屬光通訊 InP")
    assert "field" in {h["neuron"] for h in field}
    naked = classify_spoken("先要習慣裸K看盤，看股票要先看量再看價")
    assert "tape" in {h["neuron"] for h in naked}
