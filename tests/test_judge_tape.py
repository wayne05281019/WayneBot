# -*- coding: utf-8 -*-
"""當下判斷默默落檔：不改畫面、不寫未收盤、官方收才對隔日／五日。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from judge_tape import remember_rows, score_live_judges, store_path
from screening_engine import ScreeningEngine
from screen_sessions import save_screen_session
from wayne_db import ensure_core_schema


def _seed(db: str, last: dict[str, float], as_of: str = "20260915") -> None:
    ensure_core_schema(db)
    start = datetime(2026, 8, 1)
    end = datetime.strptime(as_of, "%Y%m%d")
    conn = sqlite3.connect(db)
    d = start
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        is_last = d == end
        for sid, px in last.items():
            close = float(px if is_last else 50.0)
            conn.execute(
                "INSERT OR REPLACE INTO daily_quotes("
                "date,stock_id,stock_name,market,open,high,low,close,volume,"
                "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ymd, sid, sid, "TW", close, close, close, close, 8000, 400000, 0.0, close),
            )
        d += timedelta(days=1)
    conn.commit()
    conn.close()


def test_remember_stays_off_product_db_and_scores_next_close(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.0}, "20260915")
    n = remember_rows(
        db,
        "leave_zero",
        [{"stock_id": "1101", "stock_name": "台泥", "close": 50.0, "profit_pct": 0.8}],
        as_of="20260915",
    )
    assert n == 1
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "live_judge" not in names
    store = store_path(db)
    assert Path(store).name == "wayne_evolve.db"
    conn = sqlite3.connect(store)
    row = conn.execute(
        "SELECT kind, sid, px FROM live_judge WHERE as_of='20260915'"
    ).fetchone()
    conn.close()
    assert row == ("leave_zero", "1101", 50.0)

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO daily_quotes("
        "date,stock_id,stock_name,market,open,high,low,close,volume,"
        "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260916", "1101", "台泥", "TW", 51.0, 51.0, 51.0, 51.0, 8000, 400000, 2.0, 51.0),
    )
    conn.commit()
    conn.close()
    filled = score_live_judges(db, "20260916")
    assert filled >= 1
    conn = sqlite3.connect(store)
    sc = conn.execute(
        "SELECT horizon, check_as_of, fwd_pct, verdict FROM live_judge_score "
        "WHERE sid='1101' AND horizon=1"
    ).fetchone()
    conn.close()
    assert sc[0] == 1
    assert sc[1] == "20260916"
    assert abs(float(sc[2]) - 2.0) < 0.01
    assert sc[3] == "up"


def test_unclosed_bar_is_not_used_for_score(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.0}, "20260915")
    remember_rows(
        db,
        "day_trade",
        [{"stock_id": "1101", "close": 50.0}],
        as_of="20260915",
    )
    assert score_live_judges(db, "20260915") == 0
    store = store_path(db)
    conn = sqlite3.connect(store)
    n = conn.execute("SELECT COUNT(*) FROM live_judge_score").fetchone()[0]
    conn.close()
    assert n == 0
    conn = sqlite3.connect(db)
    extra = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE REPLACE(CAST(date AS TEXT),'-','')>'20260915'"
    ).fetchone()[0]
    conn.close()
    assert extra == 0


def test_leave_zero_now_still_returns_same_and_remembers(tmp_path, monkeypatch):
    db = str(tmp_path / "lz.db")
    _seed(db, {"1101": 50.4, "1102": 50.0}, "20260915")
    save_screen_session(
        db,
        "20260915",
        "morning",
        {
            "leave_zero": [{"stock_id": "1101", "stock_name": "台泥", "close": 50.4}],
            "golden_buy": [{"stock_id": "1102", "stock_name": "亞泥", "close": 50.0}],
        },
    )
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: False)
    engine = ScreeningEngine(db)
    rows = engine.screen_leave_zero_now("20260915")
    assert [r["code"] for r in rows] == ["1101"]
    store = store_path(db)
    conn = sqlite3.connect(store)
    sids = [r[0] for r in conn.execute("SELECT sid FROM live_judge WHERE kind='leave_zero'")]
    conn.close()
    assert sids == ["1101"]


def test_snapshot_button_lists_without_press_freezes_bar_not_png(tmp_path):
    from judge_tape import snapshot_button_lists

    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.4, "1102": 51.0}, "20260915")
    save_screen_session(
        db,
        "20260915",
        "morning",
        {
            "leave_zero": [{"stock_id": "1101", "stock_name": "台泥", "close": 50.4}],
            "day_trade": [{"stock_id": "1102", "stock_name": "亞泥", "close": 51.0}],
        },
    )
    stats = snapshot_button_lists(db, "20260915")
    assert stats.get("leave_zero") == 1
    assert stats.get("day_trade") == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    rows = conn.execute(
        "SELECT kind, sid, extra FROM live_judge WHERE pick='rule' AND sid!=''"
    ).fetchall()
    conn.close()
    by_kind = {k: (sid, extra) for k, sid, extra in rows}
    assert by_kind["leave_zero"][0] == "1101"
    extra = json.loads(by_kind["leave_zero"][1])
    assert extra["c"] == 50.4
    assert extra["o"] == 50.4
    assert extra["h"] == 50.4
    assert extra["l"] == 50.4
    assert extra["v"] == 8000
    assert extra.get("src") == "session"
    blob = json.dumps(extra)
    assert "png" not in blob.lower()
    assert "jpeg" not in blob.lower()
    assert "image" not in blob.lower()
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "live_judge" not in names


def test_remember_keeps_why_and_official_chips(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.4}, "20260915")
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE daily_quotes SET foreign_net=120, trust_net=30, dealer_net=-10, pct_change=1.5 "
        "WHERE stock_id='1101' AND date='20260915'"
    )
    conn.commit()
    conn.close()
    n = remember_rows(
        db,
        "leave_zero",
        [
            {
                "stock_id": "1101",
                "stock_name": "台泥",
                "close": 50.4,
                "profit_pct": 0.8,
                "why": "獲利剛離零且趨勢向上",
                "q": 2.1,
            }
        ],
        as_of="20260915",
    )
    assert n == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    extra = json.loads(
        conn.execute("SELECT extra FROM live_judge WHERE sid='1101'").fetchone()[0]
    )
    conn.close()
    assert extra["why"] == "獲利剛離零且趨勢向上"
    assert extra["q"] == 2.1
    assert extra["fn"] == 120
    assert extra["tn"] == 30
    assert extra["dn"] == -10
    assert extra["pct"] == 1.5
    assert extra["v"] == 8000


def test_snapshot_dongzhu_without_press(tmp_path, monkeypatch):
    from judge_tape import snapshot_button_lists

    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"2408": 56.0}, "20260915")

    def fake_picks(_db, *, spoken=None, record_flow=True):
        del spoken
        assert record_flow is False
        return {
            "field": "記憶體製造",
            "why": "佔比升還沒當第一",
            "five": "量價結構：量起來。",
            "recs": [
                {
                    "sid": "2408",
                    "name": "南亞科",
                    "close": 56.0,
                    "role": "次級",
                    "vs20": -8.0,
                }
            ],
        }

    monkeypatch.setattr("biaoke_field_scan.dongzhu_picks", fake_picks)
    stats = snapshot_button_lists(db, "20260915")
    assert stats.get("dongzhu") == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    row = conn.execute(
        "SELECT sid, extra FROM live_judge WHERE kind='dongzhu' AND sid!=''"
    ).fetchone()
    conn.close()
    assert row[0] == "2408"
    extra = json.loads(row[1])
    assert extra["why"] == "佔比升還沒當第一"
    assert extra["five"] == "量價結構：量起來。"
    assert extra["field"] == "記憶體製造"
    assert extra["src"] == "dongzhu"


def test_leave_zero_pick_remembers_stable_pick_not_button_label(tmp_path, monkeypatch):
    db = str(tmp_path / "lz.db")
    _seed(db, {"1101": 50.0}, "20260915")
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: False)
    engine = ScreeningEngine(db)
    monkeypatch.setattr(engine, "_load_profit_scan_frames", lambda as_of: ({}, set()))
    assert engine.screen_leave_zero_pick("20260915", pick="z") == []
    assert engine.screen_leave_zero_pick("20260915", pick="2") == []
    store = store_path(db)
    conn = sqlite3.connect(store)
    rows = conn.execute(
        "SELECT kind, pick, sid FROM live_judge WHERE kind='leave_zero'"
    ).fetchall()
    conn.close()
    assert all(str(r[2] or "").strip() for r in rows)
    picks = {str(p): str(k) for k, p, _sid in rows}
    assert "獲利為零" not in picks
    assert "脫離2" not in picks
    assert "剛脫離零" not in picks


def test_remember_keeps_star_trend_and_buy_gate(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.4}, "20260915")
    n = remember_rows(
        db,
        "leave_zero",
        [
            {
                "stock_id": "1101",
                "stock_name": "台泥",
                "close": 50.4,
                "profit_pct": 0.8,
                "entry_stars": 5,
                "buy_star": True,
                "bucket_key": "leave_zero",
                "buy_gate": "ok",
                "trend_up_now": True,
                "trend_now_label": "趨勢已向上",
                "leave_days": 1,
            }
        ],
        as_of="20260915",
        pick="1",
    )
    assert n == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    kind, pick, extra_raw = conn.execute(
        "SELECT kind, pick, extra FROM live_judge WHERE sid='1101'"
    ).fetchone()
    conn.close()
    assert kind == "leave_zero"
    assert pick == "1"
    extra = json.loads(extra_raw)
    assert extra["entry_stars"] == 5
    assert extra["buy_star"] is True
    assert extra["bucket_key"] == "leave_zero"
    assert extra["buy_gate"] == "ok"
    assert extra["trend_up_now"] is True
    assert extra["leave_days"] == 1


def test_snapshot_outer_and_market_without_yahoo(tmp_path):
    from judge_tape import snapshot_button_lists

    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.4}, "20260915")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TWII',
            close REAL NOT NULL,
            volume REAL DEFAULT 0,
            pct_change REAL DEFAULT 0,
            ma20 REAL,
            ma60 REAL,
            regime TEXT,
            updated_at TEXT NOT NULL DEFAULT '',
            open REAL,
            high REAL,
            low REAL,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO index_daily(
            date, symbol, open, high, low, close, volume, pct_change, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        ("20260915", "TWII", 27000.0, 27100.0, 26900.0, 27050.0, 8e10, 0.2, "t"),
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS us_overnight (
            as_of TEXT PRIMARY KEY, payload TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO us_overnight(as_of, payload) VALUES (?,?)",
        (
            "20260915",
            json.dumps(
                {
                    "brent_px": 97.47,
                    "brent_pct": -1.79,
                    "dx_f_px": 101.06,
                    "dx_f_pct": 0.62,
                    "usdtwd_px": 31.763,
                    "usdtwd_pct": 0.08,
                    "ixic_px": 22000.0,
                    "ixic_pct": 0.8,
                    "sox_px": 5400.0,
                    "sox_pct": -0.4,
                    "tsm_px": 185.0,
                    "tsm_pct": 1.2,
                },
                ensure_ascii=False,
            ),
        ),
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS futures_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TX',
            session TEXT NOT NULL DEFAULT 'regular',
            open REAL, high REAL, low REAL, close REAL NOT NULL,
            volume INTEGER DEFAULT 0, pct_change REAL DEFAULT 0,
            PRIMARY KEY (date, symbol, session)
        )
        """
    )
    for sid, sess, px in (
        ("TX", "regular", 24000.0),
        ("TX", "night", 23900.0),
        ("TE", "regular", 15000.0),
        ("TE", "night", 14950.0),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO futures_daily("
            "date,symbol,session,open,high,low,close,volume,pct_change) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("20260915", sid, sess, px, px, px, px, 100, 0.1),
        )
    conn.commit()
    conn.close()
    stats = snapshot_button_lists(db, "20260915")
    assert stats.get("market") == 1
    assert stats.get("outer") == 3
    assert stats.get("fut") == 4
    assert stats.get("us") == 3
    store = store_path(db)
    conn = sqlite3.connect(store)
    tw = conn.execute(
        "SELECT sid, px, extra FROM live_judge WHERE kind='market' AND sid!=''"
    ).fetchone()
    outer = conn.execute(
        "SELECT sid, px, extra FROM live_judge WHERE kind='outer' AND sid!='' ORDER BY sid"
    ).fetchall()
    fut = conn.execute(
        "SELECT sid, px FROM live_judge WHERE kind='fut' AND sid!='' ORDER BY sid"
    ).fetchall()
    us = conn.execute(
        "SELECT sid, px, extra FROM live_judge WHERE kind='us' AND sid!='' ORDER BY sid"
    ).fetchall()
    conn.close()
    assert tw[0] == "TWII"
    assert abs(float(tw[1]) - 27050.0) < 0.01
    sids = [r[0] for r in outer]
    assert sids == ["_BRENT", "_DXY", "_USDTWD"]
    brent = json.loads(outer[0][2])
    assert abs(float(brent["c"]) - 97.47) < 0.01
    assert brent.get("src") == "outer"
    assert [r[0] for r in fut] == ["_TE_D", "_TE_N", "_TX_D", "_TX_N"]
    assert abs(float(fut[2][1]) - 24000.0) < 0.01
    assert [r[0] for r in us] == ["_IXIC", "_SOX", "_TSMUS"]
    ixic = json.loads(us[0][2])
    assert abs(float(ixic["c"]) - 22000.0) < 0.01
    assert abs(float(ixic["pct"]) - 0.8) < 0.01
    assert ixic.get("src") == "us"
    src = Path("judge_tape.py").read_text(encoding="utf-8")
    assert "query1.finance" not in src
    assert "fetch_outer_tape" not in src
    assert score_live_judges(db, "20260916") == 0


def test_agents_silent_record_is_rank_three():
    text = Path("AGENTS.md").read_text(encoding="utf-8")
    assert "默默落檔（2026-09-21 鎖死）" in text
    assert "沒按也一樣" in text
    assert "佐證同時留（數字，不是每檔截圖）" in text
    assert "每檔每天 K 圖 PNG" in text
    assert "對話不准報" in text
    assert "還沒做／做到一半" in text
    assert "明確優化狀態" in text
    assert "近窗" in text
    assert "不准等使用者提醒才記" in text
    assert "能講才講（B）" in text
    assert "空名單／空代號不算有記" in text
    assert "對後續判斷／對質有幫助的官方收才凍" in text
    assert "對質結果要講" not in text
    i3 = text.find("## 3. 能量化就直接量化")
    i4 = text.find("## 4. 不准假資料")
    i_silent = text.find("### 默默落檔")
    assert 0 < i3 < i_silent < i4


def test_empty_list_is_not_a_recorded_day(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.0}, "20260915")
    n = remember_rows(db, "leave_zero", [], as_of="20260915", pick="z", src="radar")
    assert n == 0
    store = store_path(db)
    assert not Path(store).is_file() or sqlite3.connect(store).execute(
        "SELECT COUNT(*) FROM live_judge"
    ).fetchone()[0] == 0


