# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from decision_card_signals import calc_volume_rank
from taiwan_market import (
    _fetch_twse_index_breadth,
    _fetch_twse_index_close,
    _merge_index_closes,
    _classify_regime_plus_raw,
    _confirm_regime_plus,
    analyze_taiwan_market,
    apply_market_weights,
    market_screening_note,
    regime_plus_screening_note,
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


def test_apply_market_weights_trims_on_high_falling_risk():
    base = {"day_trade": [{"stock_id": f"{i:04d}"} for i in range(8)], "overnight": [{"stock_id": f"{i}"} for i in range(6)]}
    out = apply_market_weights(
        base,
        {"ok": True, "regime": "neutral", "confidence": 50, "falling_risk": 65},
    )
    assert len(out["day_trade"]) == 3
    assert len(out["overnight"]) == 3


def test_compute_falling_risk_below_ma20():
    import pandas as pd

    from taiwan_market import compute_falling_risk

    idx = pd.DataFrame(
        {
            "close": [110 - i * 0.5 for i in range(25)],
            "volume": [1e9] * 25,
            "pct_change": [-0.5] * 25,
        }
    )
    fr = compute_falling_risk(idx, breadth_pct=30.0)
    assert fr["falling_risk"] >= 40


def test_market_screening_note_bull():
    note = market_screening_note(
        {
            "ok": True,
            "regime": "bull",
            "confidence": 72,
            "regime_plus": "trend_up",
            "regime_plus_label": "多頭延伸",
        }
    )
    assert "多頭" in note


def test_classify_regime_plus_trend_down():
    closes = pd.Series([100.0] * 15 + [90.0] * 5)
    raw = _classify_regime_plus_raw(
        regime="bear",
        falling_risk=65,
        risk_zone="normal",
        support_zone="none",
        closes=closes,
        futures_lead_label="期貨領跌",
    )
    assert raw == "trend_down"


def test_confirm_regime_plus_hysteresis():
    confirmed, streak, pending = _confirm_regime_plus(
        ["range", "range", "trend_down", "trend_down"], confirm_days=2
    )
    assert confirmed == "trend_down"
    assert streak == 2
    assert pending is None
    confirmed2, _, pending2 = _confirm_regime_plus(["range", "trend_down"], confirm_days=2)
    assert confirmed2 == "trend_down"
    assert pending2 is None


def test_apply_market_weights_regime_plus_late():
    base = {"day_trade": [{"stock_id": f"{i:04d}"} for i in range(10)]}
    out = apply_market_weights(
        base,
        {
            "ok": True,
            "regime": "bull",
            "regime_plus": "trend_up_late",
            "confidence": 60,
            "falling_risk": 40,
        },
    )
    assert len(out["day_trade"]) == 5


def test_regime_plus_screening_note_repair():
    note = regime_plus_screening_note(
        {"ok": True, "regime_plus": "repair", "regime_plus_label": "跌後修復"}
    )
    assert "修復" in note


def test_beta_sort_multiplier_high_beta_down():
    from taiwan_market import beta_sort_multiplier

    assert beta_sort_multiplier(1.0, "trend_down") == 1.0
    assert beta_sort_multiplier(1.5, "trend_down") < 1.0
    assert beta_sort_multiplier(2.0, "range") == 1.0


def test_compute_stock_betas(tmp_path):
    import sqlite3

    from taiwan_market import compute_stock_betas, ensure_index_daily_table

    db = str(tmp_path / "beta.db")
    ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, pct_change REAL, close REAL)")
    for i in range(30):
        d = f"202608{i+1:02d}"
        ip = 0.5 if i % 2 == 0 else -0.3
        sp = ip * 1.5
        conn.execute(
            "INSERT INTO index_daily(date,symbol,close,volume,pct_change,ma20,ma60,regime,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "TWII", 20000 + i, 1e9, ip, 20000, 19900, "neutral", "t"),
        )
        conn.execute("INSERT INTO daily_quotes VALUES ('2330', ?, ?, 100)", (d, sp))
    conn.commit()
    conn.close()
    betas = compute_stock_betas(db, "20260830", ["2330"])
    assert "2330" in betas
    assert betas["2330"] > 1.2


