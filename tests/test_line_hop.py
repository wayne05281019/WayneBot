def test_line_hop_url_uses_server_hop():
    from line_hop import line_hop_url

    assert line_hop_url("leave_zero", "https://example.com") == "https://example.com/line/leave_zero"


def test_render_line_redirect_html_opens_line_app_on_mobile():
    from line_hop import render_line_redirect_html

    page = render_line_redirect_html("WayneBot 測試\n1. 台積電 (2330)")
    assert "line://msg/text/" in page
    assert "line.me/R/share" in page
    assert "開啟 LINE App" in page
    assert "mobile" in page


def test_render_line_hop_html_compat():
    from line_hop import render_line_hop_html

    page = render_line_hop_html("開 LINE・起漲", "測試內容")
    assert "line://msg/text/" in page


def test_long_line_share_uses_clipboard_not_url():
    from line_hop import render_line_redirect_html

    long_body = "WayneBot 海選\n" + ("1. 測試 (2330)\n" * 80)
    page = render_line_redirect_html(long_body)
    assert "複製文字並開 LINE" in page
    assert "navigator.share" in page
    assert "shareLong" in page
    assert 'href="line://' not in page
