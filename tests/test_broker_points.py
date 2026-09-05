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

    from wayne_navigator import (
        NavigatorEngine,
        generate_decision_card,
        render_decision_card_png,
        render_first_glance_png,
        render_stock_pack,
    )

    card_src = inspect.getsource(NavigatorEngine.get_decision_card)
    assert "attach_main_cost" not in card_src
    assert "ensure_broker_for_stock" not in card_src
    pack_src = inspect.getsource(render_stock_pack)
    html_src = inspect.getsource(generate_decision_card)
    png_src = inspect.getsource(render_decision_card_png)
    glance_src = inspect.getsource(render_first_glance_png)
    assert "attach_main_cost" in pack_src
    assert "主力成本" in html_src
    assert "主力成本" in png_src
    assert "分點平均買超" in png_src
    assert "主力成本" in glance_src


def test_decision_card_png_draws_main_cost_only_when_present(tmp_path, monkeypatch):
    """決策卡 PNG：有分點平均買超才寫主力成本；沒有真數就空白。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes
    import pandas as pd

    from wayne_navigator import render_decision_card_png

    table = pd.DataFrame(
        [
            {
                "date": "20260904",
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

    def capture():
        seen = []
        orig = matplotlib.axes.Axes.text

        def wrap(self, *args, **kwargs):
            if len(args) >= 3:
                seen.append(str(args[2]))
            if "s" in kwargs:
                seen.append(str(kwargs["s"]))
            return orig(self, *args, **kwargs)

        monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
        return seen

    seen = capture()
    blank = tmp_path / "no_cost.png"
    assert render_decision_card_png(card, str(blank))
    joined = "\n".join(seen)
    assert "主力成本" not in joined

    card["main_cost"] = 100.33
    seen.clear()
    with_cost = tmp_path / "with_cost.png"
    assert render_decision_card_png(card, str(with_cost))
    assert "主力成本 100.33（分點平均買超）" in seen


def test_increment_syncs_events_not_all_market_broker():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner.run_daily_increment)
    assert "sync_company_events" in src
    assert "sync_broker_archive" in src
    assert "ensure_broker_for_stock" not in src
    assert "try_fetch_remote_csv" not in src
    from broker_points import sync_broker_archive

    arch = inspect.getsource(sync_broker_archive)
    assert "ingest_csv_drop" in arch
    assert "sync_holdings_broker" in arch
    assert "stock_universe" not in arch
    from broker_points import sync_holdings_broker

    assert "daily_quotes" not in inspect.getsource(sync_holdings_broker)
    assert "stock_universe" not in inspect.getsource(sync_holdings_broker)


def test_csv_drop_and_holdings_archive_roundtrip(tmp_path, monkeypatch):
    """定時匯入：CSV 丟檔建檔；持股逐檔；ETF／驗證碼不上成本。"""
    from broker_points import ingest_csv_drop, sync_broker_archive
    from portfolio_engine import PortfolioEngine
    from wayne_db import add_to_portfolio, ensure_core_schema

    db = str(tmp_path / "arch.db")
    ensure_core_schema(db)
    csv_dir = tmp_path / "broker_csv"
    csv_dir.mkdir()
    (csv_dir / "6526_20260904.csv").write_text(NAMED_SAMPLE, encoding="utf-8")
    (csv_dir / "00892_20260904.csv").write_text(NAMED_SAMPLE, encoding="utf-8")
    (csv_dir / "readme.txt").write_text("not csv", encoding="utf-8")
    monkeypatch.setenv("WAYNE_BROKER_CSV_DIR", str(csv_dir))
    add_to_portfolio(db, "u1", "6526", "達發", 0.439, 631.6)
    add_to_portfolio(db, "u1", "3035", "智原", 4.0, 196.8)

    dropped = ingest_csv_drop(db, "20260904")
    assert dropped["files"] == 1
    assert "6526" in dropped["stocks"]
    assert "00892" not in dropped["stocks"]

    hits = {"n": 0}

    def fake_http(_url, _timeout):
        hits["n"] += 1
        return "<html>請輸入驗證碼</html>".encode("utf-8")

    monkeypatch.setattr("broker_points._http_bytes", fake_http)
    out = sync_broker_archive(db, "20260904", fetch_holdings=True)
    assert out["csv"]["files"] == 1
    assert out["holdings"]["costs"]["6526"] == 100.0
    assert "3035" not in out["holdings"]["costs"]
    assert out["holdings"]["blank"] >= 1
    assert hits["n"] >= 1

    html = PortfolioEngine(db).format_holdings_html(
        [
            {"stock_code": "6526", "stock_name": "達發", "shares": 0.439, "cost_price": 631.6},
            {"stock_code": "3035", "stock_name": "智原", "shares": 4.0, "cost_price": 196.8},
        ],
        quotes_map={
            "6526": {"close": 635.0, "pct_change": 0.79},
            "3035": {"close": 179.5, "pct_change": -0.28},
        },
    )
    assert "主力成本" in html.split("達發")[1].split("智原")[0]
    assert "100.00（分點平均買超）" in html
    assert "成本對主力" in html.split("達發")[1].split("智原")[0]
    assert "主力成本" not in html.split("智原")[-1]


def test_main_cost_not_from_three_institutional():
    """賣超分點不能灌進平均買超成本。"""
    rows = [
        {"broker": "A買超", "price": 50, "buy_shares": 1000, "sell_shares": 0, "buy_amount": 50000, "sell_amount": 0},
        {"broker": "B賣超", "price": 80, "buy_shares": 100, "sell_shares": 5000, "buy_amount": 8000, "sell_amount": 400000},
    ]
    assert main_cost_from_net_buy(rows) == 50.0
