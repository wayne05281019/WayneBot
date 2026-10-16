# -*- coding: utf-8 -*-
"""結構／大量區窗內開市日：缺官方量先補洞，不准發明假量。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def _schema(db: str) -> None:
    from wayne_db import ensure_core_schema

    ensure_core_schema(db)


def test_missing_flags_tpex_lots_div1000_corrupt_rows(tmp_path):
    """biaoke_stock_day 張誤÷1000 殘列（高價＋個位張）＝當洞，好重抓真張數。"""
    from vol_zone_chart import missing_open_quote_days

    db = str(tmp_path / "corrupt.db")
    _schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "20260701",
            "3081",
            "聯亞",
            "TWO",
            2035,
            2080,
            1970,
            1980,
            1,  # 真是 1475 張，被÷1000
            0,
            -1.98,
            1980,
            0,
            0,
            0,
            "biaoke_stock_day",
            "t",
        ),
    )
    conn.commit()
    conn.close()
    holes = missing_open_quote_days("3081", db, "20260701", "20260701")
    assert "20260701" in holes


def test_ensure_repairs_corrupt_biaoke_stock_day_lots(tmp_path, monkeypatch):
    """假小量 biaoke 列 → ensure 重抓月表寫回真張數。"""
    from vol_zone_chart import (
        clear_ensure_official_volume_cache,
        ensure_official_volume_window,
        missing_open_quote_days,
    )

    clear_ensure_official_volume_cache()
    db = str(tmp_path / "repair.db")
    _schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "20260701",
            "9083",
            "測C",
            "TWO",
            2000,
            2100,
            1900,
            1980,
            2,
            0,
            0,
            1980,
            0,
            0,
            0,
            "biaoke_stock_day",
            "t",
        ),
    )
    conn.commit()
    conn.close()
    assert "20260701" in missing_open_quote_days("9083", db, "20260701", "20260701")

    fake_rows = [
        {
            "date": "20260701",
            "stock_id": "9083",
            "stock_name": "測C",
            "market": "TWO",
            "open": 2000.0,
            "high": 2100.0,
            "low": 1900.0,
            "close": 1980.0,
            "volume": 1475,
            "pct_change": -1.98,
        }
    ]
    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", lambda *a, **k: list(fake_rows))
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TWO")
    monkeypatch.setattr("vol_zone_chart.time.sleep", lambda *_a, **_k: None)

    stats = ensure_official_volume_window(
        "9083", db, end_ymd="20260701", days=5, stock_name="測C"
    )
    assert "202607" in stats["months_ok"]
    conn = sqlite3.connect(db)
    vol = conn.execute(
        "SELECT volume FROM daily_quotes WHERE stock_id=? AND date=?",
        ("9083", "20260701"),
    ).fetchone()[0]
    conn.close()
    assert float(vol) == 1475.0
    assert "20260701" not in missing_open_quote_days("9083", db, "20260701", "20260701")


def test_ensure_official_volume_fills_missing_open_day(tmp_path, monkeypatch):
    """庫缺開市日 → 呼叫 STOCK_DAY 月表 upsert 真柱；不准編造。"""
    from vol_zone_chart import (
        clear_ensure_official_volume_cache,
        ensure_official_volume_window,
        missing_open_quote_days,
    )

    clear_ensure_official_volume_cache()

    db = str(tmp_path / "t.db")
    _schema(db)
    conn = sqlite3.connect(db)
    # 20260812 / 20260814 有列；20260813 開市缺列
    conn.executemany(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                "20260812",
                "9081",
                "測A",
                "TW",
                10,
                11,
                9,
                10.5,
                100,
                0,
                0,
                10.5,
                0,
                0,
                0,
                "test",
                "t",
            ),
            (
                "20260814",
                "9081",
                "測A",
                "TW",
                10.5,
                12,
                10,
                11,
                120,
                0,
                0,
                11,
                0,
                0,
                0,
                "test",
                "t",
            ),
        ],
    )
    conn.commit()
    conn.close()

    before = missing_open_quote_days("9081", db, "20260812", "20260814")
    assert "20260813" in before

    fake_rows = [
        {
            "date": "20260812",
            "stock_id": "9081",
            "stock_name": "測A",
            "market": "TW",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 100,
            "pct_change": 0.0,
        },
        {
            "date": "20260813",
            "stock_id": "9081",
            "stock_name": "測A",
            "market": "TW",
            "open": 10.5,
            "high": 10.8,
            "low": 10.2,
            "close": 10.6,
            "volume": 55,
            "pct_change": 0.95,
        },
        {
            "date": "20260814",
            "stock_id": "9081",
            "stock_name": "測A",
            "market": "TW",
            "open": 10.5,
            "high": 12.0,
            "low": 10.0,
            "close": 11.0,
            "volume": 120,
            "pct_change": 3.8,
        },
    ]

    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", lambda *a, **k: list(fake_rows))
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TW")

    stats = ensure_official_volume_window(
        "9081", db, end_ymd="20260814", days=5, stock_name="測A"
    )
    assert "202608" in stats["months_ok"]
    after = missing_open_quote_days("9081", db, "20260812", "20260814")
    assert "20260813" not in after
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT volume, close FROM daily_quotes WHERE stock_id=? AND date=?",
        ("9081", "20260813"),
    ).fetchone()
    conn.close()
    assert row is not None
    assert float(row[0]) == 55.0
    assert float(row[1]) == 10.6
    assert "20260813" not in (stats.get("confirmed_absent") or [])


def test_ensure_marks_confirmed_absent_when_official_month_lacks_day(
    tmp_path, monkeypatch
):
    """官方月表成功但無該日 → confirmed_absent，不准發明量。"""
    from vol_zone_chart import (
        clear_ensure_official_volume_cache,
        ensure_official_volume_window,
    )

    clear_ensure_official_volume_cache()
    db = str(tmp_path / "t2.db")
    _schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "20260812",
            "9082",
            "測B",
            "TW",
            10,
            11,
            9,
            10,
            80,
            0,
            0,
            10,
            0,
            0,
            0,
            "test",
            "t",
        ),
    )
    conn.execute(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "20260814",
            "9082",
            "測B",
            "TW",
            10,
            11,
            9,
            10.2,
            90,
            0,
            0,
            10.2,
            0,
            0,
            0,
            "test",
            "t",
        ),
    )
    conn.commit()
    conn.close()

    # 官方月表故意不含 20260813
    fake_rows = [
        {
            "date": "20260812",
            "stock_id": "9082",
            "stock_name": "測B",
            "market": "TW",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 80,
            "pct_change": 0.0,
        },
        {
            "date": "20260814",
            "stock_id": "9082",
            "stock_name": "測B",
            "market": "TW",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.2,
            "volume": 90,
            "pct_change": 2.0,
        },
    ]
    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", lambda *a, **k: list(fake_rows))
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TW")

    stats = ensure_official_volume_window(
        "9082", db, end_ymd="20260814", days=5, stock_name="測B"
    )
    assert "20260813" in (stats.get("confirmed_absent") or [])


def test_ensure_second_call_skips_network(tmp_path, monkeypatch):
    """暖路徑：第二次 ensure 不准再打 STOCK_DAY。"""
    import time

    from vol_zone_chart import (
        clear_ensure_official_volume_cache,
        ensure_official_volume_window,
    )

    clear_ensure_official_volume_cache()
    db = str(tmp_path / "t3.db")
    _schema(db)
    conn = sqlite3.connect(db)
    conn.executemany(
        """
        INSERT INTO daily_quotes
        (date, stock_id, stock_name, market, open, high, low, close, volume,
         turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
         source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                "20260812",
                "9083",
                "測C",
                "TW",
                10,
                11,
                9,
                10,
                80,
                0,
                0,
                10,
                0,
                0,
                0,
                "test",
                "t",
            ),
            (
                "20260814",
                "9083",
                "測C",
                "TW",
                10,
                11,
                9,
                10.2,
                90,
                0,
                0,
                10.2,
                0,
                0,
                0,
                "test",
                "t",
            ),
        ],
    )
    conn.commit()
    conn.close()
    calls = {"n": 0}

    def _fake_fetch(*a, **k):
        calls["n"] += 1
        return [
            {
                "date": "20260812",
                "stock_id": "9083",
                "stock_name": "測C",
                "market": "TW",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.0,
                "volume": 80,
                "pct_change": 0.0,
            },
            {
                "date": "20260814",
                "stock_id": "9083",
                "stock_name": "測C",
                "market": "TW",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.2,
                "volume": 90,
                "pct_change": 2.0,
            },
        ]

    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", _fake_fetch)
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TW")
    ensure_official_volume_window(
        "9083", db, end_ymd="20260814", days=5, stock_name="測C"
    )
    n_first = int(calls["n"])
    assert n_first >= 1  # 窗內多月缺列會各打一次；重點是第二次不准再打
    t0 = time.perf_counter()
    ensure_official_volume_window(
        "9083", db, end_ymd="20260814", days=5, stock_name="測C"
    )
    assert time.perf_counter() - t0 < 0.05
    assert calls["n"] == n_first


