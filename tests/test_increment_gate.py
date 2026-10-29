# -*- coding: utf-8 -*-
"""盤後融合關卡：該有的數字不能是 0。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from import_health import (
    MIN_CHIPS_NONZERO,
    MIN_EM,
    MIN_TWO,
    MIN_TW,
    increment_health_failures,
    increment_health_ok,
    verify_increment_import,
)
from main_runner import MainRunner
from wayne_db import ensure_core_schema


def test_increment_health_ok_rejects_any_zero_side():
    base = {"total": 2000, "chips_nonzero": 500, "em": MIN_EM}
    assert increment_health_ok({**base, "tw": 0, "two": 900}) is False
    assert increment_health_ok({**base, "tw": 900, "two": 0}) is False
    assert increment_health_ok({"total": 0, "tw": 900, "two": 900, "chips_nonzero": 500, "em": MIN_EM}) is False


def test_increment_health_ok_rejects_zero_chips_when_total_high():
    health = {"total": 2000, "tw": 900, "two": 700, "chips_nonzero": 0, "em": MIN_EM}
    assert increment_health_ok(health) is False
    assert any("法人" in r for r in increment_health_failures(health, cap="20260902"))


def test_increment_health_ok_rejects_thin_emerging():
    health = {
        "total": 2000,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": 0,
    }
    assert increment_health_ok(health) is False
    assert any("興櫃" in r for r in increment_health_failures(health, cap="20260902"))


def test_increment_health_ok_rejects_half_emerging_day():
    """半套 ~250 列不准當齊（舊門檻 50 會誤放行）。"""
    health = {
        "total": 2000,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": 259,
    }
    assert MIN_EM > 259
    assert increment_health_ok(health) is False
    assert any("興櫃 259" in r for r in increment_health_failures(health, cap="20260924"))


def test_increment_health_ok_monthly_never_blocks_fuse():
    """月營收未滿不准擋 fuse（靜態補齊；含興櫃同期 0／10 號後）。"""
    from import_health import MIN_EM_MONTHLY

    thin = {
        "total": 2000,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": MIN_EM,
        "monthly_n": 4000,
        "em_monthly_n": 0,
        "latest_month": "202608",
    }
    assert increment_health_ok(thin) is True
    assert increment_health_failures(thin, cap="20260924") == []
    assert MIN_EM_MONTHLY >= 200

    after_tenth = {
        "date": "20261011",
        "total": 2200,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": MIN_EM,
        "monthly_n": 7852,
        "em_monthly_n": 4,
        "em_monthly_latest": "202609",
        "latest_month": "202609",
    }
    assert increment_health_failures(after_tenth, cap="20261011") == []
    assert increment_health_ok(after_tenth) is True


def test_increment_health_ok_early_month_emerging_revenue_grace():
    """月初 1–10：興櫃新月僅少數先公告 → 仍不擋 fuse（月營收永不擋）。"""
    health = {
        "date": "20261001",
        "total": 2200,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": MIN_EM,
        "monthly_n": 7852,
        "em_monthly_n": 4,
        "em_monthly_latest": "202609",
        "latest_month": "202609",
    }
    assert increment_health_failures(health, cap="20261001") == []
    assert increment_health_ok(health) is True


def test_emerging_monthly_gate_month_before_tenth():
    from import_health import emerging_monthly_gate_month

    # 庫 MAX 已到 202609，但 10/1 盤點仍對 202608（報表用，不擋 fuse）
    assert emerging_monthly_gate_month("202609", "20261001") == "202608"
    assert emerging_monthly_gate_month("202608", "20261001") == "202608"
    assert emerging_monthly_gate_month("202609", "20261011") == "202609"


def test_audit_import_monthly_soft_never_in_problems():
    """日 K 齊時月營收再薄也不進 problems、不擋 today_ok（不准提醒／incomplete）。"""
    from import_health import audit_import

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        conn = sqlite3.connect(path)
        _seed_complete_day(conn, "20261001")
        # 只有上市櫃搶先 202609；興櫃月營收幾乎空
        for i in range(50):
            conn.execute(
                "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"{1100+i:04d}", "202609", "TW", "TW", "", 1_000_000, 0, 0, 0),
            )
        for i in range(4):
            conn.execute(
                "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"{7100+i:04d}", "202609", "EM", "EM", "", 1_000_000, 0, 0, 0),
            )
        for i in range(60):
            conn.execute(
                "INSERT INTO ex_rights(stock_id,ex_date,factor,source) VALUES (?,?,?,?)",
                (f"{1000+i:04d}", "20260915", 1.0, "test"),
            )
        conn.commit()
        conn.close()
        health = audit_import(path, "20261001", history=False)
        assert health["latest_month"] == "202609"
        assert int(health.get("em_monthly_head_n") or 0) == 4
        assert not any("月營收" in str(p) for p in (health.get("problems") or []))
        assert increment_health_failures(health, cap="20261001") == []
        assert health["today_ok"] is True
    finally:
        os.remove(path)


def test_increment_health_ok_passes_complete():
    health = {
        "total": 2000,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": MIN_EM,
    }
    assert increment_health_ok(health) is True
    assert increment_health_failures(health, cap="20260902") == []


def test_increment_health_failures_still_rejects_missing_daily():
    """日資料缺邊仍要正確失敗（上市／上櫃／興櫃日 K）。"""
    no_em = {
        "total": 2000,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": 0,
        "monthly_n": 8000,
        "em_monthly_n": 400,
    }
    assert increment_health_ok(no_em) is False
    assert any("興櫃" in r for r in increment_health_failures(no_em, cap="20261001"))
    half_two = {
        "total": 1000,
        "tw": max(MIN_TW, 900),
        "two": 100,
        "chips_nonzero": max(MIN_CHIPS_NONZERO, 500),
        "em": MIN_EM,
    }
    assert any("上櫃" in r for r in increment_health_failures(half_two, cap="20261001"))

def test_main_runner_increment_ok_uses_same_gate():
    runner = MainRunner.__new__(MainRunner)
    assert runner._increment_ok({"total": 0, "tw": 0, "two": 0, "em": 0}) is False
    assert runner._increment_ok(
        {"total": 2000, "tw": 900, "two": 700, "chips_nonzero": 500, "em": MIN_EM}
    ) is True


def _seed_emerging_day(conn: sqlite3.Connection, ymd: str, n: int = MIN_EM) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS emerging_quotes (
            date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT,
            market TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, turnover_k REAL, pct_change REAL, avg_price REAL,
            source TEXT, PRIMARY KEY (date, stock_id)
        )"""
    )
    for i in range(int(n)):
        conn.execute(
            """INSERT INTO emerging_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,source)
            VALUES (?,?,?,?,10,11,9,10,100,10,0.5,10,'test')""",
            (ymd, f"{7000+i:04d}", "興櫃", "EM"),
        )


