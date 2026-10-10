# -*- coding: utf-8 -*-
"""紅箭頭代理量化關：ma60_lower 已升成買訊；未確認仍不是。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from red_arrow_quant import (
    KIND,
    NEXT_CANDIDATE,
    ROUND_STOPPED,
    TAG_BASE,
    TAG_FILTER,
    TAG_HOLD,
    TAG_LOW,
    TAG_NONE,
    TAG_PREV,
    gate_status,
    nav_low_arrow_first_mask,
    nav_low_hold_low_confirm_mask,
    nav_low_ma60_lower_mask,
    nav_low_ma60_upper_mask,
    nav_low_ma60_vol_mask,
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


def test_ma60_vol_filter_rejects_freefall_below_ma60():
    """急殺遠低於 MA60 的首觸：基線有箭、過濾候選不收。"""
    df = _ohlc_flat_then_new_low()
    # 末根再砸更深，確保收盤遠低於 60 均
    df = df.copy()
    df.loc[df.index[-1], "close"] = 70.0
    df.loc[df.index[-1], "low"] = 69.0
    df.loc[df.index[-1], "high"] = 71.0
    df.loc[df.index[-1], "open"] = 72.0
    assert bool(nav_low_arrow_first_mask(df).iloc[-1]) is True
    assert bool(nav_low_ma60_vol_mask(df).iloc[-1]) is False


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


def _ohlc_mild_new_low_near_ma60(n: int = 80) -> pd.DataFrame:
    """窄幅震盪後輕觸 20 低，收盤仍在 MA60 帶內、量不過熱。"""
    last = datetime(2026, 9, 17)
    rows = []
    for i in range(n):
        d = (last - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        if i == n - 1:
            px, lo = 99.2, 98.8  # 新低但靠近均線
        else:
            # 99.5–101 震盪，MA60≈100
            px = 100.0 + (0.4 if i % 2 == 0 else -0.3)
            lo = px - 0.4
        rows.append(
            {
                "date": d,
                "stock_id": "6257",
                "stock_name": "矽格",
                "open": px,
                "high": px + 0.5,
                "low": lo,
                "close": px,
                "volume": 3000,
            }
        )
    return pd.DataFrame(rows)


def test_score_includes_prev_tag_when_ma60_vol_ok():
    """輕觸新低且在 MA60 帶＋量不過熱 → #548 對照軌記一筆。"""
    df = _ohlc_mild_new_low_near_ma60()
    assert bool(nav_low_arrow_first_mask(df).iloc[-1]) is True
    assert bool(nav_low_ma60_vol_mask(df).iloc[-1]) is True
    full = _with_fwd(df, close=100.0)
    rows = score_stock_day(full, as_of="20260917")
    tags = {r["tag"] for r in rows}
    assert TAG_LOW in tags
    assert TAG_PREV in tags
    h5 = [r for r in rows if r["tag"] == TAG_PREV and r["horizon"] == 5][0]
    assert h5["false_break"] == 0
    assert h5["verdict"] == "hit"


