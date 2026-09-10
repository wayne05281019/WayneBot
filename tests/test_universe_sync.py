# -*- coding: utf-8 -*-
"""母體同步：空 ISIN 不准把全市場關掉；全 0 要回滾。"""
from __future__ import annotations

import sqlite3

from universe import get_active_ids, restore_universe_if_wiped, sync_universe


def _mini(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE stock_universe (
            stock_id TEXT PRIMARY KEY,
            stock_name TEXT NOT NULL,
            market_type TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            industry TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO stock_universe(
            stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
        ) VALUES (?,?,?,?,?,1,'t')
        """,
        (
            ("2330", "台積電", "TW", "STOCK", "半導體"),
            ("2454", "聯發科", "TW", "STOCK", "半導體"),
        ),
    )
    conn.commit()
    conn.close()


def test_empty_isin_does_not_deactivate_universe(tmp_path):
    path = str(tmp_path / "u.db")
    _mini(path)
    stats = sync_universe(path, items=[])
    assert stats.get("skipped") == "empty_isin"
    assert stats["active"] == 2
    ids = get_active_ids(path)
    assert ids == {"2330", "2454"}


def test_zero_active_after_upsert_rolls_back(tmp_path):
    path = str(tmp_path / "u.db")
    _mini(path)
    stats = sync_universe(path, items=[{}])
    assert stats.get("skipped") == "zero_active"
    assert stats["active"] == 2
    assert get_active_ids(path) == {"2330", "2454"}


def test_restore_universe_if_wiped_turns_all_back_on(tmp_path):
    path = str(tmp_path / "u.db")
    _mini(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE stock_universe SET is_active=0")
    conn.commit()
    conn.close()
    assert restore_universe_if_wiped(path) == 2
    assert get_active_ids(path) == {"2330", "2454"}


def test_get_active_ids_heals_wiped_table(tmp_path):
    path = str(tmp_path / "u.db")
    _mini(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE stock_universe SET is_active=0")
    conn.commit()
    conn.close()
    assert get_active_ids(path) == {"2330", "2454"}


def test_successful_sync_deactivates_missing_ids(tmp_path):
    path = str(tmp_path / "u.db")
    _mini(path)
    stats = sync_universe(
        path,
        items=[
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "market_type": "TW",
                "asset_type": "STOCK",
                "industry": "半導體",
            }
        ],
    )
    assert stats.get("skipped") in (None, "", 0)
    assert stats["active"] == 1
    assert get_active_ids(path) == {"2330"}
