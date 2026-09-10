# -*- coding: utf-8 -*-
"""殘留編碼：官方頁硬解 cp950、Telegram HTML 未跳脫 S&P、股名塞進 HTML 列。"""
from __future__ import annotations

from broker_points import decode_csv_bytes, parse_broker_csv
from data_fetcher import DataFetcher
from universe import (
    clean_stock_name,
    decode_isin_bytes,
    looks_like_yahoo_english_name,
    name_or_sid,
    official_stock_name,
    prefer_display_stock_name,
)
from wayne_db import ensure_core_schema, normalize_quote_hygiene


def test_decode_isin_bytes_prefers_utf8_over_forced_cp950():
    html = "<td>有價證券代號及名稱</td>2330　台積電"
    utf = html.encode("utf-8")
    assert "台積電" not in utf.decode("cp950", errors="replace")
    assert "台積電" in decode_isin_bytes(utf)
    assert "台積電" in decode_isin_bytes(html.encode("cp950"))
    assert "台積電" in decode_isin_bytes(html.encode("utf-8-sig"))


def test_decode_csv_bytes_utf8_not_mojibake_as_cp950():
    text = "券商,買進股數\n1020合庫,2000\n"
    utf = text.encode("utf-8")
    assert "合庫" not in utf.decode("cp950", errors="replace")
    assert "合庫" in decode_csv_bytes(utf)
    assert "合庫" in decode_csv_bytes(text.encode("cp950"))
    rows = parse_broker_csv(decode_csv_bytes(utf))
    assert any("合庫" in str(r.get("broker") or "") for r in rows) or "合庫" in decode_csv_bytes(utf)


def test_watch_radar_escapes_ampersand_in_etf_name():
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.chat_id = "9001"
    runner._load_latest_quotes_map = lambda: {}

    class _Eng:
        def get_watchlist(self, uid):
            return [{"stock_id": "00706L", "stock_name": "期元大S&P日圓正2"}]

    runner.portfolio_engine = _Eng()
    html = runner._format_watch_radar_section("9001")
    assert "S&P" not in html
    assert "S&amp;P" in html
    assert "<b>" in html


def test_clean_stock_name_drops_html_row_dump():
    dump = "['2809', '京城銀', '<p style= color:green>-</p>', '0.30']"
    assert clean_stock_name(dump) == ""
    assert name_or_sid(dump, "2809") == "2809"
    assert DataFetcher.safe_stock_name("2809", dump) == "2809"
    assert DataFetcher.safe_stock_name("2330", "台積電") == "台積電"


def test_quote_hygiene_scrubs_html_names(tmp_path):
    db = str(tmp_path / "enc.db")
    ensure_core_schema(db)
    import sqlite3

    dump = "['2809', '京城銀', '<p style= color:green>-</p>']"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stock_directory (stock_id TEXT PRIMARY KEY, stock_name TEXT NOT NULL, market TEXT DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260908", "2809", dump, "TW", 50, 50, 50, 50, 1, 1, 0, 50),
    )
    conn.execute(
        "INSERT OR REPLACE INTO stock_directory(stock_id, stock_name, market) VALUES (?,?,?)",
        ("2809", "京城銀", "TW"),
    )
    conn.commit()
    conn.close()
    out = normalize_quote_hygiene(db)
    assert out.get("name_scrubbed", 0) >= 1
    conn = sqlite3.connect(db)
    name = conn.execute("SELECT stock_name FROM daily_quotes WHERE stock_id='2809'").fetchone()[0]
    conn.close()
    assert name == "京城銀"
    assert "<p" not in name


def test_prefer_display_stock_name_blocks_yahoo_english():
    yahoo = "Taiwan Semiconductor Manufacturing Company Limited"
    assert looks_like_yahoo_english_name(yahoo) is True
    assert looks_like_yahoo_english_name("台積電") is False
    assert looks_like_yahoo_english_name("LINEPAY") is False
    assert looks_like_yahoo_english_name("IKKA-KY") is False
    assert looks_like_yahoo_english_name("Q BURGER") is False
    assert looks_like_yahoo_english_name("期元大S&P日圓正2") is False
    assert prefer_display_stock_name("台積電", yahoo, "2330") == "台積電"
    assert prefer_display_stock_name("期元大S&P日圓正2", "Yuanta S&P 500 ETF", "00706L") == "期元大S&P日圓正2"
    assert prefer_display_stock_name("LINEPAY", "LINE Pay Taiwan Limited", "7722") == "LINEPAY"
    assert prefer_display_stock_name("2330", "台積電", "2330") == "台積電"
    assert prefer_display_stock_name(yahoo, "", "2330") == "2330"


def test_official_stock_name_skips_yahoo_english(tmp_path):
    import sqlite3

    db = str(tmp_path / "names.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE stock_universe(stock_id TEXT, stock_name TEXT, is_active INT)"
    )
    conn.execute(
        "INSERT INTO stock_universe VALUES ('2330','台積電',1)"
    )
    conn.commit()
    conn.close()
    assert official_stock_name("2330", db) == "台積電"
