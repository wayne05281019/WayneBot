# -*- coding: utf-8 -*-
"""產業同業：不准用「其他」互相比；櫃買細項只蓋籌碼K其他桶。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from industry_fine import chain_peer_ids, extra_tags_for, membership_keys
from tpex_industry_chain import apply_tpex_overlay, is_catchall_label, load_tpex_seed
from wayne_db import ensure_core_schema


def _fine(db: str, rows: list) -> None:
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_fine_industry (
            stock_id TEXT PRIMARY KEY,
            chain TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            cat_id TEXT DEFAULT '',
            source TEXT DEFAULT '',
            fetched_at TEXT NOT NULL
        )
        """
    )
    for sid, name, chain in rows:
        tags = chain.split("-")
        conn.execute(
            "INSERT OR REPLACE INTO stock_universe"
            "(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (sid, name, "TWO", "STOCK", "其他業", now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO stock_fine_industry"
            "(stock_id,chain,tags_json,cat_id,source,fetched_at) VALUES (?,?,?,?,?,?)",
            (sid, chain, json.dumps(tags, ensure_ascii=False), "", "test", now),
        )
    conn.commit()
    conn.close()


def test_catchall_label_and_tpex_seed_skips_tianpin():
    assert is_catchall_label("其他")
    assert is_catchall_label("其他業")
    assert is_catchall_label("其他電子產品及電子服務產業")
    assert not is_catchall_label("散熱零組件")
    assert not is_catchall_label("導線架")
    seed = load_tpex_seed()
    assert "2330" in seed
    assert seed["2330"]["finest"] == "IC/晶圓製造"
    assert "6199" not in seed
    assert "6933" not in seed
    assert "3324" in seed
    assert "散熱" in seed["3324"]["chain"] or "散熱" in "".join(seed["3324"]["tags"])


def test_other_bucket_is_not_a_peer_key():
    assert membership_keys("6199", "其他") == set()
    assert membership_keys("5604", "其他") == set()
    assert extra_tags_for("6933") == ["散熱"]
    assert ("x", "散熱") in membership_keys("6933", "其他")
    assert ("fine", "其他") not in membership_keys("6933", "其他")
    assert not (membership_keys("6199", "其他") & membership_keys("6933", "其他"))
    assert membership_keys("3324", "散熱零組件") & membership_keys("6933", "其他")


def test_tianpin_not_peer_with_amax(tmp_path):
    db = str(tmp_path / "peers.db")
    _fine(
        db,
        [
            ("6199", "天品", "傳產-其他"),
            ("6933", "AMAX-KY", "電子中游-其他"),
            ("5604", "中連", "傳產-其他"),
            ("3324", "雙鴻", "電子中游-散熱零組件"),
            ("3653", "健策", "電子中游-散熱零組件"),
            ("3017", "奇鋐", "電子中游-NB與手機零組件"),
        ],
    )
    assert chain_peer_ids(db, "6199") == []
    amax = set(chain_peer_ids(db, "6933"))
    assert "6199" not in amax
    assert "5604" not in amax
    assert {"3324", "3653", "3017", "6933"} <= amax


def test_tpex_overlay_only_replaces_catchall(tmp_path):
    db = str(tmp_path / "ov.db")
    _fine(
        db,
        [
            ("2330", "台積電", "電子上游-IC-代工"),
            ("2459", "敦吉", "電子中游-其他"),
            ("6199", "天品", "傳產-其他"),
        ],
    )
    stats = apply_tpex_overlay(db, force=True)
    assert stats["seed"] >= 2000
    conn = sqlite3.connect(db)
    rows = {
        r[0]: (r[1], r[2], r[3])
        for r in conn.execute("SELECT stock_id, chain, source, tags_json FROM stock_fine_industry")
    }
    conn.close()
    assert rows["2330"][0] == "電子上游-IC-代工"
    assert rows["2330"][1] != "tpex_ic"
    assert rows["2459"][1] == "tpex_ic"
    assert "其他" not in rows["2459"][0]
    assert rows["6199"][0] == "傳產-其他"


def test_lookup_face_uses_taught_not_other_bucket(tmp_path):
    from universe import listing_industry_face

    db = str(tmp_path / "face.db")
    _fine(
        db,
        [
            ("6199", "天品", "傳產-其他"),
            ("6933", "AMAX-KY", "電子中游-其他"),
        ],
    )
    tian = listing_industry_face("6199", db)
    amax = listing_industry_face("6933", db)
    assert "傳產-其他" not in tian
    assert "電子中游-其他" not in amax
    assert "散熱" in amax
    assert "其他業" in tian or tian.startswith("上櫃")
