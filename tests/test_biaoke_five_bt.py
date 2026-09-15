# -*- coding: utf-8 -*-
"""五件工具對官方柱：發文日對得上才算，個股不數 5／9。"""
import sqlite3

from biaoke_five_bt import one_liner, render_md, run_five_bt
from biaoke_mind import method_body, views_for_neuron


def _seed(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE biaoke_posts (
            id TEXT, n INTEGER, date TEXT, time TEXT, parent TEXT,
            layer INTEGER, kind TEXT, tags TEXT, text TEXT, updated_at TEXT
        );
        CREATE TABLE biaoke_mentions (
            post_id TEXT, stock_id TEXT, stock_name TEXT,
            PRIMARY KEY (post_id, stock_id)
        );
        CREATE TABLE index_daily (
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
            volume REAL, pct_change REAL
        );
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            pct_change REAL,
            PRIMARY KEY (date, stock_id)
        );
        """
    )
    # 7/16 不破 40000 → 7/29 低 39385
    tw = [
        ("20260716", 45200, 45500, 44971, 45000),
        ("20260717", 44000, 44200, 42671, 43000),
        ("20260720", 43000, 43800, 42000, 42800),
        ("20260721", 42800, 44233, 42500, 44000),
        ("20260722", 44000, 44500, 43000, 43600),
        ("20260723", 43600, 44000, 42500, 43200),
        ("20260724", 43200, 43800, 43000, 43607),
        ("20260727", 43000, 43400, 42000, 42200),
        ("20260728", 42000, 42200, 41000, 41603),
        ("20260729", 41000, 41200, 39385, 40000),
        ("20260730", 40000, 40500, 39933, 40200),
        ("20260731", 41000, 43120, 40800, 43120),
        ("20260803", 43200, 44000, 43000, 43800),
        ("20260804", 43800, 44500, 43500, 44200),
        ("20260805", 44200, 45000, 44000, 44800),
        ("20260806", 44800, 45500, 44500, 45200),
        ("20260807", 45200, 45800, 45000, 45600),
        ("20260810", 45600, 46000, 45400, 45800),
        ("20260811", 45800, 46200, 45600, 46000),
        ("20260812", 46000, 46500, 45800, 46200),
        ("20260813", 46200, 46800, 46000, 46500),
    ]
    for d, o, h, lo, c in tw:
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
            (d, "TWII", o, h, lo, c, 1, 0),
        )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "p1",
            0,
            "2026-07-16",
            "22:00",
            "",
            0,
            "post",
            "[]",
            "台積電量價選第一種。大盤絕對不可能破 40000。",
            "",
        ),
    )
    # 假跌破：3653 7/20 破、3 日內站回
    bars = [
        ("20260716", 5000, 5100, 4900, 5050, 800),
        ("20260717", 5050, 5120, 4950, 5000, 900),
        ("20260720", 4980, 5000, 4700, 4720, 2000),
        ("20260721", 4800, 5050, 4750, 5020, 700),
        ("20260722", 5020, 5080, 4980, 5060, 600),
        ("20260723", 5060, 5100, 5000, 5080, 500),
        ("20260724", 5080, 5120, 5040, 5100, 500),
    ]
    for d, o, h, lo, c, v in bars:
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "3653", "健策", o, h, lo, c, v, 0),
        )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "p2",
            0,
            "2026-07-20",
            "15:00",
            "",
            1,
            "reply",
            "[]",
            "健策今天假跌破，過幾天就知道。",
            "",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_mentions VALUES (?,?,?)",
        ("p2", "3653", "健策"),
    )
    # 量縮站撐：爆量 7/16、後量縮收在撐上、20 日後更高——窗不夠就至少不炸
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "p3",
            0,
            "2026-07-16",
            "18:00",
            "",
            0,
            "post",
            "[]",
            "台積電量價結構低檔爆大量收在撐上。",
            "",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_mentions VALUES (?,?,?)",
        ("p3", "2330", "台積電"),
    )
    for i, d in enumerate(
        [
            "20260710",
            "20260711",
            "20260714",
            "20260715",
            "20260716",
            "20260717",
            "20260720",
            "20260721",
            "20260722",
            "20260723",
            "20260724",
            "20260727",
            "20260728",
            "20260729",
            "20260730",
            "20260731",
            "20260803",
            "20260804",
            "20260805",
            "20260806",
            "20260807",
            "20260810",
            "20260811",
            "20260812",
            "20260813",
            "20260814",
        ]
    ):
        vol = 100000 if d == "20260716" else 20000
        close = 2200 + i * 10
        lo = 2180 if d == "20260716" else close - 20
        hi = close + 20
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "2330", "台積電", close, hi, lo, close, vol, 0),
        )
    conn.commit()
    conn.close()


def test_five_bt_wave_40000_is_miss(tmp_path):
    db = str(tmp_path / "five.db")
    _seed(db)
    snap = run_five_bt(db)
    assert snap["ok"]
    wave = snap["tools"]["wave"]
    notes = " ".join(str(s.get("note")) for s in wave["samples"])
    assert "40000" in notes or wave["miss"] >= 1
    assert any(s.get("ok") is False and s.get("px") == 40000 for s in wave["samples"])
    morph = snap["tools"]["morph"]
    assert any(s.get("sid") == "3653" and s.get("ok") is True for s in morph["samples"])
    md = render_md(snap)
    assert "不數個股" in md
    assert "偏多偏空" in md
    line = one_liner(snap)
    assert "波浪" in line
    assert "不是買訊" in line


def test_five_bt_method_in_neurons():
    body = method_body("五件回測")
    assert "67%" in body or "128/190" in body
    assert "假跌破" in body or "破線當天" in body
    assert "不進海選" in body
    five = method_body("真正有用的五件")
    assert "67%" in five or "假跌破過幾天" in five
    doubt = [t for t, _b in views_for_neuron("doubt")]
    assert "五件回測" in doubt
    blind = method_body("盲測要疊條件")
    assert "69%" in blind or "主跌" in blind
