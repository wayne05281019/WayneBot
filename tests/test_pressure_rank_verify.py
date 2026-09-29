# -*- coding: utf-8 -*-
"""壓撐排序靜默對質：第一次優化鍵 vs 現況；飆大真測真落。"""
from __future__ import annotations

import sqlite3

from pressure_rank_verify import (
    FORWARD_H,
    SECOND_MAX_ROWS,
    TRACK_VARIANTS,
    VARIANT_BIAOKE_SILENT,
    VARIANT_CURRENT,
    VARIANT_FIRST,
    VARIANT_SECOND,
    biaoke_hard_cut,
    ensure_tables,
    gate_status,
    optimize_status_one_liner,
    outcome_win,
    persist_ranked,
    phone_uses_first,
    phone_uses_second,
    rank_key_first,
    rank_key_second,
    rank_pool,
    recompute_rates,
    score_pending,
    unique_days,
)
from pressure_support_watch import (
    TAG_SIDEWAYS,
    TAG_STAND_SUPPORT,
    TAG_TEST_PRESS,
    rank_key_current,
)


def _row(**kw):
    base = {
        "stock_id": "2330",
        "close": 100.0,
        "pressure": 105.0,
        "support": 90.0,
        "vol_ratio": 0.5,
        "dist_to_press_pct": 1.0,
    }
    base.update(kw)
    return base


def test_first_rank_sideways_thin_before_dist():
    a = _row(stock_id="A", vol_ratio=0.2, dist_to_press_pct=0.4)  # thin
    b = _row(stock_id="B", vol_ratio=0.8, dist_to_press_pct=0.1)  # not thin, closer
    ranked = rank_pool([b, a], TAG_SIDEWAYS, VARIANT_FIRST)
    assert [r["stock_id"] for r in ranked[:2]] == ["A", "B"]


def test_first_rank_test_press_dist_before_thin():
    a = _row(stock_id="A", vol_ratio=0.8, dist_to_press_pct=0.1)
    b = _row(stock_id="B", vol_ratio=0.2, dist_to_press_pct=0.4)
    ranked = rank_pool([b, a], TAG_TEST_PRESS, VARIANT_FIRST)
    assert [r["stock_id"] for r in ranked[:2]] == ["A", "B"]


def test_first_rank_stand_in_band_then_moderate_dist():
    # in band + dist≈2 應優於出帶或太貼壓
    good = _row(
        stock_id="G",
        close=103.0,
        pressure=105.0,
        support=90.0,
        dist_to_press_pct=1.9,
        vol_ratio=0.4,
    )
    too_close = _row(
        stock_id="C",
        close=104.8,
        pressure=105.0,
        support=90.0,
        dist_to_press_pct=0.2,
        vol_ratio=0.4,
    )
    out_band = _row(
        stock_id="O",
        close=106.0,
        pressure=105.0,
        support=90.0,
        dist_to_press_pct=-0.95,
        vol_ratio=0.3,
    )
    ranked = rank_pool([out_band, too_close, good], TAG_STAND_SUPPORT, VARIANT_FIRST)
    assert ranked[0]["stock_id"] == "G"
    assert ranked[-1]["stock_id"] == "O"


def test_current_unchanged_key_order():
    # 現況：離壓近優先（與第一次橫盤「量縮優先」不同）
    a = _row(stock_id="A", vol_thin_bonus=True, dist_to_press_pct=0.4)
    b = _row(stock_id="B", vol_thin_bonus=False, dist_to_press_pct=0.1)
    assert rank_key_current(b) < rank_key_current(a)
    assert rank_key_first(TAG_SIDEWAYS, a) < rank_key_first(TAG_SIDEWAYS, b)


def test_biaoke_silent_cuts_and_caps():
    dump = _row(stock_id="D", dump_pause=True, vol_ratio=0.2, dist_to_press_pct=0.1)
    ok = [
        _row(stock_id=str(i), vol_ratio=0.2, dist_to_press_pct=0.1 + i * 0.01)
        for i in range(10)
    ]
    ranked = rank_pool([dump] + ok, TAG_TEST_PRESS, VARIANT_BIAOKE_SILENT)
    assert all(r["stock_id"] != "D" for r in ranked)
    assert len(ranked) <= 8
    assert biaoke_hard_cut(dump, TAG_TEST_PRESS) is True


def test_outcome_win_defs():
    bars = [
        {"close": 106, "high": 107, "low": 105},
        {"close": 107, "high": 108, "low": 106},
        {"close": 108, "high": 109, "low": 107},
        {"close": 109, "high": 110, "low": 108},
        {"close": 110, "high": 111, "low": 109},
    ]
    side = outcome_win(
        TAG_SIDEWAYS, pressure=105, support=90, entry=100, bars=bars
    )
    assert side["stand_press"] == 1 and side["win"] == 1
    hold = outcome_win(
        TAG_TEST_PRESS, pressure=105, support=90, entry=100, bars=bars
    )
    assert hold["hold_support"] == 1 and hold["win"] == 1
    broke_bars = list(bars)
    broke_bars[2] = {"close": 80, "high": 90, "low": 79}
    bad = outcome_win(
        TAG_STAND_SUPPORT, pressure=105, support=90, entry=100, bars=broke_bars
    )
    assert bad["broke_support"] == 1 and bad["win"] == 0


