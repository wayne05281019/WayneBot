# -*- coding: utf-8 -*-
"""復原路漏斗：硬閘／兩欄／處置解析（非買訊）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from recovery_funnel import (
    active_punish_ids,
    ensure_recovery_tables,
    format_recovery_funnel_html,
    run_recovery_funnel,
)


def _mem_db(tmp_path: Path) -> str:
    db = str(tmp_path / "rec.db")
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE stock_universe (
          stock_id TEXT PRIMARY KEY, stock_name TEXT, market_type TEXT,
          asset_type TEXT, industry TEXT, is_active INT, updated_at TEXT
        );
        CREATE TABLE daily_quotes (
          date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
          open REAL, high REAL, low REAL, close REAL, volume REAL,
          turnover_k REAL, pct_change REAL
        );
        CREATE TABLE index_daily (
          date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
          volume REAL, regime TEXT
        );
        CREATE TABLE quarterly_income (
          stock_id TEXT, year INT, season INT, eps REAL
        );
        CREATE TABLE monthly_revenue (
          stock_id TEXT, yyyymm TEXT, revenue REAL, yoy_pct REAL
        );
        CREATE TABLE daily_valuation (
          stock_id TEXT, date TEXT, pe REAL
        );
        CREATE TABLE stock_fine_industry (
          stock_id TEXT PRIMARY KEY, chain TEXT
        );
        """
    )
    desk = "20261119"
    con.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
        (desk, "TWII", 40000, 40100, 38000, 38426, 1e7, "bear"),
    )
    specs = (
        ("6115", "鎰勝", "TW", "STOCK", "電子零組件業", "電子上游-連接元件", 1.2, 10.0, 12.0),
        ("9907", "統一實", "TW", "STOCK", "其他業", "傳產-鋼鐵", -0.2, -20.0, 50.0),
        ("0050", "元大台灣50", "TW", "ETF", "ETF", "ETF", 1.0, 5.0, 15.0),
    )
    for sid, name, mkt, atype, ind, fine, eps, yoy, pe in specs:
        con.execute(
            "INSERT INTO stock_universe VALUES (?,?,?,?,?,?,?)",
            (sid, name, mkt, atype, ind, 1, ""),
        )
        con.execute("INSERT INTO stock_fine_industry VALUES (?,?)", (sid, fine))
        base = 40.0
        for j in range(30):
            day = (datetime(2026, 11, 19) - timedelta(days=29 - j)).strftime("%Y%m%d")
            c = base + j * 0.2
            con.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    day,
                    sid,
                    name,
                    "TW",
                    c,
                    c + 0.5,
                    c - 0.5,
                    c,
                    800.0,
                    9000.0 if sid != "0050" else 100.0,
                    0.1,
                ),
            )
        con.execute(
            "INSERT INTO quarterly_income VALUES (?,?,?,?)", (sid, 2026, 3, eps)
        )
        con.execute(
            "INSERT INTO monthly_revenue VALUES (?,?,?,?)", (sid, "202610", 1e6, yoy)
        )
        con.execute(
            "INSERT INTO daily_valuation VALUES (?,?,?)", (sid, desk, pe)
        )
    con.commit()
    con.close()
    ensure_recovery_tables(db)
    return db


def test_format_recovery_two_columns():
    html = format_recovery_funnel_html(
        {
            "as_of": "20261119",
            "regime": "bear",
            "twii": {"date": "20261119", "c": 38426.89},
            "buy_ok": [
                {"sid": "6115", "name": "鎰勝", "entry": ["winrate"], "labels": ["首日"]}
            ],
            "observe": [
                {"sid": "9907", "name": "統一實", "entry": [], "labels": ["還在零"]}
            ],
            "punish_n": 0,
        }
    )
    assert "真可買" in html and "復原觀察" in html
    assert "6115" in html and "9907" in html
    assert "不准總分" in html
    assert "尚等買點" in html
    # 真可買一檔一行，不准長串頓號塞爆
    buy_chunk = html.split("<b>真可買</b>")[1].split("<b>復原觀察</b>")[0]
    assert "6115 鎰勝" in buy_chunk


