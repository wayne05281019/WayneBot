import pandas as pd

from live_quote import (
    append_live_bar,
    calc_vol_rank_120,
    is_live_merge_window,
    live_vol_rank_120,
)


def test_calc_vol_rank_120_highest_is_one():
    assert calc_vol_rank_120([100, 200, 500, 300, 800]) == 1


def test_calc_vol_rank_120_lowest_is_window_size():
    assert calc_vol_rank_120([800, 700, 600, 500, 100]) == 5


def test_calc_vol_rank_120_mid_rank():
    assert calc_vol_rank_120([100, 200, 150, 180, 120]) == 4


def test_append_live_bar_updates_existing_today_row(monkeypatch):
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(
        live_quote,
        "fetch_mis_quote",
        lambda sid, mkt="": {
            "stock_name": "台積電",
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 55000,
            "pct_change": 2.0,
            "update_time": "10:35:00",
        },
    )
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20260901")
    df = pd.DataFrame(
        [
            {"date": "20260829", "close": 95.0, "volume": 10000},
            {"date": "20260901", "close": 96.0, "volume": 8000, "is_live": True},
        ]
    )
    out = append_live_bar(df, "2330")
    assert int(out.iloc[-1]["volume"]) == 55000
    assert float(out.iloc[-1]["close"]) == 101.0
    assert bool(out.iloc[-1]["is_live"]) is True


def test_append_live_bar_does_not_overwrite_official_today(monkeypatch):
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(
        live_quote,
        "fetch_mis_quote",
        lambda sid, mkt="": {
            "stock_name": "台積電",
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 55000,
            "pct_change": 2.0,
            "update_time": "13:40:00",
        },
    )
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20260901")
    df = pd.DataFrame(
        [
            {"date": "20260829", "close": 95.0, "volume": 10000},
            {"date": "20260901", "close": 100.0, "volume": 20000},
        ]
    )
    out = append_live_bar(df, "2330")
    assert float(out.iloc[-1]["close"]) == 100.0
    assert int(out.iloc[-1]["volume"]) == 20000


def test_append_live_bar_appends_when_missing_today(monkeypatch):
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(
        live_quote,
        "fetch_mis_quote",
        lambda sid, mkt="": {
            "stock_name": "台積電",
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 12000,
            "pct_change": 2.0,
            "update_time": "11:05:00",
        },
    )
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20260901")
    df = pd.DataFrame([{"date": "20260829", "close": 95.0, "volume": 10000}])
    out = append_live_bar(df, "2330")
    assert len(out) == 2
    assert str(out.iloc[-1]["date"]) == "20260901"
    assert int(out.iloc[-1]["volume"]) == 12000


def test_append_live_bar_skips_weekend_new_day(monkeypatch):
    """週六即使硬開盤中窗，也不要生出一根假 K 蓋掉上個交易日官方收。"""
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(
        live_quote,
        "fetch_mis_quote",
        lambda sid, mkt="": {
            "stock_name": "台積電",
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 12000,
            "pct_change": 2.0,
            "update_time": "11:05:00",
        },
    )
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20260905")
    df = pd.DataFrame([{"date": "20260904", "close": 95.0, "volume": 10000}])
    out = append_live_bar(df, "2330")
    assert len(out) == 1
    assert float(out.iloc[-1]["close"]) == 95.0


def test_live_vol_rank_120_uses_live_volume(tmp_path):
    import sqlite3

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, volume INTEGER)"
    )
    for i, vol in enumerate([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000], start=1):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, ?, ?)",
            (f"2026082{i:02d}", "2330", vol),
        )
    conn.commit()
    conn.close()
    assert live_vol_rank_120(str(db), "2330", 950) == 2
    assert live_vol_rank_120(str(db), "2330", 50) == 11


def test_is_live_merge_window_hours(monkeypatch):
    import live_quote
    from datetime import datetime
    from zoneinfo import ZoneInfo

    def fake_now():
        return datetime(2026, 9, 1, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    monkeypatch.setattr(live_quote, "taipei_now", fake_now)
    assert is_live_merge_window() is True

    def early():
        return datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    monkeypatch.setattr(live_quote, "taipei_now", early)
    assert is_live_merge_window() is False

    def saturday():
        return datetime(2026, 8, 29, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    monkeypatch.setattr(live_quote, "taipei_now", saturday)
    assert is_live_merge_window() is False

    def after_close_before_fuse():
        return datetime(2026, 9, 4, 16, 10, tzinfo=ZoneInfo("Asia/Taipei"))

    monkeypatch.setattr(live_quote, "taipei_now", after_close_before_fuse)
    assert is_live_merge_window() is True

    def fuse_done():
        return datetime(2026, 9, 4, 16, 30, tzinfo=ZoneInfo("Asia/Taipei"))

    monkeypatch.setattr(live_quote, "taipei_now", fuse_done)
    assert is_live_merge_window() is False

    def midautumn_friday():
        return datetime(2026, 9, 25, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    monkeypatch.setattr(live_quote, "taipei_now", midautumn_friday)
    assert is_live_merge_window() is False
