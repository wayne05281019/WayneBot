# -*- coding: utf-8 -*-
"""分點建檔與平均買超成本：有列才上主力成本，禁止 T86 推估。"""
from __future__ import annotations

from broker_points import (
    attach_main_cost,
    ensure_broker_for_stock,
    main_cost_from_net_buy,
    parse_broker_csv,
    upsert_branch_rows,
)
from wayne_db import ensure_core_schema


TWSE_SAMPLE = """證券代碼,2330
序號,券商,價格,買進股數,賣出股數,序號,券商,價格,買進股數,賣出股數
1,1020合庫,100.00,2000,0,2,1021合庫北,99.00,0,1000
3,5850統一,101.00,1000,500,4,5920元富,98.00,0,3000
"""

NAMED_SAMPLE = """券商,買進股數,賣出股數,買進金額,賣出金額
1020合庫,2000,0,200000,0
1021合庫北,0,1000,0,99000
"""


def test_parse_dual_table_and_net_buy_cost():
    rows = parse_broker_csv(TWSE_SAMPLE)
    names = {r["broker"] for r in rows}
    assert "1020合庫" in names
    assert "1021合庫北" in names
    assert "5850統一" in names
    cost = main_cost_from_net_buy(rows)
    # 買超：合庫 2000@100、統一 1000@101（淨買 500 仍算買超）
    # 金額 200000+101000 = 301000 / 股數 3000 = 100.333 → 100.33
    assert cost == 100.33


def test_named_amount_columns():
    rows = parse_broker_csv(NAMED_SAMPLE)
    assert main_cost_from_net_buy(rows) == 100.0


def test_captcha_html_yields_no_rows():
    assert parse_broker_csv("<html>請輸入驗證碼</html>") == []


def test_persist_and_attach_without_fetch(tmp_path):
    db = str(tmp_path / "br.db")
    ensure_core_schema(db)
    rows = parse_broker_csv(TWSE_SAMPLE)
    n = upsert_branch_rows("2330", "20260904", rows, db_path=db, source="fixture")
    assert n >= 3
    cost = ensure_broker_for_stock("2330", db, "20260904", fetch=False)
    assert cost == 100.33
    card = {"stock_id": "2330", "latest_date": "20260904"}
    attach_main_cost(card, db, fetch=False)
    assert card["main_cost"] == 100.33
    empty = {"stock_id": "9999", "latest_date": "20260904"}
    attach_main_cost(empty, db, fetch=False)
    assert "main_cost" not in empty


def test_failed_http_fetch_cools_down(monkeypatch):
    import broker_points

    broker_points._FETCH_COOLDOWN.clear()
    hits = {"n": 0}

    def fake_http(_url, _timeout):
        hits["n"] += 1
        return "<html>請輸入驗證碼</html>".encode("utf-8")

    monkeypatch.setattr("broker_points._http_bytes", fake_http)
    assert broker_points.try_fetch_remote_csv("2330", "20260904") == []
    assert hits["n"] >= 1
    first = hits["n"]
    assert broker_points.try_fetch_remote_csv("2330", "20260904") == []
    assert hits["n"] == first
    broker_points._FETCH_COOLDOWN.clear()


def test_etf_never_fetches(tmp_path):
    db = str(tmp_path / "etf.db")
    ensure_core_schema(db)
    assert ensure_broker_for_stock("00892", db, "20260904", fetch=True) is None


def test_local_csv_drop_builds_archive(tmp_path, monkeypatch):
    db = str(tmp_path / "drop.db")
    ensure_core_schema(db)
    csv_dir = tmp_path / "broker_csv"
    csv_dir.mkdir()
    (csv_dir / "2454_20260904.csv").write_text(NAMED_SAMPLE, encoding="utf-8")
    monkeypatch.setenv("WAYNE_BROKER_CSV_DIR", str(csv_dir))
    cost = ensure_broker_for_stock("2454", db, "20260904", fetch=True)
    assert cost == 100.0
    card = {"stock_id": "2454", "latest_date": "20260904"}
    attach_main_cost(card, db, fetch=False)
    assert card["main_cost"] == 100.0


def test_lookup_attaches_cost_screen_does_not_fetch():
    import inspect

    from wayne_navigator import NavigatorEngine, generate_decision_card, render_stock_pack

    card_src = inspect.getsource(NavigatorEngine.get_decision_card)
    assert "attach_main_cost" not in card_src
    assert "ensure_broker_for_stock" not in card_src
    pack_src = inspect.getsource(render_stock_pack)
    html_src = inspect.getsource(generate_decision_card)
    assert "attach_main_cost" in pack_src
    assert "主力成本" in html_src


def test_increment_syncs_events_not_all_market_broker():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner.run_daily_increment)
    assert "sync_company_events" in src
    assert "ensure_broker_for_stock" not in src
    assert "try_fetch_remote_csv" not in src


def test_main_cost_not_from_three_institutional():
    """賣超分點不能灌進平均買超成本。"""
    rows = [
        {"broker": "A買超", "price": 50, "buy_shares": 1000, "sell_shares": 0, "buy_amount": 50000, "sell_amount": 0},
        {"broker": "B賣超", "price": 80, "buy_shares": 100, "sell_shares": 5000, "buy_amount": 8000, "sell_amount": 400000},
    ]
    assert main_cost_from_net_buy(rows) == 50.0