def _seed_complete_day(conn: sqlite3.Connection, ymd: str) -> None:
    for i in range(MIN_TW):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,10,0,0)""",
            (ymd, f"{1000+i:04d}", "TW", "TW"),
        )
    for i in range(MIN_TWO):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,50,0,0)""",
            (ymd, f"{6000+i:04d}", "上櫃", "TWO"),
        )
    _seed_emerging_day(conn, ymd)


def test_verify_increment_import_fails_on_empty_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        report = verify_increment_import(path, cap="20260902")
        assert report["ok"] is False
        assert any("為 0" in r or "興櫃" in r for r in report["reasons"])
    finally:
        os.remove(path)


def test_verify_increment_import_fails_without_emerging():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        conn = sqlite3.connect(path)
        for i in range(MIN_TW):
            conn.execute(
                """INSERT INTO daily_quotes
                (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
                VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,10,0,0)""",
                ("20260902", f"{1000+i:04d}", "TW", "TW"),
            )
        for i in range(MIN_TWO):
            conn.execute(
                """INSERT INTO daily_quotes
                (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
                VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,50,0,0)""",
                ("20260902", f"{6000+i:04d}", "上櫃", "TWO"),
            )
        conn.commit()
        conn.close()
        report = verify_increment_import(path, cap="20260902")
        assert report["ok"] is False
        assert any("興櫃" in r for r in report["reasons"])
    finally:
        os.remove(path)


def test_verify_increment_import_passes_when_sides_full():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        conn = sqlite3.connect(path)
        _seed_complete_day(conn, "20260902")
        conn.commit()
        conn.close()
        report = verify_increment_import(path, cap="20260902")
        assert report["ok"] is True, report["reasons"]
    finally:
        os.remove(path)


def test_fuse_done_message_is_not_a_screen_or_buy_signal():
    from main_runner import MainRunner

    msg = MainRunner._fuse_done_message("20260907", {"tw": 980, "two": 720, "em": 180})
    assert "2026/09/07" in msg
    assert "上市 980" in msg
    assert "上櫃 720" in msg
    assert "興櫃 180" in msg
    assert "官方收盤已寫進庫" in msg
    assert "不是海選" in msg
    assert "不是買訊" in msg
    assert "黃金買點" not in msg
    assert "買進" not in msg


