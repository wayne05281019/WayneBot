def test_line_stock_headline_no_yahoo_url():
    from line_share_format import format_line_stock_block, line_bucket_header, line_stock_headline

    headline = line_stock_headline(1, "2330", "台積電")
    assert headline == "1. 台積電 (2330)"
    assert "yahoo" not in headline.lower()

    block = format_line_stock_block(
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "pct_change": 2.5,
            "volume": 8000,
            "q60r": 2.1,
            "turnover_k": 80000,
            "ma20": 98,
            "ma60": 95,
            "foreign_net": 100,
            "trust_net": 20,
            "dealer_net": -5,
            "profit": 12.3,
            "industry_plain": "半導體業近期營收轉強，法人買超持續增加中",
        },
        1,
    )
    lines = block.split("\n")
    assert lines[0] == "1. 台積電 (2330)"
    assert "yahoo" not in block.lower()
    assert lines[1].startswith("格局：")
    assert lines[2].startswith("收　")
    assert lines[3].startswith("量　")
    assert lines[4].startswith("額　")
    assert "0.80億" in lines[4]  # 80,000 千元＝0.80 億
    assert lines[5].startswith("均線　")
    assert lines[6].startswith("法人　")
    assert "獲利　12.3%" in block
    assert "近60日低點上來" not in block
    assert "產業" in block
    assert "半導體業近期營收轉強" in block
    assert "＝＝周帶量＝＝" in line_bucket_header("select_01", 3)
    assert "突破5日高" not in line_bucket_header("select_01", 3)
    assert "說明：" not in line_bucket_header("leave_zero", 2)
    assert line_bucket_header("leave_zero", 2) == "＝＝起漲＝＝\n共 2 檔"
