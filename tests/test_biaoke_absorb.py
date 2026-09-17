# -*- coding: utf-8 -*-
"""抓文先入匣；台北 02:00／開市日 13:00 才進神經元。輔助底料當下存好。"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_absorb import (
    absorb_slot_id,
    aux_for_post,
    next_absorb_at,
    pending_events,
    queue_absorb_events,
    run_absorb,
)
from biaoke_ingest import _after_ingest_analyze, parse_api_thread
from biaoke_neurons import latest_bundle

TAIPEI = ZoneInfo("Asia/Taipei")


def _seed_quotes(db: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    for i, close in enumerate((420.0, 430.0, 444.0, 454.0)):
        day = f"2026091{2 + i}"
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
            (day, "3105", "穩懋", close - 8, close + 6, close - 12, close, 30000 + i, 1.2),
        )
    conn.commit()
    conn.close()


def test_poll_slots_taipei_only():
    wed_open = datetime(2026, 9, 16, 13, 0, tzinfo=TAIPEI)
    wed_morn = datetime(2026, 9, 16, 10, 0, tzinfo=TAIPEI)
    dawn = datetime(2026, 9, 17, 2, 0, tzinfo=TAIPEI)
    sat_noon = datetime(2026, 9, 19, 13, 0, tzinfo=TAIPEI)
    assert absorb_slot_id(dawn) == "20260917-0200"
    assert absorb_slot_id(wed_open) == "20260916-1300"
    assert absorb_slot_id(wed_morn) == ""
    assert absorb_slot_id(sat_noon) == ""
    nxt = next_absorb_at(datetime(2026, 9, 16, 12, 0, tzinfo=TAIPEI))
    assert nxt.tzinfo is not None
    assert nxt.strftime("%H:%M") == "13:00"
    after = next_absorb_at(datetime(2026, 9, 16, 13, 10, tzinfo=TAIPEI))
    assert after.strftime("%Y-%m-%d %H:%M") == "2026-09-17 02:00"


def test_queue_saves_aux_before_neurons(tmp_path):
    db = str(tmp_path / "a.db")
    _seed_quotes(db)
    _after_ingest_analyze(
        db,
        [
            {
                "id": "p1",
                "date": "2026-09-16",
                "time": "10:02",
                "kind": "post",
                "layer": 0,
                "text": "穩懋昨天跌破支撐立刻站回，近期會比台達電強",
            }
        ],
    )
    conn = sqlite3.connect(db)
    hits = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='biaoke_neuron_hits'").fetchone()
    if hits and hits[0]:
        n = conn.execute("SELECT COUNT(*) FROM biaoke_neuron_hits").fetchone()[0]
        assert n == 0
    tape = conn.execute("SELECT COUNT(*) FROM biaoke_tape WHERE stock_id='3105'").fetchone()[0]
    conn.close()
    assert tape >= 1
    pending = pending_events(db)
    assert pending and pending[0]["id"] == "p1"
    aux = aux_for_post(db, "p1")
    sids = {a["stock_id"] for a in aux}
    assert "3105" in sids
    w = next(a for a in aux if a["stock_id"] == "3105")
    assert w["official"].get("close") == 454.0
    assert w["card"].get("cal60") is not None
    assert w["tz"] == "Asia/Taipei"


def test_absorb_only_at_taipei_slots(tmp_path):
    db = str(tmp_path / "b.db")
    _seed_quotes(db)
    queue_absorb_events(
        db,
        [
            {
                "id": "r1",
                "date": "2026-09-16",
                "time": "09:45",
                "kind": "reply",
                "layer": 1,
                "text": "穩懋昨天跌破支撐立刻站回",
            }
        ],
        now=datetime(2026, 9, 16, 10, 0, tzinfo=TAIPEI),
    )
    skipped = run_absorb(db, now=datetime(2026, 9, 16, 10, 0, tzinfo=TAIPEI))
    assert skipped.get("reason") == "not_slot"
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master").fetchall()}
    conn.close()
    assert "biaoke_neuron_hits" not in names
    got = run_absorb(db, now=datetime(2026, 9, 16, 13, 0, tzinfo=TAIPEI))
    assert got["ok"] is True
    assert got["tz"] == "Asia/Taipei"
    assert got["slot"] == "20260916-1300"
    bundle = latest_bundle(db, "3105")
    assert "站回" in (bundle.get("tape") or "")


def test_parse_api_thread_keeps_layer3():
    payload = [
        {
            "id": "a1",
            "memberId": 111,
            "nickname": "路人",
            "content": {"text": "這根怎麼看"},
            "replies": [
                {
                    "id": "a1-1",
                    "memberId": 222,
                    "nickname": "路人2",
                    "content": {"text": "再問一次"},
                    "replies": [
                        {
                            "id": "a1-1-1",
                            "memberId": 25263,
                            "nickname": "期股多空雙飆客",
                            "content": {"text": "點到為止，三日低點先看"},
                        }
                    ],
                }
            ],
        }
    ]
    rows = parse_api_thread(payload, parent_id="1847")
    him = [r for r in rows if r["kind"] == "reply"]
    assert him
    assert any(int(r.get("layer") or 0) == 3 for r in him)
    assert all(int(r.get("layer") or 0) <= 3 for r in rows)
