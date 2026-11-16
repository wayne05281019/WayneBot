# -*- coding: utf-8 -*-
"""sample_universe 必須跳過尖端瘦日，改用夠厚的行情日。"""
from __future__ import annotations

import sqlite3

from tests.card_face_audit import sample_universe


def test_sample_universe_skips_thin_tip_day(tmp_path):
    db = str(tmp_path / "thin_tip.db")
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE stock_universe (
            stock_id TEXT PRIMARY KEY,
            stock_name TEXT,
            market_type TEXT
        );
        CREATE TABLE daily_quotes (
            stock_id TEXT,
            date TEXT,
            close REAL
        );
        CREATE TABLE emerging_quotes (
            stock_id TEXT,
            date TEXT,
            close REAL
        );
        """
    )
    # 上市櫃：舊日厚、尖端日只 12 檔
    rows = []
    for i in range(1, 1201):
        sid = f"{i:04d}"
        mkt = "TW" if i <= 800 else "TWO"
        con.execute(
            "INSERT INTO stock_universe(stock_id, stock_name, market_type) VALUES (?,?,?)",
            (sid, f"名{sid}", mkt),
        )
        close = 10.0 if i % 3 == 0 else (50.0 if i % 3 == 1 else 250.0)
        rows.append((sid, "20261109", close))
        if i <= 12:
            rows.append((sid, "20261113", close))
    con.executemany(
        "INSERT INTO daily_quotes(stock_id, date, close) VALUES (?,?,?)", rows
    )
    # 興櫃：舊日厚、尖端瘦
    for i in range(1, 301):
        sid = f"E{i:04d}"
        con.execute(
            "INSERT INTO stock_universe(stock_id, stock_name, market_type) VALUES (?,?,?)",
            (sid, f"興{sid}", "EM"),
        )
        close = 8.0 if i % 3 == 0 else (40.0 if i % 3 == 1 else 220.0)
        con.execute(
            "INSERT INTO emerging_quotes(stock_id, date, close) VALUES (?,?,?)",
            (sid, "20261103", close),
        )
        if i <= 5:
            con.execute(
                "INSERT INTO emerging_quotes(stock_id, date, close) VALUES (?,?,?)",
                (sid, "20261113", close),
            )
    con.commit()
    con.close()

    sample = sample_universe(db, 1000)
    assert len(sample) >= 1000, f"應跳過尖端瘦日，實際只有 {len(sample)}"
    ids = {x["stock_id"] for x in sample}
    assert "0001" in ids
    assert any(x["market"] == "EM" for x in sample)
