# -*- coding: utf-8 -*-
"""季報業外：NULL 不准蓋掉已有官方數。"""
from __future__ import annotations

import sqlite3

from fundamentals import _upsert_income, ensure_fundamentals_tables
from wayne_db import ensure_core_schema, init_database


def _row(*, season: int, non_operating):
    return {
        "stock_id": "2383",
        "year": 2026,
        "season": season,
        "stock_name": "台光電",
        "market": "TW",
        "revenue": 1000.0,
        "cogs": 0.0,
        "gross_profit": 100.0,
        "gross_margin_pct": 10.0,
        "operating_income": 50.0,
        "non_operating": non_operating,
        "net_income": 40.0,
        "eps": 1.0,
        "published_roc": "1151118",
    }


def test_upsert_income_keeps_non_operating_when_new_is_null(tmp_path):
    db = str(tmp_path / "non.db")
    init_database(db)
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    con = sqlite3.connect(db)
    try:
        _upsert_income(con, [_row(season=3, non_operating=134137.0)])
        con.commit()
        # 後續同步缺業外欄 → NULL；不准洗掉
        _upsert_income(con, [_row(season=3, non_operating=None)])
        con.commit()
        got = con.execute(
            "SELECT non_operating FROM quarterly_income WHERE stock_id='2383' AND year=2026 AND season=3"
        ).fetchone()[0]
        assert abs(float(got) - 134137.0) < 1e-6
    finally:
        con.close()
