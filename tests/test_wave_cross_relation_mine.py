# -*- coding: utf-8 -*-
"""聯動×位階系統化挖礦：結構／閘門／非買訊。"""
from __future__ import annotations

import pytest

import wave_cross_relation_mine as crm


def test_hypotheses_nonempty_and_families():
    hyps = crm._hypotheses()
    assert len(hyps) >= 15
    fams = {h["family"] for h in hyps}
    assert "co_move" in fams
    assert "lead_lag" in fams
    assert "wave_x_link" in fams


def test_eval_hyp_on_synthetic_rows():
    rows = []
    for i, (sx, tw, touch, hold) in enumerate(
        [
            ("down", "hold", True, True),
            ("down", "up", True, True),
            ("down", "down", True, False),
            ("down", "soft", True, True),
            ("up", "up", False, False),
            ("up", "hold", True, True),
        ]
        * 6  # sox_down n=24
    ):
        rows.append(
            {
                "tw_day": f"202401{i%20+1:02d}",
                "year": "2024" if i < 20 else "2025",
                "sides": {
                    "sox": sx,
                    "tsm_adr": "na",
                    "2330": "hold",
                    "twii": tw,
                    "te_night": "na",
                    "te_day": "na",
                    "tx_night": "na",
                },
                "rets": {
                    "sox": -1.0 if sx == "down" else 1.0,
                    "tsm_adr": None,
                    "2330": 0.0,
                    "twii": 0.0 if tw == "hold" else (-1.0 if tw == "down" else 1.0),
                    "te_night": None,
                    "te_day": None,
                    "tx_night": None,
                },
                "level": {
                    "n_levels": 1 if touch else 0,
                    "touch": touch,
                    "hold": hold,
                    "break": touch and not hold,
                },
            }
        )
    hyp = next(h for h in crm._hypotheses() if h["id"] == "sox_down_tw_not_down")
    out = crm._eval_hyp(rows, hyp)
    assert out["n"] >= 20
    assert out["rate"] is not None
    assert out["buy_signal"] is False
    assert out["phone_sync"] == "blocked"


def test_run_suite_schema_tolerant_smoke(tmp_path):
    """smoke-no-db：空／缺表庫不得炸；結構欄位仍完整。"""
    import sqlite3

    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE biaoke_posts (id TEXT, date TEXT, text TEXT, kind TEXT)")
    conn.commit()
    conn.close()
    payload = crm.run_suite(str(db), write_daily=False)
    assert payload.get("buy_signal") is False
    assert payload.get("phone_sync") == "blocked"
    assert payload.get("WAVE_NEURONS_MATCH") is False
    assert (payload.get("gate") or {}).get("replace") is False
    mine = payload.get("mine") or {}
    assert mine.get("n_hypotheses", 0) >= 15
    assert "dig_worth" in mine
    assert "wave_strengthen_hints" in payload


@pytest.mark.production_db
def test_run_suite_live_db_smoke():
    """需要完整行情表；不進 smoke-no-db。"""
    import sqlite3
    from pathlib import Path

    db = Path(__file__).resolve().parents[1] / "data" / "wayne_market.db"
    if not db.is_file():
        pytest.skip("no wayne_market.db")
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_daily'"
        ).fetchone()
        n = (
            conn.execute("SELECT COUNT(*) FROM index_daily WHERE symbol='TWII'").fetchone()
            if row
            else (0,)
        )
    except sqlite3.Error:
        row, n = None, (0,)
    finally:
        conn.close()
    if not row or not n or int(n[0] or 0) < 20:
        pytest.skip("index_daily TWII too thin (smoke-no-db)")
    payload = crm.run_suite(str(db), write_daily=False)
    assert payload.get("buy_signal") is False
    assert payload.get("phone_sync") == "blocked"
    assert payload.get("WAVE_NEURONS_MATCH") is False
    assert (payload.get("gate") or {}).get("replace") is False
    mine = payload.get("mine") or {}
    assert mine.get("n_hypotheses", 0) >= 15
    assert "dig_worth" in mine
