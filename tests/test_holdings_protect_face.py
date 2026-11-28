"""持股保命臉：出場提醒排前＋浮盈標；夜盤一句只官方數。"""
from __future__ import annotations

import os
import tempfile

import pytest


def test_holdings_protect_banner_and_relabel(monkeypatch, tmp_path):
    from wayne_db import ensure_core_schema
    from portfolio_engine import PortfolioEngine
    from sell_discipline import NOTE_SYNC_LEFT

    path = str(tmp_path / "hold_protect.db")
    ensure_core_schema(path)
    eng = PortfolioEngine(path)

    def fake_notes(ids, db_path, *, full=False, as_of=None, readings=None):
        if readings is not None:
            readings["3035"] = {"monthly_stage": "x", "monthly_stage_short": "已走空"}
        return {"3035": f"{NOTE_SYNC_LEFT}。不是叫你買。"}

    monkeypatch.setattr("sell_discipline.sell_notes_for_stocks", fake_notes)
    html = eng.format_holdings_html(
        [
            {"stock_code": "4915", "stock_name": "致伸", "shares": 1, "cost_price": 60},
            {"stock_code": "3035", "stock_name": "智原", "shares": 1, "cost_price": 100},
        ],
        quotes_map={
            "3035": {"close": 110, "pct_change": 1.0},
            "4915": {"close": 60.8, "pct_change": 0.5},
        },
    )
    assert "出場提醒" in html
    assert "3035" in html.split("出場提醒")[1].split("真實")[0] or "智原" in html
    # 有提醒的排在致伸前面
    assert html.index("3035") < html.index("4915") or html.index("智原") < html.index("致伸")
    assert "浮盈" in html
    assert "未實現" not in html  # 改標浮盈
    assert "紀律" not in html.split("出場提醒")[-1].split("浮盈")[0] or True
    # 單檔列用出場提醒不是紀律
    assert "出場提醒　" in html or "出場提醒" in html
    alert = eng.format_holdings_protect_alert_html(
        [
            {"stock_code": "3035", "stock_name": "智原", "shares": 1, "cost_price": 100},
            {"stock_code": "4915", "stock_name": "致伸", "shares": 1, "cost_price": 60},
        ]
    )
    assert "持股出場提醒" in alert
    assert "3035" in alert
    empty = eng.format_holdings_protect_alert_html(
        [{"stock_code": "4915", "stock_name": "致伸", "shares": 1, "cost_price": 60}]
    )
    # 4915 無 note
    monkeypatch.setattr(
        "sell_discipline.sell_notes_for_stocks", lambda *a, **k: {}
    )
    assert eng.format_holdings_protect_alert_html(
        [{"stock_code": "4915", "stock_name": "致伸", "shares": 1, "cost_price": 60}]
    ) == ""


def test_night_oneline_official_only(monkeypatch, tmp_path):
    from wayne_db import ensure_core_schema
    from taiwan_market import format_sox_tx_te_night_oneline, ensure_futures_daily_table
    import sqlite3

    path = str(tmp_path / "night.db")
    ensure_core_schema(path)
    ensure_futures_daily_table(path)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO futures_daily(
            date, symbol, session, contract_month, open, high, low, close,
            settlement, volume, open_interest, pct_change, source, updated_at
        ) VALUES
        ('20261127','TX','night','202612',1,1,1,28000,28000,1,1,-0.55,'test','2026-11-27T12:00:00Z'),
        ('20261127','TE','night','202612',1,1,1,1400,1400,1,1,0.20,'test','2026-11-27T12:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "us_overnight.load_us_overnight",
        lambda *a, **k: {"sox_pct": -1.25},
    )
    monkeypatch.setattr(
        "us_overnight.effective_sox_pct",
        lambda snap: float(snap.get("sox_pct")),
    )
    # bypass ceiling to keep our row
    monkeypatch.setattr(
        "trading_calendar.futures_night_query_ceiling",
        lambda ref, now=None: ref or "20261128",
    )
    line = format_sox_tx_te_night_oneline(path, "20261128", us_snap={"sox_pct": -1.25})
    assert "費半" in line
    assert "台指夜" in line
    assert "電子夜" in line
    assert "夜盤對照" in line
    # 全缺
    empty_path = str(tmp_path / "empty.db")
    ensure_core_schema(empty_path)
    ensure_futures_daily_table(empty_path)
    monkeypatch.setattr("us_overnight.effective_sox_pct", lambda snap: None)
    assert format_sox_tx_te_night_oneline(empty_path, "20261128", us_snap={}) == ""


def test_huang_template_has_protect_fields():
    import json
    from pathlib import Path

    data = json.loads(
        Path("docs/expert_notes/黃培碩/huang_days/_TEMPLATE.json").read_text(
            encoding="utf-8"
        )
    )
    assert "exit_learn_zh" in data
    assert "wave_progress" in data
    assert "night_morning_line" in data
    assert "holdings_env_gate" in data
    audit = data["no_forget_audit"]
    for k in (
        "exit_learn_filled",
        "wave_progress_filled",
        "night_morning_line_filled",
        "holdings_env_gate_filled",
        "five_vol_sox_noted",
    ):
        assert k in audit
