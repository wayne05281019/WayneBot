# -*- coding: utf-8 -*-
"""月營收／季報：休市漏抓防再發＋查股 ensure＋介紹圖指紋。"""
from __future__ import annotations

import sqlite3

from fundamentals import (
    ensure_stock_fundamentals,
    filing_month_coverage,
    get_latest_monthly,
    glance_fund_split_layout,
    parse_t21sc03_html,
    refresh_announced_monthly,
    stock_fundamentals_fingerprint,
    stock_month_row,
)
from wayne_db import ensure_core_schema

FIXTURE_7853_SEP = """
<html><table>
<tr><th class=tt align=left >產業別：半導體業</th></tr>
<tr align=right><td align=center>7853</td><td align=left>政美應用</td>
<td nowrap>153210</td><td nowrap>30300</td><td nowrap>5387</td>
<td nowrap>405.64</td><td nowrap>2744.06</td>
<td nowrap>526036</td><td nowrap>258088</td><td nowrap>103.82</td>
<td align=left></td></tr>
<tr align=right><td align=center>3595</td><td align=left>山太士</td>
<td nowrap>92752</td><td nowrap>84567</td><td nowrap>70773</td>
<td nowrap>9.67</td><td nowrap>31.05</td>
<td nowrap>590233</td><td nowrap>350487</td><td nowrap>68.4</td>
<td align=left></td></tr>
</table></html>
"""


