"""碟滿守衛：白名單路徑鎖死；只清可重建出圖快取；不准掃私人表／官方柱／飆大材料。"""

from __future__ import annotations

import inspect
import os
import sqlite3
import time
from pathlib import Path

import disk_guard as dg
from wayne_db import PRIVATE_USER_TABLES


def _scratch_name(code: str = "2330", kind: str = "card", uid: str = "1") -> str:
    """對齊 unique_chart_path：{code}_{kind}_{uid}_{pid}_{ms}_{seq}.png"""
    return f"{code}_{kind}_{uid}_123_4567890123_1.png"


def test_default_ttl_is_24_hours():
    assert dg.DEFAULT_CHART_TTL_SEC == 24 * 60 * 60


def test_free_floor_and_target_locked():
    """5GB 碟：下限 2GB、目標 2.5GB。"""
    assert dg.DEFAULT_MIN_FREE_MB == 2000
    assert dg.DEFAULT_TARGET_FREE_MB == 2500
    assert dg.DEFAULT_TARGET_FREE_MB >= dg.DEFAULT_MIN_FREE_MB


def test_cap_and_interval_tightened():
    """2026-10-04：cap 400MB、排程 15 分；TTL 仍 24h。"""
    assert dg.DEFAULT_CHARTS_CAP_MB == 400
    assert dg.DEFAULT_INTERVAL_SEC == 15 * 60
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


def test_cleanup_purges_lookup_memo_and_scratch(tmp_path: Path, monkeypatch):
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    old_memo = memo / "a.jpg"
    old_memo.write_bytes(b"x" * 5000)
    os.utime(old_memo, (time.time() - 25 * 3600, time.time() - 25 * 3600))
    fresh_memo = memo / "fresh.jpg"
    fresh_memo.write_bytes(b"w" * 3000)
    scratch = charts / _scratch_name("2330", "card", "1")
    scratch.write_bytes(b"y" * 8000)
    old_scratch = charts / _scratch_name("2330", "old", "9")
    old_scratch.write_bytes(b"z" * 4000)
    old_mtime = time.time() - 25 * 60 * 60
    os.utime(old_scratch, (old_mtime, old_mtime))

    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")
    # free 夠高：只走 TTL，不觸發 until_free
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 1000, "free": 4000}
    )

    stats = dg.cleanup_rebuildable_charts(
        str(charts), aggressive=False, root=str(tmp_path), disk_usage_fn=dg.disk_usage_mb
    )
    assert stats["ttl_sec"] == 24 * 60 * 60
    assert stats["allow_subdirs"] == ["_lookup_memo", "wr_pair_cache"]
    assert stats["files"] >= 2
    assert not old_memo.exists()
    assert fresh_memo.exists()
    assert not old_scratch.exists()
    assert scratch.exists()
    assert db.exists()
    assert "until_free" not in stats["parts"]


def test_below_2gb_purges_recent_allowlisted(tmp_path: Path, monkeypatch):
    """規則 2：TTL 後 free 仍＜2GB → 清更近白名單直到目標。"""
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    fresh = memo / "fresh.jpg"
    fresh.write_bytes(b"f" * 4000)
    marks = charts / "marks" / "keep.png"
    marks.parent.mkdir(parents=True)
    marks.write_bytes(b"k" * 2000)

    free_state = {"free": 1500.0}

    def fake_usage(_p):
        return {"total": 5000.0, "used": 5000.0 - free_state["free"], "free": free_state["free"]}

    def tracking_unlink(path, charts_dir):
        mb = dg._file_mb(path) if dg.is_allowlisted_deletable(path, charts_dir) else 0.0
        if mb <= 0:
            return 0.0
        try:
            os.unlink(path)
        except OSError:
            return 0.0
        free_state["free"] += 2000.0  # 模擬清出空間
        return mb

    monkeypatch.setattr(dg, "disk_usage_mb", fake_usage)
    monkeypatch.setattr(dg, "_unlink_allowlisted", tracking_unlink)

    stats = dg.cleanup_rebuildable_charts(
        str(charts),
        aggressive=False,
        root=str(tmp_path),
        min_free_mb=2000,
        target_free_mb=2500,
        disk_usage_fn=fake_usage,
    )
    assert "until_free" in stats["parts"]
    assert stats["parts"]["until_free"]["files"] >= 1
    assert not fresh.exists()
    assert marks.exists()  # 非白名單不動


