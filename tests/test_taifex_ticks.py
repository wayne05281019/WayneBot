# -*- coding: utf-8 -*-
"""期交所成交 → 台指期 15／60 分。本機 fixture，不打外網。"""
from __future__ import annotations

import io
import sqlite3
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from taifex_ticks import (
    _candidate_zip_dates,
    _rollup_60,
    aggregate_minute_bars,
    bars_from_zip_bytes,
    parse_tx_ticks,
    refresh_tx_minutes,
    unzip_csv,
    zip_url,
)


def _csv() -> str:
    lines = [
        "成交日期,商品代號,到期月份(週別),成交時間,成交價格,成交數量(B+S),近月價格,遠月價格,開盤集合競價"
    ]
    px = 46300
    t = 15 * 60
    while t <= 16 * 60 + 45:
        hh, mm = divmod(t, 60)
        lines.append(
            f"20260911,TX     ,202609,{hh:02d}{mm:02d}05,{px},2,0,0,"
        )
        lines.append(
            f"20260911,TX     ,202609,{hh:02d}{mm:02d}40,{px + 20},4,0,0,"
        )
        px += 5
        t += 15
    lines.extend(
        [
            "20260912,TX     ,202609,000010,46660,2,0,0,",
            "20260912,TX     ,202609,000020,46663,2,0,0,",
            "20260912,TX     ,202609,044500,46041,2,0,0,",
            "20260912,TX     ,202609,044559,46050,2,0,0,",
            "20260911,TX     ,202609/202610,150000,1,2,0,0,",
            "20260911,MTX    ,202609,150000,46300,1,0,0,",
            "20260911,TX     ,202610,150000,47000,1,0,0,",
        ]
    )
    return "\n".join(lines) + "\n"


def _zip_blob(text: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Daily_2026_09_14.csv", (text or _csv()).encode("big5"))
    return buf.getvalue()


def test_zip_url_and_parse_skips_spread_and_far_month():
    assert zip_url("2026-09-14") == (
        "https://www.taifex.com.tw/file/taifex/Dailydownload/"
        "DailydownloadCSV/Daily_2026_09_14.zip"
    )
    ticks = parse_tx_ticks(_csv())
    assert ticks
    assert all(t["month"] == "202609" for t in ticks)
    assert all(t["px"] != 47000 for t in ticks)
    assert all(t["px"] != 1 for t in ticks)


def test_aggregate_and_rollup_keep_ohlc_not_close_only():
    bars15 = aggregate_minute_bars(parse_tx_ticks(_csv()), 15)
    first = next(b for b in bars15 if b["t"] == "202609111500")
    assert first["o"] == 46300
    assert first["h"] == 46320
    assert first["l"] == 46300
    assert first["c"] == 46320
    night_hi = max(b["h"] for b in bars15)
    night_lo = min(b["l"] for b in bars15)
    assert night_hi == 46663
    assert night_lo == 46041
    bars60 = _rollup_60(bars15)
    hour = next(b for b in bars60 if b["t"] == "202609111500")
    chunk = [b for b in bars15 if b["t"].startswith("2026091115")]
    assert hour["o"] == chunk[0]["o"]
    assert hour["h"] == max(b["h"] for b in chunk)
    assert hour["l"] == min(b["l"] for b in chunk)
    assert hour["c"] == chunk[-1]["c"]
    assert hour["h"] > hour["c"] or hour["l"] < hour["c"] or len(chunk) == 1


def test_bars_from_zip_bytes_big5():
    bars = bars_from_zip_bytes(_zip_blob())
    assert bars
    assert bars[0]["t"].startswith("20260911")
    assert unzip_csv(_zip_blob()).startswith("成交日期")


def test_candidate_zip_dates_include_next_session_filename():
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    dates = _candidate_zip_dates(days=10)
    ahead = (now + timedelta(days=3)).strftime("%Y%m%d")
    back = (now + timedelta(days=-9)).strftime("%Y%m%d")
    assert dates[0] == ahead
    assert back in dates


def test_refresh_marks_zip_name_not_bar_calendar_day(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_ALLOW_MINUTES", "1")
    db = str(tmp_path / "t.db")
    blob = _zip_blob()
    target = _candidate_zip_dates(days=5)[0]
    seen: list[str] = []

    def fake_fetch(ymd, timeout=40):
        seen.append(ymd)
        if ymd == target:
            return 200, blob
        return 404, b""

    monkeypatch.setattr("taifex_ticks.fetch_daily_zip", fake_fetch)
    out = refresh_tx_minutes(db, limit_zips=1, days=5)
    assert out["ok"] is True
    assert out["fetched"] == 1
    assert any(x.startswith(target + ":") for x in out["days"])
    conn = sqlite3.connect(db)
    n = conn.execute(
        "SELECT COUNT(*) FROM minute_bars WHERE stock_id='TX' AND interval='15'"
    ).fetchone()[0]
    marked = conn.execute(
        "SELECT ymd, n FROM taifex_tick_zips"
    ).fetchall()
    conn.close()
    assert n >= 8
    assert marked == [(target, n)]
    seen.clear()
    again = refresh_tx_minutes(db, limit_zips=1, days=5)
    assert again["fetched"] == 0
    assert target not in seen


def test_refresh_tx_minutes_skips_under_pytest(tmp_path, monkeypatch):
    monkeypatch.delenv("WAYNE_ALLOW_MINUTES", raising=False)
    called = []
    monkeypatch.setattr(
        "taifex_ticks.fetch_daily_zip",
        lambda *a, **k: called.append(1) or (200, b""),
    )
    out = refresh_tx_minutes(str(tmp_path / "t.db"))
    assert out.get("skipped") == "pytest"
    assert called == []


def test_fetch_budget_bursts_until_window_filled(tmp_path):
    from datetime import datetime, timedelta
    from taifex_ticks import _mark_zip, fetch_budget

    db = str(tmp_path / "t.db")
    assert fetch_budget(db) == 20
    assert fetch_budget(db, limit_zips=1) == 1
    start = datetime(2026, 8, 4)
    for i in range(22):
        _mark_zip(db, (start + timedelta(days=i)).strftime("%Y%m%d"), 10)
    assert fetch_budget(db) == 3


def test_tx_health_stats_latest_night(tmp_path):
    from kline_hop import save_minute_bars
    from taifex_ticks import _mark_zip, tx_health_stats

    db = str(tmp_path / "t.db")
    bars = []
    t = 15 * 60
    while t <= 16 * 60 + 45:
        hh, mm = divmod(t, 60)
        bars.append(
            {
                "t": f"20260911{hh:02d}{mm:02d}",
                "o": 46300,
                "h": 46400,
                "l": 46200,
                "c": 46350,
                "v": 1,
            }
        )
        t += 15
    bars.append(
        {
            "t": "202609120000",
            "o": 46600,
            "h": 46663,
            "l": 46580,
            "c": 46650,
            "v": 1,
        }
    )
    bars.append(
        {
            "t": "202609120445",
            "o": 46050,
            "h": 46100,
            "l": 46041,
            "c": 46080,
            "v": 1,
        }
    )
    save_minute_bars("TX", "15", bars, db, source="taifex")
    _mark_zip(db, "20260914", len(bars))
    st = tx_health_stats(db)
    assert st["tx_15_n"] >= 8
    assert st["tx_zip_n"] == 1
    assert st["tx_15_from"].startswith("20260911")
    assert st["tx_15_to"].startswith("20260912")
    assert st["tx_night_n"] >= 8
    assert st["tx_night_high"] == "46663"
    assert st["tx_night_low"] == "46041"
    assert st["tx_night_date"] == "2026-09-11"
