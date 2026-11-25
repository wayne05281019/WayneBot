# -*- coding: utf-8 -*-
"""聯動×位階系統化挖礦：結構／閘門／非買訊。"""
from __future__ import annotations

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


def test_run_suite_live_db_smoke():
    from pathlib import Path

    db = str(Path(__file__).resolve().parents[1] / "data" / "wayne_market.db")
    payload = crm.run_suite(db, write_daily=False)
    assert payload.get("ok") is not False or payload.get("mine")
    assert payload.get("buy_signal") is False
    assert payload.get("phone_sync") == "blocked"
    assert payload.get("WAVE_NEURONS_MATCH") is False
    assert (payload.get("gate") or {}).get("replace") is False
    mine = payload.get("mine") or {}
    assert mine.get("n_hypotheses", 0) >= 15
    # 結構完整即可；dig_worth 數量依實盤
    assert "dig_worth" in mine
    assert "wave_strengthen_hints" in payload
