# -*- coding: utf-8 -*-
"""BK-CHAIN 三層觀測操作手：結構＋唯讀快照；非買訊；不准改黃金買點。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import observe_chain_snapshot as ocs

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"
PLAYBOOK_JSON = MANUAL / "chain_playbook.json"
PLAYBOOK_MD = MANUAL / "chain_playbook.md"


def test_playbook_files_exist_and_schema():
    assert PLAYBOOK_JSON.is_file()
    assert PLAYBOOK_MD.is_file()
    doc = json.loads(PLAYBOOK_JSON.read_text(encoding="utf-8"))
    assert doc["schema"] == "biaoke_observe_chain_playbook_v1"
    assert doc["track"] == "BK-CHAIN"
    assert doc["tz"] == "Asia/Taipei"
    assert doc["not_buy_signal"] is True
    assert doc["buy_signal"] is False
    assert doc["golden_buy_untouched"] is True
    assert "試標" in doc["warning_zh"]
    assert "非買訊" in doc["warning_zh"]
    layers = {x["id"] for x in doc["layers"]}
    assert "L1_us_overnight_emini" in layers
    assert "L2_tx_morning_confirm" in layers
    assert "L3_twii_spot_verify" in layers
    assert "LX_sox_link" in layers
    ids = [x["id"] for x in doc["daily_checklist"]]
    assert ids[:4] == ["A1", "A2", "A3", "A4"]
    assert "B3" in ids and "C4" in ids and "D1" in ids
    assert "es_f_pct" in doc["field_map"]
    assert doc["field_map"]["tx_night_*"]["filter"] == "symbol=TX AND session=night"
    assert any(g["id"] == "G1_es_f_column" for g in doc["gaps"])
    md = PLAYBOOK_MD.read_text(encoding="utf-8")
    assert "e-mini" in md or "emini" in md.lower() or "標普期" in md
    assert "不准倒灌" in md
    assert "leave_zero" in md or "黃金買點" in md


def test_load_playbook_helper_matches_file():
    doc = ocs.load_playbook()
    assert doc.get("schema") == "biaoke_observe_chain_playbook_v1"
    assert ocs.playbook_checklist_ids(doc) == [
        x["id"] for x in doc["daily_checklist"]
    ]


def test_blank_day_sheet_locked():
    d = ocs.blank_day_sheet(as_of="2026-11-13")
    assert d["schema"] == ocs.SCHEMA_DAY
    assert d["as_of"] == "20261113"
    assert d["buy_signal"] is False
    assert d["not_buy_signal"] is True
    assert d["golden_buy_untouched"] is True
    assert "A1" in d["checks"]
    assert d["checks"]["A1"]["status"] == "pending"
    assert d["official"]["tx_night"] is None


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE us_overnight (
            as_of TEXT PRIMARY KEY,
            fetched_at TEXT,
            us_session TEXT DEFAULT '',
            regime TEXT DEFAULT 'unknown',
            vix REAL,
            vix_pct REAL,
            dji_pct REAL,
            spx_pct REAL,
            ixic_pct REAL,
            sox_pct REAL,
            nq_f_pct REAL,
            tsm_pct REAL,
            nvda_pct REAL,
            payload TEXT DEFAULT '{}'
        );
        CREATE TABLE futures_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TX',
            session TEXT NOT NULL DEFAULT 'regular',
            contract_month TEXT,
            open REAL, high REAL, low REAL, close REAL,
            settlement REAL, volume INTEGER, open_interest INTEGER,
            pct_change REAL, source TEXT,
            PRIMARY KEY (date, symbol, session)
        );
        CREATE TABLE index_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TWII',
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, pct_change REAL,
            PRIMARY KEY (date, symbol)
        );
        """
    )
    payload = json.dumps(
        {
            "es_f_pct": 0.42,
            "es_f_chg": 25.0,
            "es_f_px": 6800.0,
            "nq_f_chg": 110.0,
            "sox_chg": -12.0,
            "soxx_post_pct": -0.3,
        },
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO us_overnight(
            as_of, fetched_at, us_session, regime, vix,
            dji_pct, spx_pct, ixic_pct, sox_pct, nq_f_pct, payload
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "20261112",
            "2026-11-12T20:00:00+08:00",
            "20261112",
            "ok",
            18.0,
            0.1,
            0.2,
            0.3,
            -1.5,
            0.5,
            payload,
        ),
    )
    for sess, o, h, l, c, v in (
        ("night", 44177, 44911, 43957, 44606, 47550),
        ("regular", 44166, 44555, 43057, 43178, 87240),
    ):
        conn.execute(
            """
            INSERT INTO futures_daily(
                date, symbol, session, contract_month,
                open, high, low, close, settlement, volume, open_interest, pct_change, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("20261112", "TX", sess, "202611", o, h, l, c, c, v, 0, 0.0, "test"),
        )
    conn.execute(
        """
        INSERT INTO futures_daily(
            date, symbol, session, contract_month,
            open, high, low, close, settlement, volume, open_interest, pct_change, source
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("20261112", "TE", "night", "202611", 2800, 2850, 2780, 2820, 2820, 1000, 0, 0.0, "test"),
    )
    conn.execute(
        """
        INSERT INTO index_daily(date, symbol, open, high, low, close, volume, pct_change)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        ("20261112", "TWII", 44180.46, 44525.24, 42943.5, 43091.87, 13614522, -2.0),
    )
    conn.commit()
    conn.close()


def test_load_chain_snapshot_aligns_fields(tmp_path):
    db = tmp_path / "wayne.db"
    _seed_db(db)
    snap = ocs.load_chain_snapshot(str(db), "20261112")
    assert snap["buy_signal"] is False
    assert snap["golden_buy_untouched"] is True
    us = snap["official"]["us_overnight"]
    assert us["sox_pct"] == -1.5
    assert us["nq_f_pct"] == 0.5
    assert us["es_f_pct"] == 0.42
    assert us["es_f_source"] == "payload"
    assert snap["official"]["tx_night"]["high"] == 44911
    assert snap["official"]["tx_regular"]["open"] == 44166
    assert snap["official"]["te_night"]["close"] == 2820
    assert snap["official"]["twii"]["low"] == 42943.5
    assert snap["checks"]["A1"]["status"] == "pending"
    assert snap["checks"]["A2"]["status"] == "pending"
    assert snap["checks"]["A4"]["status"] == "pending"
    assert snap["checks"]["B2"]["status"] == "gap_proxy_day"
    assert snap["checks"]["C2"]["status"] == "gap"
    # 缺 e-mini 日
    empty = ocs.load_chain_snapshot(str(db), "20261199")
    # 無該日 us → 退回最新或 gap；至少結構完整
    assert empty["schema"] == ocs.SCHEMA_DAY
    assert "A2" in empty["checks"]


def test_sox_link_flags_fake_strength():
    flags = ocs.sox_link_flags({"sox_pct": -1.6, "es_f_pct": 0.5, "nq_f_pct": 0.4}, tx_night_bias="up")
    assert flags["D1_fake_strength"] is True
    assert flags["not_buy_signal"] is True
    assert "假強" in flags["note_zh"]


def test_helper_does_not_import_golden_buy_mutators():
    src = Path(ocs.__file__).read_text(encoding="utf-8")
    assert "leave_zero" not in src
    assert "golden_buy" not in src.lower() or "golden_buy_untouched" in src
    assert "UPDATE" not in src or "不寫" in Path(ocs.__file__).read_text(encoding="utf-8")
    # 硬鎖：檔案聲明不改買點
    assert "不改黃金買點" in src
