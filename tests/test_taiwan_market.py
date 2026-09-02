# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

import pandas as pd

from decision_card_signals import calc_volume_rank
from taiwan_market import (
    _fetch_twse_index_close,
    _merge_index_closes,
    analyze_taiwan_market,
    apply_market_weights,
    market_screening_note,
    sync_index_daily,
)


def test_calc_volume_rank_turnover_changes_order():
    vols = [100, 200, 150, 180, 120]
    closes = [10, 10, 10, 10, 50]
    assert calc_volume_rank(vols, 5) == 4
    assert calc_volume_rank(vols, 5, closes=closes) == 1


def test_apply_market_filter_trims_bear_lists():
    base = {"day_trade": [{"stock_id": f"{i:04d}"} for i in range(10)], "overnight": [{"stock_id": "x"}]}
    out = apply_market_weights(base, {"ok": True, "regime": "bear", "confidence": 40})
    assert len(out["day_trade"]) == 4
    assert len(out["overnight"]) == 1


def test_market_screening_note_bull():
    note = market_screening_note({"ok": True, "regime": "bull", "confidence": 72})
    assert "多頭" in note


@patch("taiwan_market._fetch_index_daily")
def test_analyze_taiwan_market_regime(mock_fetch, tmp_path):
    import sqlite3

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT, is_active INT)"
    )
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, close REAL, volume REAL)"
    )
    conn.execute("INSERT INTO stock_universe VALUES ('2330', 1)")
    for i, c in enumerate([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120]):
        conn.execute(
            "INSERT INTO daily_quotes VALUES ('2330', ?, ?, 1000)",
            (f"202608{i+1:02d}", float(c)),
        )
    conn.commit()
    conn.close()
    mock_fetch.return_value = pd.DataFrame(
        {
            "date": [f"202608{i:02d}" for i in range(1, 25)],
            "close": [float(22000 + i * 50) for i in range(24)],
            "volume": [1e9] * 24,
        }
    )
    snap = analyze_taiwan_market(str(db), "20260824")
    assert snap.get("ok")
    assert snap.get("regime") in ("bull", "neutral", "bear")
    assert snap.get("confidence", 0) > 0


def test_fetch_twse_index_close_parses_weighted_index():
    payload = {
        "stat": "OK",
        "tables": [
            {
                "title": "114年08月29日 價格指數(臺灣證券交易所)",
                "data": [
                    ["寶島股價指數", "27,261.26", "<p style ='color:red'>+</p>", "5.08", "0.02", ""],
                    ["發行量加權股價指數", "24,233.10", "<p style ='color:green'>-</p>", "3.35", "0.01", ""],
                ],
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = payload
    with patch("taiwan_market._SESSION.get", return_value=mock_resp):
        row = _fetch_twse_index_close("20250829")
    assert row is not None
    assert row["close"] == 24233.10
    assert row["pct_change"] == -0.01
    assert row["source"] == "twse"


def test_fetch_twse_index_close_returns_none_on_holiday():
    payload = {"stat": "很抱歉，沒有符合條件的資料!", "tables": []}
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = payload
    with patch("taiwan_market._SESSION.get", return_value=mock_resp):
        assert _fetch_twse_index_close("20250830") is None


@patch("taiwan_market._fetch_twse_index_close")
def test_merge_index_closes_prefers_official(mock_twse):
    def _official(date):
        if date == "20250829":
            return {
                "date": "20250829",
                "close": 24233.10,
                "pct_change": -0.01,
                "source": "twse",
            }
        return None

    mock_twse.side_effect = _official
    yahoo = pd.DataFrame(
        {
            "date": ["20250828", "20250829"],
            "close": [24100.0, 24230.0],
            "volume": [1e9, 1.1e9],
            "pct_change": [0.2, 0.41],
        }
    )
    merged, alerts = _merge_index_closes(yahoo)
    last = merged.iloc[-1]
    assert last["close"] == 24233.10
    assert last["source"] == "twse"
    assert alerts == []


@patch("taiwan_market._fetch_twse_index_close")
def test_merge_index_closes_alerts_on_large_diff(mock_twse):
    mock_twse.return_value = {
        "date": "20250829",
        "close": 24233.10,
        "pct_change": -0.01,
        "source": "twse",
    }
    yahoo = pd.DataFrame(
        {
            "date": ["20250829"],
            "close": [24500.0],
            "volume": [1e9],
            "pct_change": [1.0],
        }
    )
    _, alerts = _merge_index_closes(yahoo)
    assert len(alerts) == 1
    assert "Yahoo" in alerts[0] and "TWSE" in alerts[0]


@patch("taiwan_market._fetch_index_daily")
@patch("taiwan_market._fetch_twse_index_close")
def test_sync_index_daily_prefers_official(mock_twse, mock_yahoo, tmp_path):
    import sqlite3

    db = str(tmp_path / "idx.db")
    mock_yahoo.return_value = pd.DataFrame(
        {
            "date": ["20250828", "20250829"],
            "close": [24100.0, 24200.0],
            "volume": [1e9, 1.1e9],
            "pct_change": [0.2, 0.41],
        }
    )
    mock_twse.return_value = {
        "date": "20250829",
        "close": 24233.10,
        "pct_change": -0.01,
        "source": "twse",
    }
    r = sync_index_daily(db)
    assert r["ok"] and r["rows"] == 2
    assert r.get("latest_source") == "twse"
    conn = sqlite3.connect(db)
    close = conn.execute(
        "SELECT close FROM index_daily WHERE date=?",
        ("20250829",),
    ).fetchone()[0]
    conn.close()
    assert close == 24233.10


@patch("taiwan_market._fetch_index_daily")
def test_format_taiwan_market_page_read_only(mock_fetch, tmp_path):
    import sqlite3

    from taiwan_market import ensure_index_daily_table, format_taiwan_market_page_html

    db = tmp_path / "page.db"
    ensure_index_daily_table(str(db))
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE stock_universe (stock_id TEXT, is_active INT)")
    conn.execute("CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, close REAL, volume REAL)")
    conn.execute("INSERT INTO stock_universe VALUES ('2330', 1)")
    for i, c in enumerate(range(100, 121)):
        conn.execute(
            "INSERT INTO daily_quotes VALUES ('2330', ?, ?, 1000)",
            (f"202608{i+1:02d}", float(c)),
        )
    for i in range(1, 25):
        d = f"202608{i:02d}"
        close = 22000.0 + i * 50
        conn.execute(
            """
            INSERT INTO index_daily(date, symbol, close, volume, pct_change, ma20, ma60, regime, updated_at)
            VALUES (?, 'TWII', ?, 1e9, 0.1, ?, ?, 'bull', 'test')
            """,
            (d, close, close - 100, close - 200),
        )
    conn.commit()
    conn.close()
    html = format_taiwan_market_page_html(str(db), "20260824")
    assert "台股大盤" in html
    assert "只讀庫內資料" in html
    assert "Regime" in html
    assert "官方融合" in html
    mock_fetch.assert_not_called()


@patch("taiwan_market._fetch_index_daily")
def test_format_taiwan_market_page_no_yahoo_fallback(mock_fetch, tmp_path):
    from taiwan_market import format_taiwan_market_page_html

    db = tmp_path / "empty.db"
    html = format_taiwan_market_page_html(str(db))
    assert "暫不可用" in html
    mock_fetch.assert_not_called()