def test_increment_job_sends_done_only_after_gate_passes():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner.run_increment_job)
    # 2026-10-30：成功前必過興櫃閘＋_increment_ok（listed_ok）
    fail_at = src.index("if not em_gate.get(\"ok\") or not listed_ok")
    done_at = src.index("_fuse_done_message")
    assert fail_at < done_at
    before_done = src[:done_at]
    assert "return False" in before_done
    assert "盤後繼續補齊" in before_done
    assert "融合興櫃閘" in before_done
    assert "_fuse_done_message" not in src.split("return False")[0]


def test_increment_job_stamps_when_bars_already_complete():
    import inspect

    from main_runner import MainRunner
    from ops_watchdog import INCREMENT_RUNNING_STALE_SEC

    src = inspect.getsource(MainRunner.run_increment_job)
    assert "already-complete" in src
    assert "increment-claim" in src
    assert src.index("already-complete") < src.index("盤後融合開始")
    assert "INCREMENT_RUNNING_STALE_SEC" in src
    assert "_morning_running_lease" in src
    assert "increment crashed" in src
    assert INCREMENT_RUNNING_STALE_SEC <= 600


def test_boot_backfill_uses_increment_job():
    import inspect

    import main

    src = inspect.getsource(main.start_market_backfill)
    assert "run_increment_job(skip_if_done=True, notify=False)" in src
    assert "run_daily_increment(notify=False)" not in src
    # §14：開市日早報未寄前開機融合必須讓路
    assert "_morning_digest_still_due" in src
    assert "開市日早報尚未寄達" in src
    # 休市日開機也不准 fuse（光復節補假／颱風等同精神）
    assert "closed_tw_session" in src
    assert "開市日才融合" in src
    # 06:30 前不准開機融合：避 /live 健檢重啟循環
    assert "06:30 前" in src
    assert "健檢重啟循環" in src


def test_catch_up_skips_screen_cache_before_morning():
    """台北 06:30 前補跑不准背景全掃海選（跟開機融合互鎖會重啟循環）。"""
    import inspect

    import main

    src = inspect.getsource(main.catch_up_missed_jobs)
    assert "06:30 前略過背景補建海選快取" in src
    assert "健檢重啟循環" in src


def test_watchdog_retry_skips_fuse_before_morning():
    import inspect

    import main

    src = inspect.getsource(main.retry_missed_owned_jobs)
    assert "06:30 前不補跑 fuse" in src
    assert "健檢重啟循環" in src


def test_catch_up_skips_fuse_on_closed_day():
    import inspect

    import main

    src = inspect.getsource(main.catch_up_missed_jobs)
    assert "跳過盤後融合補跑" in src
    assert "closed_tw_session" in src
    fuse_chunk = src.split("if need_fuse:")[1].split("if need_midday:")[0]
    assert "closed_fuse" in fuse_chunk
    assert "now=now" in fuse_chunk
    assert "run_increment_job" in fuse_chunk