def test_chart_window_no_missing_vol_when_official_has_data():
    """3081 結構／大量區近窗：開市日有官方量就不准再缺列（補洞後）。"""
    from trading_calendar import iter_tw_open_days
    from vol_zone_chart import (
        clear_ensure_official_volume_cache,
        ensure_official_volume_window,
        load_official_ohlc,
        missing_open_quote_days,
        official_work,
        prepare_volume_zone,
    )

    db = get_db_path()
    if not Path(db).is_file():
        pytest.skip("no production db")
    clear_ensure_official_volume_cache()
    stats = ensure_official_volume_window("3081", db, days=200, stock_name="聯亞")
    raw = load_official_ohlc("3081", db, 200)
    work = official_work(
        raw, skip_invent_dates=set(stats.get("confirmed_absent") or [])
    )
    assert work is not None and len(work) >= 40
    start = str(work["date"].iloc[0]).replace("-", "")[:8]
    end = str(work["date"].iloc[-1]).replace("-", "")[:8]
    # 窗內開市日：要嘛庫有真列，要嘛 confirmed_absent（官方無列＝非交易／休市）
    open_days = set(iter_tw_open_days(start, end))
    absent = set(stats.get("confirmed_absent") or [])
    still = set(stats.get("still_missing") or [])
    # 仍缺且官方有資料時不准過（still_missing 應空或僅網路失敗）
    holes = missing_open_quote_days("3081", db, start, end)
    invent_holes = [d for d in holes if d not in absent]
    # 畫窗 invent 洞 ⊆ still_missing（網路失敗／未補完）；still 可含 ensure 窗外日，不准 list 比序
    assert set(invent_holes) <= still, (
        invent_holes,
        still,
        stats,
    )
    # 畫面上的每根真列必須有非 NULL volume（0＝真停價可）
    for _, row in work.iterrows():
        assert row["volume"] == row["volume"], row["date"]  # not NaN
        assert float(row["volume"]) >= 0.0
        # 對齊發明的停價柱：若 skip 後不應再出現 no_trade_fill
        if bool(row.get("no_trade_fill", False)):
            d = str(row["date"]).replace("-", "")[:8]
            assert d not in absent
    # prepare 路徑也要跑過 ensure
    pack = prepare_volume_zone("3081", "聯亞", db, str(Path(db).parent / "_vz_probe.png"))
    assert pack is not None
    ve = pack.get("vol_ensure") or {}
    view = pack["view"]
    v_start = str(view["date"].iloc[0]).replace("-", "")[:8]
    v_end = str(view["date"].iloc[-1]).replace("-", "")[:8]
    view_holes = [
        d
        for d in missing_open_quote_days("3081", db, v_start, v_end)
        if d not in set(ve.get("confirmed_absent") or [])
    ]
    assert view_holes == [], (view_holes, ve)