def test_snapshot_falls_back_to_screen_picks_with_real_sids(tmp_path):
    from judge_tape import snapshot_button_lists
    from screen_review import save_screen_picks

    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"2330": 900.0, "2454": 1400.0}, "20260915")
    save_screen_picks(
        db,
        "20260915",
        {
            "leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 900.0}],
            "golden_buy": [{"stock_id": "2454", "stock_name": "聯發科", "close": 1400.0}],
        },
    )
    stats = snapshot_button_lists(db, "20260915")
    assert stats.get("leave_zero") == 1
    assert stats.get("golden_buy") == 1
    store = store_path(db)
    conn = sqlite3.connect(store)
    rows = conn.execute(
        "SELECT kind, sid, extra FROM live_judge WHERE pick='rule' AND sid!=''"
    ).fetchall()
    conn.close()
    by_kind = {k: (sid, extra) for k, sid, extra in rows}
    assert by_kind["leave_zero"][0] == "2330"
    extra = json.loads(by_kind["leave_zero"][1])
    assert extra["c"] == 900.0
    assert extra["o"] == 900.0
    assert extra["h"] == 900.0
    assert extra["l"] == 900.0
    assert extra["v"] == 8000
    assert extra.get("src") == "picks"
    assert by_kind["golden_buy"][0] == "2454"