def test_catch_up_skips_fuse_on_guangfu_makeup_holiday(monkeypatch):
    """光復節補假下午：補跑不准呼叫 run_increment_job。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import main
    import main_runner

    calls = []

    class _R:
        db_path = ":memory:"

        def morning_claim_is_fresh_running(self):
            return False

        def demote_orphaned_increment_claims(self, **kw):
            return 0

        def demote_orphaned_morning_claims(self, **kw):
            return 0

        def reconcile_push_deliveries(self, **kw):
            return 0

        def run_nightly_open_check(self, **kw):
            calls.append(("open_check", kw))

        def run_morning_screen(self, **kw):
            calls.append(("morning", kw))

        def run_increment_job(self, **kw):
            calls.append(("fuse", kw))

        def run_midday_review(self, **kw):
            calls.append(("midday", kw))

        def run_evening_screen(self, **kw):
            calls.append(("evening", kw))

        def run_winrate_buypoint(self, **kw):
            calls.append(("winrate", kw))

    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    monkeypatch.setattr(main_runner, "MainRunner", lambda *a, **k: _R())
    monkeypatch.setattr(
        "tw_holidays.closed_tw_session",
        lambda now=None, db_path=None: {
            "ymd": "20261026",
            "zh": "光復節補假",
            "kind": "full_close",
        },
    )
    now = datetime(2026, 10, 26, 19, 10, tzinfo=ZoneInfo("Asia/Taipei"))
    main.catch_up_missed_jobs(now)
    kinds = [c[0] for c in calls]
    assert "fuse" not in kinds
    assert "morning" in kinds


def test_morning_digest_still_due_helper_exists():
    import inspect

    import main

    assert callable(main._morning_digest_still_due)
    src = inspect.getsource(main._morning_digest_still_due)
    assert "screen-" in src
    assert "success" in src


def test_increment_job_holiday_checks_prior_cap_before_skip():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner.run_increment_job)
    # 休市一律跳過重融合；上一收盤未齊也不准掉進 busy_window
    assert "跳過盤後融合（開市日才融合）" in src
    assert "仍跳過融合／不推 busy" in src
    assert "改補齊" not in src
    closed_block = src.split("if closed:")[1].split("if skip_if_done")[0]
    assert "sync_emerging_quotes" in closed_block
    assert "audit_import" in closed_block
    assert "_increment_ok" in closed_block
    assert 'busy_window("fuse"' not in closed_block
    assert "return True" in closed_block
    # busy 融合本體只在 closed 分支之後
    assert src.index("if closed:") < src.index('busy_window("fuse"')


def test_increment_job_closed_never_enters_busy_even_if_prior_incomplete(
    tmp_path, monkeypatch
):
    """光復節補假等：上一收盤未齊也不准推「資料處理中」／跑重融合。"""
    from main_runner import MainRunner

    db = tmp_path / "w.db"
    db.write_text("", encoding="utf-8")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = str(db)
    runner.today_str = "20261026"
    runner.fetcher = None

    monkeypatch.setattr(
        "tw_holidays.closed_tw_session",
        lambda db_path=None, now=None: {
            "ymd": "20261026",
            "zh": "光復節補假",
            "kind": "full_close",
            "prev_ymd": "20261023",
        },
    )
    monkeypatch.setattr(
        "tw_holidays.refresh_tw_holiday_calendar", lambda *a, **k: {"ok": True}
    )
    monkeypatch.setattr(
        "tw_holidays.refresh_tw_typhoon_halt", lambda *a, **k: {"ok": True}
    )
    monkeypatch.setattr(
        "main_runner.fuse_end_date", lambda *a, **k: "20261023"
    )
    monkeypatch.setattr(
        "emerging_quotes.sync_emerging_quotes", lambda *a, **k: {"n": 0}
    )
    monkeypatch.setattr(
        "import_health.audit_import",
        lambda *a, **k: {"tw": 10, "two": 10, "em": 0},
    )

    marks = []
    busy_calls = []

    runner._increment_ok = lambda health: False  # type: ignore[method-assign]
    runner._refresh_official_sidecars = lambda: None  # type: ignore[method-assign]
    runner._run_post_fuse_silent_tracks = lambda *a, **k: {}  # type: ignore[method-assign]
    runner._mark_pipeline = lambda status, notes="", **kw: marks.append(  # type: ignore[method-assign]
        (status, notes)
    )

    def _no_busy(*a, **k):
        busy_calls.append(1)
        raise AssertionError("休市日不准進 busy_window")

    monkeypatch.setattr(
        "busy_window_notice.busy_window", _no_busy
    )

    assert runner.run_increment_job(skip_if_done=True, notify=True) is True
    assert busy_calls == []
    assert marks and marks[0][0] == "success"
    assert "skip increment" in marks[0][1]
    assert "光復節補假" in marks[0][1]
    assert "prior_incomplete" in marks[0][1]


def test_pipeline_stamp_and_finished_at_are_taipei():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from main_runner import MainRunner, _stamp_age_seconds

    tw = ZoneInfo("Asia/Taipei")
    naive_utc = "2026-10-06T10:47:44"
    assert MainRunner._pipeline_finished_tw_ymd(naive_utc) == "20261006"
    aware = "2026-10-06T18:47:44+08:00"
    assert MainRunner._pipeline_finished_tw_ymd(aware) == "20261006"
    from inspect import getsource

    assert "taipei_stamp()" in getsource(MainRunner._mark_pipeline)
    now = datetime(2026, 10, 6, 18, 49, tzinfo=tw)
    assert _stamp_age_seconds("2026-10-06T18:47:44+08:00", now=now) == 76.0
    # 舊 naive＝UTC：10:47Z＝台北 18:47
    assert _stamp_age_seconds(naive_utc, now=now) == 76.0
