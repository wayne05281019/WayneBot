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
    TAG_NONE,
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


def _with_fwd(df: pd.DataFrame, *, days: int = 12, close: float = 96.5) -> pd.DataFrame:
    extra = []
    last = datetime(2026, 9, 17)
    for i in range(1, days + 1):
        d = (last + timedelta(days=i)).strftime("%Y%m%d")
        extra.append(
            {
                "date": d,
                "stock_id": "6257",
                "stock_name": "矽格",
                "open": close,
                "high": close + 1,
                "low": close - 0.5,
                "close": close,
                "volume": 3000,
            }
        )
    return pd.concat([df, pd.DataFrame(extra)], ignore_index=True)


def test_nav_low_arrow_first_on_new_low():
    df = _ohlc_flat_then_new_low()
    m = nav_low_arrow_first_mask(df)
    assert bool(m.iloc[-1]) is True
    assert bool(m.iloc[-2]) is False


def test_score_stock_day_records_low_tag_and_false_break(tmp_path):
    full = _with_fwd(_ohlc_flat_then_new_low(), close=96.5)
    rows = score_stock_day(full, as_of="20260917")
    tags = {r["tag"] for r in rows}
    assert TAG_LOW in tags
    assert TAG_NONE not in tags  # 當日有低點首觸，不算無箭頭
    assert all(r["kind"] == KIND for r in rows)
    assert all("false_break" in r for r in rows)
    # 後續收 96.5 > 進場 95 → 非假突破
    h5 = [r for r in rows if r["tag"] == TAG_LOW and r["horizon"] == 5][0]
    assert h5["false_break"] == 0
    assert h5["verdict"] == "hit"
    db = str(tmp_path / "m.db")
    open(db, "a").close()
    n = persist_scores(db, rows)
    assert n > 0
    rates = recompute_rates(db)
    assert any(k.startswith(TAG_LOW) for k in rates)
    assert rates[f"{TAG_LOW}:h5"]["false_break"] == 0


def test_score_false_break_when_close_under_entry(tmp_path):
    """後窗收盤跌破進場收＝假突破。"""
    full = _with_fwd(_ohlc_flat_then_new_low(), close=90.0)
    rows = score_stock_day(full, as_of="20260917")
    h5 = [r for r in rows if r["tag"] == TAG_LOW and r["horizon"] == 5][0]
    assert h5["false_break"] == 1
    assert h5["verdict"] == "miss"


def test_no_arrow_baseline_when_neither_signal(monkeypatch):
    """抬高走勢無新低；leave_zero 關掉 → 記無箭頭基線。"""
    monkeypatch.setattr(
        "decision_card_signals.leave_zero_from_quote_df",
        lambda df: False,
    )
    df = _ohlc_flat_then_new_low(drop_last=False)
    full = _with_fwd(df, close=112.0)
    as_of = str(df["date"].iloc[-1])
    assert bool(nav_low_arrow_first_mask(df).iloc[-1]) is False
    rows_scored = score_stock_day(full, as_of=as_of)
    tags = {r["tag"] for r in rows_scored}
    assert TAG_NONE in tags
    assert TAG_LOW not in tags
    assert TAG_BASE not in tags


def test_promote_ready_false_until_gate(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    open(db, "a").close()
    st = gate_status(db, horizon=5)
    assert st["promote_ready"] is False
    assert st["n_ok"] is False
    assert st["beats_leave_zero"] is False
    assert "no_arrow" in st
    assert promote_ready(db) is False
    assert "不是買訊" in st["note"]
    assert st["min_distinct_sids"] >= 100
    assert st["min_unique_days"] >= 20
    assert st.get("next_candidate")


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


def test_nav_legend_marks_red_arrow_proxy_not_passed():
    """話筒圖例：低點箭頭標未過關，不當買訊。"""
    import inspect

    from wayne_navigator import _draw_nav_legend

    src = inspect.getsource(_draw_nav_legend)
    assert "紅箭頭代理·未過關" in src
    assert "買點↑首清楚／續淡" in src or "買點↑藍▲紅框" in src
