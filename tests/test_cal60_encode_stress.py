# -*- coding: utf-8 -*-
"""編碼後獨立壓力測試：向量化 60 曆日獲利對產線庫一批股票要算完。"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd
import pytest

from decision_card_signals import cal60_profit_bundle
from tests.conftest import require_production_db

pytestmark = pytest.mark.production_db


def test_cal60_encode_stress_200_names():
    db = require_production_db()
    conn = sqlite3.connect(db)
    as_of = conn.execute("SELECT MAX(date) FROM daily_quotes").fetchone()[0]
    assert as_of
    sids = [
        r[0]
        for r in conn.execute(
            """
            SELECT stock_id FROM daily_quotes
            WHERE close IS NOT NULL
            GROUP BY stock_id
            HAVING COUNT(*) >= 40
            LIMIT 200
            """
        )
    ]
    t0 = time.perf_counter()
    n = 0
    last_pct = None
    for sid in sids:
        rows = conn.execute(
            "SELECT date, close FROM daily_quotes WHERE stock_id=? ORDER BY date",
            (sid,),
        ).fetchall()
        if len(rows) < 40:
            continue
        df = pd.DataFrame(rows, columns=["date", "close"])
        _floors, pct = cal60_profit_bundle(df)
        assert len(pct) == len(df)
        last_pct = float(pct.iloc[-1])
        n += 1
    elapsed = time.perf_counter() - t0
    conn.close()
    assert n >= 80, f"有效樣本不足 n={n}"
    assert elapsed < 60.0, f"編碼壓測過慢 {elapsed:.2f}s / {n} 檔"
    report = f"as_of={as_of} names={n} elapsed_s={elapsed:.3f} last_pct={last_pct}\n"
    art = Path("/opt/cursor/artifacts")
    try:
        art.mkdir(parents=True, exist_ok=True)
        (art / "cal60_encode_stress.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