def test_format_recovery_observe_entry_blocked_not_wait_buy():
    """已有買訊但估值閘擋 → 不准寫成「尚等買點」。"""
    html = format_recovery_funnel_html(
        {
            "as_of": "20261117",
            "regime": "bear",
            "twii": {"date": "20261117", "c": 38000.0},
            "buy_ok": [],
            "observe": [
                {
                    "sid": "2317",
                    "name": "鴻海",
                    "entry": ["leave_zero", "winrate"],
                    "labels": ["首日"],
                    "reasons": ["本益落後"],
                    "signals": ["leave_zero", "winrate"],
                },
                {
                    "sid": "2476",
                    "name": "鉅祥",
                    "entry": [],
                    "labels": [],
                    "reasons": [],
                    "signals": ["undervalue_star"],
                },
            ],
            "punish_n": 0,
        }
    )
    assert "買訊被擋" in html
    assert "買訊被擋≠尚等買點" in html
    obs = html.split("<b>復原觀察</b>")[1]
    # 分桶：2317 在買訊被擋；2476 在連買／估值等；不准混成尚等買點
    blocked = obs.split("·買訊被擋")[1].split("·")[0]
    assert "2317" in blocked
    assert "尚等買點" not in blocked
    assert "連買／估值等" in obs
    assert "2476" in obs.split("·連買／估值等")[1]


def test_golden_buy_dict_rows_norm_sid_not_dict_repr(tmp_path: Path, monkeypatch):
    """海選 golden_buy 列是 dict 時，sid 必須是代號，HTML 不准出現 stock_id 字面。"""
    from recovery_funnel import _collect_signal_maps
    from screen_sessions import save_screen_session

    db = _mem_db(tmp_path)
    day = "20261119"
    save_screen_session(
        db,
        day,
        "evening",
        {
            "leave_zero": [],
            "ma60_lower": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 1000.0}
            ],
            "golden_buy": [
                {
                    "stock_id": "1304",
                    "stock_name": "台聚",
                    "close": 11.05,
                    "hi20_close": 14.0,
                    "entry_price": None,
                    "defense_price": None,
                    "chase_warning": False,
                }
            ],
        },
    )
    # 宇宙補 1304／2330
    con = sqlite3.connect(db)
    for sid, name in (("1304", "台聚"), ("2330", "台積電")):
        con.execute(
            "INSERT OR REPLACE INTO stock_universe VALUES (?,?,?,?,?,?,?)",
            (sid, name, "TW", "STOCK", "塑膠工業", 1, ""),
        )
        for j in range(30):
            d = (datetime(2026, 11, 19) - timedelta(days=29 - j)).strftime("%Y%m%d")
            c = 11.0 + j * 0.01
            con.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (d, sid, name, "TW", c, c + 0.2, c - 0.2, c, 900.0, 8000.0, 0.1),
            )
        con.execute(
            "INSERT OR REPLACE INTO daily_valuation VALUES (?,?,?)", (sid, day, 12.0)
        )
    con.commit()
    con.close()

    sigs, names = _collect_signal_maps(db, day)
    assert "1304" in sigs and "golden_buy" in sigs["1304"]
    assert "2330" in sigs and "ma60_lower" in sigs["2330"]
    assert names.get("1304") == "台聚"
    assert all(not (isinstance(k, str) and k.startswith("{")) for k in sigs)

    monkeypatch.setattr("recovery_funnel.fetch_and_store_punish", lambda *a, **k: 0)
    out = run_recovery_funnel(db, as_of=day, refresh_punish=False)
    html = format_recovery_funnel_html(out)
    assert "stock_id" not in html
    assert "&#x27;stock_id&#x27;" not in html
    obs_sids = {r["sid"] for r in out["observe"]}
    buy_sids = {r["sid"] for r in out["buy_ok"]}
    assert "1304" in obs_sids or "1304" in buy_sids
    assert all(isinstance(s, str) and not s.startswith("{") for s in obs_sids | buy_sids)