def test_ensure_fetches_missing_months_in_parallel(tmp_path, monkeypatch):
    """缺多月時並行抓 STOCK_DAY（ThreadPool），不准串行 sleep 拖死第二→第三。"""
    import inspect
    import threading
    import time

    from vol_zone_chart import (
        _ENSURE_MONTH_FETCH_WORKERS,
        clear_ensure_official_volume_cache,
        ensure_official_volume_window,
        lookup_vol_ensure_days,
    )

    assert _ENSURE_MONTH_FETCH_WORKERS >= 2
    src = inspect.getsource(ensure_official_volume_window)
    assert "ThreadPoolExecutor" in src
    assert "as_completed" in src
    assert lookup_vol_ensure_days() >= 180

    clear_ensure_official_volume_cache()
    db = str(tmp_path / "par.db")
    _schema(db)
    # 三個缺月：並行應同時進 fetch（active>=2），總牆鐘 < 串行 3×sleep
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}
    calls = {"ym": []}

    def _slow_fetch(sid, ym, **kwargs):
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
            calls["ym"].append(str(ym))
        time.sleep(0.35)
        with lock:
            active["n"] -= 1
        y, m = int(str(ym)[:4]), int(str(ym)[4:6])
        return [
            {
                "date": f"{y:04d}-{m:02d}-10",
                "stock_id": sid,
                "stock_name": "測並",
                "market": "TW",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100,
                "pct_change": 1.0,
            }
        ]

    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", _slow_fetch)
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TW")
    t0 = time.perf_counter()
    stats = ensure_official_volume_window(
        "9099", db, end_ymd="20260820", days=90, stock_name="測並"
    )
    elapsed = time.perf_counter() - t0
    assert len(stats.get("months_fetched") or []) >= 2
    assert active["peak"] >= 2, active
    # 串行 3×0.35≈1.05+；並行牆鐘應明顯較短
    assert elapsed < 0.95, elapsed


