# -*- coding: utf-8 -*-
"""洞燭每日落檔：不必按鈕；隔日官方收對質；不改黃金買點。"""
import sqlite3
from datetime import datetime, timedelta

from dongzhu_tape import (
    score_dongzhu_picks,
    scoreboard_lines,
    snapshot_and_score_dongzhu,
    snapshot_dongzhu_picks,
    snapshot_screen_picks,
    tape_store_path,
    write_snapshot,
)
from wayne_db import PRIVATE_USER_TABLES


def _quotes(db: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS daily_quotes ("
        "date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, "
        "PRIMARY KEY (date, stock_id))"
    )
    conn.commit()
    conn.close()


def _put(db: str, sid: str, day: str, close: float, high=None) -> None:
    high = close if high is None else high
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO daily_quotes("
        "date, stock_id, stock_name, open, high, low, close, volume) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (day, sid, sid, close, high, close, close, 1000),
    )
    conn.commit()
    conn.close()


def _bars(db: str, sid: str, last: str, n: int, last_close: float, high: float) -> None:
    end = datetime.strptime(last, "%Y%m%d")
    for i in range(n):
        day = (end - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        close = last_close if i == n - 1 else high * 0.9
        _put(db, sid, day, close, high)


def _store(db: str) -> str:
    return tape_store_path(db)


def test_pick_tables_are_public_not_private():
    for name in (
        "dongzhu_pick_run",
        "dongzhu_pick_tape",
        "dongzhu_pick_score",
        "dongzhu_pick_rates",
        "dongzhu_pick_rule",
    ):
        assert name not in PRIVATE_USER_TABLES


def test_snapshot_skips_zero_close(tmp_path):
    db = str(tmp_path / "t.db")
    _quotes(db)
    n = write_snapshot(
        db,
        {
            "cap": "20260917",
            "field": "高階測試／封測",
            "pre_sign": "pre",
            "flow": {"share_last": 12.3},
            "buys": [
                {"sid": "6257", "name": "矽格", "close": 222.5, "vs20": -8.1},
                {"sid": "0000", "name": "空柱", "close": 0, "vs20": -9.0},
            ],
            "watches": [],
            "laggards": [],
        },
    )
    assert n == 1
    conn = sqlite3.connect(_store(db))
    rows = conn.execute("SELECT sid, why FROM dongzhu_pick_tape").fetchall()
    conn.close()
    assert rows == [("6257", "黃金買點獲利剛離零；高階測試／封測；佔比升還沒第一；距20高 -8.1%")]
    conn = sqlite3.connect(_store(db))
    enc_id, encoding, field = conn.execute(
        "SELECT enc_id, encoding, field FROM dongzhu_pick_tape WHERE sid='6257'"
    ).fetchone()
    rules = conn.execute(
        "SELECT enc_id, spec FROM dongzhu_pick_rule WHERE tag='leave_zero'"
    ).fetchone()
    run_enc = conn.execute("SELECT encoding FROM dongzhu_pick_run").fetchone()[0]
    conn.close()
    assert enc_id == "leave_zero.cal60_leave0_max5"
    assert "222.5" in encoding and "vs20" in encoding
    assert field == "高階測試／封測"
    assert rules[0] == "leave_zero.cal60_leave0_max5"
    assert "近60曆日收盤低" in rules[1]
    assert "leave_zero" in run_enc


def test_next_official_close_scores_hit_miss_pending(tmp_path):
    db = str(tmp_path / "t.db")
    _quotes(db)
    write_snapshot(
        db,
        {
            "cap": "20260917",
            "field": "封測",
            "pre_sign": "pre",
            "buys": [{"sid": "6257", "name": "矽格", "close": 100.0, "vs20": -8.0}],
            "watches": [{"sid": "2449", "name": "京元電子", "close": 100.0, "vs20": -20.0}],
            "laggards": [{"sid": "3264", "name": "欣銓", "close": 90.0, "vs20": -10.0}],
        },
    )
    _put(db, "6257", "20260918", 101.0)
    _put(db, "2449", "20260918", 99.0)
    _bars(db, "3264", "20260918", 25, 93.0, 100.0)
    n = score_dongzhu_picks(db, "20260918")
    assert n == 3
    conn = sqlite3.connect(_store(db))
    got = {
        r[0]: r[1]
        for r in conn.execute("SELECT sid, verdict FROM dongzhu_pick_score").fetchall()
    }
    rates = {
        r[0]: (r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT tag, hit, miss, pending FROM dongzhu_pick_rates WHERE horizon=1"
        ).fetchall()
    }
    conn.close()
    assert got["6257"] == "對"
    assert got["2449"] == "偏"
    assert got["3264"] == "對"
    assert rates["leave_zero"] == (1, 0, 0)
    assert rates["golden_buy"] == (0, 1, 0)
    assert rates["capture"] == (1, 0, 0)
    lines = scoreboard_lines(db, "20260918")
    assert lines[0].startswith("1日對質")
    assert "6257 矽格 對" in lines
    assert "2449 京元電子 偏" in lines
    assert "3264 欣銓 對" in lines
    assert "買點對1偏0還沒0" in lines
    assert "不是改黃金買點" in lines
    assert all(len(x) <= 18 for x in lines)


def test_score_skips_missing_or_zero_official_close(tmp_path):
    db = str(tmp_path / "t.db")
    _quotes(db)
    write_snapshot(
        db,
        {
            "cap": "20260917",
            "buys": [
                {"sid": "6257", "name": "矽格", "close": 100.0},
                {"sid": "2330", "name": "台積電", "close": 100.0},
            ],
        },
    )
    _put(db, "6257", "20260918", 0.0)
    _put(db, "2330", "20260918", 100.2)
    n = score_dongzhu_picks(db, "20260918")
    assert n == 1
    conn = sqlite3.connect(_store(db))
    sids = [r[0] for r in conn.execute("SELECT sid FROM dongzhu_pick_score").fetchall()]
    verdict = conn.execute(
        "SELECT verdict FROM dongzhu_pick_score WHERE sid='2330'"
    ).fetchone()[0]
    conn.close()
    assert sids == ["2330"]
    assert verdict == "還沒走完"


def test_snapshot_uses_empty_spoken(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    seen = {}

    def fake_picks(_db, *, spoken="x"):
        seen["spoken"] = spoken
        return {
            "cap": "20260917",
            "field": "封測",
            "buys": [{"sid": "6257", "name": "矽格", "close": 222.5}],
        }

    monkeypatch.setattr("biaoke_field_scan.dongzhu_picks", fake_picks)
    n = snapshot_dongzhu_picks(db, "20260917", spoken="")
    assert n == 1
    assert seen["spoken"] == ""
    out = snapshot_and_score_dongzhu(db, "20260918")
    assert out["scored"] == 0
    assert seen["spoken"] == ""


def test_runner_skips_tape_until_quotes_complete(tmp_path, monkeypatch):
    from main_runner import MainRunner

    called = []
    monkeypatch.setattr(
        "dongzhu_judge.refresh_dongzhu_judgment",
        lambda *_a, **_k: {"skipped": "quotes_incomplete", "want": "20260917"},
    )
    monkeypatch.setattr(
        "dongzhu_tape.snapshot_and_score_dongzhu",
        lambda *a, **k: called.append(a) or {"snap": 0, "scored": 0},
    )
    runner = object.__new__(MainRunner)
    runner.db_path = str(tmp_path / "t.db")
    out = MainRunner._refresh_dongzhu_after_close(runner, "20260917")
    assert out["skipped"] == "quotes_incomplete"
    assert called == []


def test_runner_tapes_after_complete_judgment(tmp_path, monkeypatch):
    from main_runner import MainRunner

    called = []
    monkeypatch.setattr(
        "dongzhu_judge.refresh_dongzhu_judgment",
        lambda *_a, **_k: {"cap": "20260917", "rates": {}},
    )
    monkeypatch.setattr(
        "dongzhu_tape.snapshot_and_score_dongzhu",
        lambda db, cap: called.append(cap) or {"snap": 2, "scored": 1, "cap": cap},
    )
    runner = object.__new__(MainRunner)
    runner.db_path = str(tmp_path / "t.db")
    out = MainRunner._refresh_dongzhu_after_close(runner, "20260917")
    assert called == ["20260917"]
    assert out["tape"]["snap"] == 2


def test_dongzhu_page_hides_scoreboard(tmp_path, monkeypatch):
    from biaoke_field_scan import dongzhu_page

    db = str(tmp_path / "f.db")
    _quotes(db)
    write_snapshot(
        db,
        {
            "cap": "20260916",
            "buys": [{"sid": "9999", "name": "對質股", "close": 100.0}],
        },
    )
    _put(db, "9999", "20260917", 102.0)
    score_dongzhu_picks(db, "20260917")
    monkeypatch.setattr(
        "biaoke_field_scan.dongzhu_picks",
        lambda *_a, **_k: {"cap": "20260917", "field": "", "line": "還沒對上"},
    )
    html = dongzhu_page(db)
    assert "對質自記" not in html
    assert "對質股" not in html
    assert "盤後自己落檔" not in html


def test_screen_leave_zero_scores_like_dongzhu(tmp_path):
    from screen_sessions import save_screen_session

    db = str(tmp_path / "t.db")
    _quotes(db)
    save_screen_session(
        db,
        "20260917",
        "morning",
        {
            "leave_zero": [
                {
                    "stock_id": "6257",
                    "stock_name": "矽格",
                    "close": 100.0,
                    "profit_pct": 1.2,
                    "reason": "獲利格實綠（剛離零）",
                }
            ],
            "golden_buy": [{"stock_id": "2449", "stock_name": "京元電子", "close": 100.0}],
            "select_01": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}],
            "day_trade": [{"stock_id": "1101", "stock_name": "台泥", "close": 100.0}],
        },
    )
    conn = sqlite3.connect(_store(db))
    tags = {
        r[0]
        for r in conn.execute(
            "SELECT tag FROM dongzhu_pick_tape WHERE kind='screen'"
        ).fetchall()
    }
    conn.close()
    assert tags == {"leave_zero", "golden_buy", "select_01"}
    conn = sqlite3.connect(_store(db))
    enc_id, encoding = conn.execute(
        "SELECT enc_id, encoding FROM dongzhu_pick_tape WHERE sid='6257' AND kind='screen'"
    ).fetchone()
    conn.close()
    assert enc_id == "leave_zero.cal60_leave0_max5"
    assert "1.2" in encoding
    assert "獲利格實綠" in encoding
    _put(db, "6257", "20260918", 101.0)
    _put(db, "2449", "20260918", 99.0)
    _put(db, "2330", "20260918", 100.2)
    n = score_dongzhu_picks(db, "20260918")
    assert n == 3
    conn = sqlite3.connect(_store(db))
    got = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT sid, verdict FROM dongzhu_pick_score WHERE kind='screen'"
        ).fetchall()
    }
    conn.close()
    assert got["6257"] == "對"
    assert got["2449"] == "偏"
    assert got["2330"] == "還沒走完"