def test_collect_leave_zero_prefers_screen_over_empty_live_judge(tmp_path: Path, monkeypatch):
    """復原路 leave_zero 必須吃海選桶（與綜合篩選同源）；不准只靠空 live_judge 漏掉。"""
    from recovery_funnel import _collect_signal_maps
    from screen_sessions import save_screen_session

    db = _mem_db(tmp_path)
    day = "20261119"
    save_screen_session(
        db,
        day,
        "morning",
        {
            "leave_zero": [
                {"stock_id": "4728", "stock_name": "雙美", "pick_close": 80.0}
            ],
            "ma60_lower": [],
            "golden_buy": [],
        },
    )
    con = sqlite3.connect(db)
    con.execute(
        "INSERT OR REPLACE INTO stock_universe VALUES (?,?,?,?,?,?,?)",
        ("4728", "雙美", "TW", "STOCK", "生技醫療業", 1, ""),
    )
    con.commit()
    con.close()

    # live_judge 一律空 → 仍必須從海選桶拿到 leave_zero
    monkeypatch.setattr(
        "pipeline_observe._live_judge_pack",
        lambda *a, **k: ("", []),
    )
    sigs, names = _collect_signal_maps(db, day)
    assert "4728" in sigs and "leave_zero" in sigs["4728"]
    assert names.get("4728") == "雙美"


def test_format_recovery_defends_dict_repr_sid():
    """舊 payload sid 誤為 dict／dict 字串時，格式化仍出代號，不准整列 dump。"""
    html = format_recovery_funnel_html(
        {
            "as_of": "20261106",
            "regime": "bear",
            "twii": {"date": "20261106", "c": 39702.0},
            "buy_ok": [],
            "observe": [
                {
                    "sid": {
                        "stock_id": "1304",
                        "stock_name": "台聚",
                        "close": 11.05,
                    },
                    "name": "",
                    "entry": [],
                    "labels": ["還在零"],
                },
                {
                    "sid": "{'stock_id': '1308', 'stock_name': '亞聚', 'close': 12.25}",
                    "name": "",
                    "entry": [],
                    "labels": ["還在零"],
                },
            ],
            "punish_n": 0,
        }
    )
    assert "1304" in html and "台聚" in html
    assert "1308" in html and "亞聚" in html
    assert "stock_id" not in html
    assert "&#x27;stock_id&#x27;" not in html


def test_punish_active_window(tmp_path: Path):
    db = str(tmp_path / "p.db")
    ensure_recovery_tables(db)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO recovery_punish VALUES (?,?,?,?,?,?)",
        ("1234", "punish", "20261118", "20261122", "第一次處置", "t"),
    )
    con.commit()
    con.close()
    assert "1234" in active_punish_ids(db, "20261120")
    assert "1234" not in active_punish_ids(db, "20261123")


def test_run_funnel_excludes_etf_and_keeps_structure(tmp_path: Path, monkeypatch):
    db = _mem_db(tmp_path)

    def fake_maps(db_path, desk):
        return (
            {
                "6115": {"winrate"},
                "9907": {"leave_zero"},
                "0050": {"winrate"},
            },
            {"6115": "鎰勝", "9907": "統一實", "0050": "元大台灣50"},
        )

    monkeypatch.setattr("recovery_funnel._collect_signal_maps", fake_maps)
    monkeypatch.setattr("recovery_funnel.fetch_and_store_punish", lambda *a, **k: 0)

    out = run_recovery_funnel(db, as_of="20261119", refresh_punish=False)
    sids_buy = {r["sid"] for r in out["buy_ok"]}
    sids_obs = {r["sid"] for r in out["observe"]}
    assert "0050" not in sids_buy and "0050" not in sids_obs
    # 9907 本益 50 → 本益過熱，不准真可買（可進觀察）
    assert "9907" not in sids_buy
    assert "9907" in sids_obs
    # 6115 有買訊＋當日本益＋額度夠 → 真可買
    assert "6115" in sids_buy


