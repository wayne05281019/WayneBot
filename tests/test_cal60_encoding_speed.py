# -*- coding: utf-8 -*-
"""60 曆日獲利編碼：向量化結果必須等於舊逐列公式。"""
from __future__ import annotations

import pandas as pd
import pytest

from decision_card_signals import (
    cal60_low_close_at,
    profit_pct_cal60_series,
    profit_pct_series,
)


def _legacy_cal60_low(df, idx: int, close_col: str = "close") -> float:
    dts = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    if len(dts) == 0 or not dts.notna().any():
        return float(df[close_col].iloc[idx] or 0)
    end = dts.iloc[idx]
    mask = (dts >= (end - pd.Timedelta(days=60))) & (dts <= end) & dts.notna()
    if not mask.any():
        return float(df[close_col].iloc[idx] or 0)
    lo = float(df.loc[mask, close_col].astype(float).min())
    return lo if lo > 0 else float(df[close_col].iloc[idx] or 0)


def _legacy_profit_series(df, close_col: str = "close") -> pd.Series:
    closes = df[close_col].astype(float)
    out = []
    for i in range(len(df)):
        c = float(closes.iloc[i])
        floor = _legacy_cal60_low(df, i, close_col)
        if floor <= 0:
            floor = c or 1.0
        out.append(round((c - floor) / floor * 100.0, 1))
    return pd.Series(out, index=df.index)


def test_cal60_vectorized_matches_legacy_synthetic():
    df = pd.DataFrame(
        {
            "date": ["20260102", "20260115", "20260220", "20260310", "20260401"],
            "close": [10.0, 8.0, 12.0, 9.0, 11.0],
        }
    )
    got = profit_pct_cal60_series(df)
    want = _legacy_profit_series(df)
    pd.testing.assert_series_equal(got, want, check_names=False)
    assert cal60_low_close_at(df, -1) == pytest.approx(_legacy_cal60_low(df, -1))


@pytest.mark.production_db
def test_cal60_vectorized_matches_legacy_on_live_names():
    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    eng = NavigatorEngine(get_db_path())
    for sid in ("2383", "3037", "9925", "2633", "3115"):
        card = eng.get_decision_card(sid, merge_live=False)
        assert not card.get("error"), card.get("error")
        tbl = card["table"]
        src = tbl[["date", "close"]].copy()
        src["date"] = src["date"].astype(str).str.replace("-", "", regex=False)
        got = profit_pct_cal60_series(src)
        want = _legacy_profit_series(src)
        pd.testing.assert_series_equal(got.reset_index(drop=True), want.reset_index(drop=True))
        # 內部 max(cal60, l20) 路徑也只算一次陣列，語意仍對齊逐列
        got_floor = profit_pct_series(src)
        want_floor = []
        closes = src["close"].astype(float)
        l20 = closes.rolling(20, min_periods=1).min()
        for i in range(len(src)):
            c = float(closes.iloc[i])
            cal = _legacy_cal60_low(src, i)
            lo = float(l20.iloc[i] or 0)
            floor = cal if lo <= 0 else max(cal, lo)
            if floor <= 0:
                floor = c or 1.0
            want_floor.append(round((c - floor) / floor * 100.0, 1))
        pd.testing.assert_series_equal(
            got_floor.reset_index(drop=True),
            pd.Series(want_floor),
        )