def test_leave_zero_radar_snapshot_remembers_real_sids(tmp_path, monkeypatch):
    from judge_tape import _snapshot_leave_zero_picks

    db = str(tmp_path / "wayne_market.db")
    _seed(db, {"1101": 50.4}, "20260915")

    class FakeEngine:
        def __init__(self, _db):
            pass

        def _load_profit_scan_frames(self, _day):
            return ({"1101": None}, set())

        def _screen_leave_zero_from_profit(self, _day, **kwargs):
            if kwargs.get("mode") == "ago" and kwargs.get("days_ago") == 0:
                return [{"stock_id": "1101", "stock_name": "台泥", "close": 50.4}]
            return []

    monkeypatch.setattr("screening_engine.ScreeningEngine", FakeEngine)
    stats = _snapshot_leave_zero_picks(db, "20260915")
    assert stats.get("leave_zero_0") == 1
    assert stats.get("leave_zero_z") is None
    store = store_path(db)
    conn = sqlite3.connect(store)
    row = conn.execute(
        "SELECT sid, pick, extra FROM live_judge WHERE kind='leave_zero' AND sid!=''"
    ).fetchone()
    blanks = conn.execute(
        "SELECT COUNT(*) FROM live_judge WHERE sid=''"
    ).fetchone()[0]
    conn.close()
    assert row[0] == "1101"
    assert row[1] == "0"
    extra = json.loads(row[2])
    assert extra["c"] == 50.4
    assert extra["v"] == 8000
    assert extra.get("src") == "radar"
    assert blanks == 0


def test_snapshot_skips_screenshot_and_telegram():
    src = Path("judge_tape.py").read_text(encoding="utf-8")
    assert "snapshot_button_lists" in src
    assert "savefig" not in src
    assert "Image.save" not in src
    assert "send_telegram" not in src
    assert "render_twii" not in src
    fc = Path("biaoke_forecast.py").read_text(encoding="utf-8")
    assert "ensure_wave_inputs" in fc
    assert 'os.getenv("PYTEST_CURRENT_TEST")' in fc
    src = Path("judge_tape.py").read_text(encoding="utf-8")
    assert "send_telegram" not in src
    assert "TELEGRAM_BOT_TOKEN" not in src
    silent = Path("silent_progress.py").read_text(encoding="utf-8")
    assert "judge_tape" not in silent
    assert "remember_rows" not in silent
    bot = Path("bot_servers.py").read_text(encoding="utf-8")
    assert "judge_tape" not in bot
