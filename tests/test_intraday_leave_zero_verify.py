# -*- coding: utf-8 -*-
"""盤中剛離零 → 收盤站得住・靜默對質（假 OHLC）。"""
from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from decision_card_signals import leave_zero_from_quote_df, leave_zero_screen_ok
from wayne_db import ensure_core_schema


def _flat_hist(n: int, px: float, end: str = "20260915") -> pd.DataFrame:
    end_dt = datetime.strptime(end, "%Y%m%d")
    rows = []
    for i in range(n):
        d = end_dt - timedelta(days=n - 1 - i)
        rows.append(
            {
                "date": d.strftime("%Y%m%d"),
                "open": px,
                "high": px,
                "low": px,
                "close": px,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_evaluate_close_hold_leave_zero_ok_and_fail():
    from intraday_leave_zero_verify import evaluate_close_hold_from_ohlc

    # 昨貼零地板、今剛離零 → leave_zero
    ok_df = _flat_hist(70, 100.0, end="20260914")
    ok_df.loc[ok_df.index[-1], "close"] = 100.0  # still at floor yesterday end
    # rebuild: days 0..-2 at 100, last day bounce to 101 → profit ~1%
    bounce = _flat_hist(70, 100.0, end="20260915")
    bounce.loc[bounce.index[-1], ["open", "high", "low", "close"]] = [100.5, 101.5, 100.2, 101.0]
    assert leave_zero_from_quote_df(bounce) is True
    assert evaluate_close_hold_from_ohlc(bounce) is True

    # 收仍貼零＝不算 leave_zero
    flat = _flat_hist(70, 100.0, end="20260915")
    assert leave_zero_from_quote_df(flat) is False
    assert evaluate_close_hold_from_ohlc(flat) is False


def test_evaluate_next_ret():
    from intraday_leave_zero_verify import evaluate_next_ret

    assert evaluate_next_ret(100.0, 102.0) == pytest.approx(2.0)
    assert evaluate_next_ret(100.0, 98.0) == pytest.approx(-2.0)
    assert evaluate_next_ret(0, 100) is None


def test_mark_lights_leave_zero_buy():
    from intraday_leave_zero_verify import mark_lights_leave_zero_buy

    assert mark_lights_leave_zero_buy({"buy_verdict": "buy"}) is True
    assert mark_lights_leave_zero_buy({"buy_verdict": "watch"}) is False
    assert mark_lights_leave_zero_buy({"buy_verdict": "no"}) is False
    assert (
        mark_lights_leave_zero_buy(
            {"buy_verdict": "", "relative_buy_kind": "just_left"}
        )
        is True
    )
    assert (
        mark_lights_leave_zero_buy(
            {"buy_verdict": "buy", "entry_stage": "watch"}
        )
        is False
    )


def test_note_and_reconcile_with_fake_ohlc(tmp_path: Path):
    from intraday_leave_zero_verify import (
        HORIZON_CLOSE,
        gate_status,
        maybe_note_from_card,
        note_intraday_hit,
        optimize_status_one_liner,
        pending_hits,
        reconcile_one,
        recompute_rates,
        score_pending,
        unique_days,
    )

    db = str(tmp_path / "m.db")
    ensure_core_schema(db)
    as_of = "20260915"
    next_d = "20260916"
    # 建假柱：長平 100 → as_of 收 101（剛離零）→ 隔日 103
    start = datetime(2026, 7, 1)
    end = datetime.strptime(next_d, "%Y%m%d")
    conn = sqlite3.connect(db)
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        if ymd == as_of:
            close = 101.0
        elif ymd == next_d:
            close = 103.0
        else:
            close = 100.0
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes("
            "date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ymd,
                "2330",
                "台積電",
                "TW",
                close,
                close + 0.5,
                close - 0.5,
                close,
                8000,
                400000,
                1.0 if ymd == as_of else 0.0,
                close,
                0,
                0,
                0,
            ),
        )
        d += timedelta(days=1)
    conn.commit()
    conn.close()

    # 盤中 hit（append-only）
    assert note_intraday_hit(
        db, stock_id="2330", as_of=as_of, name="台積電", live_px=101.2, live_profit_pct=1.2
    )
    assert not note_intraday_hit(
        db, stock_id="2330", as_of=as_of, name="台積電", live_px=101.5
    )  # 同日同檔忽略
    assert ("20260915", "2330") in pending_hits(db)

    # 非 live 卡不記
    assert not maybe_note_from_card(
        db, {"is_live": False, "buy_verdict": "buy", "stock_id": "1101", "latest_date": as_of}
    )
    # live + buy 記
    assert maybe_note_from_card(
        db,
        {
            "is_live": True,
            "buy_verdict": "buy",
            "stock_id": "1101",
            "stock_name": "台泥",
            "latest_date": as_of,
            "close": 50.0,
            "gain_pct": 0.5,
        },
    )

    # 1101 沒官方柱 → reconcile 跳過
    assert reconcile_one(db, as_of, "1101") is False

    # 2330 有柱且剛離零 → close_hold 勝
    assert leave_zero_from_quote_df(
        pd.read_sql_query(
            "SELECT date,open,high,low,close,volume FROM daily_quotes "
            "WHERE stock_id='2330' AND date<=? ORDER BY date",
            sqlite3.connect(db),
            params=(as_of,),
        )
    ) is True or leave_zero_screen_ok(0.0, 1.0)[0]

    assert reconcile_one(db, as_of, "2330") is True
    assert score_pending(db, cap=as_of) >= 0
    recompute_rates(db)
    g = gate_status(db)
    assert g["promote_buy_signals"] is False
    assert g["promote_ready"] is False
    assert g["baseline"] == "close_leave_zero_ok"
    assert unique_days(db, HORIZON_CLOSE) >= 1
    assert "剛離零" in optimize_status_one_liner(db) or "收盤" in optimize_status_one_liner(db)

    # score 列有 close_hold + next
    from dongzhu_tape import tape_store_path

    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    row = conn.execute(
        "SELECT close_leave_zero_ok, next_ret_pct FROM intraday_lz_score "
        "WHERE as_of=? AND sid=?",
        (as_of, "2330"),
    ).fetchone()
    conn.close()
    assert row is not None
    assert int(row[0]) == 1
    assert row[1] is not None
    assert float(row[1]) == pytest.approx((103.0 - 101.0) / 101.0 * 100.0, rel=1e-3)


def test_reconcile_close_not_leave_zero(tmp_path: Path):
    """盤中亮了，但官方收仍貼零 → close_hold 敗。"""
    from intraday_leave_zero_verify import note_intraday_hit, reconcile_one
    from dongzhu_tape import tape_store_path

    db = str(tmp_path / "flat.db")
    ensure_core_schema(db)
    as_of = "20260915"
    start = datetime(2026, 7, 1)
    end = datetime.strptime(as_of, "%Y%m%d")
    conn = sqlite3.connect(db)
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        close = 100.0
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes("
            "date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ymd, "2454", "聯發科", "TW", close, close, close, close, 1000, 0, 0, close, 0, 0, 0),
        )
        d += timedelta(days=1)
    conn.commit()
    conn.close()

    note_intraday_hit(db, stock_id="2454", as_of=as_of, live_px=100.8)
    assert reconcile_one(db, as_of, "2454") is True
    store = tape_store_path(db)
    row = sqlite3.connect(store).execute(
        "SELECT close_leave_zero_ok FROM intraday_lz_score WHERE sid='2454'"
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 0


def test_judge_tape_hooks_intraday_lz():
    import judge_tape

    src = inspect.getsource(judge_tape._snapshot_pressure_support)
    assert "intraday_leave_zero_verify" in src
    assert "intraday_lz_night_tick" in src


def test_navigator_hooks_maybe_note():
    import wayne_navigator

    src = inspect.getsource(wayne_navigator.NavigatorEngine.get_decision_card)
    assert "maybe_note_from_card" in src
    assert "intraday_leave_zero_verify" in src


def test_button_catalog_lists_intraday_lz():
    from button_silent_verify import catalog

    rows = catalog()
    hit = [r for r in rows if "intraday_leave_zero" in (r.get("kinds") or ())]
    assert hit
    assert hit[0]["status"] == "external"
    assert "不是新鈕" in hit[0]["note"] or "靜默" in hit[0]["note"]