def _ohlc_hold_low_confirm_ok(n: int = 80) -> pd.DataFrame:
    """窄幅後首觸新低、收復前低且收在振幅上半 → hold_low_confirm 應過。"""
    last = datetime(2026, 9, 17)
    rows = []
    for i in range(n):
        d = (last - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        if i == n - 1:
            # 前一日低≈100；刺破到 98.5，收 100.2（≥前低）；振幅上半≈0.74
            px, lo, hi, op = 100.2, 98.5, 100.8, 99.5
        else:
            px = 100.0 + (0.4 if i % 2 == 0 else -0.3)
            lo, hi, op = px - 0.4, px + 0.5, px
        rows.append(
            {
                "date": d,
                "stock_id": "6257",
                "stock_name": "矽格",
                "open": op,
                "high": hi,
                "low": lo,
                "close": px,
                "volume": 3000,
            }
        )
    return pd.DataFrame(rows)


def test_hold_low_confirm_accepts_reclaim_and_rejects_close_on_low():
    """收復前低＋上半收＝過；貼底收＝不過。"""
    df = _ohlc_hold_low_confirm_ok()
    assert bool(nav_low_arrow_first_mask(df).iloc[-1]) is True
    assert bool(nav_low_hold_low_confirm_mask(df).iloc[-1]) is True
    bad = df.copy()
    bad.loc[bad.index[-1], "close"] = 98.6  # 貼當日低、也跌破前低
    bad.loc[bad.index[-1], "open"] = 99.2
    assert bool(nav_low_arrow_first_mask(bad).iloc[-1]) is True
    assert bool(nav_low_hold_low_confirm_mask(bad).iloc[-1]) is False


def test_score_includes_hold_tag_when_hold_low_ok():
    """#556 hold_low_confirm 過 → TAG_HOLD 歷史軌記一筆（不再當 TAG_FILTER）。"""
    df = _ohlc_hold_low_confirm_ok()
    full = _with_fwd(df, close=100.5)
    rows = score_stock_day(full, as_of="20260917")
    tags = {r["tag"] for r in rows}
    assert TAG_LOW in tags
    assert TAG_HOLD in tags
    assert TAG_HOLD == "nav_low_first_hold_low_confirm"
    h5 = [r for r in rows if r["tag"] == TAG_HOLD and r["horizon"] == 5][0]
    assert h5["false_break"] == 0
    assert h5["verdict"] == "hit"


def test_ma60_upper_requires_ma60_vol_and_upper_half():
    """#557 歷史：ma60_upper＝ma60_vol 且收在振幅上半；貼底收剔除。"""
    df = _ohlc_mild_new_low_near_ma60()
    # mild 末根 close 99.2、low 98.8 → 需抬高／收高才過上半
    df = df.copy()
    df.loc[df.index[-1], "high"] = 100.0
    df.loc[df.index[-1], "close"] = 99.6  # (99.6-98.8)/(100-98.8)=0.667
    df.loc[df.index[-1], "open"] = 99.0
    assert bool(nav_low_ma60_vol_mask(df).iloc[-1]) is True
    assert bool(nav_low_ma60_upper_mask(df).iloc[-1]) is True
    bad = df.copy()
    bad.loc[bad.index[-1], "close"] = 99.0  # (99-98.8)/(100-98.8)=0.167
    assert bool(nav_low_ma60_vol_mask(bad).iloc[-1]) is True
    assert bool(nav_low_ma60_upper_mask(bad).iloc[-1]) is False


def test_ma60_lower_requires_ma60_vol_and_lower_half():
    """ma60_lower＝ma60_vol 且收在振幅下半；上半收剔除。"""
    df = _ohlc_mild_new_low_near_ma60().copy()
    df.loc[df.index[-1], "high"] = 100.0
    df.loc[df.index[-1], "low"] = 98.8
    df.loc[df.index[-1], "close"] = 99.1  # (99.1-98.8)/(100-98.8)=0.25
    df.loc[df.index[-1], "open"] = 99.5
    assert bool(nav_low_ma60_vol_mask(df).iloc[-1]) is True
    assert bool(nav_low_ma60_lower_mask(df).iloc[-1]) is True
    assert bool(nav_low_ma60_upper_mask(df).iloc[-1]) is False
    bad = df.copy()
    bad.loc[bad.index[-1], "close"] = 99.6  # (99.6-98.8)/(100-98.8)=0.667
    bad.loc[bad.index[-1], "open"] = 99.0
    assert bool(nav_low_ma60_vol_mask(bad).iloc[-1]) is True
    assert bool(nav_low_ma60_lower_mask(bad).iloc[-1]) is False


def test_score_includes_filter_tag_when_ma60_lower_ok():
    """本輪候選 ma60_lower 過 → TAG_FILTER 記一筆。"""
    df = _ohlc_mild_new_low_near_ma60().copy()
    df.loc[df.index[-1], "high"] = 100.0
    df.loc[df.index[-1], "low"] = 98.8
    df.loc[df.index[-1], "close"] = 99.1
    df.loc[df.index[-1], "open"] = 99.5
    full = _with_fwd(df, close=100.0)
    rows = score_stock_day(full, as_of="20260917")
    tags = {r["tag"] for r in rows}
    assert TAG_LOW in tags
    assert TAG_PREV in tags
    assert TAG_FILTER in tags
    assert TAG_FILTER == "nav_low_first_ma60_lower"
    h5 = [r for r in rows if r["tag"] == TAG_FILTER and r["horizon"] == 5][0]
    assert h5["false_break"] == 0
    assert h5["verdict"] == "hit"


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
    assert st.get("false_break_ok") is False
    assert st.get("beats_prev") is False
    assert "no_arrow" in st
    assert "filtered" in st
    assert "prev_filter" in st
    assert st.get("filter_tag") == TAG_FILTER
    assert st.get("prev_tag") == TAG_PREV
    assert st.get("hold_tag") == TAG_HOLD
    assert promote_ready(db) is False
    assert st.get("product_entry") is True
    assert st.get("entry_bucket") == "ma60_lower"
    assert "不是買訊" in st["note"]
    assert "已升成買訊" in st["note"] or "ma60_lower" in st["note"]
    assert st["min_distinct_sids"] >= 100
    assert st["min_unique_days"] >= 20
    assert st.get("next_candidate") == NEXT_CANDIDATE
    assert NEXT_CANDIDATE == "nav_low_first_ma60_lower_tight"
    assert ROUND_STOPPED is False
    assert st.get("round_stopped") is False
    assert TAG_FILTER == "nav_low_first_ma60_lower"
    assert st.get("min_fb_drop", 0) > 0
    assert st.get("min_fb_drop_vs_prev", 0) > 0


def test_ai_trader_promotes_ma60_lower_entry(tmp_path):
    """使用者已確認：ma60_lower 進場；未確認紅箭頭仍不是買訊。"""
    from ai_trader import current_ai_encoding, format_evolve_report_html
    from red_arrow_quant import ENTRY_BUCKET, PRODUCT_ENTRY
    from wayne_db import ensure_core_schema

    assert PRODUCT_ENTRY is True
    assert ENTRY_BUCKET == "ma60_lower"
    path = str(tmp_path / "e.db")
    ensure_core_schema(path)
    enc = current_ai_encoding(path, "ai_1")
    assert enc["entry"] == "leave_zero+ma60_lower"
    assert enc["not_entry"] == "red_arrow_unconfirmed"
    html = format_evolve_report_html(path, "ai_1")
    assert "未確認紅箭頭不是買訊" in html
    assert "ma60_lower" in html


def test_nav_legend_marks_red_arrow_proxy_confirmed_entry():
    """話筒圖例：低點箭頭不再標未過關；買點藍▲含 ma60_lower 確認。"""
    import inspect

    from wayne_navigator import _draw_nav_legend, _nav_trade_marks

    src = inspect.getsource(_draw_nav_legend)
    assert "紅箭頭代理·未過關" not in src
    assert "20低（紅箭頭代理）" in src
    assert "買點↑首清楚／續淡" in src or "買點↑藍▲紅框" in src
    marks_src = inspect.getsource(_nav_trade_marks)
    assert "paint_buy_entry_indices" in marks_src


def test_paint_buy_entry_includes_ma60_lower_not_raw_low():
    """藍▲進場：ma60_lower 過確認可進；僅首觸未確認不進。"""
    from buy_exclude import paint_buy_entry_indices, paint_ma60_lower_indices
    from red_arrow_quant import PRODUCT_ENTRY, nav_low_arrow_first_mask

    assert PRODUCT_ENTRY is True
    ok = _ohlc_mild_new_low_near_ma60().copy()
    ok.loc[ok.index[-1], "high"] = 100.0
    ok.loc[ok.index[-1], "low"] = 98.8
    ok.loc[ok.index[-1], "close"] = 99.1
    ok.loc[ok.index[-1], "open"] = 99.5
    assert bool(nav_low_ma60_lower_mask(ok).iloc[-1]) is True
    assert (len(ok) - 1) in paint_ma60_lower_indices(ok)
    assert (len(ok) - 1) in paint_buy_entry_indices(ok)

    raw = _ohlc_flat_then_new_low()
    assert bool(nav_low_arrow_first_mask(raw).iloc[-1]) is True
    assert bool(nav_low_ma60_lower_mask(raw).iloc[-1]) is False
    assert paint_ma60_lower_indices(raw) == []
