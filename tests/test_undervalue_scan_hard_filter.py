# -*- coding: utf-8 -*-
"""低估硬濾：官方本益＋同鏈中位／下緣；不是 stub 空轉。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from wayne_db import ensure_core_schema, init_database


def _seed(db: str, as_of: str = "20261113") -> None:
    ensure_core_schema(db)
    try:
        from industry_fine import ensure_fine_industry_table

        ensure_fine_industry_table(db)
    except Exception:
        pass
    conn = sqlite3.connect(db)
    try:
        # 宇宙＋細項鏈（光通訊教過組）
        for sid, name in (
            ("6442", "光聖"),
            ("3081", "聯亞"),
            ("2455", "全新"),
            ("3105", "穩懋"),
            ("9999", "假貴"),
        ):
            conn.execute(
                "INSERT OR REPLACE INTO stock_universe "
                "(stock_id, stock_name, market_type, is_active, asset_type, updated_at) "
                "VALUES (?, ?, 'TW', 1, 'STOCK', ?)",
                (sid, name, as_of),
            )
            conn.execute(
                "INSERT OR REPLACE INTO stock_fine_industry "
                "(stock_id, chain, tags_json, source, fetched_at) "
                "VALUES (?, '電子中游-通訊設備-光通訊', ?, 'test', ?)",
                (sid, '["電子中游","通訊設備","光通訊"]', as_of),
            )
        # 官方本益：6442 近窗低緣＋遠低同鏈中位；9999 很貴
        pes = {
            "6442": [45, 42, 40, 38, 35, 33, 32, 31, 30.5, 30, 29.9, 29.8, 29.73],
            "3081": [120] * 13,
            "2455": [60] * 13,
            "3105": [55] * 13,
            "9999": [90] * 13,
        }
        for sid, series in pes.items():
            for i, pe in enumerate(series):
                d = f"202610{i+1:02d}" if i < 12 else as_of
                if i == 12:
                    d = as_of
                elif i < 9:
                    d = f"2026100{i+1}"
                else:
                    d = f"202610{i+1}"
                conn.execute(
                    "INSERT OR REPLACE INTO daily_valuation "
                    "(stock_id, date, pe, pb, dividend_yield, source, updated_at) "
                    "VALUES (?, ?, ?, 1.0, 0, 'test', ?)",
                    (sid, d, pe, as_of),
                )
            for j in range(20):
                day = f"202610{j+1:02d}" if j < 9 else (as_of if j == 19 else f"202611{j-8:02d}")
                conn.execute(
                    "INSERT OR REPLACE INTO daily_quotes "
                    "(date, stock_id, stock_name, market, open, high, low, close, "
                    "volume, turnover_k, pct_change, avg_price) "
                    "VALUES (?, ?, ?, 'TW', 100, 101, 99, 100, 5000, 0, 0, 100)",
                    (day, sid, pes and sid),
                )
        # 補齊 6442 名字
        conn.execute(
            "UPDATE daily_quotes SET stock_name='光聖' WHERE stock_id='6442'"
        )
        conn.commit()
    finally:
        conn.close()


def test_hard_filter_marks_chain_cheap_star(tmp_path, monkeypatch):
    from undervalue_scan import RULE_PHONE, run_undervalue_scan

    db = str(tmp_path / "uv_hf.db")
    init_database(db)
    _seed(db)
    monkeypatch.setattr(
        "undervalue_scan._leader_ids",
        lambda _db, _meta: {"6442"},
    )
    # peer index：用教過光通訊組
    monkeypatch.setattr(
        "undervalue_scan._peer_index",
        lambda _db: {
            "6442": ["6442", "3081", "2455", "3105"],
            "3081": ["6442", "3081", "2455", "3105"],
            "2455": ["6442", "3081", "2455", "3105"],
            "3105": ["6442", "3081", "2455", "3105"],
            "9999": ["9999", "3081", "2455", "3105"],
        },
    )
    out = run_undervalue_scan(db, "20261113", rule_key=RULE_PHONE)
    assert out["ok"] is True
    by = {r["stock_id"]: r for r in out["rows"]}
    assert "6442" in by
    assert by["6442"]["mark"] == "star"
    assert by["6442"]["pe_est"] is False
    assert by["6442"]["peer_pe_median"] > by["6442"]["pe"]
    assert "9999" not in by or by.get("9999", {}).get("mark") != "star"


def test_next_variant_key_differs():
    from undervalue_scan import RULE_NEXT, RULE_PHONE, _CLASSIFIERS

    assert RULE_PHONE != RULE_NEXT
    assert RULE_PHONE in _CLASSIFIERS and RULE_NEXT in _CLASSIFIERS


def test_confront_status_shape(tmp_path):
    from undervalue_confront import confront_status

    db = str(tmp_path / "uv_c.db")
    Path(db).write_text("")
    st = confront_status(db)
    assert st["n_gate"] == 20
    assert st["promote_ready"] is False
    assert "phone_rule" in st and "next_rule" in st
