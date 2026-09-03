# -*- coding: utf-8 -*-
"""連買區域：外資／投信／皆買天數、張數、佔成交％須對得上日K。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from buy_streak import (
    KIND_BOTH,
    KIND_FOREIGN,
    KIND_TRUST,
    MARKET_TW,
    MARKET_TWO,
    MIN_STREAK,
    clear_cache,
    find_row,
    format_list_html,
    format_row_lines,
    load_snapshot,
    parse_days,
    parse_kind,
    parse_market,
    parse_stock_code,
)


def _init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE stock_universe (
            stock_id TEXT PRIMARY KEY,
            stock_name TEXT NOT NULL,
            market_type TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            industry TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE daily_quotes (
            date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            market TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER,
            PRIMARY KEY (date, stock_id)
        );
        """
    )
    uni = [
        ("2330", "台積電", "TW", "STOCK"),
        ("2317", "鴻海", "TW", "STOCK"),
        ("2454", "聯發科", "TW", "STOCK"),
        ("3105", "穩懋", "TWO", "STOCK"),
        ("0050", "元大台灣50", "TW", "ETF_PASSIVE"),
    ]
    conn.executemany(
        "INSERT INTO stock_universe VALUES (?,?,?,?, '', 1, 't')",
        uni,
    )
    # 8 sessions; 基準日 as_of = 20260908（fixture 自洽）
    dates = [
        "20260901",
        "20260902",
        "20260903",
        "20260904",
        "20260905",
        "20260906",
        "20260907",
        "20260908",
    ]
    # 2330: last 6 days foreign>0 (3..8), trust mixed so both=2 (7-8)
    # 2317: last 3 days foreign>0, trust>0 both=3
    # 2454: last 1 day foreign>0 → not listed (min 2)
    # 3105 TWO: last 4 days foreign>0
    rows = []

    def add(sid, name, mkt, series):
        for d, f, t, v in series:
            rows.append((d, sid, name, mkt, 10, 11, 9, 10, v, 0, 0, 10, f, t, 0))

    f2330 = {
        "20260901": (-10, 5, 1000),
        "20260902": (-20, -3, 1000),
        "20260903": (100, -1, 2000),
        "20260904": (110, 0, 2000),
        "20260905": (120, -2, 2000),
        "20260906": (130, 4, 2000),
        "20260907": (140, 8, 2500),
        "20260908": (150, 9, 2500),
    }
    add("2330", "台積電", "TW", [(d, *f2330[d]) for d in dates])
    f2317 = {
        "20260901": (5, 5, 800),
        "20260902": (5, 5, 800),
        "20260903": (5, 5, 800),
        "20260904": (5, 5, 800),
        "20260905": (-1, -1, 800),
        "20260906": (10, 20, 1000),
        "20260907": (20, 30, 1000),
        "20260908": (30, 40, 1000),
    }
    add("2317", "鴻海", "TW", [(d, *f2317[d]) for d in dates])
    f2454 = {
        "20260901": (9, 9, 500),
        "20260902": (9, 9, 500),
        "20260903": (9, 9, 500),
        "20260904": (9, 9, 500),
        "20260905": (9, 9, 500),
        "20260906": (9, 9, 500),
        "20260907": (-4, 2, 500),
        "20260908": (8, -1, 500),
    }
    add("2454", "聯發科", "TW", [(d, *f2454[d]) for d in dates])
    f3105 = {
        "20260901": (-1, 1, 300),
        "20260902": (-1, 1, 300),
        "20260903": (-1, 1, 300),
        "20260904": (-1, 1, 300),
        "20260905": (40, -1, 400),
        "20260906": (50, -1, 400),
        "20260907": (60, -1, 400),
        "20260908": (70, -1, 400),
    }
    add("3105", "穩懋", "TWO", [(d, *f3105[d]) for d in dates])
    conn.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path):
    clear_cache()
    path = str(tmp_path / "s.db")
    _init_db(path)
    yield path
    clear_cache()


