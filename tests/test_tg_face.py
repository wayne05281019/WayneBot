# -*- coding: utf-8 -*-
"""資金氣泡那套藍連結／黑內文／橘數字，套到股名與大盤數字。"""
from __future__ import annotations

from money_flow import _flow_stock_lines
from stock_links import NAMED_URLS, TWII_QUOTE_URL, TX_NIGHT_URL, html_index_anchor, html_named, html_tx_anchor
from tg_layout import html_face, html_href, html_listing_suffix, html_move


def test_html_face_is_telegram_code():
    assert html_face("+1.8%") == "<code>+1.8%</code>"
    assert html_face("龍頭") == "<code>龍頭</code>"


def test_html_listing_suffix_oranges_leader_keeps_listing_black():
    s = html_listing_suffix("上市 成熟製程　龍頭")
    assert s.startswith("　上市 成熟製程")
    assert s.endswith("<code>龍頭</code>")
    assert "<code>上市" not in s
    plain = html_listing_suffix("上市 成熟製程")
    assert plain == "　上市 成熟製程"
    assert "<code>" not in plain


def test_html_move_uses_code_not_bold():
    down = html_move(-5.50, -3.05)
    assert down.startswith("<code>")
    assert "<b>" not in down
    assert "▼" in down and "-3.05%" in down


def test_named_market_links():
    twii = html_index_anchor("加權指數")
    assert TWII_QUOTE_URL in twii
    assert ">加權指數</a>" in twii
    night = html_tx_anchor("夜盤", night=True)
    assert TX_NIGHT_URL in night
    assert ">夜盤</a>" in night
    assert html_named("那斯達克").startswith("<a href=")
    assert "%5EIXIC" in html_named("那斯達克")
    assert html_named("沒這名") == "沒這名"
    assert NAMED_URLS["加權指數"].endswith("%5ETWII")
    assert html_href("https://example.com/x", "夜盤") == '<a href="https://example.com/x">夜盤</a>'


def test_flow_stock_lines_no_blank_separators():
    bits = _flow_stock_lines(["1. a", "2. b"])
    assert bits == ["1. a", "2. b"]
    assert "" not in bits
