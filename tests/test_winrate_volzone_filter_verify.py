# -*- coding: utf-8 -*-
"""勝率買點×大量區再篩靜默對質：變體閘／落檔／不過閘不改話筒。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pandas as pd

from winrate_volzone_filter_verify import (
    FILTER_VARIANTS,
    KIND,
    MIN_UNIQUE_DAYS,
    TRACK_VARIANTS,
    VARIANT_COMBO,
    VARIANT_COMBO_TRIPLE,
    VARIANT_COMBO_VZ_SPACE,
    VARIANT_COMBO_VZ_UNTANGLE,
    VARIANT_CURRENT,
    VARIANT_MA60_RISING,
    VARIANT_SPACE_H20,
    VARIANT_UNTANGLE_UP,
    VARIANT_VZ_MID_THIN,
    gate_status,
    hit_map,
    optimize_status_one_liner,
    persist_tape,
    recompute_rates,
    variant_pass,
)


def _feat(**kwargs):
    base = {
        "close": 100.0,
        "zone_pos": 0.4,
        "vol_ratio": 0.3,
        "ma60_rising": True,
        "ma20_rising": True,
        "ma_spread_pct": 5.0,
        "tangled": False,
        "close_ge_ma5": True,
        "dist_h20_pct": 8.0,
        "in_band": True,
        "near_press": False,
    }
    base.update(kwargs)
    return base


def test_variant_pass_rules():
    f = _feat()
    assert variant_pass(f, VARIANT_CURRENT) is True
    assert variant_pass(f, VARIANT_VZ_MID_THIN) is True
    assert variant_pass(f, VARIANT_MA60_RISING) is True
    assert variant_pass(f, VARIANT_SPACE_H20) is True
    assert variant_pass(f, VARIANT_UNTANGLE_UP) is True
    assert variant_pass(f, VARIANT_COMBO) is True
    assert variant_pass(f, VARIANT_COMBO_VZ_UNTANGLE) is True
    assert variant_pass(f, VARIANT_COMBO_VZ_SPACE) is True
    assert variant_pass(f, VARIANT_COMBO_TRIPLE) is True
    # §13 再生臂都在 FILTER_VARIANTS
    assert VARIANT_COMBO_VZ_UNTANGLE in FILTER_VARIANTS
    assert VARIANT_COMBO_VZ_SPACE in FILTER_VARIANTS
    assert VARIANT_COMBO_TRIPLE in FILTER_VARIANTS
    assert VARIANT_CURRENT not in FILTER_VARIANTS
    assert set(FILTER_VARIANTS) | {VARIANT_CURRENT} == set(TRACK_VARIANTS)
    hits = hit_map(f)
    assert hits[VARIANT_COMBO_TRIPLE] is True
    # 貼壓＝大量區中帶不過
    assert variant_pass(_feat(near_press=True), VARIANT_VZ_MID_THIN) is False
    assert variant_pass(_feat(near_press=True), VARIANT_COMBO_TRIPLE) is False
    # 區外
    assert variant_pass(_feat(in_band=False), VARIANT_VZ_MID_THIN) is False
    # 量太大
    assert variant_pass(_feat(vol_ratio=0.9), VARIANT_VZ_MID_THIN) is False
    # 季線不升
    assert variant_pass(_feat(ma60_rising=False), VARIANT_MA60_RISING) is False
    assert variant_pass(_feat(ma60_rising=False), VARIANT_COMBO_TRIPLE) is False
    # 距 20 高太近
    assert variant_pass(_feat(dist_h20_pct=3.0), VARIANT_SPACE_H20) is False
    assert variant_pass(_feat(dist_h20_pct=3.0), VARIANT_COMBO_VZ_SPACE) is False
    # 仍糾結
    assert variant_pass(_feat(ma_spread_pct=1.0), VARIANT_UNTANGLE_UP) is False
    assert variant_pass(_feat(ma_spread_pct=1.0), VARIANT_COMBO_VZ_UNTANGLE) is False
    # 缺真數不准假過
    assert variant_pass(_feat(zone_pos=None), VARIANT_VZ_MID_THIN) is False


def test_persist_tape_stores_ohlcv_and_hit():
    """母體列要凍官方開高低收＋量；current 列附 hit 命中。"""
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        open(market, "a").close()
        os.environ["WAYNE_EVOLVE_DB"] = os.path.join(td, "evolve.db")
        from winrate_volzone_filter_verify import ensure_tables

        rows = [
            {
                "as_of": "20261016",
                "sid": "2330",
                "variant": VARIANT_CURRENT,
                "name": "測",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 12345.0,
                "zone_pos": 0.4,
                "vol_ratio": 0.3,
                "ma60_rising": True,
                "ma_spread_pct": 5.0,
                "dist_h20_pct": 8.0,
                "hit": {VARIANT_VZ_MID_THIN: True, VARIANT_COMBO_TRIPLE: False},
            }
        ]
        assert persist_tape(market, rows) == 1
        store = ensure_tables(market)
        conn = sqlite3.connect(store)
        try:
            r = conn.execute(
                """
                SELECT open, high, low, close, volume, extra
                FROM winrate_volzone_filter_tape
                WHERE kind=? AND sid=? AND variant=?
                """,
                (KIND, "2330", VARIANT_CURRENT),
            ).fetchone()
        finally:
            conn.close()
        os.environ.pop("WAYNE_EVOLVE_DB", None)
        assert r is not None
        assert r[0] == 100.0 and r[1] == 105.0 and r[2] == 99.0
        assert r[3] == 102.0 and r[4] == 12345.0
        import json

        extra = json.loads(r[5] or "{}")
        assert extra.get("hit", {}).get(VARIANT_VZ_MID_THIN) is True
        assert extra.get("hit", {}).get(VARIANT_COMBO_TRIPLE) is False


def test_persist_gate_not_passed_low_n(monkeypatch=None):
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        # tape_store_path 相對 market → evolve 旁檔
        open(market, "a").close()
        os.environ["WAYNE_EVOLVE_DB"] = os.path.join(td, "evolve.db")
        rows = []
        for i, day in enumerate(["20260102", "20260103", "20260106"]):
            rows.append(
                {
                    "as_of": day,
                    "sid": f"233{i}",
                    "variant": VARIANT_CURRENT,
                    "name": "測",
                    "close": 100.0,
                    "zone_pos": 0.4,
                    "vol_ratio": 0.3,
                    "ma60_rising": True,
                    "ma_spread_pct": 5.0,
                    "dist_h20_pct": 8.0,
                }
            )
            rows.append(
                {
                    "as_of": day,
                    "sid": f"233{i}",
                    "variant": VARIANT_MA60_RISING,
                    "name": "測",
                    "close": 100.0,
                    "zone_pos": 0.4,
                    "vol_ratio": 0.3,
                    "ma60_rising": True,
                    "ma_spread_pct": 5.0,
                    "dist_h20_pct": 8.0,
                }
            )
        assert persist_tape(market, rows) == len(rows)
        # 直接灌 score（略過官方前瞻）
        from winrate_volzone_filter_verify import ensure_tables

        store = ensure_tables(market)
        conn = sqlite3.connect(store)
        try:
            for r in rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO winrate_volzone_filter_score(
                        kind, as_of, sid, variant, horizon, check_as_of,
                        entry, exit_close, fwd_pct, win
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        r["as_of"],
                        r["sid"],
                        r["variant"],
                        5,
                        r["as_of"],
                        100.0,
                        101.0,
                        1.0,
                        1,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        recompute_rates(market)
        g = gate_status(market)
        assert g["n_days"] == 3
        assert g["n_days"] < MIN_UNIQUE_DAYS
        assert g["passed"] is False
        line = optimize_status_one_liner(market)
        assert "尚未改話筒" in line or "收集中" in line
        # 清理 env
        os.environ.pop("WAYNE_EVOLVE_DB", None)


def test_compute_features_needs_bars():
    from winrate_volzone_filter_verify import compute_filter_features

    short = pd.DataFrame(
        {
            "date": [f"202601{i:02d}" for i in range(1, 10)],
            "open": [10] * 9,
            "high": [11] * 9,
            "low": [9] * 9,
            "close": [10] * 9,
            "volume": [1000] * 9,
        }
    )
    assert compute_filter_features(short) is None


def test_gate_rejects_wr_up_avg_down():
    """勝率微升但平均報酬變差 → 不過閘（不准改話筒）。"""
    with tempfile.TemporaryDirectory() as td:
        market = os.path.join(td, "m.db")
        open(market, "a").close()
        from winrate_volzone_filter_verify import ensure_tables

        store = ensure_tables(market)
        conn = sqlite3.connect(store)
        try:
            # 造 ≥20 獨立日：current wr=0.40 avg=+1；thin wr=0.60 avg=-2
            for i in range(22):
                day = f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}"
                cur_wins = [0, 1, 0, 0, 1]  # 2/5
                thin_wins = [1, 1, 0, 1, 0]  # 3/5
                for j, win in enumerate(cur_wins):
                    conn.execute(
                        """
                        INSERT INTO winrate_volzone_filter_score(
                            kind, as_of, sid, variant, horizon, check_as_of,
                            entry, exit_close, fwd_pct, win
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            KIND,
                            day,
                            f"c{i:02d}{j}",
                            VARIANT_CURRENT,
                            5,
                            day,
                            100.0,
                            101.0,
                            1.0,
                            win,
                        ),
                    )
                for j, win in enumerate(thin_wins):
                    conn.execute(
                        """
                        INSERT INTO winrate_volzone_filter_score(
                            kind, as_of, sid, variant, horizon, check_as_of,
                            entry, exit_close, fwd_pct, win
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            KIND,
                            day,
                            f"t{i:02d}{j}",
                            VARIANT_VZ_MID_THIN,
                            5,
                            day,
                            100.0,
                            98.0,
                            -2.0,
                            win,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
        recompute_rates(market)
        g = gate_status(market)
        assert g["n_days"] >= MIN_UNIQUE_DAYS
        assert g["passed"] is False
        assert "不改話筒" in optimize_status_one_liner(market) or "尚未" in optimize_status_one_liner(
            market
        )
