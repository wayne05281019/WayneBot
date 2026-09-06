def test_line_stock_headline_no_yahoo_url():
    from line_share_format import (
        _disp_w,
        _pad_label,
        format_line_stock_block,
        line_bucket_header,
        line_stock_headline,
    )

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
            "industry_plain": "半導體業近期營收轉強，法人買超持續增加中，這檔剛離低點產業還沒全面轉強。",
        },
        1,
    )
    lines = block.split("\n")
    assert lines[0] == "1. 台積電 (2330)"
    assert "tw.stock.yahoo.com" not in block
    assert "/y/2330" in block
    assert any(ln.startswith(_pad_label("格局")) for ln in lines)
    assert any(ln.startswith(_pad_label("收")) for ln in lines)
    assert any(ln.startswith(_pad_label("量")) for ln in lines)
    assert any(ln.startswith(_pad_label("額")) for ln in lines)
    assert "0.80億" in block
    assert any(ln.startswith(_pad_label("均線")) for ln in lines)
    assert "月　" in block and "季　" in block
    assert "外資" in block and "　投信" in block
    assert any(ln.startswith(_pad_label("法人")) for ln in lines)
    assert "獲利" in block and "12.3%" in block
    assert "近60日低點上來" not in block
    assert "產業" in block
    assert "半導體業近期營收轉強" in block
    val_col = _disp_w(_pad_label("收") + "　")
    for ln in lines[1:]:
        if ln.startswith("　　　"):
            assert _disp_w("　　　") == val_col
        elif ln.startswith(_pad_label("奇摩")):
            continue
        elif any(ln.startswith(_pad_label(lab)) for lab in ("格局", "收", "量", "額", "均線", "法人", "獲利", "產業")):
            assert _disp_w(ln[: len(_pad_label("收") + "　")]) == val_col or ln.startswith(_pad_label(ln[:2]))
    industry_lines = [ln for ln in lines if "半導體" in ln or ln.startswith("　　　")]
    assert industry_lines
    assert all(len(ln.replace("　", "").strip()) != 1 for ln in industry_lines)
    assert "＝＝周帶量＝＝" in line_bucket_header("select_01", 3)
    assert "突破5日高" not in line_bucket_header("select_01", 3)
    assert "說明：" not in line_bucket_header("leave_zero", 2)
    assert line_bucket_header("leave_zero", 2) == "＝＝起漲＝＝\n共 2 檔"


def test_yahoo_hop_html_has_no_preview_card():
    from line_hop import render_yahoo_hop_html

    page = render_yahoo_hop_html("2330", "台積電")
    assert "og:image" not in page
    assert "location.replace" not in page
    assert "tw.stock.yahoo.com/quote/2330" in page
    assert "開奇摩股市" in page
