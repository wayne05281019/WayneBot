# -*- coding: utf-8 -*-
"""演算延伸建檔：尚未走完的路徑先存，官方柱到了再對質。"""
import sqlite3
from datetime import date, timedelta

from biaoke_forecast import glance_forecast, record_stock, verify_due


def _wash_rows():
    day = date(2026, 7, 1)
    rows = []
    px = 100.0
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 12:
            o, h, l, c, v = 130, 148, 120, 140, 20000
        elif i == 15:
            o, h, l, c, v = 128, 130, 110, 118, 4000
        elif i == 18:
            o, h, l, c, v = 120, 126, 118, 124, 1800
        elif i == 24:
            o, h, l, c, v = 128, 136, 126, 130, 2200
        elif i == 30:
            o, h, l, c, v = 128, 132, 124, 126, 1600
        else:
            px = 100 + i * 1.2
            o, h, l, c, v = px, px + 3, px - 3, px + 1, 1200
        rows.append(
            {
                "date": d,
                "stock_id": "3035",
                "stock_name": "智原",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return rows


def _seed_quotes(db: str, rows) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            pct_change REAL,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    for r in rows:
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
            (
                r["date"],
                r.get("stock_id") or "3035",
                r.get("stock_name") or "智原",
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
            ),
        )
    conn.commit()
    conn.close()


def test_record_stock_pending_then_hits_target(tmp_path):
    rows = _wash_rows()
    db = str(tmp_path / "fc.db")
    _seed_quotes(db, rows)
    rec = record_stock(db, "3035", rows)
    assert rec.get("key") == "wash"
    assert rec.get("as_of") == str(rows[-1]["date"]).replace("-", "")[:8]
    verify_due(db, "3035")
    g0 = glance_forecast(db, "3035")
    assert "還沒走完" in g0
    assert "對得上" not in g0
    last = date(int(rec["as_of"][:4]), int(rec["as_of"][4:6]), int(rec["as_of"][6:8]))
    conn = sqlite3.connect(db)
    for i in range(10):
        d = (last + timedelta(days=i + 1)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
            (d, "3035", "智原", 140, 150, 138, 149, 1800),
        )
    conn.commit()
    conn.close()
    verify_due(db, "3035")
    g1 = glance_forecast(db, "3035")
    assert "對得上" in g1
    assert "還沒走完" not in g1


def test_score_line_counts_hit_miss_pending(tmp_path):
    from biaoke_forecast import score_line

    rows = _wash_rows()
    db = str(tmp_path / "sc.db")
    _seed_quotes(db, rows)
    rec = record_stock(db, "3035", rows)
    last = date(int(rec["as_of"][:4]), int(rec["as_of"][4:6]), int(rec["as_of"][6:8]))
    conn = sqlite3.connect(db)
    for i in range(10):
        d = (last + timedelta(days=i + 1)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
            (d, "3035", "智原", 140, 150, 138, 149, 1800),
        )
    conn.commit()
    conn.close()
    verify_due(db, "3035")
    line = score_line(db)
    assert "對" in line
    assert "n=" in line
    assert "不是買訊" in line


def _seed_twii(db: str, rows, *, close_last=None):
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_daily (
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
            volume REAL, pct_change REAL
        )
        """
    )
    conn.execute("DELETE FROM index_daily")
    for i, (d, o, h, lo, c) in enumerate(rows):
        if close_last is not None and i == len(rows) - 1:
            c = close_last
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
            (d, "TWII", o, h, lo, c, 1, 0),
        )
    conn.commit()
    conn.close()


def _twii_rows(n=24, start=None, base=45000.0):
    day = start or date(2026, 8, 1)
    rows = []
    px = base
    for i in range(n):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        o, h, lo, c = px, px + 120, px - 80, px + 40
        rows.append((d, o, h, lo, c))
        px += 30
    return rows


def test_twii_snapshot_hides_try_from_glance_and_scores(tmp_path):
    from biaoke_forecast import (
        KIND_TWII_TRY,
        glance_forecast,
        snapshot_and_score_twii,
        verify_due,
        verify_twii_try,
    )

    db = str(tmp_path / "tw.db")
    store = str(tmp_path / "wayne_evolve.db")
    rows = _twii_rows()
    _seed_twii(db, rows)
    out = snapshot_and_score_twii(db, rows[-1][0])
    assert out.get("twii") == 0
    assert out.get("try") == 1
    g = glance_forecast(db, "TWII")
    assert "內部試畫" not in g
    assert "1-2-3-4-5" not in g
    assert "演算建檔" not in g
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    kinds = set()
    if "biaoke_forecast" in names:
        kinds = {r[0] for r in conn.execute("SELECT kind FROM biaoke_forecast").fetchall()}
    conn.close()
    assert "twii" not in kinds
    assert KIND_TWII_TRY not in kinds
    conn = sqlite3.connect(store)
    try_mark = conn.execute(
        "SELECT mark, label FROM biaoke_forecast WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()
    assert try_mark[0] == "內部試畫"
    assert "不進話筒" in try_mark[1]
    rate_n = conn.execute(
        "SELECT n FROM silent_twii_rates WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()
    conn.close()
    last = date(int(rows[-1][0][:4]), int(rows[-1][0][4:6]), int(rows[-1][0][6:8]))
    conn = sqlite3.connect(db)
    for i in range(10):
        d = (last + timedelta(days=i + 1)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
            (d, "TWII", 44000, 44200, 43000, 43100, 1, 0),
        )
    conn.commit()
    conn.close()
    verify_due(db, "TWII")
    conn = sqlite3.connect(store)
    try_v0 = conn.execute(
        "SELECT verdict FROM biaoke_forecast WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()[0]
    conn.close()
    assert not try_v0 or "對得上" not in try_v0 or "還沒走完" in (try_v0 or "")
    verify_twii_try(db)
    conn = sqlite3.connect(store)
    try_v = conn.execute(
        "SELECT verdict FROM biaoke_forecast WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()[0]
    hit = conn.execute(
        "SELECT hit FROM silent_twii_rates WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()[0]
    dz = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dongzhu_pick_rates'"
    ).fetchone()
    ai = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_fills'"
    ).fetchone()
    conn.close()
    assert "對得上" in try_v
    assert "還沒走完" not in try_v
    assert int(hit) >= 1
    assert dz is None
    assert ai is None
    assert rate_n is not None
    assert int(rate_n[0]) >= 1


def test_silent_snapshot_does_not_touch_product_forecast(tmp_path):
    from biaoke_forecast import KIND_TWII_TRY, glance_forecast, record_twii, snapshot_and_score_twii

    db = str(tmp_path / "tw.db")
    store = str(tmp_path / "wayne_evolve.db")
    rows = _twii_rows()
    _seed_twii(db, rows)
    bars = [
        {"date": d, "open": o, "high": h, "low": lo, "close": c}
        for d, o, h, lo, c in rows
    ]
    rec = record_twii(db, bars, last_tag="逃命波C-2")
    assert rec
    g0 = glance_forecast(db, "TWII")
    assert "演算建檔" in g0
    assert "內部試畫" not in g0
    conn = sqlite3.connect(db)
    before = conn.execute(
        "SELECT created_at, mark, verdict, kind FROM biaoke_forecast WHERE kind='twii'"
    ).fetchone()
    conn.close()
    snapshot_and_score_twii(db, rows[-1][0])
    conn = sqlite3.connect(db)
    kinds = {r[0] for r in conn.execute("SELECT kind FROM biaoke_forecast").fetchall()}
    after = conn.execute(
        "SELECT created_at, mark, verdict, kind FROM biaoke_forecast WHERE kind='twii'"
    ).fetchone()
    conn.close()
    assert kinds == {"twii"}
    assert after == before
    g1 = glance_forecast(db, "TWII")
    assert g1 == g0
    conn = sqlite3.connect(store)
    try_n = conn.execute(
        "SELECT COUNT(*) FROM biaoke_forecast WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()[0]
    conn.close()
    assert try_n == 1


def test_twii_snapshot_skips_zero_close(tmp_path):
    from biaoke_forecast import snapshot_and_score_twii

    db = str(tmp_path / "z.db")
    rows = _twii_rows()
    _seed_twii(db, rows, close_last=0)
    out = snapshot_and_score_twii(db, rows[-1][0])
    assert out.get("skipped") == "zero_close"
    assert out.get("twii") == 0
    assert out.get("try") == 0


def test_twii_forecast_hooks_fuse_not_telegram():
    from pathlib import Path

    src = Path("main_runner.py").read_text(encoding="utf-8")
    assert "snapshot_and_score_twii" in src
    assert "record_twii_session_preopen" in src or "_record_twii_session_preopen" in src
    assert "twii-session" in src
    i = src.find("def _refresh_twii_forecast_after_close")
    assert i > 0
    chunk = src[i : i + 900]
    assert "send_telegram" not in chunk
    assert "snapshot_and_score_twii" in chunk
    assert src.find("sync_index_daily") < src.find("_refresh_twii_forecast_after_close")
    # 當日盤勢落檔在早報路徑，但不准跟寄話筒綁在一起當預報文案
    assert "不准塞進早報" in src
    assert "_record_twii_session_preopen" in src
    assert "send_telegram" not in src[src.find("def _record_twii_session_preopen") : src.find("def _record_twii_session_preopen") + 500]
    try_src = Path("biaoke_forecast.py").read_text(encoding="utf-8")
    a = try_src.find("def record_twii_try")
    b = try_src.find("def _judge_stock", a)
    body = try_src[a:b]
    assert "內部試畫" in body
    assert "不進話筒" in body
    assert "1-2-3-4-5" not in body
    assert "第5波" not in body
    assert "_evolve_store" in body
    sess = try_src.find("def record_twii_session_preopen")
    assert sess > 0
    assert "不進話筒" in try_src[sess : sess + 1200]
    assert "after_open" in try_src[sess : sess + 2500]
    from biaoke_wave import format_twii_plain
    import inspect

    cap = inspect.getsource(format_twii_plain)
    assert "內部試畫" not in cap
    assert "開盤前當日盤勢" not in cap


def test_twii_session_preopen_before_open_then_score(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_forecast import (
        KIND_TWII_SESSION,
        record_twii_session_preopen,
        verify_twii_session,
    )

    db = str(tmp_path / "sess.db")
    store = str(tmp_path / "wayne_evolve.db")
    # 連續開市日前置柱＋昨收 20261103
    rows = []
    px = 45000.0
    day0 = date(2026, 10, 1)
    for i in range(25):
        d = (day0 + timedelta(days=i)).strftime("%Y%m%d")
        rows.append((d, px, px + 100, px - 80, px + 20))
        px += 40
    rows.append(("20261103", 44480, 44610, 43190, 43307))
    _seed_twii(db, rows)
    session = "20261104"
    pre = datetime(2026, 11, 4, 6, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    rec = record_twii_session_preopen(db, session, now=pre)
    assert not rec.get("skipped"), rec
    assert rec.get("as_of") == session
    assert rec.get("key") in {"up", "down", "range"}
    assert float(rec.get("last_close") or 0) == 43307.0
    conn = sqlite3.connect(store)
    mark, label, key = conn.execute(
        "SELECT mark, label, key FROM biaoke_forecast WHERE kind=? AND as_of=?",
        (KIND_TWII_SESSION, session),
    ).fetchone()
    conn.close()
    assert mark == "開盤前當日盤勢"
    assert "不進話筒" in label
    after = datetime(2026, 11, 4, 9, 5, tzinfo=ZoneInfo("Asia/Taipei"))
    skip = record_twii_session_preopen(db, session, now=after)
    assert skip.get("skipped") == "after_open"
    # 強制方向往下再對質
    conn = sqlite3.connect(store)
    conn.execute(
        "UPDATE biaoke_forecast SET key='down' WHERE kind=? AND as_of=?",
        (KIND_TWII_SESSION, session),
    )
    conn.commit()
    conn.close()
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
        (session, "TWII", 43200, 43500, 42000, 42100, 1, 0),
    )
    conn.commit()
    conn.close()
    n = verify_twii_session(db)
    assert n >= 1
    conn = sqlite3.connect(store)
    verd, hit = conn.execute(
        """
        SELECT v.verdict, r.hit FROM biaoke_forecast v
        LEFT JOIN silent_twii_rates r ON r.kind=?
        WHERE v.kind=? AND v.as_of=?
        """,
        (KIND_TWII_SESSION, KIND_TWII_SESSION, session),
    ).fetchone()
    conn.close()
    assert "對得上往下" in verd
    assert "還沒走完" not in verd
    assert int(hit or 0) >= 1


def test_ensure_wave_inputs_skips_under_pytest(tmp_path, monkeypatch):
    from biaoke_forecast import ensure_wave_inputs

    called = []
    monkeypatch.setattr(
        "taiwan_market.sync_index_daily",
        lambda *a, **k: called.append("twii"),
    )
    out = ensure_wave_inputs(str(tmp_path / "w.db"), "20260918")
    assert out.get("skipped") == "pytest"
    assert called == []


def test_chi_tue_gate_sep24_wick_stays_pending(tmp_path):
    from biaoke_forecast import glance_forecast, record_spoken_path, score_line, verify_due

    rows = []
    for d, o, h, l, c, v in [
        ("20260826", 2880, 3155, 2850, 3155, 5242),
        ("20260827", 3305, 3440, 3265, 3340, 6114),
        ("20260828", 3360, 3450, 3320, 3360, 4035),
        ("20260831", 3280, 3425, 3250, 3425, 4468),
        ("20260901", 3435, 3465, 3350, 3410, 3084),
        ("20260902", 3365, 3490, 3280, 3310, 3136),
        ("20260903", 3395, 3525, 3290, 3300, 4418),
        ("20260904", 3465, 3570, 3410, 3570, 4515),
        ("20260907", 3595, 3595, 3410, 3420, 3303),
        ("20260908", 3455, 3455, 3245, 3285, 3350),
        ("20260915", 3265, 3300, 3100, 3115, 3217),
        ("20260917", 3285, 3350, 3175, 3185, 3034),
        ("20260923", 3425, 3590, 3410, 3470, 2649),
    ]:
        rows.append(
            {
                "date": d,
                "stock_id": "3017",
                "stock_name": "奇鋐",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    db = str(tmp_path / "chi.db")
    _seed_quotes(db, rows)
    rec = record_spoken_path(
        db,
        "3017",
        spoken="奇鋐已經出現股票噴出前 關前整理量價結構確認完成訊號，下星期就開啟主升段。",
        bar=rows[-1],
        bars=rows,
    )
    assert rec.get("key") == "tue_gate"
    assert rec.get("target") == 3595
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
        ("20260924", "3017", "奇鋐", 3460, 3600, 3455, 3555, 2261),
    )
    conn.commit()
    conn.close()
    verify_due(db, "3017")
    g = glance_forecast(db, "3017")
    assert "3600" in g
    assert "碰到" in g
    assert "還沒走完" in g
    assert "待驗證" in g
    assert "對得上" not in g
    line = score_line(db)
    assert "還沒走完" in line
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
        ("20260929", "3017", "奇鋐", 3580, 3620, 3570, 3610, 2800),
    )
    conn.commit()
    conn.close()
    verify_due(db, "3017")
    g1 = glance_forecast(db, "3017")
    assert "對得上" in g1
    assert "3610" in g1
    assert "有效過" in g1
