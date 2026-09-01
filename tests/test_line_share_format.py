def test_line_stock_headline_puts_yahoo_on_same_line():
    from line_share_format import format_line_stock_block, line_bucket_header

    block = format_line_stock_block(
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "pct_change": 2.5,
            "volume": 8000,
            "q60r": 2.1,
            "ma20": 98,
            "ma60": 95,
            "foreign_net": 100,
            "trust_net": 20,
            "dealer_net": -5,
        },
        1,
    )
    first = block.split("\n", 1)[0]
    assert "台積電(2330)" in first
    assert "tw.stock.yahoo.com/quote/2330" in first
    assert first.count("\n") == 0
    assert "【周帶量】突破5日高" in line_bucket_header("select_01", 3)
