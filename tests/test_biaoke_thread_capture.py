# -*- coding: utf-8 -*-
"""最新兩則討論串：他自己的回文全部進庫、對官方收、進抽屜。路人不当判斷。"""
import json
import sqlite3
from pathlib import Path

from biaoke_ingest import _after_ingest_analyze, _carry_parent_names
from biaoke_neurons import classify_spoken
from biaoke_watch import latest_watch_line

FIX = Path("tests/fixtures/biaoke_20260917_thread.json")
_THANKS = (
    "感謝分享",
    "那就好",
    "你要賣隨你",
    "管理者應該有考核",
    "應該會走得比較慢",
)


def _load():
    return json.loads(FIX.read_text(encoding="utf-8"))


def _seed_official(db: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            pct_change REAL, PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE index_daily (
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
            close REAL, volume REAL, pct_change REAL, updated_at TEXT,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    conn.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("20260916", "2383", "台光電", 5060, 5175, 5030, 5085, 1686, -0.59),
            ("20260916", "3443", "創意", 6070, 6295, 6050, 6170, 1261, 2.24),
            ("20260916", "4971", "IET-KY", 530, 574, 530, 574, 2213, 9.96),
            ("20260916", "3017", "奇鋐", 3115, 3225, 3100, 3175, 2744, 1.93),
            ("20260916", "3081", "聯亞", 2695, 2930, 2695, 2805, 5534, 4.86),
            ("20260916", "2455", "全新", 515, 534, 506, 515, 19718, -0.96),
        ],
    )
    conn.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260916", "TWII", 45546.56, 46077.82, 45546.56, 45848.9, 0, 0.74, ""),
    )
    conn.commit()
    conn.close()


def _is_thanks(text: str) -> bool:
    t = (text or "").strip()
    if t in _THANKS:
        return True
    if t == "感謝分享":
        return True
    return t in {"那就好", "你要賣隨你"}


def test_fixture_is_latest_main_plus_all_self_replies():
    rows = _load()
    ids = {r["id"] for r in rows}
    assert "184757774" in ids
    assert "184750441" in ids
    replies = [r for r in rows if r["kind"] == "reply"]
    assert len(replies) >= 44
    assert any(r["layer"] == 2 for r in replies)
    latest = next(r for r in rows if r["id"] == "184757774")
    assert "升息" in latest["text"]
    assert "創意" in latest["text"]
    assert any("三日低點" in (r["text"] or "") for r in replies)
    assert any("4000" in (r["text"] or "") for r in replies)
    assert any("做頭" in (r["text"] or "") for r in replies)


def test_carry_parent_names_gives_emc_to_nameless_reply():
    packed = _carry_parent_names(
        [
            {
                "id": "184757774",
                "kind": "post",
                "tags": [],
                "text": "台光電至少要整理三個月，PCB全面走弱，只留一檔台光電。",
            },
            {
                "id": "r1",
                "kind": "reply",
                "parent": "184757774",
                "tags": [],
                "text": "有可能跌到4000~4300",
            },
        ]
    )
    tags = packed[1].get("tags") or []
    assert "台光電" in tags


def test_all_self_replies_watch_tape_neurons(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_official(db)
    rows = _load()
    _after_ingest_analyze(db, rows)
    conn = sqlite3.connect(db)
    packed = _carry_parent_names(rows, db)
    by = {str(r.get("id")): r for r in packed}
    replies = [r for r in rows if r["kind"] == "reply"]
    missing_watch = []
    missing_neuron = []
    for r in replies:
        if not conn.execute(
            "SELECT 1 FROM biaoke_watch WHERE post_id=?", (r["id"],)
        ).fetchone():
            missing_watch.append(r["id"])
        tags = (by.get(r["id"]) or r).get("tags")
        if _is_thanks(r["text"]):
            continue
        if classify_spoken(r["text"], tags) or classify_spoken(r["text"]):
            if not conn.execute(
                "SELECT 1 FROM biaoke_neuron_hits WHERE post_id=?",
                (r["id"],),
            ).fetchone():
                missing_neuron.append(r["id"] + ":" + (r["text"] or "")[:48])
    assert missing_watch == []
    pid4000 = next(r["id"] for r in replies if "4000" in (r["text"] or ""))
    row4000 = conn.execute(
        "SELECT stock_id, close, bar_date FROM biaoke_tape WHERE post_id=? AND stock_id='2383'",
        (pid4000,),
    ).fetchone()
    assert row4000 is not None
    assert float(row4000[1]) == 5085
    assert str(row4000[2]).replace("-", "")[:8] == "20260916"
    nest_c = conn.execute(
        """
        SELECT 1 FROM biaoke_neuron_hits
        WHERE neuron_id='nest' AND snippet LIKE '%C波%'
        """
    ).fetchone()
    assert nest_c
    rate = conn.execute(
        """
        SELECT 1 FROM biaoke_neuron_hits
        WHERE neuron_id='nest' AND snippet LIKE '%升息%'
        """
    ).fetchone()
    assert rate
    three = conn.execute(
        """
        SELECT 1 FROM biaoke_neuron_hits
        WHERE neuron_id='tape' AND snippet LIKE '%三日低點%'
        """
    ).fetchone()
    assert three
    conn.close()
    line = latest_watch_line(db)
    assert "12:13" in line or "13:30" in line
    assert "不是買訊" in line
    assert missing_neuron == []