def test_below_target_purges_recent_allowlisted(tmp_path: Path, monkeypatch):
    """2026-10-04：2GB≤free＜2.5GB 也要清近窗白名單直到目標（舊版只清＞24h＝卡在 below_target）。"""
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    fresh = memo / "fresh.jpg"
    fresh.write_bytes(b"f" * 4000)
    pair = charts / "wr_pair_cache" / "x" / "y.jpg"
    pair.parent.mkdir(parents=True)
    pair.write_bytes(b"p" * 3000)
    marks = charts / "marks" / "keep.png"
    marks.parent.mkdir(parents=True)
    marks.write_bytes(b"k" * 2000)
    corrupt = tmp_path / "wayne_market.db.corrupt-keep"
    corrupt.write_bytes(b"c" * 8000)

    free_state = {"free": 2200.0}

    def fake_usage(_p):
        return {"total": 5000.0, "used": 5000.0 - free_state["free"], "free": free_state["free"]}

    def tracking_unlink(path, charts_dir):
        mb = dg._file_mb(path) if dg.is_allowlisted_deletable(path, charts_dir) else 0.0
        if mb <= 0:
            return 0.0
        try:
            os.unlink(path)
        except OSError:
            return 0.0
        free_state["free"] += 200.0  # 模擬逐步抬 free
        return mb

    monkeypatch.setattr(dg, "disk_usage_mb", fake_usage)
    monkeypatch.setattr(dg, "_unlink_allowlisted", tracking_unlink)

    stats = dg.cleanup_rebuildable_charts(
        str(charts),
        aggressive=False,
        root=str(tmp_path),
        min_free_mb=2000,
        target_free_mb=2500,
        disk_usage_fn=fake_usage,
    )
    assert "until_free" in stats["parts"]
    assert stats["parts"]["until_free"]["files"] >= 1
    assert stats["parts"]["until_free"]["want_free_mb"] == 2500
    assert free_state["free"] >= 2500.0
    assert not fresh.exists()
    assert not pair.exists()
    assert marks.exists()
    assert corrupt.exists()  # .corrupt-* 絕對不動


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
    os.utime(aged, (time.time() - 25 * 3600, time.time() - 25 * 3600))

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

    # free=900 → 低於下限一半 → aggressive；仍不准動私人列
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 4100, "free": 900}
    )
    # checkpoint／VACUUM 只重整；測私人列時直接跳過，避免本機連假 DB
    monkeypatch.setattr(dg, "_try_wal_checkpoint", lambda _p: "skip")
    monkeypatch.setattr(dg, "_try_vacuum_if_room", lambda _p, **_k: "skip")

    out = dg.ensure_disk_headroom(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        force=True,
        min_free_mb=2000,
        target_free_mb=2500,
    )
    assert out["cleaned"] is True
    assert out["min_free_mb"] == 2000
    assert out["target_free_mb"] == 2500
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
    assert "DEFAULT_MIN_FREE_MB = 2000" in src
    assert "DEFAULT_TARGET_FREE_MB = 2500" in src
    assert "DEFAULT_CHARTS_CAP_MB = 400" in src
    assert "DEFAULT_INTERVAL_SEC = 15 * 60" in src
    assert '.corrupt-' in src
    # 近窗 until_free 必須對齊目標，不准只看下限（否則卡在 below_target）
    assert "if free_now < float(target_free_mb):" in src


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


