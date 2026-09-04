# -*- coding: utf-8 -*-
"""過夜品質：匯入人話、禁止假資料、籌碼改名、除權息預告、台指期 datetime。"""
from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile

from chips import format_major_player_html
from ex_rights import (
    format_next_event_label,
    nearest_event_label,
    parse_twt48u_row,
    upsert_events,
)
from import_health import (
    expected_latest_revenue_month,
    format_audit_plain,
    inventory_payload,
    monthly_revenue_status,
)
from wayne_db import ensure_core_schema
from wayne_navigator import render_decision_card_png


def test_expected_revenue_month_before_tenth():
    assert expected_latest_revenue_month("20260904") == "202607"
    assert expected_latest_revenue_month("20260911") == "202608"
    assert expected_latest_revenue_month("20260105") == "202511"


def test_monthly_july_on_sep4_is_unpublished_not_missing():
    st = monthly_revenue_status(8000, "202607", today_ymd="20260904")
    assert st["ok"] is True
    assert st["missing"] is False
    assert st["unpublished"] is True
    assert "尚未公布 202608" in st["label"]
    assert not st["problem"]


def test_monthly_empty_is_real_missing():
    st = monthly_revenue_status(0, "", today_ymd="20260904")
    assert st["missing"] is True
    assert "待補月營收" in st["problem"]


def test_format_audit_plain_says_today_ok_when_quotes_complete():
    text = format_audit_plain(
        {
            "date": "20260903",
            "tw": 1307,
            "two": 879,
            "total": 2186,
            "chips_nonzero": 2051,
            "monthly_n": 8000,
            "latest_month": "202607",
            "income_n": 4000,
            "latest_quarter": "2026Q2",
            "ex_rights_n": 1200,
            "latest_ex": "20260901",
            "ok": True,
            "today_ok": True,
            "problems": [],
            "history_issues": [{"date": "20250102", "tw": 10, "two": 2}],
            "history_issue_n": 1,
        }
    )
    assert "今天正常" in text
    assert "官方尚未公布 202608" in text
    assert "月營收 8000　202607" in text or "月營收 8000 202607" in text or "8000　202607" in text
    assert "舊日缺邊" in text
    assert "待補：" not in text


def test_inventory_payload_reports_disk(tmp_path):
    db = str(tmp_path / "inv.db")
    ensure_core_schema(db)
    from unittest.mock import patch

    with patch("import_health.db_quick_check_ok", return_value=True):
        inv = inventory_payload(db)
    assert "disk" in inv
    assert inv["disk"]["bytes"] >= 0
    assert "today_ok" in inv
    assert "history_ok" in inv


def test_chips_html_must_not_call_institutional_主力():
    html = format_major_player_html(
        [
            {
                "date": "20260903",
                "stock_id": "2330",
                "stock_name": "台積電",
                "close": 100,
                "volume": 1,
                "foreign_net": 1,
                "trust_net": 0,
                "dealer_net": 0,
                "three_net": 1,
                "ratio_pct": 0.1,
                "acc_10d": 1,
            }
        ],
        "2330",
    )
    assert "三大法人" in html
    assert "主力買賣超" not in html
    empty = format_major_player_html([], "2330")
    assert "主力買賣超" not in empty
    assert "三大法人" in empty


def test_twt48u_parse_and_nearest_event(tmp_path):
    fields = ["除權除息日期", "股票代號", "名稱", "除權息"]
    row = ["115年09月07日", "2330", "台積電", "息"]
    item = parse_twt48u_row(fields, row)
    assert item["stock_id"] == "2330"
    assert item["ex_date"] == "20260907"
    assert item["source"] == "TWT48U"
    assert item["factor"] == 0.0
    db = str(tmp_path / "ex.db")
    ensure_core_schema(db)
    upsert_events(db, [item])
    label = nearest_event_label("2330", db, today="20260904")
    assert label == "3天後除息"
    assert nearest_event_label("9999", db, today="20260904") == ""
    assert format_next_event_label("權息", "20260904", "20260904") == "今日除權息"
    assert format_next_event_label("息", "20260903", "20260904") == ""
    assert format_next_event_label("法說", "20260911", "20260904") == "7天後法說"


def test_audit_latest_ex_ignores_preview_rows(tmp_path):
    from import_health import audit_import
    from wayne_db import ensure_core_schema

    db = str(tmp_path / "ex3.db")
    ensure_core_schema(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "2330",
                "ex_date": "20260903",
                "kind": "息",
                "factor": 0.99,
                "source": "TWT49U",
            },
            {
                "stock_id": "2330",
                "ex_date": "20261028",
                "kind": "息",
                "factor": 0.0,
                "source": "TWT48U",
            },
        ],
    )
    health = audit_import(db, "20260903")
    assert health["latest_ex"] == "20260903"
    assert health["ex_rights_n"] == 2