def test_lookup_path_early_vol_ensure_outside_paint():
    """查股：ensure 提早在 paint 外；高低卡後可顯示補官方量，不准長沉默。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "ensure_official_volume_window" in src
    assert "lookup_vol_ensure_days" in src
    assert "volfill" in src
    assert "_await_vol_ensure" in src
    assert "glance_queued" in src
    assert "struct_prep_task" in src
    assert "prepare_volume_zone" in src
    # ensure 與 MIS／建卡並行（在 card_item await 之前）；結構 prepare 在 paint 外
    assert src.find("ensure_task = asyncio.create_task") < src.find(
        "card_item = await card_render_task"
    )
    assert src.find("struct_prep_task = asyncio.create_task") < src.find(
        "card_item = await card_render_task"
    )
    assert src.find("create_task(_struct_item())") < src.find(
        "card_item = await card_render_task"
    )
    # 結構 paint 吃預先 pack，不准只在 paint 內才 ensure+prepare
    assert "pack=_struct_pack_box[0]" in src or "pack=_struct_pack_box" in src


def test_confirmed_absent_persisted_skips_refetch(tmp_path, monkeypatch):
    """官方月表確認無列落庫後：清 memo 再 ensure 不准重打網路。"""
    import time

    from vol_zone_chart import (
        clear_ensure_official_volume_cache,
        ensure_official_volume_window,
        load_confirmed_absent_dates,
        missing_open_quote_days,
        save_confirmed_absent_dates,
    )

    db = str(tmp_path / "abs.db")
    _schema(db)
    calls = {"n": 0}

    def _fetch(sid, ym, **kwargs):
        calls["n"] += 1
        # 月表成功但沒有 20260813 → confirmed_absent
        return [
            {
                "date": "2026-08-12",
                "stock_id": sid,
                "stock_name": "測缺",
                "market": "TW",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100,
                "pct_change": 1.0,
            }
        ]

    import biaoke_walk as bw

    monkeypatch.setattr(bw, "fetch_stock_month", _fetch)
    monkeypatch.setattr(bw, "_market_of", lambda *a, **k: "TW")
    clear_ensure_official_volume_cache()
    st = ensure_official_volume_window(
        "9077", db, end_ymd="20260814", days=5, stock_name="測缺"
    )
    assert "20260813" in (st.get("confirmed_absent") or [])
    assert calls["n"] >= 1
    assert "20260813" in load_confirmed_absent_dates("9077", db, "20260801", "20260831")
    assert "20260813" not in missing_open_quote_days("9077", db, "20260812", "20260814")
    n1 = calls["n"]
    clear_ensure_official_volume_cache()
    t0 = time.perf_counter()
    st2 = ensure_official_volume_window(
        "9077", db, end_ymd="20260814", days=5, stock_name="測缺"
    )
    assert time.perf_counter() - t0 < 0.2
    assert calls["n"] == n1
    assert "20260813" in (st2.get("confirmed_absent") or [])
    # 手動落庫路徑也要能擋缺洞
    save_confirmed_absent_dates("9077", db, ["20260814"])
    assert "20260814" not in missing_open_quote_days("9077", db, "20260812", "20260814")
