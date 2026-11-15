# -*- coding: utf-8 -*-
"""電子盤 tip：缺起日日盤結算不准誤用更舊日盤收（籌碼K −0.30% vs 假 +1.22%）。"""
from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_level_learn import _ensure_teach_tx_day_row, _resolve_tx_after_hours_tip
from bot_servers import WayneTelegramBot


def _seed_tx(db: str, *, with_fri_regular: bool) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE futures_daily (
            date TEXT, symbol TEXT, session TEXT, contract_month TEXT,
            open REAL, high REAL, low REAL, close REAL, settlement REAL,
            volume INTEGER, open_interest INTEGER, pct_change REAL,
            source TEXT, updated_at TEXT,
            PRIMARY KEY (date, symbol, session)
        )
        """
    )
    rows = [
        (
            "20261112",
            "TX",
            "regular",
            "202611",
            43000.0,
            43500.0,
            42800.0,
            43178.0,
            43128.0,
            1,
            0,
            -2.22,
            "taifex",
            "t",
        ),
        # 週五夜官方標週一；pct_change=-0.3 對齊籌碼K −133/−0.30%
        (
            "20261116",
            "TX",
            "night",
            "202611",
            43800.0,
            44000.0,
            43500.0,
            43706.0,
            43706.0,
            56132,
            0,
            -0.3,
            "taifex",
            "t",
        ),
    ]
    if with_fri_regular:
        rows.append(
            (
                "20261113",
                "TX",
                "regular",
                "202611",
                43200.0,
                44000.0,
                43000.0,
                43834.0,
                43839.0,
                1,
                0,
                1.61,
                "taifex",
                "t",
            )
        )
    conn.executemany(
        """
        INSERT INTO futures_daily(
            date, symbol, session, contract_month, open, high, low, close,
            settlement, volume, open_interest, pct_change, source, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def test_tx_tip_with_fri_settle_matches_chip(tmp_path):
    db = str(tmp_path / "ok.db")
    _seed_tx(db, with_fri_regular=True)
    tz = ZoneInfo("Asia/Taipei")
    pack = {"query_at": datetime(2026, 11, 15, 21, 48, tzinfo=tz).isoformat()}
    tip = _resolve_tx_after_hours_tip(db, pack)
    assert tip is not None
    assert abs(float(tip["close"]) - 43706.0) < 1.0
    assert abs(float(tip["prev"]) - 43839.0) < 1.0
    assert tip["asof"] == "20261113"
    chg = float(tip["close"]) - float(tip["prev"])
    pct = 100.0 * chg / float(tip["prev"])
    assert abs(chg - (-133.0)) < 1.0
    assert abs(pct - (-0.30)) < 0.05


def test_tx_tip_missing_fri_settle_not_use_thu_close(tmp_path, monkeypatch):
    """缺 11/13 regular 時：不准退成 43178→假 +528；改用夜盤 pct 反推。"""
    db = str(tmp_path / "miss.db")
    _seed_tx(db, with_fri_regular=False)

    # 斷網：ensure 補抓也不會憑空寫出週五日盤
    monkeypatch.setattr(
        "taiwan_market.sync_futures_daily",
        lambda *_a, **_k: {"ok": False, "n": 0},
    )

    tz = ZoneInfo("Asia/Taipei")
    pack = {"query_at": datetime(2026, 11, 15, 21, 48, tzinfo=tz).isoformat()}
    tip = _resolve_tx_after_hours_tip(db, pack)
    assert tip is not None
    assert abs(float(tip["close"]) - 43706.0) < 1.0
    prev = float(tip.get("prev") or 0)
    assert prev > 0
    # 舊 bug：prev=43178 → +528 / +1.22%
    assert abs(prev - 43178.0) > 50.0
    chg = float(tip["close"]) - prev
    pct = 100.0 * chg / prev
    assert chg < 0
    assert abs(pct - (-0.30)) < 0.08


def test_ensure_teach_tx_day_row_accepts_explicit_day():
    src = inspect.getsource(_ensure_teach_tx_day_row)
    assert "day:" in src or "day =" in src
    assert "週末" in src or "起日" in src


def test_market_wave_wait_keeps_overtime():
    src = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "overtime_keep=True" in src
    assert "max_elapsed=360" in src or "max_elapsed=360.0" in src
    assert "_retry_market_micro_paint" in src


def test_micro_paint_prefers_local_minute_bars():
    from biaoke_level_learn import _render_twii_c_wave_60_dark

    src = inspect.getsource(_render_twii_c_wave_60_dark)
    # 先讀庫再決定要不要 Yahoo
    load_i = src.index("_load_twii60_day_rows")
    yahoo_i = src.index("fetch_yahoo_minutes")
    assert load_i < yahoo_i
    assert "len(rows_full) < 16" in src