def test_apply_market_weights_beta_reorders(tmp_path):
    import sqlite3

    from taiwan_market import apply_market_weights, ensure_index_daily_table

    db = str(tmp_path / "bw.db")
    ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, pct_change REAL, close REAL)")
    for i in range(30):
        d = f"202608{i+1:02d}"
        ip = 0.5 if i % 2 == 0 else -0.3
        conn.execute(
            "INSERT INTO index_daily(date,symbol,close,volume,pct_change,ma20,ma60,regime,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "TWII", 20000 + i, 1e9, ip, 20000, 19900, "bear", "t"),
        )
        conn.execute("INSERT INTO daily_quotes VALUES ('2330', ?, ?, 100)", (d, ip * 1.5))
        conn.execute("INSERT INTO daily_quotes VALUES ('2317', ?, ?, 100)", (d, ip * 0.2))
    conn.commit()
    conn.close()
    base = {
        "day_trade": [
            {"stock_id": "2330", "q60r": 10, "pct_change": 1},
            {"stock_id": "2317", "q60r": 10, "pct_change": 1},
        ]
    }
    snap = {
        "ok": True,
        "regime": "bear",
        "regime_plus": "trend_down",
        "as_of": "20260830",
        "confidence": 50,
        "falling_risk": 40,
    }
    out = apply_market_weights(base, snap, db_path=db)
    assert out["day_trade"][0]["stock_id"] == "2317"


def test_backtest_regime_plus_empty(tmp_path):
    from taiwan_market import backtest_bucket_win_rate_by_regime_plus

    assert backtest_bucket_win_rate_by_regime_plus(str(tmp_path / "empty.db")) == []


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


