# -*- coding: utf-8 -*-
"""勝率買點：電子＋AI 生態系 ONLY（live 刪非 AI；不改 leave_zero）。"""
from __future__ import annotations

import sqlite3

from winrate_ai_priority import (
    ELEC_INDUSTRIES,
    filter_winrate_rows_ai_only,
    is_ai_wide_chain,
    is_elec_industry,
    is_winrate_priority,
    load_priority_flags,
    partition_winrate_ai_rows,
    priority_mapping_zh,
    sort_winrate_rows_ai_first,
)
from winrate_buypoint import KIND_NON_AI_CTRL, load_winrate_roster, save_winrate_roster


def test_elec_industry_and_ai_wide_chain():
    assert is_elec_industry("半導體業")
    assert is_elec_industry("電腦及週邊設備業")
    assert is_elec_industry("光電業")
    assert is_elec_industry("光電")  # 別名
    assert is_elec_industry("電機機械")
    assert is_elec_industry("電機機械業")  # 別名
    assert not is_elec_industry("建材營造業")
    assert not is_elec_industry("生技醫療業")
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
    assert is_winrate_priority("光電業", chain="")
    assert is_winrate_priority("光電", chain="")
    assert is_winrate_priority("電機機械", chain="")
    assert is_winrate_priority("建材營造業", chain="電子上游-PCB-製造")
    assert not is_winrate_priority("建材營造業", chain="傳產-水泥")
    assert not is_winrate_priority("觀光餐旅", chain="電子商務-物流倉儲服務")
    assert not is_winrate_priority("生技醫療業", chain="")
    assert not is_winrate_priority("食品工業", chain="")


def _seed_ai_db(db: str) -> None:
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
            ("4743", "合一", "TW", "STOCK", "生技醫療業", 1, ""),
        ],
    )
    conn.executemany(
        "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
        [
            ("2330", "電子上游-IC-代工", '["電子上游","IC","代工"]', "", "", ""),
            ("3653", "電子中游-散熱零組件", '["電子中游","散熱零組件"]', "", "", ""),
            ("1216", "傳產-食品", '["傳產","食品"]', "", "", ""),
            ("9900", "傳產-水泥", '["傳產","水泥"]', "", "", ""),
            ("4743", "生技-新藥", '["生技","新藥"]', "", "", ""),
        ],
    )
    conn.commit()
    conn.close()


def test_filter_ai_only_drops_non_ai(tmp_path):
    db = str(tmp_path / "p.db")
    _seed_ai_db(db)
    rows = [
        {"stock_id": "1216", "stock_name": "統一"},
        {"stock_id": "9900", "stock_name": "假水泥"},
        {"stock_id": "3653", "stock_name": "健策"},
        {"stock_id": "2330", "stock_name": "台積電"},
        {"stock_id": "4743", "stock_name": "合一"},
    ]
    kept = filter_winrate_rows_ai_only(rows, db)
    ids = [r["stock_id"] for r in kept]
    assert ids == ["2330", "3653"]  # 只 AI／電子；代號升冪
    assert "1216" not in ids and "9900" not in ids and "4743" not in ids
    # 相容舊名＝同樣刪非 AI
    assert [r["stock_id"] for r in sort_winrate_rows_ai_first(rows, db)] == ids
    ai, dropped = partition_winrate_ai_rows(rows, db)
    assert [r["stock_id"] for r in ai] == ids
    assert {r["stock_id"] for r in dropped} == {"1216", "9900", "4743"}


def test_load_roster_ai_only(tmp_path):
    db = str(tmp_path / "r.db")
    _seed_ai_db(db)
    save_winrate_roster(
        db,
        "20261001",
        [
            {"stock_id": "1216", "stock_name": "統一", "close": 70.0},
            {"stock_id": "2330", "stock_name": "台積電", "close": 900.0},
            {"stock_id": "4743", "stock_name": "合一", "close": 50.0},
        ],
    )
    rows = load_winrate_roster(db, "20261001")
    assert [r["stock_id"] for r in rows] == ["2330"]


def test_filter_keeps_opto_and_motor(tmp_path):
    """keep-set 明示含光電／電機機械；生技仍刪。"""
    db = str(tmp_path / "o.db")
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
            ("2383", "台光電", "TW", "STOCK", "光電業", 1, ""),
            ("1504", "東元", "TW", "STOCK", "電機機械", 1, ""),
            ("4743", "合一", "TW", "STOCK", "生技醫療業", 1, ""),
            ("3017", "奇鋐", "TW", "STOCK", "光電", 1, ""),  # 別名
        ],
    )
    conn.commit()
    conn.close()
    rows = [
        {"stock_id": "2383"},
        {"stock_id": "1504"},
        {"stock_id": "4743"},
        {"stock_id": "3017"},
    ]
    ids = [r["stock_id"] for r in filter_winrate_rows_ai_only(rows, db)]
    assert ids == ["1504", "2383", "3017"]
    assert "4743" not in ids


def test_mapping_mentions_ai_only():
    text = priority_mapping_zh()
    assert "電機機械" in text and "光電" in text
    assert "500" in text or "成交額" in text
    assert "near_h20" in text or "距20" in text or "不含 near" in text
    assert "刪" in text or "不推" in text
    assert "半導體業" in ELEC_INDUSTRIES
    assert "光電業" in ELEC_INDUSTRIES and "電機機械" in ELEC_INDUSTRIES
    assert KIND_NON_AI_CTRL == "winrate_non_ai_ctrl"
    flags = load_priority_flags("", [])
    assert flags == {}
