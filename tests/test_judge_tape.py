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


def test_agents_silent_record_is_rank_three():
    text = Path("AGENTS.md").read_text(encoding="utf-8")
    assert "默默落檔（2026-09-21 鎖死）" in text
    assert "沒按也一樣" in text
    assert "佐證同時留（數字，不是每檔截圖）" in text
    assert "每檔每天 K 圖 PNG" in text
    assert "對話不准報" in text
    assert "還沒做／做到一半" in text
    assert "明確優化狀態" in text
    i3 = text.find("## 3. 能量化就直接量化")
    i4 = text.find("## 4. 不准假資料")
    i_silent = text.find("### 默默落檔")
    assert 0 < i3 < i_silent < i4


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
