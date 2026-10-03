"""碟滿守衛：只清可重建出圖快取；週期／開機必跑；不准動官方庫／私人材料。"""

from __future__ import annotations

import inspect
import os
import time
from pathlib import Path

import disk_guard as dg


def test_default_ttl_is_24_hours():
    assert dg.DEFAULT_CHART_TTL_SEC == 24 * 60 * 60


def test_cleanup_purges_lookup_memo_and_scratch(tmp_path: Path):
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    old_memo = memo / "a.jpg"
    old_memo.write_bytes(b"x" * 5000)
    os.utime(old_memo, (time.time() - 25 * 3600, time.time() - 25 * 3600))
    fresh_memo = memo / "fresh.jpg"
    fresh_memo.write_bytes(b"w" * 3000)
    scratch = charts / "2330_card_1_123_1.png"
    scratch.write_bytes(b"y" * 8000)
    old = charts / "2330_old.png"
    old.write_bytes(b"z" * 4000)
    old_mtime = time.time() - 25 * 60 * 60
    os.utime(old, (old_mtime, old_mtime))

    # 保護：假裝官方庫路徑不可被清（放在 charts 外）
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")

    stats = dg.cleanup_rebuildable_charts(str(charts), aggressive=False)
    assert stats["ttl_sec"] == 24 * 60 * 60
    assert stats["files"] >= 2
    assert not old_memo.exists()
    assert fresh_memo.exists()
    assert not old.exists()
    # 未過 24h 的 scratch 留下
    assert scratch.exists()
    assert db.exists()


def test_cleanup_aggressive_clears_all_scratch(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    fresh = charts / "2330_card_fresh.png"
    fresh.write_bytes(b"f" * 3000)
    stats = dg.cleanup_rebuildable_charts(str(charts), aggressive=True)
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
    n, _mb = dg._purge_old_pair_cache(str(charts), ttl_sec=24 * 3600)
    assert n >= 1
    assert fresh.exists()
    assert not old.exists()


def test_protected_db_not_deleted(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"keep")
    assert dg._is_protected(str(db))
    assert dg._unlink(str(db)) == 0.0
    assert db.exists()


def test_ensure_disk_headroom_force_cleans(tmp_path: Path, monkeypatch):
    charts = tmp_path / "charts"
    memo = charts / "_lookup_memo"
    memo.mkdir(parents=True)
    (memo / "b.jpg").write_bytes(b"m" * 4000)
    db = tmp_path / "wayne_market.db"
    db.write_bytes(b"db")

    monkeypatch.setattr(dg, "disk_usage_mb", lambda _p: {"total": 5000, "used": 100, "free": 4900})
    monkeypatch.setattr(
        "config.get_charts_dir",
        lambda: str(charts),
        raising=False,
    )
    # ensure imports config inside — patch via injecting paths
    out = dg.ensure_disk_headroom(
        data_dir=str(tmp_path),
        charts_dir=str(charts),
        db_path=str(db),
        force=True,
        min_free_mb=400,
    )
    assert out["cleaned"] is True
    assert out["stats"]["files"] >= 1
    assert not (memo / "b.jpg").exists()


def test_run_web_starts_disk_guard():
    import main

    src = inspect.getsource(main.run_web)
    assert "ensure_disk_headroom" in src
    assert "start_disk_guard" in src
    assert src.find("start_health_server") < src.find("ensure_disk_headroom")
    assert src.find("ensure_disk_headroom") < src.find("from wayne_db import")
