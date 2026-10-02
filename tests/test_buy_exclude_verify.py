# -*- coding: utf-8 -*-
"""買點排除靜默對質：可排程／可落檔／閘門。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pandas as pd

from buy_exclude_verify import (
    CLOSE_CAP,
    KIND,
    TAG_RAW,
    TAG_V2,
    TAG_V3_CLOSE_UP,
    TAG_V3_RANGE,
    TAGS,
    _v3_close_up,
    _v3_range_upper,
    gate_status,
    night_tick,
    optimize_status_one_liner,
    persist_tape,
    price_tier,
    recompute_rates,
    score_pending,
    tags_for_frame,
)


def _df(closes, opens=None, highs=None, lows=None, volumes=None):
    n = len(closes)
    opens = opens or list(closes)
    highs = highs or [c + 1 for c in closes]
    lows = lows or [c - 1 for c in closes]
    volumes = volumes or [1000.0] * n
    dates = [f"202601{i+1:02d}" for i in range(n)]
    return pd.DataFrame(
        {
            "stock_id": ["9999"] * n,
            "stock_name": ["測"] * n,
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def test_price_tier_and_close_cap():
    assert price_tier(8) == "penny"
    assert price_tier(30) == "low"
    assert price_tier(120) == "mid"
    assert price_tier(800) == "high"
    assert price_tier(3000) == "xhigh"
    assert price_tier(12000) == "ultra"
    assert CLOSE_CAP == 20000.0


def test_v3_helpers():
    df = _df([10, 11, 12], opens=[10, 11, 11], highs=[11, 12, 13], lows=[9, 10, 11])
    assert _v3_close_up(df) is True
    assert _v3_range_upper(df) is True
    df2 = _df([10, 11, 10.5], opens=[10, 11, 11], highs=[11, 12, 12], lows=[9, 10, 10])
    assert _v3_close_up(df2) is False
    # 收在振幅下半
    assert _v3_range_upper(df2) is False


def test_tags_skip_over_cap():
    closes = [100.0] * 70 + [25000.0]
    df = _df(closes)
    assert tags_for_frame(df) == []


def test_persist_score_gate_empty():
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        conn = sqlite3.connect(market)
        conn.execute(
            "CREATE TABLE daily_quotes("
            "stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,"
            "close REAL, volume REAL)"
        )
        conn.commit()
        conn.close()
        g = gate_status(market)
        assert g["kind"] == KIND
        assert g["promote_golden_buy"] is False
        assert g["promote_paint"] is False
        line = optimize_status_one_liner(market)
        assert "買點排除" in line
        assert "n=" in line


def test_score_pending_hit_miss():
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        conn = sqlite3.connect(market)
        conn.execute(
            "CREATE TABLE daily_quotes("
            "stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,"
            "close REAL, volume REAL)"
        )
        # as_of 20260102 entry 100；+1=101 hit；+5 缺 → pending for h5
        rows = [
            ("A", "20260102", 100, 101, 99, 100, 1000),
            ("A", "20260103", 100, 102, 99, 101, 1000),
        ]
        conn.executemany(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?)", rows
        )
        conn.commit()
        conn.close()
        persist_tape(
            market,
            [
                {
                    "as_of": "20260102",
                    "sid": "A",
                    "tag": TAG_V2,
                    "name": "A",
                    "close": 100.0,
                    "tier": "mid",
                    "emerging": False,
                }
            ],
        )
        n = score_pending(market)
        assert n >= 3  # 3 horizons
        rates = recompute_rates(market)
        key = f"{TAG_V2}:h1"
        assert key in rates
        assert rates[key]["hit"] == 1


def test_night_tick_swallows_bad_path():
    out = night_tick("/no/such/path.db", as_of="20260102")
    assert "wrote" in out
    assert out.get("tags") == list(TAGS) or out.get("gate") == {}


def test_judge_tape_hooks_buy_exclude_night():
    import inspect
    import judge_tape as jt

    src = inspect.getsource(jt._snapshot_pressure_support)
    assert "buy_exclude_verify" in src
    assert "buy_exclude_night_tick" in src


def test_catalog_has_buy_exclude():
    from button_silent_verify import BUTTON_CATALOG

    kinds = []
    for row in BUTTON_CATALOG:
        kinds.extend(row.get("kinds") or ())
    assert "buy_exclude" in kinds


def test_tag_constants_cover_v3():
    assert TAG_RAW in TAGS and TAG_V2 in TAGS
    assert TAG_V3_CLOSE_UP in TAGS and TAG_V3_RANGE in TAGS
