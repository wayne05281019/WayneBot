# -*- coding: utf-8 -*-
"""全系統正確性＋出圖熱路徑：細項 TTL、tpex seed 快取、估值資料日、決策卡短快取。"""
from __future__ import annotations

import inspect
import sqlite3
import time
from datetime import datetime

import pytest

from industry_fine import CACHE_DAYS, clear_fine_industry_ensure_cache, ensure_fine_industry_table
from official_snapshots import ensure_schema, valuation_plain_rows
from tpex_industry_chain import apply_tpex_overlay, clear_tpex_seed_cache, load_tpex_seed
from wayne_navigator import NavigatorEngine


def test_fine_industry_paths_use_week_ttl_not_year():
    assert CACHE_DAYS == 7
    import industry_fine
    import money_flow
    import universe

    assert "max_age_days=365" not in inspect.getsource(money_flow)
    assert "max_age_days=365" not in inspect.getsource(universe)
    assert "max_age_days=365" not in inspect.getsource(industry_fine.chain_peer_ids)


def test_tpex_seed_and_ensure_are_cached(tmp_path):
    clear_tpex_seed_cache()
    clear_fine_industry_ensure_cache()
    a = load_tpex_seed()
    b = load_tpex_seed()
    assert a is b
    assert len(a) > 100

    db = str(tmp_path / "fine.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE stock_universe (
            stock_id TEXT PRIMARY KEY, stock_name TEXT, market_type TEXT,
            asset_type TEXT, industry TEXT, is_active INT, updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO stock_universe VALUES ('2330','台積電','TW','STOCK','電子工業',1,'t')"
    )
    conn.commit()
    conn.close()

    t0 = time.perf_counter()
    ensure_fine_industry_table(db)
    first = time.perf_counter() - t0
    t1 = time.perf_counter()
    for _ in range(20):
        ensure_fine_industry_table(db)
        apply_tpex_overlay(db)
    second = time.perf_counter() - t1
    assert second < 0.05, f"ensure/overlay 重跑應被快取，實際 {second:.3f}s（首跑 {first:.3f}s）"


def test_valuation_plain_rows_marks_lagging_data_day(tmp_path):
    db = str(tmp_path / "val.db")
    ensure_schema(db)
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO daily_valuation(stock_id, date, pe, pb, dividend_yield, source, updated_at) "
        "VALUES ('2330','20260923',28.98,10.08,0.88,'twse_bwibbu',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO daily_margin(stock_id, date, margin_bal, margin_limit, margin_util, "
        "short_bal, short_limit, short_util, source, updated_at) "
        "VALUES ('2330','20260923',28833,1,0.5,18,1,0.01,'twse_margn',?)",
        (now,),
    )
    conn.commit()
    conn.close()
    text = " ".join(f"{a} {b}" for a, b in valuation_plain_rows("2330", db, quote_as_of="20260924"))
    assert "本益 28.98" in text
    assert "資料日 9/23" in text
    assert "融資 28,833張" in text
    same = " ".join(f"{a} {b}" for a, b in valuation_plain_rows("2330", db, quote_as_of="20260923"))
    assert "資料日" not in same


@pytest.mark.production_db
def test_decision_card_memo_hits_same_as_of():
    """同代號＋同 as_of 短窗內重用；呼叫端 pop 不准打壞 memo。"""
    from tests.conftest import require_production_db

    db = require_production_db()
    NavigatorEngine.clear_card_memo()
    eng = NavigatorEngine(db)
    t0 = time.perf_counter()
    a = eng.get_decision_card("2330", lookback=20, merge_live=False, as_of="20260924")
    cold = time.perf_counter() - t0
    assert not a.get("error")
    t1 = time.perf_counter()
    b = eng.get_decision_card("2330", lookback=20, merge_live=False, as_of="20260924")
    warm = time.perf_counter() - t1
    assert b.get("close") == a.get("close")
    assert b.get("gain_pct") == a.get("gain_pct")
    assert warm < 0.05, f"memo 應 <50ms，實際 {warm:.3f}s（cold {cold:.3f}s）"
    b.pop("_ohlc", None)
    c = eng.get_decision_card("2330", lookback=20, merge_live=False, as_of="20260924")
    assert "_ohlc" in c


def test_apply_tpex_overlay_skips_before_seed_reload():
    src = inspect.getsource(apply_tpex_overlay)
    assert src.index("_OVERLAID") < src.index("load_tpex_seed()")


def test_index_volume_read_path_throttle_not_boot_clock(tmp_path, monkeypatch):
    """節流只看『有沒有打過』，不准把 monotonic≈0 當成 10 分內已打。"""
    import taiwan_market as tm

    db = str(tmp_path / "ix.db")
    tm.ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO index_daily(date,symbol,close,volume,pct_change,ma20,ma60,regime,updated_at) "
        "VALUES ('20260924','TWII',48024.6,0.0,-0.28,0,0,'unknown','t')"
    )
    conn.commit()
    conn.close()
    tm._INDEX_VOL_TRY_AT.clear()
    calls = {"n": 0}

    def fake_fill(path):
        calls["n"] += 1
        conn2 = sqlite3.connect(path)
        conn2.execute(
            "UPDATE index_daily SET volume=? WHERE symbol='TWII' AND date='20260924'",
            (8626110.0,),
        )
        conn2.commit()
        conn2.close()
        return 1

    monkeypatch.setattr(tm, "_backfill_zero_index_volumes", fake_fill)
    monkeypatch.setattr(tm.time, "monotonic", lambda: 100.0)  # <600s since epoch-ish
    df = tm.load_index_daily(db, "20260924", db_only=True)
    assert calls["n"] == 1
    assert float(df.iloc[-1]["volume"]) == 8626110.0
    # 同一節流窗內不再打
    monkeypatch.setattr(tm.time, "monotonic", lambda: 200.0)
    df2 = tm.load_index_daily(db, "20260924", db_only=True)
    assert calls["n"] == 1
    assert float(df2.iloc[-1]["volume"]) == 8626110.0