def test_buy_ok_rejects_stale_or_missing_pe(tmp_path: Path, monkeypatch):
    from recovery_funnel import _pe_fresh_ok

    assert _pe_fresh_ok("20261120", "20261120", "TWO")
    assert not _pe_fresh_ok("20261109", "20261120", "TWO")
    assert _pe_fresh_ok("20261119", "20261120", "TW")  # 上市允許 T-1
    assert not _pe_fresh_ok("20261106", "20261120", "TW")

    db = _mem_db(tmp_path)
    con = sqlite3.connect(db)
    # 3685 風格：有買訊但本益缺
    con.execute(
        "INSERT INTO stock_universe VALUES (?,?,?,?,?,?,?)",
        ("3685", "元創精密", "TWO", "STOCK", "電機機械", 1, ""),
    )
    con.execute("INSERT INTO stock_fine_industry VALUES (?,?)", ("3685", "機構"))
    for j in range(30):
        day = (datetime(2026, 11, 19) - timedelta(days=29 - j)).strftime("%Y%m%d")
        c = 25.0 + j * 0.1
        con.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (day, "3685", "元創精密", "TWO", c, c + 0.5, c - 0.5, c, 800.0, 9000.0, 0.1),
        )
    con.execute(
        "INSERT INTO daily_valuation VALUES (?,?,?)", ("3685", "20261119", None)
    )
    # 5314 風格：本益落後多日
    con.execute(
        "INSERT INTO stock_universe VALUES (?,?,?,?,?,?,?)",
        ("5314", "世紀*", "TWO", "STOCK", "其他業", 1, ""),
    )
    con.execute("INSERT INTO stock_fine_industry VALUES (?,?)", ("5314", "其他"))
    for j in range(30):
        day = (datetime(2026, 11, 19) - timedelta(days=29 - j)).strftime("%Y%m%d")
        c = 22.0 + j * 0.1
        con.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (day, "5314", "世紀*", "TWO", c, c + 0.5, c - 0.5, c, 800.0, 9000.0, 0.1),
        )
    con.execute(
        "INSERT INTO daily_valuation VALUES (?,?,?)", ("5314", "20261109", 4.6)
    )
    con.commit()
    con.close()

    def fake_maps(db_path, desk):
        return (
            {
                "6115": {"winrate"},
                "3685": {"leave_zero"},
                "5314": {"leave_zero"},
            },
            {"6115": "鎰勝", "3685": "元創精密", "5314": "世紀*"},
        )

    monkeypatch.setattr("recovery_funnel._collect_signal_maps", fake_maps)
    monkeypatch.setattr("recovery_funnel.fetch_and_store_punish", lambda *a, **k: 0)
    out = run_recovery_funnel(db, as_of="20261119", refresh_punish=False)
    buy = {r["sid"] for r in out["buy_ok"]}
    assert "6115" in buy
    assert "3685" not in buy
    assert "5314" not in buy
    reasons = {r["sid"]: r.get("reasons") for r in out["observe"]}
    assert "本益缺" in (reasons.get("3685") or [])
    assert "本益落後" in (reasons.get("5314") or [])


def test_schedule_hooks_wired():
    main_src = Path("main.py").read_text(encoding="utf-8")
    runner = Path("main_runner.py").read_text(encoding="utf-8")
    observe = Path("pipeline_observe.py").read_text(encoding="utf-8")
    assert '(6, 45, "recovery")' in main_src
    assert 'kind == "recovery"' in main_src
    assert "recovery-funnel" in runner
    assert "format_recovery_funnel_html" in observe
    assert "load_recovery_run" in observe