def test_evolve_file_not_in_public_zip():
    from pathlib import Path

    daily = Path(".github/workflows/daily_run.yml").read_text(encoding="utf-8")
    assert "zip -1 -j waynebot_production_complete.zip data/wayne_market.db" in daily
    assert "wayne_evolve.db" not in daily


def test_schema_migrate_does_not_drop_scores(tmp_path):
    db = str(tmp_path / "t.db")
    _quotes(db)
    write_snapshot(
        db,
        {"cap": "20260917", "buys": [{"sid": "6257", "name": "矽格", "close": 100.0}]},
    )
    _put(db, "6257", "20260918", 101.0)
    score_dongzhu_picks(db, "20260918")
    from dongzhu_tape import ensure_dongzhu_tape_tables

    ensure_dongzhu_tape_tables(db)
    ensure_dongzhu_tape_tables(db)
    conn = sqlite3.connect(_store(db))
    n = conn.execute("SELECT COUNT(*) FROM dongzhu_pick_score").fetchone()[0]
    conn.close()
    assert n == 1


def test_scores_1_5_10_trade_days_without_button(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    _quotes(db)
    start = datetime(2026, 9, 1)
    closes = [100.0, 101.0, 101.2, 100.8, 100.4, 99.0, 99.2, 99.4, 99.6, 99.8, 108.0]
    for i, px in enumerate(closes):
        day = (start + timedelta(days=i)).strftime("%Y%m%d")
        _put(db, "6257", day, px)
    write_snapshot(
        db,
        {
            "cap": "20260901",
            "buys": [{"sid": "6257", "name": "矽格", "close": 100.0, "vs20": -8.0}],
        },
    )
    n = score_dongzhu_picks(db, "20260911")
    assert n == 3
    conn = sqlite3.connect(_store(db))
    rows = {
        int(r[0]): (r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT horizon, check_as_of, fwd_pct, verdict "
            "FROM dongzhu_pick_score WHERE sid='6257'"
        ).fetchall()
    }
    conn.close()
    assert rows[1][0] == "20260902" and rows[1][2] == "對"
    assert rows[5][0] == "20260906" and rows[5][2] == "偏"
    assert rows[10][0] == "20260911" and rows[10][2] == "對"
    seen = {}

    def fake_picks(_db, *, spoken="x"):
        seen["spoken"] = spoken
        return {
            "cap": "20260911",
            "buys": [{"sid": "6257", "name": "矽格", "close": 108.0}],
        }

    monkeypatch.setattr("biaoke_field_scan.dongzhu_picks", fake_picks)
    out = snapshot_and_score_dongzhu(db, "20260911")
    assert seen["spoken"] == ""
    assert out["scored"] == 3
    assert out["snap"] == 1


def test_tape_does_not_push_telegram():
    from pathlib import Path

    src = Path("main_runner.py").read_text(encoding="utf-8")
    i = src.find("snapshot_and_score_dongzhu")
    assert i > 0
    assert "send_telegram" not in src[i : i + 500]
