# -*- coding: utf-8 -*-
"""飆大對話腦：沒寫過的檔也套框架；止跌上警語；食衣住行不答。"""
import sqlite3

from biaoke_brain import (
    DISCLAIMER,
    OFFTOPIC,
    answer_biaoke,
    is_desk_query,
    is_offtopic,
    volume_first_price,
)
from biaoke_desk import format_biaoke_desk_html, search_biaoke


def _db(tmp_path):
    path = str(tmp_path / "biaoke.db")
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE index_daily (
            date TEXT, symbol TEXT DEFAULT 'TWII', close REAL,
            volume REAL, pct_change REAL, high REAL, low REAL,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE us_overnight (
            as_of TEXT PRIMARY KEY,
            fetched_at TEXT, us_session TEXT, regime TEXT,
            vix REAL, vix_pct REAL, dji_pct REAL, spx_pct REAL,
            ixic_pct REAL, sox_pct REAL, nq_f_pct REAL,
            tsm_pct REAL, nvda_pct REAL, payload TEXT DEFAULT '{}'
        )
        """
    )
    rows = [
        ("20260908", "2756", "藝舍-KY", 40, 42, 38, 41, 80000, 2.5),
        ("20260909", "2756", "藝舍-KY", 41, 41.5, 39, 39.5, 20000, -3.66),
        ("20260910", "2756", "藝舍-KY", 39.5, 40, 38.8, 39.2, 12000, -0.76),
        ("20260908", "2330", "台積電", 1400, 1420, 1380, 1400, 90000, -1.2),
        ("20260909", "2330", "台積電", 1390, 1395, 1360, 1365, 40000, -2.5),
        ("20260910", "2330", "台積電", 1360, 1370, 1350, 1355, 30000, -0.73),
    ]
    for d, sid, name, o, h, l, c, v, pct in rows:
        conn.execute(
            """
            INSERT INTO daily_quotes(
                date, stock_id, stock_name, market, open, high, low, close,
                volume, turnover_k, pct_change, avg_price
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (d, sid, name, "TW", o, h, l, c, v, 0, pct, c),
        )
    for d, c, pct in (
        ("20260908", 27200, -1.1),
        ("20260909", 26800, -1.47),
        ("20260910", 26500, -1.12),
    ):
        conn.execute(
            """
            INSERT INTO index_daily(date, symbol, close, pct_change, high, low)
            VALUES (?,?,?,?,?,?)
            """,
            (d, "TWII", c, pct, c + 80, c - 60),
        )
    conn.execute(
        """
        INSERT INTO us_overnight(
            as_of, regime, vix, dji_pct, spx_pct, ixic_pct, sox_pct, nq_f_pct,
            tsm_pct, nvda_pct, payload
        ) VALUES ('20260910','risk_off',28,-1.8,-2.1,-2.6,-3.1,-1.4,-2.0,-2.8,'{}')
        """
    )
    conn.execute(
        """
        INSERT INTO us_overnight(
            as_of, regime, vix, dji_pct, spx_pct, ixic_pct, sox_pct, payload
        ) VALUES ('20260909','caution',24,-0.8,-1.0,-1.2,-1.5,'{}')
        """
    )
    conn.commit()
    conn.close()
    return path


def test_yishe_not_in_corpus_still_answers(tmp_path):
    db = _db(tmp_path)
    html = answer_biaoke(db, "藝舍-KY")
    assert "這不是買訊" in html
    assert "藝舍" in html
    assert "語料從頭到尾沒點名" in html
    assert "不猜" not in html
    assert "爆大量日" in html
    assert "2026-09-08" in html
    assert "三買點對照" not in html
    assert "他這套怎麼想" not in html
    assert "KD" not in html


def test_hello_is_short_not_a_lecture():
    html = answer_biaoke(":memory:", "你好")
    assert html == "在，你說。"
    assert "這不是買訊" not in html


def test_stop_drop_uses_conditions_not_a_date(tmp_path):
    db = _db(tmp_path)
    html = answer_biaoke(db, "台股美股連跌 晚上又大跌 大概何時止跌")
    assert "這不是買訊" in html
    assert "不猜日曆" in html
    assert "費半" in html
    assert "夜盤" in html
    assert "台積電" in html
    assert "下週三" not in html
    assert "2026/09/20" not in html
    assert "逆風" in html or "條件還沒齊" in html


def test_offtopic_lifestyle_refused():
    assert is_offtopic("今晚吃什麼")
    html = answer_biaoke(":memory:", "今晚吃什麼")
    assert html == OFFTOPIC
    assert "買訊" not in html


def test_desk_query_still_rules():
    assert is_desk_query("")
    assert is_desk_query("   ")
    assert not is_desk_query("怎麼觀察")
    assert not is_desk_query("去年年底")
    assert not is_desk_query("藝舍-KY")
    html = answer_biaoke(":memory:", "怎麼觀察")
    assert "這不是買訊" in html
    assert "細微波" in html
    assert "兩年進步在哪" not in html
    assert "在。打字" not in html


def test_volume_first_price_spike_is_high_volume_day():
    bars = [
        {"date": "20260908", "stock_id": "2756", "stock_name": "藝舍-KY",
         "high": 42, "low": 38, "close": 41, "volume": 80000, "pct_change": 2.5},
        {"date": "20260909", "stock_id": "2756", "stock_name": "藝舍-KY",
         "high": 41.5, "low": 39, "close": 39.5, "volume": 20000, "pct_change": -3.66},
        {"date": "20260910", "stock_id": "2756", "stock_name": "藝舍-KY",
         "high": 40, "low": 38.8, "close": 39.2, "volume": 12000, "pct_change": -0.76},
    ]
    st = volume_first_price(bars)
    assert st["spike_date"] == "2026-09-08"
    assert st["spike_high"] == 42
    assert st["spike_low"] == 38
    assert st["above_support"] is True
    assert st["shrinking"] is True
    assert st["down_streak"] == 2


def test_search_miss_does_not_say_wont_guess():
    html = search_biaoke("這個代號絕對不存在xyzzy")
    assert "不猜" not in html
    assert "不是買訊" in html


def test_desk_html_mentions_unmentioned_names():
    html = format_biaoke_desk_html()
    assert "藝舍" in html or "沒寫過" in html
    assert "不是買訊" in html
