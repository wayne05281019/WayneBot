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
            ("4979", "華星光"),
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
        # 6442 末值壓低：成長規則會把同鏈中位封頂到產業合理 PE，須相對便宜才進 ★
        pes = {
            "6442": [45, 42, 40, 38, 35, 33, 32, 31, 28, 24, 22, 20, 18.0],
            "3081": [120] * 13,
            "2455": [60] * 13,
            "3105": [55] * 13,
            "4979": [58] * 13,
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
            # 硬濾 YoY≥15%；成長鐵律需季報＋月營收可外推
            for mm, rev, mom, ytd in (
                ("202608", 900, 3.0, 7000),
                ("202609", 950, 5.0, 7950),
                ("202610", 1000, 5.0, 9000),
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO monthly_revenue "
                    "(stock_id, yyyymm, stock_name, market, industry, revenue, "
                    "revenue_prev_month, revenue_prev_year, mom_pct, yoy_pct, "
                    "ytd_revenue, ytd_prev_year, ytd_yoy_pct, published_roc, updated_at) "
                    "VALUES (?, ?, ?, 'TW', '', ?, 900, 800, ?, 25.0, "
                    "?, 7000, 20.0, '', ?)",
                    (sid, mm, name, rev, mom, ytd, as_of),
                )
            for season, gm, op, net, eps, rev_q in (
                (1, 40.0, 200, 220, 2.0, 3000),
                (2, 42.0, 420, 450, 4.2, 6200),
                (3, 45.0, 700, 750, 6.5, 9500),
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO quarterly_income "
                    "(stock_id, year, season, stock_name, market, revenue, cogs, "
                    "gross_profit, gross_margin_pct, operating_income, net_income, "
                    "eps, published_roc, updated_at) "
                    "VALUES (?, 2026, ?, ?, 'TW', ?, 0, 0, ?, ?, ?, ?, '', ?)",
                    (sid, season, name, rev_q, gm, op, net, eps, as_of),
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
            "6442": ["6442", "3081", "2455", "3105", "4979"],
            "3081": ["6442", "3081", "2455", "3105", "4979"],
            "2455": ["6442", "3081", "2455", "3105", "4979"],
            "3105": ["6442", "3081", "2455", "3105", "4979"],
            "4979": ["6442", "3081", "2455", "3105", "4979"],
            "9999": ["9999", "3081", "2455", "3105", "4979"],
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


def test_night_tick_hook_and_gate():
    import inspect

    from judge_tape import _snapshot_pressure_support
    from undervalue_verify import gate_status, night_tick

    src = inspect.getsource(_snapshot_pressure_support)
    assert "undervalue_verify" in src
    assert "undervalue_night_tick" in src
    g = gate_status("")
    assert g["buy_signal"] is False
    assert g["promote_golden_buy"] is False
    assert "min_n" in g
    tick = night_tick("", as_of="")
    assert tick["buy_signal"] is False
