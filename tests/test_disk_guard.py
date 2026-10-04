"""碟滿守衛：白名單路徑鎖死；只清可重建出圖快取；不准掃私人表／官方柱／飆大材料。"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import time
from pathlib import Path

import disk_guard as dg
from wayne_db import PRIVATE_USER_TABLES


def _scratch_name(code: str = "2330", kind: str = "card", uid: str = "1") -> str:
    """對齊 unique_chart_path：{code}_{kind}_{uid}_{pid}_{ms}_{seq}.png"""
    return f"{code}_{kind}_{uid}_123_4567890123_1.png"


def test_default_emergency_floor_relaxed():
    """2026-10-04：取消 2GB／2.5GB 追趕；緊急線 ~250MB。"""
    assert dg.DEFAULT_MIN_FREE_MB == 250
    assert dg.DEFAULT_TARGET_FREE_MB == 250
    assert dg._VACUUM_MIN_FREE_MB >= 1000


def test_cap_and_day_interval():
    assert dg.DEFAULT_CHARTS_CAP_MB == 400
    assert dg.DEFAULT_INTERVAL_SEC == 30 * 60
    assert dg.DEFAULT_CHART_TTL_SEC == 24 * 60 * 60


def test_allowlist_subdirs_locked():
    assert dg.ALLOW_CHART_SUBDIRS == ("_lookup_memo", "wr_pair_cache")


def test_is_allowlisted_deletable_paths(tmp_path: Path):
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    memo_file = memo / "a.jpg"
    memo_file.write_bytes(b"x")
    pair = charts / "wr_pair_cache" / "x" / "y.jpg"
    pair.parent.mkdir(parents=True)
    pair.write_bytes(b"y")
    scratch = charts / _scratch_name()
    scratch.write_bytes(b"z")
    marks = charts / "marks" / "keep.png"
    marks.parent.mkdir(parents=True)
    marks.write_bytes(b"k")
    plain = charts / "2330_card.png"
    plain.write_bytes(b"p")
    archive = charts / "archive_1709.json.gz"
    archive.write_bytes(b"a")
    db_in_charts = charts / "wayne_market.db"
    db_in_charts.write_bytes(b"d")
    corrupt = charts / "wayne_market.db.corrupt-20261004"
    corrupt.write_bytes(b"c")

    root = str(charts)
    assert dg.is_allowlisted_deletable(str(memo_file), root)
    assert dg.is_allowlisted_deletable(str(pair), root)
    assert dg.is_allowlisted_deletable(str(scratch), root)
    assert not dg.is_allowlisted_deletable(str(marks), root)
    assert not dg.is_allowlisted_deletable(str(plain), root)
    assert not dg.is_allowlisted_deletable(str(archive), root)
    assert not dg.is_allowlisted_deletable(str(db_in_charts), root)
    assert not dg.is_allowlisted_deletable(str(corrupt), root)
    assert not dg.is_allowlisted_deletable(str(tmp_path / "wayne_market.db"), root)


def test_daytime_skips_when_above_emergency(tmp_path: Path, monkeypatch):
    """白天 free≥緊急線：不准清、不准追高 free。"""
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    kept = memo / "keep.jpg"
    kept.write_bytes(b"k" * 4000)
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 3000, "free": 1865}
    )
    vacuum_calls = []
    monkeypatch.setattr(
        dg, "_try_vacuum_if_room", lambda *_a, **_k: vacuum_calls.append(1) or "ok"
    )
    out = dg.ensure_disk_headroom(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        force=True,
        mode="daytime",
    )
    assert out["reason"] == "ok_daytime"
    assert out["cleaned"] is False
    assert kept.exists()
    assert vacuum_calls == []
    assert db.exists()


def test_emergency_purges_allowlisted_only(tmp_path: Path, monkeypatch):
    """free≈200～300MB：只強清白名單。"""
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    drop = memo / "drop.jpg"
    drop.write_bytes(b"d" * 4000)
    scratch = charts / _scratch_name()
    scratch.write_bytes(b"s" * 3000)
    marks = charts / "marks" / "keep.png"
    marks.parent.mkdir(parents=True)
    marks.write_bytes(b"k" * 2000)
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")
    corrupt = tmp_path / "wayne_market.db.corrupt-keep"
    corrupt.write_bytes(b"c")
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 4800, "free": 220}
    )
    monkeypatch.setattr(dg, "_try_wal_checkpoint", lambda _p: "ok")
    vacuum_calls = []
    monkeypatch.setattr(
        dg, "_try_vacuum_if_room", lambda *_a, **_k: vacuum_calls.append(1) or "ok"
    )
    out = dg.ensure_disk_headroom(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        mode="daytime",
    )
    assert out["reason"] == "emergency"
    assert out["cleaned"] is True
    assert out["vacuum"] == "skip_below_target"
    assert vacuum_calls == []
    assert not drop.exists()
    assert not scratch.exists()
    assert marks.exists()
    assert db.exists()
    assert corrupt.exists()


def test_midnight_purges_allowlisted(tmp_path: Path, monkeypatch):
    """台北午夜：例行全清白名單（即使 free 尚可）。"""
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    drop = memo / "night.jpg"
    drop.write_bytes(b"n" * 4000)
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 2800, "free": 2200}
    )
    monkeypatch.setattr(dg, "_try_wal_checkpoint", lambda _p: "ok")
    monkeypatch.setattr(dg, "_try_vacuum_if_room", lambda *_a, **_k: "ok")
    out = dg.run_midnight_cache_purge(
        data_dir=str(tmp_path), charts_dir=str(charts), db_path=str(db)
    )
    assert out["reason"] == "midnight"
    assert out["cleaned"] is True
    assert not drop.exists()
    assert db.exists()


def test_cleanup_aggressive_clears_all_allowlisted_scratch(tmp_path: Path, monkeypatch):
    charts = tmp_path / "charts"
    charts.mkdir()
    fresh = charts / _scratch_name("2330", "card", "fresh")
    fresh.write_bytes(b"f" * 3000)
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 4900, "free": 100}
    )
    stats = dg.cleanup_rebuildable_charts(
        str(charts), aggressive=True, root=str(tmp_path), disk_usage_fn=dg.disk_usage_mb
    )
    assert stats["files"] >= 1
    assert not fresh.exists()


def test_pair_cache_deletes_over_24h(tmp_path: Path):
    charts = tmp_path / "charts"
    root = charts / "wr_pair_cache" / "card_lz_paint_ex5" / "2026-10-01"
    root.mkdir(parents=True)
    fresh = root / "2330_vz.jpg"
    old = root / "2330_card.jpg"
    fresh.write_bytes(b"p" * 2000)
    old.write_bytes(b"q" * 2000)
    os.utime(old, (time.time() - 25 * 3600, time.time() - 25 * 3600))
    cutoff = time.time() - 24 * 3600
    n, _mb = dg._purge_allowlisted(str(charts), older_than=cutoff, all_files=False)
    assert n >= 1
    assert fresh.exists()
    assert not old.exists()


def test_protected_db_and_non_allowlist_not_deleted(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"keep")
    corrupt = tmp_path / "wayne_market.db.corrupt-20261004"
    corrupt.write_bytes(b"keep-corrupt")
    marks = charts / "marks" / "keep.png"
    marks.parent.mkdir()
    marks.write_bytes(b"keep")
    silent = tmp_path / "silent_verify.json"
    silent.write_bytes(b"keep")
    archive = tmp_path / "archive_1709.json.gz"
    archive.write_bytes(b"keep-archive")
    assert dg._unlink_allowlisted(str(db), str(charts)) == 0.0
    assert dg._unlink_allowlisted(str(corrupt), str(charts)) == 0.0
    assert dg._unlink_allowlisted(str(marks), str(charts)) == 0.0
    assert dg._unlink_allowlisted(str(silent), str(charts)) == 0.0
    assert dg._unlink_allowlisted(str(archive), str(charts)) == 0.0
    assert db.exists()
    assert corrupt.exists()
    assert marks.exists()
    assert silent.exists()
    assert archive.exists()


def test_cleanup_never_touches_private_tables_or_ohlc(tmp_path: Path, monkeypatch):
    """清碟不准掃到私人表／官方柱／飆大材料；偉權與哥哥列都留。"""
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    aged = memo / "drop.jpg"
    aged.write_bytes(b"m" * 4000)

    db = tmp_path / "wayne_market.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE daily_ohlc (stock_id TEXT, trade_date TEXT, open REAL, "
            "high REAL, low REAL, close REAL, volume REAL)"
        )
        conn.execute(
            "INSERT INTO daily_ohlc VALUES ('2330','2026-10-01',1,2,0.5,1.5,100)"
        )
        conn.execute(
            "CREATE TABLE biaoke_posts (post_id TEXT PRIMARY KEY, body TEXT)"
        )
        conn.execute("INSERT INTO biaoke_posts VALUES ('p1','keep')")
        for table in (
            "user_holdings",
            "user_watchlist",
            "tg_actor_pending",
            "user_states",
            "ai_fills",
            "tg_users",
        ):
            assert table in PRIVATE_USER_TABLES
            conn.execute(f"CREATE TABLE {table} (user_id TEXT, payload TEXT)")
            conn.execute(
                f"INSERT INTO {table} VALUES ('wayne','w'), ('8772209416','b')"
            )
        conn.execute(
            "CREATE TABLE silent_verify_tape (as_of TEXT, rule_key TEXT, codes TEXT)"
        )
        conn.execute(
            "INSERT INTO silent_verify_tape VALUES ('2026-10-01','leave_zero','2330')"
        )
        conn.commit()
    finally:
        conn.close()

    archive = tmp_path / "archive_1709.json.gz"
    archive.write_bytes(b"archive")
    corpus = tmp_path / "corpus" / "corpus_index.json"
    corpus.parent.mkdir()
    corpus.write_bytes(b"{}")
    corrupt = tmp_path / "wayne_market.db.corrupt-keep"
    corrupt.write_bytes(b"corrupt-backup")

    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 4800, "free": 200}
    )
    monkeypatch.setattr(dg, "_try_wal_checkpoint", lambda _p: "skip")
    monkeypatch.setattr(dg, "_try_vacuum_if_room", lambda _p, **_k: "skip")

    out = dg.ensure_disk_headroom(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        force=False,
        mode="daytime",
    )
    assert out["cleaned"] is True
    assert out["reason"] == "emergency"
    assert not aged.exists()

    assert archive.exists()
    assert corpus.exists()
    assert corrupt.exists()
    assert db.exists()
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM daily_ohlc").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM biaoke_posts").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM silent_verify_tape").fetchone()[0] == 1
        )
        for table in (
            "user_holdings",
            "user_watchlist",
            "tg_actor_pending",
            "user_states",
            "ai_fills",
            "tg_users",
        ):
            rows = conn.execute(
                f"SELECT user_id FROM {table} ORDER BY user_id"
            ).fetchall()
            assert [r[0] for r in rows] == ["8772209416", "wayne"], table
    finally:
        conn.close()


def test_disk_guard_source_has_no_table_delete():
    src = inspect.getsource(dg)
    assert "DELETE FROM" not in src.upper()
    assert "DROP TABLE" not in src.upper()
    assert "PRIVATE_USER_TABLES" not in src
    assert "is_allowlisted_deletable" in src
    assert "_lookup_memo" in src
    assert "wr_pair_cache" in src
    assert "DEFAULT_MIN_FREE_MB = 250" in src
    assert "run_midnight_cache_purge" in src
    assert "mode=\"midnight\"" in src or "mode='midnight'" in src or 'mode_s == "midnight"' in src
    assert "skip_below_target" in src
    assert '.corrupt-' in src
    assert "maybe_push_runway_alert" in src
    assert "DEFAULT_WARN_FREE_MB" in src


def test_iter_allowlisted_never_walks_outside_charts(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / _scratch_name()).write_bytes(b"s")
    private_json = tmp_path / "user_holdings_backup.json"
    private_json.write_bytes(b"{}")
    listed = list(dg._iter_allowlisted_files(str(charts)))
    assert all(str(charts) in p for p in listed)
    assert not any("user_holdings" in p for p in listed)
    assert not any(str(private_json) == p for p in listed)


def test_disk_health_fields_alerts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 4800, "free": 180}
    )
    fields = dg.disk_health_fields(data_dir=str(tmp_path), db_path=str(tmp_path / "x.db"))
    assert fields["disk_free_mb"] == 180
    assert fields["disk_min_free_mb"] == 250
    assert fields["disk_ok"] is False
    assert fields["disk_alert"] == "below_floor"

    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 4200, "free": 800}
    )
    fields = dg.disk_health_fields(data_dir=str(tmp_path))
    assert fields["disk_ok"] is True
    assert fields["disk_alert"] == "runway_warn"
    assert fields["disk_warn_free_mb"] == 900

    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 1000, "free": 4000}
    )
    fields = dg.disk_health_fields(data_dir=str(tmp_path))
    assert fields["disk_ok"] is True
    assert fields["disk_alert"] == "ok"


def test_measure_durable_excludes_rebuildable(tmp_path: Path):
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    (memo / "cache.jpg").write_bytes(b"c" * (2 * 1024 * 1024))
    scratch = charts / _scratch_name()
    scratch.write_bytes(b"s" * (1024 * 1024))
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"d" * (3 * 1024 * 1024))
    archive = tmp_path / "archive_1709.json.gz"
    archive.write_bytes(b"a" * (1024 * 1024))
    sizes = dg.measure_durable_mb(str(tmp_path), charts_dir=str(charts), db_path=str(db))
    assert sizes["durable_mb"] >= 3.9  # db + archive
    assert sizes["rebuildable_mb"] >= 2.9  # memo + scratch
    # durable 不含白名單快取
    assert sizes["durable_mb"] < 5.5


def test_runway_estimate_and_dedupe_alert(tmp_path: Path, monkeypatch):
    charts = tmp_path / "charts"
    charts.mkdir()
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"d" * 4000)
    # 模擬 5 天前較小 durable、現在較大
    state_path = tmp_path / dg._RUNWAY_STATE_NAME
    now = time.time()
    state = {
        "snapshots": [
            {
                "ts": now - 5 * 86400,
                "durable_mb": 100.0,
                "free_mb": 2000.0,
                "total_mb": 5000.0,
            },
            {
                "ts": now - 2 * 86400,
                "durable_mb": 250.0,
                "free_mb": 1200.0,
                "total_mb": 5000.0,
            },
        ],
        "last_alert": None,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 4300, "free": 700}
    )
    monkeypatch.setattr(
        dg,
        "measure_durable_mb",
        lambda *_a, **_k: {"durable_mb": 400.0, "rebuildable_mb": 10.0},
    )
    sent: list = []
    out = dg.maybe_push_runway_alert(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        now_ts=now,
        send_fn=lambda t: sent.append(t) or 2,
    )
    assert out["estimate"]["need_warn"] is True
    assert out["estimate"]["runway_days"] is not None
    assert out["estimate"]["runway_days"] < 30
    assert out["pushed"] is True
    assert len(sent) == 1
    assert "大概還能撐" in sent[0]
    assert "建議考慮加購" in sent[0]
    assert "不會自己買" in sent[0]

    # 同簽名去重
    out2 = dg.maybe_push_runway_alert(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        now_ts=now + 60,
        send_fn=lambda t: sent.append(t) or 2,
    )
    assert out2["skipped"] == "dedupe"
    assert len(sent) == 1


def test_format_runway_unknown_trend():
    text = dg.format_runway_alert_zh(
        {
            "free_mb": 1500,
            "min_free_mb": 250,
            "runway_days": None,
            "trend": "short_history",
        }
    )
    assert "估不準" in text
    assert "1500" in text or "剩餘約 1500" in text


def test_main_boot_disk_guard_emergency_only():
    import main

    src = inspect.getsource(main.run_web)
    assert "ensure_disk_headroom" in src
    assert "start_disk_guard" in src
    assert 'mode="boot"' in src or "mode='boot'" in src
    assert src.find("start_health_server") < src.find("ensure_disk_headroom")


def test_start_disk_guard_has_midnight_thread():
    src = inspect.getsource(dg.start_disk_guard)
    assert "disk-guard-midnight" in src
    assert "run_midnight_cache_purge" in src
    assert "disk-guard-day" in src
    assert "跑道" in src or "DEFAULT_WARN_FREE_MB" in src


def test_disk_guard_source_mentions_runway():
    src = inspect.getsource(dg)
    assert "maybe_push_runway_alert" in src
    assert "DEFAULT_WARN_FREE_MB" in src
    assert "ALLOWED" not in src or "allowed_telegram_uids" in src
    assert "不會自己買" in src or "不會自己買" in dg.format_runway_alert_zh(
        {"free_mb": 1, "min_free_mb": 250, "runway_days": 1, "trend": "growing"}
    )
