"""主題鏈加層樣張：★只認 TAUGHT_GROUPS；底標與主題鏈並存。"""
from __future__ import annotations

from theme_chain_preview import (
    Quote,
    build_lookup_layer_html,
    build_panorama_page04_html,
    is_taught,
)


def test_3017_is_taught_cooling():
    assert is_taught("3017")
    assert not is_taught("8996")  # 高力不在 TAUGHT_GROUPS
    assert not is_taught("9958")  # 世紀鋼不在 → 全景不准發明★


def test_lookup_layer_shows_base_and_theme():
    q = Quote(
        sid="3017",
        name="奇鋐",
        close=2365.0,
        change=160.0,
        pct=7.26,
        volume_shares=6_995_270,
        market="TW",
        source="twse:MI_INDEX",
    )
    html = build_lookup_layer_html(
        sid="3017",
        as_of="2026-11-23",
        quote=q,
        base_chain="電子中游-NB與手機零組件",
    )
    assert "電子中游" in html
    assert "NB與手機零組件" in html
    assert "主題鏈：散熱（已教過★）" in html
    assert "2,365.00" in html or "2365.00" in html
    assert "加層" in html
    assert "底標" in html


def test_panorama_star_only_taught():
    quotes = {
        "3017": Quote("3017", "奇鋐", 2365.0, 160.0, 7.26, 1000, "TW", "twse"),
        "3653": Quote("3653", "健策", 3685.0, -20.0, -0.54, 1000, "TW", "twse"),
        "8996": Quote("8996", "高力", 858.0, -65.0, -7.04, 1000, "TW", "twse"),
        "9958": Quote("9958", "世紀鋼", 52.0, -1.7, -3.17, 1000, "TW", "twse"),
        "2404": Quote("2404", "漢唐", 851.0, 34.0, 4.16, 1000, "TW", "twse"),
        "1519": Quote("1519", "華城", 425.0, 3.5, 0.83, 1000, "TW", "twse"),
    }
    html = build_panorama_page04_html("2026-11-23", quotes)
    assert 'class="star">★</span> <span class="name">奇鋐</span>' in html
    assert "世紀鋼" in html
    assert 'class="star">★</span> <span class="name">世紀鋼</span>' not in html
    assert "高力" in html
    assert 'class="star">★</span> <span class="name">高力</span>' not in html
    assert "樣張預覽" in html
    assert "加層不換底" in html