def test_ensure_disk_headroom_force_cleans(tmp_path: Path, monkeypatch):
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    aged = memo / "b.jpg"
    aged.write_bytes(b"m" * 4000)
    os.utime(aged, (time.time() - 25 * 3600, time.time() - 25 * 3600))
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")

    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 100, "free": 4900}
    )
    out = dg.ensure_disk_headroom(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        force=True,
        min_free_mb=2000,
        target_free_mb=2500,
    )
    assert out["cleaned"] is True
    assert out["stats"]["files"] >= 1
    assert not aged.exists()


def test_below_target_triggers_cleanup(tmp_path: Path, monkeypatch):
    """free＜2.5GB 即使 ≥2GB 也要開清（TTL＋近窗 until_free）。"""
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    aged = memo / "d.jpg"
    aged.write_bytes(b"m" * 4000)
    os.utime(aged, (time.time() - 25 * 3600, time.time() - 25 * 3600))
    fresh = memo / "fresh.jpg"
    fresh.write_bytes(b"f" * 4000)
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")
    free_state = {"free": 2200.0}

    def fake_usage(_p):
        return {"total": 5000.0, "used": 5000.0 - free_state["free"], "free": free_state["free"]}

    real_unlink = dg._unlink_allowlisted

    def tracking_unlink(path, charts_dir):
        mb = real_unlink(path, charts_dir)
        if mb > 0:
            # 單檔不夠達標，逼出 until_free 近窗
            free_state["free"] += 200.0
        return mb

    monkeypatch.setattr(dg, "disk_usage_mb", fake_usage)
    monkeypatch.setattr(dg, "_unlink_allowlisted", tracking_unlink)
    monkeypatch.setattr(dg, "_try_wal_checkpoint", lambda _p: "skip")
    monkeypatch.setattr(dg, "_try_vacuum_if_room", lambda _p, **_k: "skip")
    out = dg.ensure_disk_headroom(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        force=False,
        min_free_mb=2000,
        target_free_mb=2500,
    )
    assert out["cleaned"] is True
    assert out["reason"] == "below_target"
    assert not aged.exists()
    # below_target 必須連近窗白名單也清到目標
    assert "until_free" in out["stats"]["parts"]
    assert not fresh.exists()
    assert free_state["free"] >= 2500.0
    assert db.exists()


def test_disk_health_fields_alerts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 3200, "free": 1800}
    )
    fields = dg.disk_health_fields(data_dir=str(tmp_path), db_path=str(tmp_path / "x.db"))
    assert fields["disk_free_mb"] == 1800
    assert fields["disk_min_free_mb"] == 2000
    assert fields["disk_target_free_mb"] == 2500
    assert fields["disk_ok"] is False
    assert fields["disk_alert"] == "below_floor"
    assert "不足" in fields["disk_alert_zh"]

    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 2600, "free": 2400}
    )
    fields = dg.disk_health_fields(data_dir=str(tmp_path))
    assert fields["disk_ok"] is True
    assert fields["disk_alert"] == "below_target"

    monkeypatch.setattr(
        dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 1000, "free": 4000}
    )
    fields = dg.disk_health_fields(data_dir=str(tmp_path))
    assert fields["disk_ok"] is True
    assert fields["disk_alert"] == "ok"
    assert fields["disk_alert_zh"] == ""


def test_run_web_starts_disk_guard():
    import main

    src = inspect.getsource(main.run_web)
    assert "ensure_disk_headroom" in src
    assert "start_disk_guard" in src
    assert src.find("start_health_server") < src.find("ensure_disk_headroom")
    assert src.find("ensure_disk_headroom") < src.find("from wayne_db import")


def test_health_handler_includes_disk_fields():
    import main

    src = inspect.getsource(main.HealthHandler.do_GET)
    assert "disk_health_fields" in src
    assert "disk_free_mb" in src
    assert "disk_alert" in src
    assert "disk_alert_zh" in src