def test_second_rank_caps_and_prefers_quality():
    weak = _row(stock_id="W", vol_ratio=0.2, dist_to_press_pct=0.1, weak_k=True)
    strong = _row(
        stock_id="S",
        vol_ratio=0.2,
        dist_to_press_pct=0.1,
        wash=True,
        vol_asphyx=True,
    )
    ranked = rank_pool([weak, strong], TAG_SIDEWAYS, VARIANT_SECOND)
    assert ranked[0]["stock_id"] == "S"
    assert len(ranked) <= SECOND_MAX_ROWS
    assert rank_key_second(TAG_SIDEWAYS, strong) < rank_key_second(TAG_SIDEWAYS, weak)


def test_gate_biaoke_never_promote_without_first(tmp_path):
    db = str(tmp_path / "m.db")
    # empty evolve → n=0
    g = gate_status(db)
    assert g["n_ok"] is False
    assert g["biaoke_silent_only"] is True
    assert g["biaoke_promote_ready"] is False
    assert g["squeeze_candidate"] is True
    assert g["second_promote_ready"] is False
    assert g["promote_ready"] is False
    assert list(g["tracks"]) == list(TRACK_VARIANTS)
    assert VARIANT_SECOND in g["tracks"]
    assert phone_uses_first(db) is False
    assert phone_uses_second(db) is False
    line = optimize_status_one_liner(db)
    assert "尚未改碼" in line or "繼續收集" in line
    assert VARIANT_CURRENT and VARIANT_FIRST


def test_three_tracks_persist_score_and_biaoke_n(tmp_path):
    """四軌同池落檔＋同窗打分；飆大有獨立 n，永不 promote。"""
    market = str(tmp_path / "wayne_market.db")
    conn = sqlite3.connect(market)
    # as_of 20260102 + 5 交易日
    days = [
        "20260102",
        "20260103",
        "20260106",
        "20260107",
        "20260108",
        "20260109",
        "20260110",
    ]
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)"
    )
    for d in days:
        # 收一路站上壓 105 → 橫盤 win；守撐
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?)",
            ("2330", d, 100, 110, 99, 106 if d > "20260102" else 100, 1000),
        )
    conn.commit()
    conn.close()

    pool = [
        _row(
            stock_id="2330",
            close=100.0,
            pressure=105.0,
            support=90.0,
            vol_ratio=0.2,
            dist_to_press_pct=0.4,
            wash=True,
            vol_asphyx=True,
        ),
        _row(
            stock_id="2317",
            close=100.0,
            pressure=105.0,
            support=90.0,
            vol_ratio=0.9,
            dist_to_press_pct=0.2,
            dump_pause=True,
        ),
    ]
    as_of = "20260102"
    for tag in (TAG_SIDEWAYS, TAG_TEST_PRESS, TAG_STAND_SUPPORT):
        for variant in TRACK_VARIANTS:
            ranked = rank_pool(pool, tag, variant)
            assert persist_ranked(market, as_of, tag, variant, ranked) >= 1
            if variant == VARIANT_BIAOKE_SILENT:
                assert all(r["stock_id"] != "2317" for r in ranked)

    filled = score_pending(market, cap="20260110")
    assert filled > 0
    recompute_rates(market)
    assert unique_days(market, VARIANT_CURRENT) >= 1
    assert unique_days(market, VARIANT_FIRST) >= 1
    assert unique_days(market, VARIANT_SECOND) >= 1
    assert unique_days(market, VARIANT_BIAOKE_SILENT) >= 1
    g = gate_status(market)
    assert g["biaoke_n_days"] >= 1
    assert g["biaoke_promote_ready"] is False
    assert g["second_n_days"] >= 1
    assert g["second_promote_ready"] is False
    # n 不夠 20 → 不改話筒
    assert g["promote_ready"] is False
    assert phone_uses_first(market) is False
    assert phone_uses_second(market) is False
    store = ensure_tables(market)
    c = sqlite3.connect(store)
    variants = {
        r[0]
        for r in c.execute(
            "SELECT DISTINCT variant FROM pressure_rank_score WHERE horizon=?",
            (FORWARD_H,),
        )
    }
    c.close()
    assert variants == set(TRACK_VARIANTS)


def test_phone_switches_only_when_first_promotes(tmp_path, monkeypatch):
    from pressure_support_watch import screen_pressure_support

    db = str(tmp_path / "m.db")
    monkeypatch.setattr(
        "pressure_rank_verify.phone_uses_first", lambda _db: False
    )
    # empty universe → []
    assert screen_pressure_support(db, TAG_TEST_PRESS) == []
    monkeypatch.setattr(
        "pressure_rank_verify.phone_uses_first", lambda _db: True
    )
    # still empty pool, but path must not raise when first is on
    assert screen_pressure_support(db, TAG_TEST_PRESS) == []
