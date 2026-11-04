# -*- coding: utf-8 -*-
import sqlite3

from scripts.decade_lab_chips_module import load_chips_votes, snapshot_chips_factors


def test_snapshot_chips_from_temp_db(tmp_path):
    db = tmp_path / "m.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE market_margin_daily(
            date TEXT PRIMARY KEY, margin_bal_prev_k INT, margin_bal_k INT,
            margin_delta_k INT, source TEXT, updated_at TEXT
        );
        CREATE TABLE index_breadth_daily(
            date TEXT PRIMARY KEY, up_count INT, down_count INT,
            limit_up INT, limit_down INT, flat_count INT,
            up_tw INT, down_tw INT, up_two INT, down_two INT,
            source TEXT, updated_at TEXT
        );
        CREATE TABLE market_tape_daily(
            date TEXT PRIMARY KEY, amount_ntd REAL, shares REAL, trades INT,
            twii_close REAL, amount_trillion REAL, source TEXT, updated_at TEXT
        );
        CREATE TABLE futures_daily(
            date TEXT, symbol TEXT, session TEXT, contract_month TEXT,
            open REAL, high REAL, low REAL, close REAL, settlement REAL,
            volume INT, open_interest INT, pct_change REAL,
            source TEXT, updated_at TEXT,
            PRIMARY KEY(date, symbol, session)
        );
        """
    )
    days = [f"202501{i:02d}" for i in range(1, 26)]
    for i, d in enumerate(days):
        conn.execute(
            "INSERT INTO market_margin_daily VALUES (?,?,?,?,?,?)",
            (d, 1000, 1000 + i, -50 - i, "t", "now"),
        )
        conn.execute(
            "INSERT INTO index_breadth_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, 300, 700, 2, 25, 50, 0, 0, 0, 0, "t", "now"),
        )
        conn.execute(
            "INSERT INTO market_tape_daily VALUES (?,?,?,?,?,?,?,?)",
            (d, 1e12, 0, 0, 20000, 1.0 + i * 0.01, "t", "now"),
        )
        conn.execute(
            "INSERT INTO futures_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, "TX", "regular", "202503", 1, 1, 1, 1, 1, 1, 100000 + i * 100, 0, "t", "now"),
        )
    conn.commit()
    f, _miss = snapshot_chips_factors(conn, "20250125")
    conn.close()
    assert "chips_margin_delta_k" in f
    assert "chips_ud_ratio" in f
    assert f.get("chips_ud_le_0_6") is True
    assert f.get("chips_limit_down_ge_20") is True
    assert "chips_tx_oi" in f


def test_load_chips_votes_optional():
    votes = load_chips_votes()
    assert isinstance(votes, dict)
