# -*- coding: utf-8 -*-
"""主述新鮮度：過舊要標、彙整後可刷新、自主檢查可落檔。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

TAIPEI = ZoneInfo("Asia/Taipei")


def _mk_db(tmp_path, *, board_ymd="20261110", twii_ymd="20261113"):
    db = str(tmp_path / "n.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE biaoke_posts(
            id TEXT, kind TEXT, date TEXT, time TEXT, text TEXT
        );
        CREATE TABLE biaoke_level_snaps(
            as_of TEXT, post_date TEXT, post_id TEXT, snippet TEXT,
            created_at TEXT DEFAULT ''
        );
        CREATE TABLE quotes(
            stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,
            close REAL, volume REAL
        );
        """
    )
    by = f"{board_ymd[:4]}-{board_ymd[4:6]}-{board_ymd[6:8]}"
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?)",
        ("p1", "post", by, "21:00", "夜盤過C3下降壓，不再假跌破"),
    )
    conn.execute(
        "INSERT INTO biaoke_level_snaps VALUES (?,?,?,?,?)",
        (board_ymd, by, "p1", "不再假跌破", "2026-11-10T21:00:00"),
    )
    # 加權完整柱：給 latest_complete_quote_date / _twii_chart_as_of 備援
    for d in (board_ymd, twii_ymd):
        ds = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        conn.execute(
            "INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?,?,?)",
            ("^TWII", ds, 1, 2, 0.5, 1.5, 100),
        )
    conn.commit()
    conn.close()
    return db


def test_assess_stale_when_board_lags_twii(tmp_path, monkeypatch):
    from phone_narrative_freshness import assess_narrative_freshness

    db = _mk_db(tmp_path, board_ymd="20261110", twii_ymd="20261113")
    monkeypatch.setattr(
        "phone_narrative_freshness.official_twii_ymd", lambda _p: "20261113"
    )
    # 11/10→11/13：中間至少一個開市日
    fresh = assess_narrative_freshness(
        db, now=datetime(2026, 11, 13, 16, 0, tzinfo=TAIPEI), thesis_as_of="20261110"
    )
    assert fresh["board_ymd"] == "20261110"
    assert fresh["twii_ymd"] == "20261113"
    assert fresh["stale"] is True
    assert "落後" in fresh["note"] or "距今" in fresh["note"]


def test_assess_fresh_same_day(tmp_path, monkeypatch):
    from phone_narrative_freshness import assess_narrative_freshness

    db = _mk_db(tmp_path, board_ymd="20261113", twii_ymd="20261113")
    monkeypatch.setattr(
        "phone_narrative_freshness.official_twii_ymd", lambda _p: "20261113"
    )
    fresh = assess_narrative_freshness(
        db, now=datetime(2026, 11, 13, 22, 0, tzinfo=TAIPEI), thesis_as_of="20261113"
    )
    assert fresh["stale"] is False


def test_assess_weekend_ok_monday_stale(tmp_path, monkeypatch):
    """休市週末他文＝上周五收不算過舊；下周一開市仍停舊文要標。"""
    from phone_narrative_freshness import assess_narrative_freshness

    db = _mk_db(tmp_path, board_ymd="20261113", twii_ymd="20261113")
    monkeypatch.setattr(
        "phone_narrative_freshness.official_twii_ymd", lambda _p: "20261113"
    )
    sun = assess_narrative_freshness(
        db, now=datetime(2026, 11, 15, 23, 0, tzinfo=TAIPEI), thesis_as_of="20261113"
    )
    mon = assess_narrative_freshness(
        db, now=datetime(2026, 11, 16, 9, 0, tzinfo=TAIPEI), thesis_as_of="20261113"
    )
    assert sun["stale"] is False
    assert mon["stale"] is True
    assert "距今" in mon["note"]


