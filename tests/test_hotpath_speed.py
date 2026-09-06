# -*- coding: utf-8 -*-
"""互動熱路徑：資金／查股／決策卡不要被全表掃描或每張圖 GC 卡住。"""
from __future__ import annotations

import inspect
import time

import pytest

from bot_servers import WayneTelegramBot
from import_health import audit_import
from money_flow import compute_sector_rows, format_flow_html
from tests.conftest import require_production_db


def test_audit_import_counts_use_indexed_date():
    src = inspect.getsource(audit_import)
    assert "WHERE date=?" in src
    assert "replace(date,'-','')=?" not in src
    assert "history: bool = True" in src


def test_flow_sector_rows_use_indexed_date():
    src = inspect.getsource(compute_sector_rows)
    assert "WHERE q.date=?" in src
    assert "replace(q.date" not in src


def test_lookup_gc_once_after_all_pngs():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    loop = src[src.index("for kind, fn") : src.index("try:\n                gc.collect")]
    assert "gc.collect" not in loop
    assert src.count("gc.collect") == 1


def test_decision_card_quick_shares_lookup_timeouts():
    src = inspect.getsource(WayneTelegramBot._send_decision_card_quick)
    assert "_CARD_BUILD_TIMEOUT" in src
    assert "_LOOKUP_PNG_TIMEOUT" in src
    assert "timeout=20)" not in src
    assert "timeout=25," not in src
    assert "timeout=25)" not in src


@pytest.mark.production_db
def test_audit_import_cover_without_history_is_fast():
    db = require_production_db()
    t0 = time.perf_counter()
    health = audit_import(db, "20260904", history=False)
    elapsed = time.perf_counter() - t0
    assert health["tw"] >= 800
    assert health["two"] >= 600
    assert health["history_issue_n"] == 0
    assert elapsed < 0.8, f"資金封面 audit {elapsed:.2f}s"


@pytest.mark.production_db
def test_flow_html_under_telegram_budget():
    db = require_production_db()
    t0 = time.perf_counter()
    html = format_flow_html(db)
    elapsed = time.perf_counter() - t0
    assert html
    assert "資金" in html or "輪動" in html
    assert elapsed < 4.0, f"資金頁 {elapsed:.1f}s，Telegram 12s 會逾時"
