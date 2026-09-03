# -*- coding: utf-8 -*-
"""櫃買 wn1430 無均價欄時，不可把成交股數當均價。"""


def test_tpex_wn1430_row_parses_avg_from_turnover():
    from data_fetcher import DataFetcher

    payload = {
        "date": "2026/09/02",
        "tables": [
            {
                "title": "上櫃股票每日收盤行情(不含定價)",
                "fields": [
                    "代號",
                    "名稱",
                    "收盤 ",
                    "漲跌",
                    "開盤 ",
                    "最高 ",
                    "最低",
                    "成交股數  ",
                    " 成交金額(元)",
                    " 成交筆數 ",
                ],
                "data": [
                    [
                        "3693",
                        "營邦",
                        "642.00",
                        "+18.00",
                        "627.00",
                        "654.00",
                        "626.00",
                        "2,060,000",
                        "1,324,240,000",
                        "1,671",
                    ]
                ],
            }
        ],
    }
    rows = DataFetcher()._parse_tpex_payload(payload, "20260902")
    assert len(rows) == 1
    row = rows[0]
    assert row["stock_id"] == "3693"
    assert row["volume"] == 2060
    assert 640 <= row["avg_price"] <= 645
    assert row["avg_price"] != 2060000


def test_coerce_avg_price_rejects_share_count():
    from data_fetcher import DataFetcher

    avg = DataFetcher.coerce_avg_price(
        2060000, 642.0, 626.0, 654.0, 2060000, 1324240000
    )
    assert 640 <= avg <= 645


def test_avg_price_for_safety_from_bad_db_row():
    from screening_engine import _avg_price_for_safety

    item = {
        "close": 642.0,
        "low": 626.0,
        "high": 654.0,
        "volume": 2060,
        "turnover_k": 1324240.0,
        "avg_price": 2060000.0,
    }
    assert 640 <= _avg_price_for_safety(item) <= 645
