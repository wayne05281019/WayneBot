# -*- coding: utf-8 -*-
"""薄檔期月營收：本檔已有近月時不准同步全市場抓堵介紹圖（畫質／像素不變）。"""
from __future__ import annotations

import inspect
import time

import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_ensure_thin_with_recent_month_skips_sync_refresh(monkeypatch):
    import fundamentals as fund

    db = get_db_path()
    sid = "2330"
    latest = fund.get_latest_monthly(db, sid)
    assert latest, "測試庫需有近月營收"
    cover = fund.filing_month_coverage(db, fund.previous_calendar_yyyymm())
    if not cover.get("thin"):
        pytest.skip("當前檔期不薄，略過本測")

    sync_calls = {"n": 0}

    def _boom(*_a, **_k):
        sync_calls["n"] += 1
        return {"ok": False, "skipped": "mock"}

    class _NoStartThread:
        """同步路徑測完即返回；背景補抓不准擋這測。"""

        def __init__(self, *a, **k):
            pass

        def start(self):
            return None

    monkeypatch.setattr(fund, "refresh_announced_monthly", _boom)
    monkeypatch.setattr(fund.threading if hasattr(fund, "threading") else __import__("threading"), "Thread", _NoStartThread)
    # Thread 在 ensure 內 import；補丁 builtins 路徑
    import threading as _th

    monkeypatch.setattr(_th, "Thread", _NoStartThread)
    t0 = time.perf_counter()
    out = fund.ensure_stock_fundamentals(db, sid, force=False)
    elapsed = time.perf_counter() - t0
    assert out.get("deferred_thin_refresh") is True
    assert (out.get("monthly") or {}).get("skipped") == "thin_has_recent"
    assert sync_calls["n"] == 0
    assert elapsed < 2.0, elapsed


def test_glance_plain_skip_ensure_flag():
    src = inspect.getsource(
        __import__("fundamentals", fromlist=["glance_fundamentals_plain"]).glance_fundamentals_plain
    )
    assert "skip_ensure" in src
    from wayne_navigator import render_first_glance_png

    gsrc = inspect.getsource(render_first_glance_png)
    assert "skip_ensure=bool(fundamentals_ready)" in gsrc


def test_lookup_jpeg_quality_untouched_by_thin_speed():
    """加速不准降 JPEG／色度。"""
    from wayne_navigator import LOOKUP_JPEG_QUALITY

    assert int(LOOKUP_JPEG_QUALITY) >= 95
