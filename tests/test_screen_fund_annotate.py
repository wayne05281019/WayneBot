# -*- coding: utf-8 -*-
"""海選／綜合篩選基本面旁註：有數就出、缺就省略、不准改選股。"""
from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest


def _seed_fund(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE monthly_revenue (
            stock_id TEXT NOT NULL,
            yyyymm TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            market TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            revenue REAL DEFAULT 0,
            revenue_prev_month REAL DEFAULT 0,
            revenue_prev_year REAL DEFAULT 0,
            mom_pct REAL,
            yoy_pct REAL,
            ytd_revenue REAL DEFAULT 0,
            ytd_prev_year REAL DEFAULT 0,
            ytd_yoy_pct REAL,
            published_roc TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            PRIMARY KEY (stock_id, yyyymm)
        );
        CREATE TABLE quarterly_income (
            stock_id TEXT NOT NULL,
            year INTEGER NOT NULL,
            season INTEGER NOT NULL,
            stock_name TEXT DEFAULT '',
            market TEXT DEFAULT '',
            revenue REAL DEFAULT 0,
            cogs REAL DEFAULT 0,
            gross_profit REAL DEFAULT 0,
            gross_margin_pct REAL,
            operating_income REAL DEFAULT 0,
            non_operating REAL,
            net_income REAL DEFAULT 0,
            eps REAL DEFAULT 0,
            published_roc TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            PRIMARY KEY (stock_id, year, season)
        );
        """
    )
    # 2330：月 YoY＋季毛利都有；舊月不准蓋最新
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,yoy_pct) VALUES (?,?,?)",
        ("2330", "202609", 10.0),
    )
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,yoy_pct) VALUES (?,?,?)",
        ("2330", "202610", 25.5),
    )
    conn.execute(
        "INSERT INTO quarterly_income(stock_id,year,season,gross_margin_pct) VALUES (?,?,?,?)",
        ("2330", 2026, 2, 40.0),
    )
    conn.execute(
        "INSERT INTO quarterly_income(stock_id,year,season,gross_margin_pct) VALUES (?,?,?,?)",
        ("2330", 2026, 3, 54.2),
    )
    # 2317：只有 YoY
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,yoy_pct) VALUES (?,?,?)",
        ("2317", "202610", 8.0),
    )
    # 2454：只有毛利
    conn.execute(
        "INSERT INTO quarterly_income(stock_id,year,season,gross_margin_pct) VALUES (?,?,?,?)",
        ("2454", 2026, 3, 33.0),
    )
    # 9999：月列在但 YoY NULL＝缺，不准印 —
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,yoy_pct) VALUES (?,?,?)",
        ("9999", "202610", None),
    )
    conn.commit()
    conn.close()


def test_batch_latest_fund_metrics_reads_latest(tmp_path):
    from screen_fund_annotate import batch_latest_fund_metrics, format_fund_side_note

    db = tmp_path / "fund.db"
    _seed_fund(db)
    by = batch_latest_fund_metrics(str(db), ["2330", "2317", "2454", "9999", "1101"])
    assert by["2330"]["yoy_pct"] == pytest.approx(25.5)
    assert by["2330"]["yyyymm"] == "202610"
    assert by["2330"]["gross_margin_pct"] == pytest.approx(54.2)
    assert by["2330"]["season"] == 3
    assert by["2317"]["yoy_pct"] == pytest.approx(8.0)
    assert "gross_margin_pct" not in by["2317"]
    assert "yoy_pct" not in by["2454"]
    assert by["2454"]["gross_margin_pct"] == pytest.approx(33.0)
    assert "9999" not in by  # YoY 缺且無毛利＝整檔省略
    assert "1101" not in by

    card = format_fund_side_note(by["2330"], style="card")
    assert "10月YoY+25.5%" in card
    assert "26Q3毛54.2%" in card
    assert "—" not in card
    paren = format_fund_side_note(by["2330"], style="paren")
    assert paren == "(YoY+25.5%｜毛54.2%)"
    assert format_fund_side_note({}, style="card") == ""
    assert format_fund_side_note(None, style="paren") == ""


def test_stock_card_and_line_show_or_omit(tmp_path):
    from line_share_format import format_line_stock_block
    from screen_fund_annotate import hydrate_items_fund_side
    from screening_engine import _stock_card_html

    db = tmp_path / "fund.db"
    _seed_fund(db)

    rich = {
        "stock_id": "2330",
        "stock_name": "台積電",
        "close": 100.0,
        "volume": 1000,
        "pct_change": 1.0,
        "q60r": 1.2,
    }
    hydrate_items_fund_side([rich], str(db))
    card = _stock_card_html(rich, 1)
    assert "基本" in card
    assert "10月YoY+25.5%" in card
    assert "26Q3毛54.2%" in card
    assert "—" not in card.split("基本", 1)[-1].split("\n", 1)[0]

    block = format_line_stock_block(dict(rich), 1, str(db))
    assert "基本" in block
    assert "YoY+25.5%" in block

    bare = {"stock_id": "1101", "stock_name": "台泥", "close": 30.0, "volume": 10}
    hydrate_items_fund_side([bare], str(db))
    bare_card = _stock_card_html(bare, 1)
    assert "基本" not in bare_card
    assert "—" not in bare_card or "量能" in bare_card  # 量能缺才可能有 —；基本不准假 —
    fund_line = next((ln for ln in bare_card.splitlines() if "基本" in ln), "")
    assert fund_line == ""

    null_yoy = {"stock_id": "9999", "stock_name": "缺數", "close": 1.0}
    hydrate_items_fund_side([null_yoy], str(db))
    assert "fund_side_note" not in null_yoy
    assert "基本" not in _stock_card_html(null_yoy, 1)


def test_combo_sid_labels_parenthetical(tmp_path):
    from pipeline_observe import _join_sid_labels, format_combo_screen_html
    from screen_fund_annotate import hydrate_items_fund_side

    db = tmp_path / "fund.db"
    _seed_fund(db)
    items = [
        {"sid": "2330", "name": "台積電", "days": 3},
        {"sid": "1101", "name": "台泥"},
    ]
    hydrate_items_fund_side(items, str(db))
    joined = _join_sid_labels(items, limit=12)
    assert "2330台積電(YoY+25.5%｜毛54.2%)·3天" in joined
    assert "1101台泥" in joined
    assert "1101台泥(" not in joined

    html = format_combo_screen_html(
        {
            "desk_as_of": "20261120",
            "fuse_as_of": "20261120",
            "today": "20261120",
            "summary": {"ok_n": 1, "layer_n": 1, "bad_n": 0, "issue_n": 0},
            "lists": {
                "winrate": {
                    "as_of": "20261120",
                    "buy_ok": True,
                    "items": [{"sid": "2330", "name": "台積電"}],
                }
            },
            "layers": [],
            "issues": [],
            "_db_path": str(db),
        }
    )
    assert "YoY+25.5%" in html
    assert "毛54.2%" in html


def test_hydrate_does_not_change_selection_ids(tmp_path):
    from screen_fund_annotate import hydrate_screen_results_fund_notes

    db = tmp_path / "fund.db"
    _seed_fund(db)
    results = {
        "leave_zero": [
            {"stock_id": "2330", "stock_name": "台積電", "entry_stage": "buy"},
            {"stock_id": "1101", "stock_name": "台泥", "entry_stage": "watch"},
        ],
        "ma60_lower": [{"stock_id": "2317", "stock_name": "鴻海"}],
        "golden_buy": [{"stock_id": "2454", "stock_name": "聯發科"}],
    }
    before = {
        k: [str(it.get("stock_id")) for it in rows]
        for k, rows in results.items()
    }
    flags_before = {
        (it["stock_id"], it.get("entry_stage"), it.get("golden_buy"), it.get("revenue_hot"))
        for rows in results.values()
        for it in rows
    }
    hydrate_screen_results_fund_notes(results, str(db))
    after = {
        k: [str(it.get("stock_id")) for it in rows]
        for k, rows in results.items()
    }
    assert before == after
    flags_after = {
        (it["stock_id"], it.get("entry_stage"), it.get("golden_buy"), it.get("revenue_hot"))
        for rows in results.values()
        for it in rows
    }
    assert flags_before == flags_after
    assert results["leave_zero"][0].get("fund_side_note")
    assert "fund_side_note" not in results["leave_zero"][1]


def test_selection_paths_do_not_import_annotate():
    """選股／閘門路徑不准依賴旁註模組。"""
    import decision_card_signals
    import screening_engine

    assert "screen_fund_annotate" not in inspect.getsource(decision_card_signals)
    # 出卡／組字才 hydrate；leave_zero／golden_buy 公式本體不准碰
    for name in (
        "leave_zero_trade_plan",
        "leave_zero_screen_ok",
        "leave_zero_from_quote_df",
    ):
        fn = getattr(decision_card_signals, name, None)
        assert fn is not None
        assert "screen_fund_annotate" not in inspect.getsource(fn)
    # screening_engine 只在 format／assemble 出卡路徑引用，不准進選股掃描本體
    src = inspect.getsource(screening_engine)
    assert "screen_fund_annotate" in src
    assert "hydrate_screen_results_fund_notes" in inspect.getsource(
        screening_engine._assemble_screening_from_results
    )
    assert "screen_fund_annotate" not in inspect.getsource(
        screening_engine.execute_full_screening
    )