def test_banner_warns_when_stale():
    from phone_narrative_freshness import freshness_banner_html, freshness_banner_plain

    fresh = {
        "stale": True,
        "board_ymd": "20261110",
        "board_when": "2026-11-10 21:00",
        "twii_ymd": "20261113",
        "note": "他文落後加權3開市日",
    }
    html = freshness_banner_html(fresh)
    assert "他文" in html and "加權已收" in html
    assert "脫離現況" in html
    assert "as_of" not in html
    plain = freshness_banner_plain(fresh)
    assert "⚠" in plain


def test_teach_brief_dates_said_tag(monkeypatch, tmp_path):
    """硬編碼題旨分支要標文日，不准裸「他最新」。"""
    from biaoke_digest import format_teach_brief

    db = _mk_db(tmp_path, board_ymd="20261110", twii_ymd="20261113")

    def _fake_pack(_db):
        return {
            "thesis": "大A→大B→大C｜夜盤過C3下降壓・週五低不再假跌破",
            "wait_struct": "回測下降壓力線；清洗籌碼",
            "chart_as_of": "20261110",
            "thesis_as_of": "20261110",
            "intent_note": "",
            "morph_note": "",
            "pred_note": "41500｜37837",
        }

    monkeypatch.setattr("biaoke_level_learn._build_live_pack", _fake_pack)
    monkeypatch.setattr(
        "phone_narrative_freshness.official_twii_ymd", lambda _p: "20261113"
    )
    out = format_teach_brief(db)
    assert "波浪位階" in out
    assert "他曾講" in out
    assert "他最新：" not in out
    assert "脫離現況" in out or "加權已收" in out


def test_feature_self_check_marks_pipeline(tmp_path, monkeypatch):
    from feature_self_check import run_feature_self_check

    db = _mk_db(tmp_path, board_ymd="20261110", twii_ymd="20261113")
    monkeypatch.setattr(
        "phone_narrative_freshness.official_twii_ymd", lambda _p: "20261113"
    )
    monkeypatch.setattr(
        "biaoke_level_learn.teach_kit_needs_restore", lambda _p: False, raising=False
    )
    monkeypatch.setattr(
        "biaoke_level_learn.latest_teach_kit",
        lambda _p: {"far_path": "/x.png", "near_path": "/y.png", "micro_path": "/z.png"},
        raising=False,
    )
    rep = run_feature_self_check(db)
    assert "features" in rep
    assert any(f.get("feature") == "narrative" for f in rep["features"])
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT run_date, status FROM pipeline_runs WHERE run_date LIKE 'feat-check-%'"
    ).fetchall()
    conn.close()
    assert rows


def test_absorb_hooks_narrative_fresh():
    import inspect

    import biaoke_absorb

    src = inspect.getsource(biaoke_absorb.run_absorb)
    assert "refresh_and_check" in src or "run_narrative_self_check" in src


def test_post_fuse_hooks_narrative_fresh():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner._run_post_fuse_silent_tracks)
    assert "narrative-fresh" in src
    assert "refresh_and_check" in src


def test_blank_biaoke_refreshes_posts_before_oral():
    """空白飆大主述前先補公開文，與波浪同層；不准只讀舊 corpus。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "_ensure_teach_biaoke_posts_fresh" in src
    posts_at = src.index("_ensure_teach_biaoke_posts_fresh")
    focus_at = src.index("format_latest_focus")
    assert posts_at < focus_at


def test_blank_teach_charts_reject_stale_kit_fallback():
    """遠窗 fallback 不准送 as_of 落後加權的舊教具。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_biaoke_teach_charts)
    assert "_twii_chart_as_of" in src
    assert "latest_teach_kit" in src
    assert "fallback 略過" in src or "存檔 as_of" in src


