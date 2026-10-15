# -*- coding: utf-8 -*-
"""飆大他說／我說分軌：必有下一步看法；§13 過閘才換；不進話筒。"""
from __future__ import annotations

import os
import sqlite3

import biaoke_diverge as bd


def _db(tmp_path):
    path = str(tmp_path / "wayne_market.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE index_daily (
            symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER
        );
        CREATE TABLE futures_daily (
            symbol TEXT, session TEXT, date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER
        );
        """
    )
    # 完整近窗柱（截至 20261014；盤中未收不當收）
    rows = []
    base = 48000.0
    for i in range(30):
        d = f"202609{i+1:02d}" if i < 30 else "20261001"
        # simple calendar-ish dates 20260901.. then 20261001..
        if i < 14:
            d = f"202609{i+15:02d}" if i + 15 <= 30 else f"202610{i-14+1:02d}"
        else:
            d = f"202610{i-13:02d}"
        o = base + i * 10
        h = o + 80
        l = o - 60
        c = o + 20
        rows.append(("TWII", d, o, h, l, c, 1000 + i))
        conn.execute(
            "INSERT INTO futures_daily VALUES (?,?,?,?,?,?,?,?)",
            ("TX", "regular", d, o + 5, h + 5, l + 5, c + 5, 2000 + i),
        )
    # fix dates properly
    conn.execute("DELETE FROM index_daily")
    conn.execute("DELETE FROM futures_daily")
    days = [f"202609{d:02d}" for d in range(10, 31)] + [
        f"202610{d:02d}" for d in range(1, 15)
    ]
    for i, d in enumerate(days):
        o = base + i * 10
        h = o + 80
        l = o - 60
        c = o + 20
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?)",
            ("TWII", d, o, h, l, c, 1000 + i),
        )
        conn.execute(
            "INSERT INTO futures_daily VALUES (?,?,?,?,?,?,?,?)",
            ("TX", "regular", d, o + 5, h + 5, l + 5, c + 5, 2000 + i),
        )
    conn.commit()
    conn.close()
    return path


def test_must_have_our_view_for_level(tmp_path):
    db = _db(tmp_path)
    claim = {
        "post_id": "185798409",
        "post_date": "2026-10-14",
        "stock_id": "TWII",
        "stock_name": "台指",
        "role": "support",
        "lo": 47850.0,
        "hi": 47850.0,
        "snippet": "台指期低標一定要過47850否則還會再打",
        "claim_key": "t1",
        "kind": "post",
    }
    rows = bd.build_diverge_from_claim(db, claim)
    assert len(rows) == 2  # current + next
    for r in rows:
        assert r["his_lo"] == 47850.0
        assert r["our_lo"] is not None or r["our_hi"] is not None
        assert r["our_basis"]
        assert r["our_path"]
        assert "非買訊" in r["our_path"]
        assert r["variant"] in ("current", "next")
    n = bd.record_diverge_rows(db, rows)
    assert n == 2


def test_path_only_still_requires_our_next_step(tmp_path):
    db = _db(tmp_path)
    stats = bd.record_from_events(
        db,
        [
            {
                "id": "p1",
                "date": "2026-10-14",
                "kind": "post",
                "text": "大盤後續還會再打，夜盤先看方向",
                "tags": [],
            }
        ],
    )
    assert stats["rows"] >= 2
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT count(*) FROM biaoke_diverge").fetchone()[0]
    conn.close()
    assert n >= 2


def test_empty_claim_skipped():
    rows = bd.build_diverge_from_claim(
        "",
        {"post_id": "x", "post_date": "20261014", "snippet": "今天天氣好", "role": ""},
    )
    assert rows == []


def test_extract_index_levels_near_keyword_only():
    text = (
        "大盤多頭結構破壞點位在47500左右，"
        "今天抄底不成則往40000邁進，抓收盤收47300~47500"
    )
    got = bd._extract_index_levels(text)
    pairs = sorted({(r["lo"], r["hi"]) for r in got})
    assert (47500.0, 47500.0) in pairs
    assert (47300.0, 47500.0) in pairs
    # 40000 離「破／點位」關鍵字太遠，不准誤綁成破位
    assert (40000.0, 40000.0) not in pairs


def test_gate_not_ready_without_n(tmp_path):
    db = _db(tmp_path)
    bd.ensure_biaoke_diverge_table(db)
    g = bd.gate_status(db)
    assert g["n_ok"] is False
    assert g["promote_ready"] is False
    promo = bd.promote_if_ready(db)
    assert promo["promoted"] is False


def test_promote_swaps_and_regenerates(tmp_path):
    db = _db(tmp_path)
    bd.ensure_biaoke_diverge_table(db)
    # 灌滿 n≥20 且 next 勝率更高（獨立交易日）
    conn = sqlite3.connect(db)
    days = [f"202609{d:02d}" for d in range(10, 31)] + ["20261001"]  # 22 日
    for i, day in enumerate(days):
        for variant, our_v in (("current", "偏"), ("next", "對")):
            key = f"k{i}|{variant}"
            conn.execute(
                """
                INSERT INTO biaoke_diverge(
                    diverge_key, as_of, post_id, stock_id, role,
                    his_lo, his_hi, our_lo, our_hi, our_basis, our_path,
                    his_verdict, our_verdict, winner, variant, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    key,
                    day,
                    f"p{i}",
                    "TWII",
                    "support",
                    47000.0,
                    47000.0,
                    47100.0,
                    47100.0,
                    "basis",
                    "path 非買訊",
                    "偏",
                    our_v,
                    "our" if our_v == "對" else "his",
                    variant,
                    "t",
                ),
            )
    conn.commit()
    conn.close()
    g = bd.gate_status(db)
    assert g["n_ok"] is True
    assert g["promote_ready"] is True
    before = bd.load_rules(db)
    promo = bd.promote_if_ready(db)
    assert promo["promoted"] is True
    after = bd.load_rules(db)
    assert after["current"]["swing"] == before["next"]["swing"]
    assert after["next"]["gen"] == before["next"].get("gen", 1) + 1
    # 再呼叫不應在 rates 未變時無限 promote？ rates 仍 next>current 會再 promote——
    # 可接受；實務上 promote 後 next 參數變了、列仍屬舊窗，night 會重收。


def test_snapshot_context_kind(tmp_path):
    db = _db(tmp_path)
    claim = {
        "post_id": "185",
        "post_date": "20261014",
        "stock_id": "TWII",
        "role": "pressure",
        "lo": 49000.0,
        "hi": 49000.0,
        "snippet": "台指期壓力49000",
        "claim_key": "c2",
    }
    bd.record_diverge_rows(db, bd.build_diverge_from_claim(db, claim))
    n = bd.snapshot_biaoke_diverge(db, as_of="20261014")
    assert n >= 1


def test_ingest_hook_importable():
    src = open("biaoke_ingest.py", encoding="utf-8").read()
    assert "biaoke_diverge" in src
    assert "record_diverge_events" in src
    jt = open("judge_tape.py", encoding="utf-8").read()
    assert "biaoke_diverge_night_tick" in jt
    assert "biaoke_diverge" in open("button_silent_verify.py", encoding="utf-8").read()
