# -*- coding: utf-8 -*-
"""勝率買點：電子＋AI 寬鏈優先排序（不刪其他產業、不改 leave_zero）。"""
from __future__ import annotations

import sqlite3

from winrate_ai_priority import (
    ELEC_INDUSTRIES,
    is_ai_wide_chain,
    is_elec_industry,
    is_winrate_priority,
    load_priority_flags,
    priority_mapping_zh,
    sort_winrate_rows_ai_first,
)
from winrate_buypoint import load_winrate_roster, save_winrate_roster


def test_elec_industry_and_ai_wide_chain():
    assert is_elec_industry("半導體業")
    assert is_elec_industry("電腦及週邊設備業")
    assert not is_elec_industry("建材營造業")
    assert is_ai_wide_chain("電子上游-IC-代工")
    assert is_ai_wide_chain("電子中游-散熱零組件")
    assert is_ai_wide_chain("電子上游-PCB-製造")
    assert is_ai_wide_chain("雲端運算-電力設備")
    assert is_ai_wide_chain("人工智慧-系統整合")
    assert is_ai_wide_chain("半導體-生產製程及檢測設備")
    # 電子商務不是算力供應鏈
    assert not is_ai_wide_chain("電子商務-一般零售")
    assert not is_ai_wide_chain("傳產-水泥")


def test_priority_or_logic():
    assert is_winrate_priority("半導體業", chain="")
    assert is_winrate_priority("建材營造業", chain="電子上游-PCB-製造")
    assert not is_winrate_priority("建材營造業", chain="傳產-水泥")
    assert not is_winrate_priority("觀光餐旅", chain="電子商務-物流倉儲服務")


def test_sort_ai_first_keeps_all(tmp_path):
    db = str(tmp_path / "p.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE stock_universe(
            stock_id TEXT PRIMARY KEY, stock_name TEXT, market_type TEXT,
            asset_type TEXT, industry TEXT, is_active INTEGER, updated_at TEXT
        );
        CREATE TABLE stock_fine_industry(
            stock_id TEXT PRIMARY KEY, chain TEXT, tags_json TEXT,
            cat_id TEXT, source TEXT, fetched_at TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO stock_universe VALUES (?,?,?,?,?,?,?)",
        [
            ("1216", "統一", "TW", "STOCK", "食品工業", 1, ""),
            ("2330", "台積電", "TW", "STOCK", "半導體業", 1, ""),
            ("3653", "健策", "TW", "STOCK", "電子零組件業", 1, ""),
            ("9900", "假水泥", "TW", "STOCK", "建材營造業", 1, ""),
        ],
    )
    conn.executemany(
        "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
        [
            ("2330", "電子上游-IC-代工", '["電子上游","IC","代工"]', "", "", ""),
            ("3653", "電子中游-散熱零組件", '["電子中游","散熱零組件"]', "", "", ""),
            ("1216", "傳產-食品", '["傳產","食品"]', "", "", ""),
            ("9900", "傳產-水泥", '["傳產","水泥"]', "", "", ""),
        ],
    )
    conn.commit()
    conn.close()

    rows = [
        {"stock_id": "1216", "stock_name": "統一"},
        {"stock_id": "9900", "stock_name": "假水泥"},
        {"stock_id": "3653", "stock_name": "健策"},
        {"stock_id": "2330", "stock_name": "台積電"},
    ]
    ordered = sort_winrate_rows_ai_first(rows, db)
    ids = [r["stock_id"] for r in ordered]
    assert set(ids) == {"1216", "9900", "3653", "2330"}  # 不刪
    # 電子／AI 寬鏈在前
    assert ids.index("2330") < ids.index("1216")
    assert ids.index("3653") < ids.index("9900")
    # 優先組內代號升冪
    pri = [i for i in ids if i in ("2330", "3653")]
    assert pri == sorted(pri)


def test_load_roster_applies_priority(tmp_path):
    db = str(tmp_path / "r.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE stock_universe(
            stock_id TEXT PRIMARY KEY, stock_name TEXT, market_type TEXT,
            asset_type TEXT, industry TEXT, is_active INTEGER, updated_at TEXT
        );
        CREATE TABLE stock_fine_industry(
            stock_id TEXT PRIMARY KEY, chain TEXT, tags_json TEXT,
            cat_id TEXT, source TEXT, fetched_at TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO stock_universe VALUES (?,?,?,?,?,?,?)",
        [
            ("1216", "統一", "TW", "STOCK", "食品工業", 1, ""),
            ("2330", "台積電", "TW", "STOCK", "半導體業", 1, ""),
        ],
    )
    conn.execute(
        "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
        ("2330", "電子上游-IC-代工", "[]", "", "", ""),
    )
    conn.commit()
    conn.close()
    save_winrate_roster(
        db,
        "20261001",
        [
            {"stock_id": "1216", "stock_name": "統一", "close": 70.0},
            {"stock_id": "2330", "stock_name": "台積電", "close": 900.0},
        ],
    )
    rows = load_winrate_roster(db, "20261001")
    assert [r["stock_id"] for r in rows] == ["2330", "1216"]


def test_mapping_mentions_priority_not_only_elec():
    text = priority_mapping_zh()
    assert "優先" in text
    assert "電子商務" in text
    assert "仍保留" in text
    assert "半導體業" in ELEC_INDUSTRIES
    flags = load_priority_flags("", [])
    assert flags == {}
