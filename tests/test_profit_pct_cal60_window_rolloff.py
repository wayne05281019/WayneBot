# -*- coding: utf-8 -*-
"""獲利％＝近 60 曆日收盤低；連假後舊低滾出窗外會斷崖，不准當 bug 去「修」。

真實案例（官方收，2026-09）：
- 2383：9/24 收 5050／獲利 23.2%（地板 7/29＝4100）
         → 9/29 收 4920／獲利 4.8%（地板改 9/17＝4695）
- 3017：9/24 收 3555／69.7%（地板 7/29＝2095）
         → 9/29 收 3400／46.6%（地板 7/31＝2320）

9/25 中秋、9/26–27 週末、9/28 教師節 → 表上列跳 9/24→9/29 是正確交易日行為。
2383 的 4.8% 剛好等於貼 20 日低（4695），但 3017 的 46.6% ≠ (3400−3115)/3115≈9.1%，
可證獲利欄仍走 cal60，不是誤用 10／20 低。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from decision_card_signals import (
    cal60_low_close_at,
    cal60_profit_bundle,
    format_profit_pct,
    profit_pct_cal60_series,
)
from tw_holidays import lookup_tw_session


def test_2383_acceptance_formula_still_29_1():
    """永久驗收：收 5295／低 4100 → 29.1%（公式鎖，與近窗滾動無關）。"""
    pct = (5295.0 - 4100.0) / 4100.0 * 100.0
    assert abs(pct - 29.1) < 0.05
    assert format_profit_pct(pct) == "29.1%"


def test_mid_autumn_2026_gap_is_trading_calendar_not_missing_rows():
    assert lookup_tw_session("20260924")["kind"] == "open"
    assert lookup_tw_session("20260925")["kind"] == "full_close"  # 中秋
    assert lookup_tw_session("20260926")["kind"] == "weekend"
    assert lookup_tw_session("20260927")["kind"] == "weekend"
    assert lookup_tw_session("20260928")["kind"] == "full_close"  # 教師節
    assert lookup_tw_session("20260929")["kind"] == "open"


def _win_start(ymd: str) -> str:
    return (datetime.strptime(ymd, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")


def test_jul29_low_still_inside_window_on_sep24_out_by_sep29():
    """7/29 低：9/24 窗起 7/26 仍含；9/29 窗起 7/31 已滾出。"""
    assert _win_start("20260924") == "20260726"
    assert "20260729" >= "20260726"
    assert _win_start("20260929") == "20260731"
    assert "20260729" < "20260731"


def test_synthetic_rolloff_matches_observed_cliffs():
    """關鍵官方收＋9/29：斷崖必須等於話筒；3017 可證不是誤用 20 日低。"""
    # 2383：7/29=4100 滾出後，窗內真實次低是 9/17=4695（不要塞假低價污染窗）
    rows_2383 = [
        ("20260729", 4100.0),
        ("20260731", 4800.0),
        ("20260917", 4695.0),
        ("20260924", 5050.0),
        ("20260929", 4920.0),
    ]
    df = pd.DataFrame(rows_2383, columns=["date", "close"])
    floors, pct = cal60_profit_bundle(df)
    i24 = df.index[df["date"] == "20260924"][0]
    i29 = df.index[df["date"] == "20260929"][0]
    assert floors[i24] == 4100.0
    assert float(pct.iloc[i24]) == 23.2
    assert floors[i29] == 4695.0
    assert float(pct.iloc[i29]) == 4.8
    # 巧合：4.8% == (4920−4695)/4695，但地板來源是 cal60 不是 max(cal60,l20)
    assert abs((4920.0 - 4695.0) / 4695.0 * 100.0 - 4.8) < 0.05

    rows_3017 = [
        ("20260729", 2095.0),
        ("20260731", 2320.0),
        ("20260917", 3115.0),
        ("20260924", 3555.0),
        ("20260929", 3400.0),
    ]
    df2 = pd.DataFrame(rows_3017, columns=["date", "close"])
    floors2, pct2 = cal60_profit_bundle(df2)
    j24 = df2.index[df2["date"] == "20260924"][0]
    j29 = df2.index[df2["date"] == "20260929"][0]
    assert floors2[j24] == 2095.0
    assert float(pct2.iloc[j24]) == 69.7
    assert floors2[j29] == 2320.0
    assert float(pct2.iloc[j29]) == 46.6
    # 若誤用 20 日低 3115，會得到 ~9.1%，不是 46.6%
    fake_l20 = round((3400.0 - 3115.0) / 3115.0 * 100.0, 1)
    assert fake_l20 == 9.1
    assert abs(float(pct2.iloc[j29]) - fake_l20) > 30.0


@pytest.mark.production_db
def test_card_2383_3017_sep24_and_sep29_rolloff():
    """庫內柱＋官方 9/29 收：決策卡獲利須對上觀察值；表列跳過連假。"""
    import sqlite3

    from config import get_db_path
    from wayne_navigator import NavigatorEngine

    db = get_db_path()
    conn = sqlite3.connect(db)
    n = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE stock_id='2383' AND date='20260924'"
    ).fetchone()[0]
    if not n:
        conn.close()
        pytest.skip("no 2383 20260924")

    # 9/29 可能尚未進本機庫：用記憶體表擴充再走同一條 cal60（卡內同一函式）
    def _frame(sid: str, as_of: str, close_override: float | None = None) -> pd.DataFrame:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM daily_quotes "
            "WHERE stock_id=? AND date<=? ORDER BY date",
            conn,
            params=(sid, as_of if close_override is None else "20260924"),
        )
        if close_override is not None and (df.empty or str(df["date"].iloc[-1]) < as_of):
            last = df.iloc[-1].to_dict()
            last.update(
                {
                    "date": as_of,
                    "open": close_override,
                    "high": close_override,
                    "low": close_override,
                    "close": close_override,
                }
            )
            df = pd.concat([df, pd.DataFrame([last])], ignore_index=True)
        return df

    f24 = _frame("2383", "20260924")
    f29 = _frame("2383", "20260929", 4920.0)
    assert float(cal60_low_close_at(f24)) == 4100.0
    assert float(profit_pct_cal60_series(f24).iloc[-1]) == 23.2
    assert float(cal60_low_close_at(f29)) == 4695.0
    assert float(profit_pct_cal60_series(f29).iloc[-1]) == 4.8

    g24 = _frame("3017", "20260924")
    g29 = _frame("3017", "20260929", 3400.0)
    assert float(cal60_low_close_at(g24)) == 2095.0
    assert float(profit_pct_cal60_series(g24).iloc[-1]) == 69.7
    assert float(cal60_low_close_at(g29)) == 2320.0
    assert float(profit_pct_cal60_series(g29).iloc[-1]) == 46.6

    nav = NavigatorEngine(db)
    c24 = nav.get_decision_card("2383", as_of="20260924", merge_live=False)
    assert float(c24["gain_pct"]) == 23.2
    assert float(c24["cal60_low"]) == 4100.0
    dates = [str(x) for x in c24["table"]["date"].tolist()[:2]]
    # 9/24 卡頂兩列應是連續交易日，不是跳到 9/29
    assert dates[0] == "20260924"
    assert dates[1] == "20260923"

    # 若庫已有 9/29，卡上表必須 9/24→9/29（中間休市無列）
    n29 = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE stock_id='2383' AND date='20260929'"
    ).fetchone()[0]
    conn.close()
    if n29:
        c29 = nav.get_decision_card("2383", as_of="20260929", merge_live=False)
        assert float(c29["close"]) == 4920.0
        assert float(c29["gain_pct"]) == 4.8
        assert float(c29["cal60_low"]) == 4695.0
        top = [str(x) for x in c29["table"]["date"].tolist()[:2]]
        assert top == ["20260929", "20260924"]
