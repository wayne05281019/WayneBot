# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone

from stock_news import count_windows, news_label, news_search_url, parse_rss_pubdates


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>A</title><pubDate>Mon, 07 Sep 2026 10:00:00 +0800</pubDate></item>
<item><title>B</title><pubDate>Mon, 01 Sep 2026 10:00:00 +0800</pubDate></item>
<item><title>C</title><pubDate>Mon, 25 Aug 2026 10:00:00 +0800</pubDate></item>
</channel></rss>"""


def test_parse_rss_and_windows():
    dates = parse_rss_pubdates(RSS)
    assert len(dates) == 3
    now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    recent, prev = count_windows(dates, now=now)
    assert recent == 1
    assert prev == 1


def test_news_label_arrows_and_omit_zero():
    assert news_label(0, 0) == ""
    assert news_label(12, 4) == "報導12↑"
    assert news_label(2, 10) == "報導2↓"
    assert news_label(5, 5) == "報導5"
    assert "2330" in news_search_url("2330", "台積電")
    assert "news.google.com" in news_search_url("2330", "台積電")
