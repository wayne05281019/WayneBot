# -*- coding: utf-8 -*-
"""第 3 輪 §13 環境濾網（公式本體不改；再生下一版鍵存在）。"""
from __future__ import annotations


def test_active_and_next_keys():
    import multi_track_env_gates as g

    assert g.ACTIVE_A2_FILTER == "R3c_keep_pressure"
    assert g.ACTIVE_A5_FILTER == "R3a_twii_down"
    nxt = g.silent_next_keys()
    assert nxt["A2"] == g.NEXT_A2_SILENT
    assert nxt["A5"] == g.NEXT_A5_SILENT


def test_twii_closed_down_uses_db(tmp_path):
    import sqlite3

    import multi_track_env_gates as g

    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE index_daily(
          date TEXT, symbol TEXT, close REAL, open REAL, high REAL, low REAL, volume REAL
        )
        """
    )
    con.executemany(
        "INSERT INTO index_daily(date,symbol,close) VALUES (?,?,?)",
        [
            ("20261020", "TWII", 100.0),
            ("20261021", "TWII", 99.0),  # down
            ("20261022", "TWII", 101.0),  # up
        ],
    )
    con.commit()
    con.close()
    g._twii_dir_map.cache_clear()
    assert g.twii_closed_down(str(db), "20261021") is True
    assert g.twii_closed_down(str(db), "20261022") is False
    assert g.twii_closed_down(str(db), "19990101") is None
    assert g.keep_a5_stabilize(str(db), "20261021") is True
    assert g.keep_a5_stabilize(str(db), "20261022") is False
    assert g.keep_a5_stabilize(str(db), "19990101") is True


def test_em_skips_a2_pressure_filter():
    import multi_track_env_gates as g

    # 興櫃無外資壓力定義 → 不擋
    assert g.keep_a2_red_arrow("/nonexistent.db", "20261021", market="EM") is True
