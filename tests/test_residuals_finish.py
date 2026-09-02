# -*- coding: utf-8 -*-
import sqlite3

import pandas as pd

from decision_card_signals import compute_ma60s
from ex_rights import ensure_ex_rights_table, load_ex_rights, upsert_heuristic_event
from screen_review import adapt_bucket_weights, bucket_weight
from wayne_navigator import normalize_ohlc


def test_compute_ma60s_mid_price_absolute():
    """南亞帶：中價、小斜率 → 用「元」。"""
    assert compute_ma60s(180.0, 170.3, 178.0) == 9.7


def test_compute_ma60s_daf_split_band():
    """達發帶：中價但斜率用 % 更貼範本。"""
    assert compute_ma60s(98.0, 100.5, 95.0) == -2.5


def test_compute_ma60s_high_price_percent():
    assert compute_ma60s(520.0, 500.0, 600.0) == 4.0


def test_adapt_bucket_weights_applies_regime(tmp_path):
    db = str(tmp_path / "w.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ai_params (k TEXT PRIMARY KEY, v REAL NOT NULL)")
    conn.commit()
    conn.close()
    w = adapt_bucket_weights(db, regime="bear")
    assert w["select_01"] <= 0.8
    assert bucket_weight(db, "select_01") == w["select_01"]


def test_heuristic_split_persisted(tmp_path):
    db = str(tmp_path / "x.db")
    ensure_ex_rights_table(db)
    upsert_heuristic_event(db, "1234", "20260815", 2.0, kind="分割")
    rows = load_ex_rights("1234", db)
    assert rows and float(rows[0]["factor"]) == 2.0


def test_normalize_mild_split_gap():
    df = pd.DataFrame(
        {
            "date": ["20260810", "20260811", "20260812"],
            "stock_id": ["9999"] * 3,
            "open": [100.0, 200.0, 205.0],
            "high": [102.0, 205.0, 208.0],
            "low": [98.0, 198.0, 202.0],
            "close": [100.0, 200.0, 206.0],
            "volume": [1000.0, 500.0, 520.0],
        }
    )
    out, notes = normalize_ohlc(df, None)
    assert any("分割" in n or "還原" in n for n in notes)
    assert float(out["close"].iloc[0]) > 150
