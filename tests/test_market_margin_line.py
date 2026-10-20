# -*- coding: utf-8 -*-
"""前一日大盤融資增減：官方信用交易統計 → 早報／大盤一行。"""
from __future__ import annotations

import sqlite3

from official_snapshots import (
    ensure_schema,
    format_prev_day_margin_line,
    latest_market_margin,
    parse_twse_market_margin_payload,
)


def _sample_payload(
    *,
    date: str = "20261016",
    prev_k: str = "646,415,871",
    cur_k: str = "645,594,048",
) -> dict:
    return {
        "stat": "OK",
        "date": date,
        "tables": [
            {
                "title": "115年10月16日 信用交易統計",
                "fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"],
                "data": [
                    ["融資(交易單位)", "1", "1", "0", "9,000,000", "9,000,001"],
                    ["融券(交易單位)", "1", "1", "0", "200,000", "200,000"],
                    ["融資金額(仟元)", "1", "1", "0", prev_k, cur_k],
                ],
            }
        ],
    }


def test_parse_twse_market_margin_delta_yi():
    row = parse_twse_market_margin_payload(_sample_payload())
    assert row is not None
    assert row["date"] == "20261016"
    assert row["margin_bal_prev_k"] == 646415871
    assert row["margin_bal_k"] == 645594048
    assert row["margin_delta_k"] == 645594048 - 646415871
    # 仟元 → 億：約減 8.2 億
    assert abs(row["margin_delta_k"] / 100_000.0 + 8.22) < 0.01


def test_parse_skips_non_ok_and_missing_amount():
    assert parse_twse_market_margin_payload({"stat": "很抱歉，沒有符合條件的資料"}) is None
    bad = _sample_payload()
    bad["tables"][0]["data"] = [["融資(交易單位)", "1", "1", "0", "1", "2"]]
    assert parse_twse_market_margin_payload(bad) is None


def test_format_prev_day_margin_line_increase_decrease_flat(tmp_path):
    db = str(tmp_path / "m.db")
    ensure_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO market_margin_daily(
            date, margin_bal_prev_k, margin_bal_k, margin_delta_k, source, updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        ("20261016", 100_000, 50_000, -50_000, "twse_mi_margn_credit", "t"),
    )
    conn.commit()
    conn.close()
    assert format_prev_day_margin_line(db, "20261016") == "前一日融資 減 0.5 億"

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE market_margin_daily SET margin_delta_k=250000, margin_bal_k=350000 WHERE date='20261016'"
    )
    conn.commit()
    conn.close()
    assert format_prev_day_margin_line(db, "20261016") == "前一日融資 增 2.5 億"

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE market_margin_daily SET margin_delta_k=0, margin_bal_k=100000 WHERE date='20261016'"
    )
    conn.commit()
    conn.close()
    assert format_prev_day_margin_line(db, "20261016") == "前一日融資 持平"


def test_format_omits_when_no_official_row(tmp_path):
    db = str(tmp_path / "empty.db")
    ensure_schema(db)
    assert format_prev_day_margin_line(db, "20261016") == ""
    assert latest_market_margin(db, "20261016") is None


def test_market_page_inserts_between_breadth_and_index(monkeypatch, tmp_path):
    from taiwan_market import format_taiwan_market_page_html

    db = str(tmp_path / "page.db")
    ensure_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO market_margin_daily(
            date, margin_bal_prev_k, margin_bal_k, margin_delta_k, source, updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        ("20260824", 646415871, 645594048, -821823, "twse_mi_margn_credit", "t"),
    )
    conn.commit()
    conn.close()

    snap = {
        "ok": True,
        "as_of": "20260824",
        "close": 23000.0,
        "chg1_pct": 0.5,
        "vs_ma20_pct": 1.2,
        "vs_ma60_pct": 0.5,
        "chg5_pct": 0.1,
        "vs_high52_pct": -4.0,
        "vol_ratio": 1.1,
        "breadth_above_ma20": 46.0,
        "regime": "bull",
        "regime_label": "多頭",
        "regime_plus": "trend_up",
        "regime_plus_label": "多頭延伸",
        "falling_risk": 20,
    }
    monkeypatch.setattr(
        "taiwan_market.analyze_taiwan_market", lambda *_a, **_k: snap
    )
    monkeypatch.setattr(
        "taiwan_market.resolve_market_as_of", lambda *_a, **_k: "20260824"
    )
    monkeypatch.setattr(
        "taiwan_market._index_day_change", lambda *_a, **_k: 0.5
    )
    monkeypatch.setattr(
        "taiwan_market._quote_up_down_counts",
        lambda *_a, **_k: {"n": 0, "up": 0, "down": 0, "flat": 0},
    )
    monkeypatch.setattr(
        "taiwan_market._format_performance_lines", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        "taiwan_market._ohlc_from_live_or_snap",
        lambda snap, live: {"prev_close": 22900.0},
    )
    monkeypatch.setattr(
        "foreign_sell_display.market_env_section_lines", lambda *_a, **_k: []
    )

    html = format_taiwan_market_page_html(db, "20260824")
    plain = html.replace("<b>", "").replace("</b>", "").replace("<a ", " ")
    assert "個股站上月線 46%" in plain
    assert "前一日融資 減 8.2 億" in plain
    i_breadth = plain.index("個股站上月線 46%")
    i_margin = plain.index("前一日融資 減 8.2 億")
    i_index = plain.index("加權指數")
    assert i_breadth < i_margin < i_index


def test_morning_opening_appends_margin_line(monkeypatch):
    from morning_digest import build_morning_opening_html

    monkeypatch.setattr(
        "taiwan_market.format_taiwan_market_brief_html",
        lambda *_a, **_k: "＝＝台灣加權指數研究＝＝\n收盤　46500",
    )
    monkeypatch.setattr(
        "morning_digest._foreign_sell_observe_line",
        lambda *_a, **_k: "",
    )
    monkeypatch.setattr(
        "morning_digest._prev_day_margin_line",
        lambda *_a, **_k: "前一日融資 減 8.2 億",
    )
    screening = {
        "payload": [
            {"mark_key": "market", "html": "＝＝大盤狀況＝＝\n加權收盤　46000", "picks": []},
        ]
    }
    merged = build_morning_opening_html(":memory:", "20261016", screening)
    assert "前一日融資 減 8.2 億" in merged
    assert merged.index("大盤狀況") < merged.index("前一日融資 減 8.2 億")