def test_level_teach_push_skips_nov4_stale_on_rescan(tmp_path, monkeypatch):
    """重掃 11/4 大盤點位舊文不准當「飆大更新」推兩支話筒。"""
    from datetime import datetime

    from biaoke_level_learn import maybe_push_level_teach_update

    db = str(tmp_path / "push.db")
    text = (
        "目前大盤用期貨日盤比較容易定波浪位階，目前應該是在3-3走完，"
        "轉3-4機率比較高，會去測9865，3-5會去測7/29低點40000；"
        "跌到35000~38000之間，雖然非常慘烈"
    )
    ev = {
        "id": "187638311",
        "date": "2026-11-04",
        "time": "13:16",
        "kind": "post",
        "text": text,
        "_ingest": "updated",  # 重掃補齊
    }
    monkeypatch.setenv("WAYNE_LEVEL_LEARN_LIVE", "1")
    monkeypatch.setattr(
        "config.allowed_telegram_uids", lambda: ["111", "222"], raising=False
    )
    sent: list = []
    monkeypatch.setattr(
        "biaoke_alert._send_family",
        lambda *a, **k: sent.append("text") or 2,
        raising=False,
    )
    monkeypatch.setattr(
        "biaoke_alert._send_family_photos",
        lambda *a, **k: sent.append("photo") or 2,
        raising=False,
    )
    monkeypatch.setattr(
        "biaoke_alert._claim_chat_dedupe",
        lambda *a, **k: True,
        raising=False,
    )
    monkeypatch.setattr(
        "biaoke_level_learn.maybe_paint_open_day_after_ingest",
        lambda *a, **k: {"ok": False},
        raising=False,
    )
    out = maybe_push_level_teach_update(
        db,
        [ev],
        now=datetime(2026, 11, 15, 23, 43, tzinfo=TAIPEI),
    )
    assert out.get("pushed", 0) == 0
    assert not sent
    assert int(out.get("updated_skip") or 0) >= 1 or out.get("skipped") == "stale_or_updated"

    # 即使誤標 added，超過 24h 仍不准推
    ev2 = dict(ev)
    ev2["_ingest"] = "added"
    out2 = maybe_push_level_teach_update(
        db,
        [ev2],
        now=datetime(2026, 11, 15, 23, 43, tzinfo=TAIPEI),
    )
    assert out2.get("pushed", 0) == 0
    assert not sent
    assert int(out2.get("stale") or 0) >= 1 or out2.get("skipped") == "stale_or_updated"


def test_level_teach_push_allows_fresh_added(tmp_path, monkeypatch):
    """當日新 added 位階文才准推。"""
    from datetime import datetime

    from biaoke_level_learn import maybe_push_level_teach_update

    db = str(tmp_path / "push2.db")
    text = "大盤目前 C3-3 主跌段，會去測加權 42000 附近"
    ev = {
        "id": "new1",
        "date": "2026-11-15",
        "time": "21:00",
        "kind": "post",
        "text": text,
        "_ingest": "added",
    }
    monkeypatch.setenv("WAYNE_LEVEL_LEARN_LIVE", "1")
    monkeypatch.setattr(
        "config.allowed_telegram_uids", lambda: ["111"], raising=False
    )
    sent: list = []
    monkeypatch.setattr(
        "biaoke_alert._send_family",
        lambda *a, **k: sent.append(a[0] if a else "t") or 1,
        raising=False,
    )
    monkeypatch.setattr(
        "biaoke_alert._send_family_photos",
        lambda *a, **k: 0,
        raising=False,
    )
    monkeypatch.setattr(
        "biaoke_alert._claim_chat_dedupe",
        lambda *a, **k: True,
        raising=False,
    )
    monkeypatch.setattr(
        "biaoke_level_learn.maybe_paint_open_day_after_ingest",
        lambda *a, **k: {"ok": False},
        raising=False,
    )
    monkeypatch.setattr(
        "biaoke_level_learn.latest_teach_kit",
        lambda *_a, **_k: {},
        raising=False,
    )
    out = maybe_push_level_teach_update(
        db,
        [ev],
        now=datetime(2026, 11, 15, 21, 30, tzinfo=TAIPEI),
    )
    assert int(out.get("pushed") or 0) >= 1
    assert sent
    assert "飆大更新・大盤點位" in str(sent[0])
    assert "2026-11-15" in str(sent[0])