def test_upsert_preview_does_not_clobber_factor(tmp_path):
    db = str(tmp_path / "ex2.db")
    ensure_core_schema(db)
    upsert_events(
        db,
        [
            {
                "stock_id": "2330",
                "ex_date": "20260907",
                "stock_name": "台積電",
                "market": "TW",
                "kind": "息",
                "close_before": 1000,
                "ref_price": 990,
                "right_plus_div": 10,
                "factor": 0.99,
                "source": "TWT49U",
            }
        ],
    )
    upsert_events(
        db,
        [
            {
                "stock_id": "2330",
                "ex_date": "20260907",
                "stock_name": "台積電",
                "market": "TW",
                "kind": "息",
                "close_before": 0,
                "ref_price": 0,
                "right_plus_div": 0,
                "factor": 0.0,
                "source": "TWT48U",
            }
        ],
    )
    conn = sqlite3.connect(db)
    factor, source = conn.execute(
        "SELECT factor, source FROM ex_rights WHERE stock_id='2330'"
    ).fetchone()
    conn.close()
    assert factor == 0.99
    assert source == "TWT49U"


def test_decision_card_source_forbids_zebra_and_paints_event():
    src = inspect.getsource(render_decision_card_png)
    assert "row_i % 2" not in src
    assert "next_event" in src
    assert "白底" in src
    from wayne_navigator import render_first_glance_png

    glance_src = inspect.getsource(render_first_glance_png)
    assert "next_event" in glance_src


def test_decision_card_png_renders_next_event():
    import matplotlib

    matplotlib.use("Agg")
    import pandas as pd

    table = pd.DataFrame(
        [
            {
                "date": "20260903",
                "close": 100.0,
                "獲利": "2.0%",
                "高低": "No",
                "預警": "No",
                "溫度計": "36.0 °C",
                "月乖離": "+1.0%",
                "profit_pct": 2.0,
                "bias_monthly": 1.0,
                "vol_rank_120": 20,
                "120日量": "第 20 名",
            }
        ]
    )
    card = {
        "stock_id": "2330",
        "stock_name": "台積電",
        "next_event": "3天後除息",
        "close": 100.0,
        "change_pct": 1.2,
        "h10": 110,
        "dist_h10": -9.0,
        "h20": 112,
        "dist_h20": -10.7,
        "h60": 120,
        "dist_h60": -16.7,
        "l10": 95,
        "dist_l10": 5.3,
        "l20": 90,
        "dist_l20": 11.1,
        "l60": 80,
        "dist_l60": 25.0,
        "space_20": 14,
        "space_60": 25,
        "ma60s": 0.5,
        "qty60": 20000,
        "badges": ["整理格局"],
        "table": table,
    }
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        out = render_decision_card_png(card, path)
        assert out
        assert os.path.getsize(out) > 8000
    finally:
        if os.path.exists(path):
            os.remove(path)


def _mini_card(stock_id: str, name: str, event: str = ""):
    import pandas as pd

    table = pd.DataFrame(
        [
            {
                "date": "20260903",
                "close": 100.0,
                "獲利": "2.0%",
                "高低": "No",
                "預警": "No",
                "溫度計": "36.0 °C",
                "月乖離": "+1.0%",
                "profit_pct": 2.0,
                "bias_monthly": 1.0,
                "vol_rank_120": 20,
                "120日量": "第 20 名",
            }
        ]
    )
    return {
        "stock_id": stock_id,
        "stock_name": name,
        "next_event": event,
        "close": 100.0,
        "change_pct": 1.2,
        "h10": 110,
        "dist_h10": -9.0,
        "h20": 112,
        "dist_h20": -10.7,
        "h60": 120,
        "dist_h60": -16.7,
        "l10": 95,
        "dist_l10": 5.3,
        "l20": 90,
        "dist_l20": 11.1,
        "l60": 80,
        "dist_l60": 25.0,
        "space_20": 14,
        "space_60": 25,
        "ma60s": 0.5,
        "qty60": 20000,
        "badges": ["整理格局"],
        "table": table,
    }


def test_two_threads_render_cards_without_clobbering(tmp_path):
    """偉權／哥哥同時出圖：pyplot 全域鎖要讓兩張都畫完，不能空白互蓋。"""
    import threading

    import matplotlib

    matplotlib.use("Agg")
    errors = []

    def go(sid, name):
        try:
            path = str(tmp_path / f"{sid}.png")
            out = render_decision_card_png(_mini_card(sid, name), path)
            if not out or os.path.getsize(path) < 8000:
                errors.append(f"{sid} too small")
        except Exception as exc:
            errors.append(repr(exc))

    t1 = threading.Thread(target=go, args=("2330", "台積電"))
    t2 = threading.Thread(target=go, args=("2454", "聯發科"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == []
    assert os.path.getsize(tmp_path / "2330.png") > 8000
    assert os.path.getsize(tmp_path / "2454.png") > 8000