def test_parse_helpers():
    assert parse_kind("外資") == KIND_FOREIGN
    assert parse_kind("投信") == KIND_TRUST
    assert parse_kind("外資+投信") == KIND_BOTH
    assert parse_kind("投信外資皆買") == KIND_BOTH
    assert parse_market("上市") == MARKET_TW
    assert parse_market("上櫃") == MARKET_TWO
    assert parse_days("6") == 6
    assert parse_days("25天") == 25
    assert parse_stock_code("2330 台積電") == "2330"


def test_foreign_tw_exact_days_and_lots(db):
    snap = load_snapshot(db, KIND_FOREIGN, MARKET_TW, as_of="20260908", use_cache=False)
    assert snap.as_of == "20260908"
    assert snap.max_days == 6
    assert snap.days_menu() == [6, 5, 4, 3, 2]
    six = snap.stocks(6)
    assert [r.stock_id for r in six] == ["2330"]
    row = six[0]
    assert row.foreign_lots == 100 + 110 + 120 + 130 + 140 + 150
    assert row.volume_lots == 2000 + 2000 + 2000 + 2000 + 2500 + 2500
    assert row.foreign_pct == round(row.foreign_lots / row.volume_lots * 100, 1)
    lines = format_row_lines(row, KIND_FOREIGN)
    assert "6日連買 750張" in lines[0]
    assert "佔6日總成交 5.8%" in lines[1]
    assert snap.stocks(3)[0].stock_id == "2317"
    assert not snap.stocks(1)
    assert find_row(snap, 6, "2454") is None


def test_trust_and_both_require_matching_days(db):
    trust = load_snapshot(db, KIND_TRUST, MARKET_TW, as_of="20260908", use_cache=False)
    # 2330 trust last 3 days (6,7,8): 4,8,9 — day 6 is +4, 5 is -2, so 3 days
    assert trust.max_days == 3
    t3 = {r.stock_id: r for r in trust.stocks(3)}
    assert set(t3) == {"2330", "2317"}
    assert t3["2330"].trust_lots == 4 + 8 + 9
    both = load_snapshot(db, KIND_BOTH, MARKET_TW, as_of="20260908", use_cache=False)
    # 2330 both: 7-8 only (6 trust+ but wait 6 is foreign+ and trust+ so 3 days 6-8)
    assert both.max_days == 3
    b3 = {r.stock_id: r for r in both.stocks(3)}
    assert "2317" in b3
    assert "2330" in b3
    assert b3["2317"].foreign_lots == 10 + 20 + 30
    assert b3["2317"].trust_lots == 20 + 30 + 40
    lines = format_row_lines(b3["2317"], KIND_BOTH)
    assert "3日皆買" in lines[0]
    assert "外資" in lines[0] and "投信" in lines[0]


def test_two_market_isolated(db):
    tw = load_snapshot(db, KIND_FOREIGN, MARKET_TW, as_of="20260908", use_cache=False)
    two = load_snapshot(db, KIND_FOREIGN, MARKET_TWO, as_of="20260908", use_cache=False)
    assert "3105" not in {r.stock_id for xs in tw.by_days.values() for r in xs}
    assert [r.stock_id for r in two.stocks(4)] == ["3105"]
    assert two.stocks(4)[0].foreign_lots == 40 + 50 + 60 + 70


def test_etf_excluded(db):
    conn = sqlite3.connect(db)
    dates = ["20260907", "20260908"]
    for d in dates:
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, "0050", "元大台灣50", "TW", 10, 11, 9, 10, 9000, 0, 0, 10, 500, 0, 0),
        )
    conn.commit()
    conn.close()
    snap = load_snapshot(db, KIND_FOREIGN, MARKET_TW, as_of="20260908", use_cache=False)
    ids = {r.stock_id for xs in snap.by_days.values() for r in xs}
    assert "0050" not in ids


