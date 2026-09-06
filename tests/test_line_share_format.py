import pytest


def test_line_stock_headline_no_yahoo_url():
    from line_share_format import (
        STANCE_LABEL,
        _disp_w,
        _pad_label,
        format_line_stock_block,
        line_bucket_header,
        line_plain_to_html,
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
            "quote_date": "20260904",
            "industry_plain": "半導體業近期營收轉強，法人買超持續增加中，這檔剛離低點產業還沒全面轉強。",
        },
        1,
    )
    lines = block.split("\n")
    assert lines[0] == "1. 台積電 (2330)"
    assert "tw.stock.yahoo.com" not in block
    assert "/y/2330" in block
    two = ("格局", "收盤", "量能", "金額", "均線", "法人", "獲利", "產業")
    for lab in two:
        assert any(ln.startswith(_pad_label(lab)) for ln in lines)
        assert _disp_w(lab) == 4
    assert "0.80億" in block
    assert "月　" in block and "季　" in block
    assert not any(ln.rstrip().endswith("季") and "月" in ln for ln in lines)
    assert "外資" in block and "　投信" in block
    assert "近一日　09-04" in block
    assert "投信+20張" in block
    assert "投信+\n" not in block
    assert "投信+　" not in block
    assert "獲利" in block and "12.3%" in block
    assert "60日低上來" in block
    assert "今天先看表，先等" in block
    assert "不是下單指令" in block or "看下面這張" in block
    assert "半導體業近期營收轉強" in block
    assert not any(ln.startswith(_pad_label(STANCE_LABEL)) for ln in lines)
    geju = next(ln for ln in lines if ln.startswith(_pad_label("格局")))
    assert "今天先看表，先等" in geju or any(
        ln.startswith("　　　") and "今天先看表" in ln for ln in lines
    )
    val_col = _disp_w(_pad_label("收盤") + "　")
    for ln in lines[1:]:
        if ln.startswith("http"):
            continue
        if ln.startswith("　　　"):
            assert _disp_w("　　　") == val_col
        elif ln.startswith(_pad_label("奇摩")):
            continue
        elif any(ln.startswith(_pad_label(lab)) for lab in two):
            assert _disp_w(ln[: len(_pad_label("收盤") + "　")]) == val_col
    industry_lines = [ln for ln in lines if "半導體" in ln or ln.startswith("　　　")]
    assert industry_lines
    assert all(len(ln.replace("　", "").strip()) != 1 for ln in industry_lines)
    html = line_plain_to_html(block)
    assert 'class="stance"' in html
    assert "#c41e3a" not in html
    assert "今天先看表，先等" in html
    assert STANCE_LABEL not in html
    assert "＝＝周帶量＝＝" in line_bucket_header("select_01", 3)
    assert "突破5日高" not in line_bucket_header("select_01", 3)
    assert "說明：" not in line_bucket_header("leave_zero", 2)
    assert line_bucket_header("leave_zero", 2) == "＝＝黃金買點＝＝\n共 2 檔"


def test_line_profit_and_stance_leave_zero_style():
    from line_share_format import format_line_stock_block

    block = format_line_stock_block(
        {
            "stock_id": "4915",
            "stock_name": "致伸",
            "close": 60.8,
            "pct_change": 2.01,
            "volume": 12000,
            "profit": 2.4,
            "quote_date": "20260904",
        },
        1,
        bucket_key="leave_zero",
    )
    assert "收盤" in block and "量能" in block
    assert "2.4%" in block and "60日低上來" in block
    assert "近一日" in block
    assert "格局" in block and "黃金買點" in block
    assert "今天先看表，先等" in block
    geju = next(ln for ln in block.split("\n") if ln.startswith("格局"))
    assert "黃金買點" in geju
    assert "今天先看表，先等" in geju
    from line_share_format import line_plain_to_html

    html = line_plain_to_html(block)
    assert '黃金買點　<span class="stance">今天先看表，先等</span>' in html


def test_line_chip_wrap_keeps_lot_units():
    from line_share_format import format_line_stock_block

    block = format_line_stock_block(
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 1220,
            "foreign_net": 12500,
            "trust_net": 3200,
            "dealer_net": -800,
            "quote_date": "20260904",
            "profit": 29.1,
        },
        1,
    )
    assert "外資+12,500張" in block
    assert "投信+3,200張" in block
    assert "自營-800張" in block
    assert "投信+\n" not in block


def test_line_notice_wrap_keeps_industry_tag():
    """標記用全形空白切開，不要把「電子零組件」折成電／子。"""
    from line_share_format import format_line_stock_block

    block = format_line_stock_block(
        {
            "stock_id": "4915",
            "stock_name": "致伸",
            "close": 60.8,
            "pct_change": 2.01,
            "volume": 2126,
            "quote_date": "20260904",
            "profit": 2.4,
        },
        1,
        notice_fn=lambda _item: ["少追", "20低脫離", "剛輪到·電子零組件"],
    )
    assert "電子零組件" in block
    assert "剛輪到·電\n" not in block
    assert "　　　子零組件" not in block


def test_line_phone_bubble_width():
    from line_share_format import LINE_PHONE_LINE_MAX, format_line_stock_block

    block = format_line_stock_block(
        {
            "stock_id": "4915",
            "stock_name": "致伸",
            "close": 60.8,
            "pct_change": 2.01,
            "volume": 2126,
            "q60r": 1.35,
            "turnover_k": 128746.25,
            "ma20": 58.2,
            "ma60": 55.1,
            "foreign_net": 32,
            "trust_net": 73,
            "dealer_net": -119,
            "profit": 2.4,
            "quote_date": "20260904",
            "industry_plain": "電腦及週邊設備業。近期營收還可以，這一檔剛離低點。",
        },
        1,
    )
    for ln in block.split("\n"):
        if "http" in ln:
            continue
        assert len(ln) <= LINE_PHONE_LINE_MAX, ln
    assert "今天先看表，先等" in block
    assert "近一日　09-04" in block
    assert "外資+32張" in block
    assert "投信+73張" in block
    assert "自營-119張" in block
    assert "60日低上來" in block
    # 法人三欄各自成列，手機不會從張數中間折
    assert any(ln.strip() == "外資+32張" or ln.endswith("外資+32張") for ln in block.split("\n"))


def test_yahoo_hop_html_has_no_preview_card():
    from line_hop import render_yahoo_hop_html

    page = render_yahoo_hop_html("2330", "台積電")
    assert "og:image" not in page
    assert "location.replace" in page
    assert "tw.stock.yahoo.com/quote/2330.TW" in page
    assert "technical-analysis" not in page
    assert "http-equiv" not in page
    assert "正在開啟" in page


def test_yahoo_hop_4915_quote_not_chart_tab():
    from line_hop import render_yahoo_hop_html

    page = render_yahoo_hop_html("4915", "致伸")
    assert "4915.TW" in page
    assert "technical-analysis" not in page


@pytest.mark.production_db
def test_yahoo_hop_otc_uses_two_suffix():
    from line_hop import render_yahoo_hop_html
    from tests.conftest import require_production_db

    page = render_yahoo_hop_html("6488", db_path=require_production_db())
    assert "6488.TWO" in page
    assert "technical-analysis" not in page
    assert "location.replace" in page
