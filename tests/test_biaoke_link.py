# -*- coding: utf-8 -*-
"""飆大公開文連到同一顆行情庫：南亞科≠南亞、爆大量≠大量。"""
from __future__ import annotations

import os
import sqlite3

from biaoke_desk import load_corpus
from biaoke_link import (
    bar_on,
    extract_mentions,
    format_link_notes,
    link_biaoke_db,
)
from biaoke_net import related_posts


def test_nanya_is_2408_not_1303():
    hits = extract_mentions("南亞科今天值得特別關注")
    sids = [h["stock_id"] for h in hits]
    assert "2408" in sids
    assert "1303" not in sids


def test_volume_spike_is_not_ticker_3167():
    hits = extract_mentions("半獲利已經在2/26日爆大量下跌時賣出")
    sids = [h["stock_id"] for h in hits]
    names = [h["stock_name"] for h in hits]
    assert "3167" not in sids
    assert "大量" not in names


def test_zhiyuan_walk_keeps_origin_and_recent():
    blob = load_corpus(None)
    rel = related_posts("智原", blob["posts"], limit=6)
    dates = {str(p.get("date") or "") for p in rel}
    assert any(d == "2023-12-04" or d.startswith("2023-12") for d in dates)
    assert any(d.startswith("2026-") for d in dates)
    assert any("3035" in (p.get("_sids") or []) for p in rel)
    assert len(rel) <= 6


def test_link_biaoke_db_writes_mentions(tmp_path):
    db = str(tmp_path / "w.db")
    from biaoke_archive import seed_biaoke_archive

    seed_biaoke_archive(db)
    stats = link_biaoke_db(db)
    assert stats["posts"] >= 1709
    assert stats["mentions"] >= 1700
    assert stats["stocks"] >= 40
    conn = sqlite3.connect(db)
    nanya = conn.execute(
        "SELECT COUNT(*) FROM biaoke_mentions WHERE stock_id='2408'"
    ).fetchone()[0]
    zhi = conn.execute(
        "SELECT COUNT(*) FROM biaoke_mentions WHERE stock_id='3035'"
    ).fetchone()[0]
    bulk = conn.execute(
        "SELECT COUNT(*) FROM biaoke_mentions WHERE stock_id='3167'"
    ).fetchone()[0]
    conn.close()
    assert nanya >= 10
    assert zhi >= 5
    assert bulk == 0


def test_link_notes_use_official_bar_when_present():
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    bar = bar_on(db, "2408", "2025-05-22")
    if not bar:
        return
    assert abs(float(bar["close"]) - 42.85) < 0.02
    blob = load_corpus(None)
    rel = related_posts("南亞科", blob["posts"], limit=4, db_path=db)
    note = format_link_notes(rel, db_path=db, limit=3)
    assert "連線" in note
    assert "2408" in note or "南亞科" in note
    assert "語料" not in note