def test_list_html_mentions_exact_days(db):
    snap = load_snapshot(db, KIND_FOREIGN, MARKET_TW, as_of="20260908", use_cache=False)
    html = format_list_html(snap, 6, db)
    assert "剛好連買 6 天" in html
    assert "2330" in html
    assert "750張" in html


def _raw_streak(conn, sid, kind, as_of, lookback=80):
    dates = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT date FROM daily_quotes WHERE date<=? ORDER BY date DESC LIMIT ?",
            (as_of, lookback),
        )
    ]
    dates = list(reversed(dates))
    bars = {
        r[0]: (int(r[1] or 0), int(r[2] or 0), int(r[3] or 0))
        for r in conn.execute(
            "SELECT date, foreign_net, trust_net, volume FROM daily_quotes WHERE stock_id=? AND date<=?",
            (sid, as_of),
        )
    }
    n = f_acc = t_acc = v_acc = 0
    for d in reversed(dates):
        if d not in bars:
            break
        f, t, v = bars[d]
        ok = (f > 0) if kind == KIND_FOREIGN else (t > 0) if kind == KIND_TRUST else (f > 0 and t > 0)
        if not ok:
            break
        n += 1
        f_acc += f
        t_acc += t
        v_acc += v
    return n, f_acc, t_acc, v_acc


def test_production_as_of_matches_official_fuse_end():
    """連買最後一天必須是官方融合收盤日（目前應為 20260903）。"""
    from pathlib import Path

    from trading_calendar import fuse_end_trading_date, resolve_screen_as_of

    db_path = "data/wayne_market.db"
    if not Path(db_path).exists():
        pytest.skip("no production db")
    clear_cache()
    cap = fuse_end_trading_date()
    official = resolve_screen_as_of(db_path)
    assert official == cap, f"official={official} cap={cap}"
    snap = load_snapshot(db_path, KIND_FOREIGN, MARKET_TW, use_cache=False)
    assert snap.as_of == official


def test_streak_last_bar_is_as_of(db):
    snap = load_snapshot(db, KIND_FOREIGN, MARKET_TW, as_of="20260908", use_cache=False)
    row = snap.stocks(6)[0]
    conn = sqlite3.connect(db)
    last = conn.execute(
        "SELECT foreign_net FROM daily_quotes WHERE stock_id=? AND date=?",
        (row.stock_id, snap.as_of),
    ).fetchone()
    conn.close()
    assert last is not None
    assert int(last[0]) > 0


@pytest.mark.parametrize("round_i", range(10))
def test_production_db_ten_rounds_match_raw_sql(round_i):
    """十輪：抽樣上市／上櫃 × 三種連買，張數與％必須等於原始日K加總。"""
    db_path = "data/wayne_market.db"
    if not Path(db_path).exists():
        pytest.skip("no production db")
    clear_cache()
    kinds = (KIND_FOREIGN, KIND_TRUST, KIND_BOTH)
    markets = (MARKET_TW, MARKET_TWO)
    kind = kinds[round_i % 3]
    market = markets[(round_i // 3) % 2]
    snap = load_snapshot(db_path, kind, market, use_cache=False)
    assert snap.as_of
    if snap.max_days < MIN_STREAK:
        return
    assert snap.days_menu()[0] == snap.max_days
    conn = sqlite3.connect(db_path)
    checked = 0
    for days in snap.days_menu()[:4]:
        for row in snap.stocks(days)[:3]:
            n, f, t, v = _raw_streak(conn, row.stock_id, kind, snap.as_of)
            assert n == row.days == days
            assert f == row.foreign_lots
            assert t == row.trust_lots
            assert v == row.volume_lots
            if v > 0:
                if kind == KIND_FOREIGN:
                    assert row.foreign_pct == round(f / v * 100, 1)
                elif kind == KIND_TRUST:
                    assert row.trust_pct == round(t / v * 100, 1)
                else:
                    assert row.foreign_pct == round(f / v * 100, 1)
                    assert row.trust_pct == round(t / v * 100, 1)
            checked += 1
    conn.close()
    assert checked >= 1
