# -*- coding: utf-8 -*-
"""海選瘦快取出卡前補日K量／法人；缺 T86 不准印 +0。"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _seed_quotes(db: Path, as_of: str = "20261117") -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net REAL, trust_net REAL, dealer_net REAL
        )
        """
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            as_of,
            "1314",
            "中石化",
            "TWSE",
            7.2,
            7.3,
            7.1,
            7.17,
            15045,
            10800,
            -0.7,
            7.2,
            12,
            -3,
            1,
        ),
    )
    # 有日K、法人全 0＝T86 未寫
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            as_of,
            "2330",
            "台積電",
            "TWSE",
            100,
            101,
            99,
            100,
            50000,
            5000000,
            0.5,
            100,
            0,
            0,
            0,
        ),
    )
    conn.commit()
    conn.close()


def test_hydrate_fills_volume_from_daily_quotes(tmp_path):
    from screening_engine import (
        _stock_card_html,
        format_screening_payload,
        hydrate_screen_results_quotes,
    )

    db = tmp_path / "q.db"
    _seed_quotes(db)
    slim = {
        "golden_buy": [
            {
                "stock_id": "1314",
                "stock_name": "中石化",
                "close": 7.17,
                "hi20_close": 8.0,
                "entry_price": 7.0,
                "defense_price": 6.5,
                "chase_warning": False,
            }
        ]
    }
    filled = hydrate_screen_results_quotes(slim, str(db), "20261117")
    item = filled["golden_buy"][0]
    assert int(item.get("volume") or 0) == 15045
    assert int(item.get("foreign_net") or 0) == 12
    card = _stock_card_html(item, 1)
    assert "15,045張" in card
    assert "0張" not in card.split("量能", 1)[-1].split("\n", 1)[0]
    payload = format_screening_payload(filled, "20261117", morning=True)
    blob = "\n".join(p.get("html") or "" for p in payload)
    assert "15,045張" in blob


def test_stock_card_omits_fake_zero_volume_and_chips():
    from screening_engine import _stock_card_html

    slim = _stock_card_html(
        {"stock_id": "1314", "stock_name": "中石化", "close": 7.17},
        1,
    )
    assert "量能" in slim
    vol_line = next(ln for ln in slim.splitlines() if "量能" in ln)
    assert "—" in vol_line
    assert "0張" not in vol_line
    assert "法人" not in slim


def test_quote_chip_totals_none_when_t86_all_zero(tmp_path):
    from taiwan_market import _quote_chip_totals

    db = tmp_path / "chips.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net REAL, trust_net REAL, dealer_net REAL
        )
        """
    )
    # 當日日K在、法人全 0＝T86 未寫
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "20261117",
            "2330",
            "台積電",
            "TWSE",
            100,
            101,
            99,
            100,
            50000,
            5000000,
            0.5,
            100,
            0,
            0,
            0,
        ),
    )
    conn.execute(
        """
        CREATE TABLE daily_sector_flow (
            date TEXT, industry TEXT,
            foreign_net REAL, trust_net REAL, dealer_net REAL
        )
        """
    )
    conn.execute(
        "INSERT INTO daily_sector_flow VALUES (?,?,?,?,?)",
        ("20261103", "半導體業", -1000, 200, -50),
    )
    conn.commit()
    conn.close()
    # 日K在、T86 全 0 → None（不准當 +0張）
    assert _quote_chip_totals(str(db), "20261117") is None
    # 對照：真有買賣超才回 dict
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE daily_quotes SET foreign_net=-10, trust_net=5, dealer_net=1 WHERE date=? AND stock_id=?",
        ("20261117", "2330"),
    )
    conn.commit()
    conn.close()
    got = _quote_chip_totals(str(db), "20261117")
    assert got is not None
    assert got["net"] == -4.0