def _seed_em(db: str) -> None:
    ensure_core_schema(db)
    from fundamentals import ensure_fundamentals_tables

    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    now = "2026-10-08T16:12:14"
    for sid, name in (("7853", "政美應用"), ("3595", "山太士")):
        conn.execute(
            "INSERT OR REPLACE INTO stock_universe"
            "(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at)"
            " VALUES (?,?,?,?,?,1,?)",
            (sid, name, "EM", "STOCK", "半導體業", now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO monthly_revenue"
            "(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "202608", name, "EM", "半導體業", 30300 if sid == "7853" else 84567, -10, 10, 10, now),
        )
    # 上一月夠厚、本檔期偏薄＝連假漏抓訊號
    for i in range(600):
        conn.execute(
            "INSERT OR IGNORE INTO monthly_revenue"
            "(stock_id,yyyymm,stock_name,market,industry,revenue,updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (f"T{i:04d}", "202608", f"dummy{i}", "TW", "測", 1, now),
        )
    for i in range(100):
        conn.execute(
            "INSERT OR IGNORE INTO monthly_revenue"
            "(stock_id,yyyymm,stock_name,market,industry,revenue,updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (f"S{i:04d}", "202609", f"early{i}", "TW", "測", 1, now),
        )
    conn.commit()
    conn.close()


def test_filing_month_coverage_flags_thin_after_holiday_gap(tmp_path):
    db = str(tmp_path / "thin.db")
    _seed_em(db)
    cover = filing_month_coverage(db, "202609")
    assert cover["yyyymm"] == "202609"
    assert cover["prev_n"] >= 500
    assert cover["thin"] is True
    assert cover["ok"] is False


def test_ensure_stock_pulls_announced_sept_for_missing_emerging(tmp_path, monkeypatch):
    db = str(tmp_path / "ens.db")
    _seed_em(db)
    assert stock_month_row(db, "7853", "202609") is None
    monkeypatch.setattr("fundamentals.previous_calendar_yyyymm", lambda today_ymd="": "202609")
    monkeypatch.setattr("fundamentals._get", lambda url: [])
    monkeypatch.setattr(
        "fundamentals.fetch_mops_monthly_filings",
        lambda yyyymm: (parse_t21sc03_html(FIXTURE_7853_SEP, yyyymm, "EM"), []),
    )
    monkeypatch.setattr(
        "fundamentals.fetch_mops_emerging_monthly_history",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(
        "fundamentals.emerging_monthly_gap_months",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "fundamentals.refresh_announced_income",
        lambda *a, **k: {"ok": True, "skipped": "test"},
    )
    monkeypatch.setattr("universe.stock_is_emerging", lambda *_a, **_k: True)
    monkeypatch.setattr("universe.card_asset_type", lambda *_a, **_k: "STOCK")
    monkeypatch.setattr("universe.is_etf_asset", lambda *_a, **_k: False)

    out = ensure_stock_fundamentals(db, "7853", force=True)
    assert out["has_filing_month"] is True
    latest = get_latest_monthly(db, "7853")
    assert latest["yyyymm"] == "202609"
    assert latest["revenue"] == 153210
    # 同批已公告也要進來，不准只補點名那一檔
    assert get_latest_monthly(db, "3595")["yyyymm"] == "202609"

    split = glance_fund_split_layout("7853", db)
    assert split and split.get("emerging")
    sept = [p for p in split["chart_points"] if p.get("yyyymm") == "202609"]
    assert sept and sept[0]["has_data"] is True
    assert float(sept[0]["revenue"]) == 153210.0


def test_refresh_ttl_avoids_hammering(tmp_path, monkeypatch):
    db = str(tmp_path / "ttl.db")
    _seed_em(db)
    calls = {"n": 0}

    def fake_mops(yyyymm):
        calls["n"] += 1
        return parse_t21sc03_html(FIXTURE_7853_SEP, yyyymm, "EM"), []

    monkeypatch.setattr("fundamentals.previous_calendar_yyyymm", lambda today_ymd="": "202609")
    monkeypatch.setattr("fundamentals._get", lambda url: [])
    monkeypatch.setattr("fundamentals.fetch_mops_monthly_filings", fake_mops)
    monkeypatch.setattr(
        "fundamentals.fetch_mops_emerging_monthly_history",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr("fundamentals.emerging_monthly_gap_months", lambda *a, **k: [])
    a = refresh_announced_monthly(db, "202609", force=True, reason="first")
    b = refresh_announced_monthly(db, "202609", force=False, reason="second")
    assert a.get("mops_rows") == 2
    assert b.get("skipped") == "ttl"
    assert calls["n"] == 1


def test_fundamentals_fingerprint_changes_when_sept_arrives(tmp_path):
    db = str(tmp_path / "fp.db")
    _seed_em(db)
    before = stock_fundamentals_fingerprint(db, "7853")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO monthly_revenue"
        "(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("7853", "202609", "政美應用", "EM", "半導體業", 153210, 405.64, 2744.06, 103.82, "2026-10-12T18:00:00"),
    )
    conn.commit()
    conn.close()
    after = stock_fundamentals_fingerprint(db, "7853")
    assert before != after
    assert after[0] == "202609"


def test_closed_and_morning_skip_still_refresh_sidecars():
    src = open("main_runner.py", encoding="utf-8").read()
    # 休市 skip increment 仍對側車
    i_closed = src.find("tw closed")
    assert i_closed != -1
    chunk = src[src.find("if self._increment_ok(health_closed)") : src.find("if skip_if_done and self.already_completed_today()")]
    assert "_refresh_official_sidecars()" in chunk
    # 早報已寄過仍對側車
    assert "略過寄送；仍對官方側車" in src
    # 休市早報仍對側車（精簡早報路徑）
    assert "_run_closed_day_morning_digest" in src
    assert "_refresh_official_sidecars()" in src
    # 盤後已成功仍續補月營收
    assert "仍對官方側車（月營收續補）" in src


def test_glance_memo_includes_fund_fingerprint():
    src = open("wayne_navigator.py", encoding="utf-8").read()
    assert "stock_fundamentals_fingerprint" in src
    assert "ensure_stock_fundamentals" in src
    assert (
        "match-card-076-fund-rev2line-v77-card-price" in src
        or "match-card-076-fund-rev2line-v76" in src
    )