def test_fetch_twse_index_breadth_parses_table():
    payload = {
        "stat": "OK",
        "tables": [
            {
                "title": "114年08月29日 漲跌證券數合計",
                "data": [
                    ["上漲", "792", "412", "1,204"],
                    ["下跌", "428", "201", "629"],
                    ["漲停(股)", "45", "12", "57"],
                    ["跌停(股)", "8", "3", "11"],
                    ["平盤", "156", "88", "244"],
                ],
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = payload
    with patch("taiwan_market._SESSION.get", return_value=mock_resp):
        row = _fetch_twse_index_breadth("20250829")
    assert row is not None
    assert row["up_count"] == 1204
    assert row["down_count"] == 629
    assert row["up_tw"] == 792
    assert row["limit_up"] == 57


def test_fetch_twse_index_breadth_parses_combined_up_limit_row():
    """2026/09 起 MI_INDEX 把上漲與漲停併成『上漲(漲停)』＋『4,107(47)』。"""
    payload = {
        "stat": "OK",
        "tables": [
            {
                "title": "漲跌證券數合計",
                "data": [
                    ["上漲(漲停)", "4,107(47)", "209(5)"],
                    ["下跌(跌停)", "9,440(168)", "776(7)"],
                    ["持平", "845", "86"],
                ],
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = payload
    with patch("taiwan_market._SESSION.get", return_value=mock_resp):
        row = _fetch_twse_index_breadth("20260903")
    assert row is not None
    assert row["up_count"] == 4107 + 209
    assert row["down_count"] == 9440 + 776
    assert row["limit_up"] == 47 + 5
    assert row["limit_down"] == 168 + 7
    assert row["flat_count"] == 845 + 86


def test_index_performance_hides_zero_yahoo_volume():
    from taiwan_market import _format_performance_lines, _index_performance, _market_read_note

    idx = pd.DataFrame(
        {
            "date": ["20260901", "20260902", "20260903"],
            "close": [46948.0, 46164.0, 45857.0],
            "volume": [5_018_300, 4_100_600, 0.0],
            "pct_change": [1.78, -1.67, -0.67],
        }
    )
    perf = _index_performance(idx)
    assert perf["volume"] is None
    assert perf["vol_ratio"] is None
    assert perf["vol_chg_pct"] is None
    lines = _format_performance_lines({**perf, "vs_ma20_pct": 0.9, "vs_high52_pct": -4.0})
    joined = "\n".join(lines)
    assert "量比 0.00" not in joined
    assert "量縮 100" not in joined
    assert "全日量" not in joined
    note = _market_read_note({**perf, "vs_ma20_pct": 0.9, "vs_high52_pct": -4.0, "chg5_pct": 0.1})
    assert "量比 0.00" not in note


def test_format_performance_shows_fmtqik_volume():
    from taiwan_market import _format_performance_lines

    lines = _format_performance_lines(
        {"volume": 9_267_047, "vs_ma20_pct": 1.2, "vs_high52_pct": -3.0}
    )
    joined = "　".join(lines)
    assert "全日量 926.7萬張" in joined


@patch("taiwan_market._fetch_index_daily")
@patch("taiwan_market._fetch_twse_index_close")
def test_sync_index_daily_keeps_volume_when_yahoo_zero(mock_twse, mock_yahoo, tmp_path):
    import sqlite3

    db = str(tmp_path / "idx.db")
    mock_twse.return_value = None
    mock_yahoo.return_value = pd.DataFrame(
        {
            "date": ["20260902", "20260903"],
            "open": [46900.0, 46325.0],
            "high": [46946.0, 46517.0],
            "low": [46164.0, 45839.0],
            "close": [46164.0, 45857.0],
            "volume": [4_100_600.0, 3_800_000.0],
            "pct_change": [-1.67, -0.67],
        }
    )
    r = sync_index_daily(db)
    assert r["ok"]
    mock_yahoo.return_value = pd.DataFrame(
        {
            "date": ["20260902", "20260903"],
            "open": [46900.0, 46325.0],
            "high": [46946.0, 46517.0],
            "low": [46164.0, 45839.0],
            "close": [46164.0, 45857.0],
            "volume": [4_100_600.0, 0.0],
            "pct_change": [-1.67, -0.67],
        }
    )
    sync_index_daily(db)
    conn = sqlite3.connect(db)
    vol, op = conn.execute(
        "SELECT volume, open FROM index_daily WHERE date=?",
        ("20260903",),
    ).fetchone()
    conn.close()
    assert vol == 3_800_000.0
    assert op == 46325.0


@patch("taiwan_market._fetch_twse_index_breadth")
def test_sync_index_breadth_daily_writes_table(mock_fetch, tmp_path):
    import sqlite3

    from taiwan_market import sync_index_breadth_daily

    db = str(tmp_path / "br.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT PRIMARY KEY, stock_name TEXT, "
        "market_type TEXT, asset_type TEXT, industry TEXT, is_active INT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, pct_change REAL, close REAL)"
    )
    conn.executemany(
        "INSERT INTO stock_universe VALUES (?,?,?,?,?,?,?)",
        [
            ("2330", "台積電", "TW", "STOCK", "", 1, ""),
            ("1101", "台泥", "TW", "STOCK", "", 1, ""),
            ("6488", "環球晶", "TWO", "STOCK", "", 1, ""),
            ("00878", "國泰永續高股息", "TW", "ETF_PASSIVE", "ETF", 1, ""),
        ],
    )
    conn.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?)",
        [
            ("20250829", "2330", 1.2, 100.0),
            ("20250829", "1101", -0.5, 20.0),
            ("20250829", "6488", 0.8, 150.0),
            ("20250829", "00878", 3.0, 22.0),
        ],
    )
    conn.commit()
    conn.close()
    mock_fetch.return_value = {
        "date": "20250829",
        "up_count": 1204,
        "down_count": 629,
        "limit_up": 57,
        "limit_down": 11,
        "flat_count": 244,
        "up_tw": 792,
        "down_tw": 428,
        "up_two": 412,
        "down_two": 201,
        "source": "twse",
    }
    r = sync_index_breadth_daily(db, dates=["20250829"])
    assert r["ok"] and r["rows"] >= 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT up_count, down_count, up_tw, up_two, limit_up, source FROM index_breadth_daily WHERE date=?",
        ("20250829",),
    ).fetchone()
    conn.close()
    assert row[:4] == (2, 1, 1, 1)
    assert row[4] == 57
    assert row[5] == "quotes"


@patch("taiwan_market._fetch_twse_index_breadth")
def test_sync_index_breadth_daily_skips_on_fetch_fail(mock_fetch, tmp_path):
    from taiwan_market import sync_index_breadth_daily

    db = str(tmp_path / "empty_br.db")
    mock_fetch.return_value = None
    r = sync_index_breadth_daily(db, dates=["20250829"])
    assert not r["ok"] and r["rows"] == 0


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
    assert "庫內官方融合" in html
    assert "結構" in html
    assert "官方融合" in html
    assert "距月線" in html
    mock_fetch.assert_not_called()


@patch("taiwan_market._fetch_index_daily")
def test_format_taiwan_market_page_no_yahoo_fallback(mock_fetch, tmp_path):
    from taiwan_market import format_taiwan_market_page_html

    db = tmp_path / "empty.db"
    html = format_taiwan_market_page_html(str(db))
    assert "庫空" not in html
    assert "暫不可用" not in html
    assert "指數資料讀取異常" in html
    mock_fetch.assert_not_called()


def test_index_performance_periods():
    import pandas as pd

    from taiwan_market import _index_performance, _market_read_note

    dates = [f"2026{m:02d}01" for m in range(1, 8)] + ["20260820"]
    closes = [20000, 21000, 22000, 23000, 24000, 25000, 26000, 25500]
    idx = pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "volume": [1e9] * 8,
            "pct_change": [0.2] * 7 + [-1.9],
        }
    )
    perf = _index_performance(idx)
    assert perf["chg1_pct"] == -1.9
    assert perf["vs_high52_pct"] is not None
    assert perf["vs_high52_pct"] < 0
    assert perf["vol_ratio"] == 1.0
    snap = {
        "vs_ma20_pct": -1.2,
        "vs_ma60_pct": 2.0,
        "chg5_pct": -2.1,
        "vs_high52_pct": -4.0,
        "vol_ratio": 0.7,
        "breadth_above_ma20": 42,
        "falling_risk": 10,
    }
    note = _market_read_note(snap)
    assert "月線下" in note
    assert "量比" in note


@pytest.mark.production_db
def test_production_db_market_page_has_real_data():
    """Release 庫存在時，大盤頁必須有完整官方融合輸出（非庫空）。"""
    from config import get_db_path
    from taiwan_market import analyze_taiwan_market, format_taiwan_market_page_html

    db = get_db_path()
    snap = analyze_taiwan_market(db, db_only=True)
    assert snap.get("ok") is True
    assert float(snap.get("close") or 0) > 1000
    assert int(snap.get("sample_n") or 0) > 100

    html = format_taiwan_market_page_html(db)
    assert "庫空" not in html
    assert "暫不可用" not in html
    assert "台股大盤" in html
    assert "加權指數" in html
    assert "距月線" in html
    assert "量比 0.00" not in html
    assert "量縮 100" not in html
    assert "漲 " in html and "跌 " in html


def test_compute_basis_pct():
    from taiwan_market import compute_basis_pct

    assert compute_basis_pct(46000, 47200) == round((47200 - 46000) / 46000 * 100, 2)
    assert compute_basis_pct(0, 100) is None


def test_parse_taifex_history_csv_picks_front_month():
    from taiwan_market import _parse_taifex_history_csv

    sample = (
        "交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量\n"
        "2026/08/03,TX,202608  ,43186,43836,42989,43230,-497,-1.14%,69550,43219,109589,43231,43247,49470,39442,,一般,,\n"
        "2026/08/03,TX,202609  ,43368,43966,43260,43388,-500,-1.14%,485,43363,6108,43373,43391,49651,24962,,一般,,\n"
    ).encode("big5")
    out = _parse_taifex_history_csv(sample)
    assert "20260803" in out
    assert out["20260803"]["close"] == 43230.0
    assert out["20260803"]["volume"] == 69550


@patch("taiwan_market._fetch_taifex_tx_day")
def test_sync_futures_daily_writes_row(mock_fetch, tmp_path):
    from taiwan_market import ensure_futures_daily_table, load_futures_daily, sync_futures_daily

    db = str(tmp_path / "fut.db")
    mock_fetch.return_value = {
        "date": "20260901",
        "contract_month": "202609",
        "open": 46000.0,
        "high": 47220.0,
        "low": 45987.0,
        "close": 47209.0,
        "settlement": 47201.0,
        "volume": 57627,
        "open_interest": 104368,
        "pct_change": 2.68,
        "source": "taifex",
    }
    r = sync_futures_daily(db, dates=["20260901"], backfill_days=0)
    assert r["ok"]
    row = load_futures_daily(db, "20260901")
    assert row and row["close"] == 47209.0


@patch("taiwan_market._fetch_taifex_tx_day")
def test_sync_futures_daily_backfill_zero_with_existing_rows(mock_fetch, tmp_path):
    """庫已有足夠列且 backfill_days=0 時，不可再 UnboundLocalError(datetime)。"""
    import sqlite3

    from taiwan_market import ensure_futures_daily_table, sync_futures_daily

    db = str(tmp_path / "fut2.db")
    ensure_futures_daily_table(db)
    conn = sqlite3.connect(db)
    for i in range(12):
        conn.execute(
            """
            INSERT INTO futures_daily(
                date, symbol, session, contract_month, open, high, low, close,
                settlement, volume, open_interest, pct_change, source, updated_at
            ) VALUES (?, 'TX', 'regular', '202609', 1, 2, 1, 2, 2, 10, 10, 0, 'taifex', 't')
            """,
            (f"202608{i + 10:02d}",),
        )
    conn.commit()
    conn.close()
    mock_fetch.return_value = {
        "date": "20260901",
        "contract_month": "202609",
        "open": 1.0,
        "high": 2.0,
        "low": 1.0,
        "close": 2.0,
        "settlement": 2.0,
        "volume": 1,
        "open_interest": 1,
        "pct_change": 0.0,
        "source": "taifex",
    }
    r = sync_futures_daily(db, dates=["20260901"], backfill_days=0)
    assert r["ok"]
    assert "error" not in r


def test_market_page_includes_futures_section(tmp_path):
    import sqlite3

    from taiwan_market import (
        ensure_futures_daily_table,
        ensure_index_daily_table,
        format_taiwan_market_page_html,
    )

    db = str(tmp_path / "mf.db")
    ensure_index_daily_table(db)
    ensure_futures_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE stock_universe (stock_id TEXT, is_active INT)")
    conn.execute("CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, close REAL, volume REAL)")
    conn.execute("INSERT INTO stock_universe VALUES ('2330', 1)")
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
        conn.execute(
            """
            INSERT INTO futures_daily(
                date, symbol, session, contract_month, open, high, low, close,
                settlement, volume, open_interest, pct_change, source, updated_at
            ) VALUES (?, 'TX', 'regular', '202608', ?, ?, ?, ?, ?, 1000, 50000, 0.2, 'taifex', 'test')
            """,
            (d, close + 50, close + 100, close + 30, close + 80, close + 75),
        )
        conn.execute("INSERT INTO daily_quotes VALUES ('2330', ?, ?, 1000)", (d, float(100 + i)))
    conn.commit()
    conn.close()
    html = format_taiwan_market_page_html(db, "20260824")
    assert "基差" in html
    assert "結構" in html
