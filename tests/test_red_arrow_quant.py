# -*- coding: utf-8 -*-
"""紅箭頭代理量化關：過關前 promote_ready=False；不改買訊。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from red_arrow_quant import (
    KIND,
    TAG_BASE,
    TAG_LOW,
    gate_status,
    nav_low_arrow_first_mask,
    persist_scores,
    promote_ready,
    recompute_rates,
    score_stock_day,
)


def _ohlc_flat_then_new_low(n: int = 80, *, drop_last: bool = True) -> pd.DataFrame:
    """先抬高再砸新低，才會出現「首觸」20／60 低（全程貼底會天天 is_20l）。"""
    last = datetime(2026, 9, 17)
    rows = []
    for i in range(n):
        d = (last - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        if drop_last and i == n - 1:
            px, lo = 95.0, 94.0
        else:
            # 後半抬到 110，讓最後一跌相對 20／60 窗是新低
            px = 100.0 + min(i, 40) * 0.25
            lo = px - 1.0
        rows.append(
            {
                "date": d,
                "stock_id": "6257",
                "stock_name": "矽格",
                "open": px,
                "high": px + 1,
                "low": lo,
                "close": px,
                "volume": 3000,
            }
        )
    return pd.DataFrame(rows)


def test_nav_low_arrow_first_on_new_low():
    df = _ohlc_flat_then_new_low()
    m = nav_low_arrow_first_mask(df)
    assert bool(m.iloc[-1]) is True
    assert bool(m.iloc[-2]) is False


def test_score_stock_day_records_low_tag(tmp_path):
    df = _ohlc_flat_then_new_low()
    # 補足夠未來柱讓 h1 可結
    extra = []
    last = datetime(2026, 9, 17)
    for i in range(1, 12):
        d = (last + timedelta(days=i)).strftime("%Y%m%d")
        extra.append(
            {
                "date": d,
                "stock_id": "6257",
                "stock_name": "矽格",
                "open": 96.0,
                "high": 97.0,
                "low": 95.5,
                "close": 96.5,
                "volume": 3000,
            }
        )
    full = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    rows = score_stock_day(full, as_of="20260917")
    tags = {r["tag"] for r in rows}
    assert TAG_LOW in tags
    assert all(r["kind"] == KIND for r in rows)
    db = str(tmp_path / "m.db")
    # evolve 旁路：tape_store_path 會寫同目錄 wayne_evolve.db
    open(db, "a").close()
    n = persist_scores(db, rows)
    assert n > 0
    rates = recompute_rates(db)
    assert any(k.startswith(TAG_LOW) for k in rates)


def test_promote_ready_false_until_gate(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    open(db, "a").close()
    st = gate_status(db, horizon=5)
    assert st["promote_ready"] is False
    assert st["n_ok"] is False
    assert promote_ready(db) is False
    assert "不是買訊" in st["note"]
    assert st["min_distinct_sids"] >= 100
    assert st["min_unique_days"] >= 20


def test_ai_trader_still_says_red_arrow_not_entry(tmp_path):
    """關未過：產品編碼仍鎖紅箭頭不是買訊。"""
    from ai_trader import current_ai_encoding, format_evolve_report_html
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "e.db")
    ensure_core_schema(path)
    enc = current_ai_encoding(path, "ai_1")
    assert enc["not_entry"] == "red_arrow"
    html = format_evolve_report_html(path, "ai_1")
    assert "紅箭頭不是買訊" in html
