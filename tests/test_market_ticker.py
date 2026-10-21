# -*- coding: utf-8 -*-
"""TAIFEX helper 仍活；跑馬燈面已削，話筒不得再送 ticker。"""


def test_pick_tx_front_month_by_volume():
    from market_ticker import pick_tx_quote_row

    rows = [
        {"SymbolID": "TXF-S", "CLastPrice": "47326", "CTotalVolume": "99999"},
        {"SymbolID": "TXFI6-F", "CLastPrice": "47470", "CTotalVolume": "80000", "CDiffRate": "1.63"},
        {"SymbolID": "TXFJ6-F", "CLastPrice": "47667", "CTotalVolume": "1200", "CDiffRate": "1.67"},
        {"SymbolID": "TXFI6-M", "CLastPrice": "47333", "CTotalVolume": "5000", "CDiffRate": "-0.20"},
    ]
    day = pick_tx_quote_row(rows, night=False)
    assert day["SymbolID"] == "TXFI6-F"
    night = pick_tx_quote_row(rows, night=True)
    assert night["SymbolID"] == "TXFI6-M"


def test_num_or_none_parses_and_skips():
    from market_ticker import _num_or_none

    assert _num_or_none("47,470") == 47470.0
    assert _num_or_none("+1.63%") == 1.63
    assert _num_or_none("--") is None
    assert _num_or_none("") is None


def test_biaoke_verify_can_import_taifex_helpers():
    """刪前／刪後閘：fetch_tx_ohlc 仍能從本檔拿到同一組符號。"""
    from market_ticker import (
        _TAIFEX_HEADERS,
        _TAIFEX_QUOTE_URL,
        _num_or_none,
        pick_tx_quote_row,
    )

    assert "getQuoteList" in _TAIFEX_QUOTE_URL
    assert _TAIFEX_HEADERS.get("Origin") == "https://mis.taifex.com.tw"
    assert callable(_num_or_none)
    assert callable(pick_tx_quote_row)


def test_ticker_face_symbols_removed():
    import market_ticker as mt

    for name in (
        "build_market_ticker",
        "ticker_html",
        "ticker_plain",
        "collect_ticker",
        "render_ticker_gif",
        "ticker_slot",
        "ticker_send_kwargs",
    ):
        assert not hasattr(mt, name), name


def test_bot_market_page_no_longer_sends_ticker():
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "build_market_ticker" not in src
    assert "_ticker_keyboard" not in src
    assert "tk:r" not in src
    assert "刷新跑馬燈" not in src
    assert "from market_ticker" not in src
    assert "import market_ticker" not in src
