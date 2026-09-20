# -*- coding: utf-8 -*-
"""產品已拿掉傳給 LINE：中轉頁、按鈕、幫助文都不該再出現。"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_http_server_has_no_line_share_routes():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'startswith("/line")' not in src
    assert "render_line_redirect_html" not in src
    assert "render_line_rich_share_html" not in src
    assert not (ROOT / "line_hop.py").exists()
    assert not (ROOT / "line_rich_pack.py").exists()


def test_bot_has_no_line_share_buttons_or_copy():
    src = (ROOT / "bot_servers.py").read_text(encoding="utf-8")
    assert "開 LINE" not in src
    assert "一鍵傳 LINE" not in src
    assert "傳這檔" not in src
    assert "選聯絡人" not in src
    assert "_send_line_rich_bucket" not in src
    assert "_reply_line_share" not in src
    from bot_servers import HELP_TOPICS

    blob = "\n".join(HELP_TOPICS.values())
    assert "開 LINE" not in blob
    assert "一鍵傳 LINE" not in blob
    assert "轉 LINE" not in blob
    assert HELP_TOPICS == {}


def test_screening_html_has_no_line_stock_link():
    from screening_engine import _stock_card_html

    html = _stock_card_html(
        {"stock_id": "2330", "stock_name": "台積電", "close": 100, "volume": 1},
        1,
    )
    assert "開 LINE" not in html
    assert "/line/" not in html


def test_line_messenger_persist_and_stickers_are_gone():
    import screen_sessions
    import screening_engine
    import telegram_cat_marks
    from bot_servers import WayneTelegramBot

    for name in (
        "save_line_share",
        "load_line_share",
        "save_line_packs",
        "load_line_pack",
        "save_line_stocks",
        "load_line_stock",
        "upsert_line_pack",
        "upsert_line_stocks",
        "save_bucket_rich_manifest",
        "load_bucket_rich_manifest",
    ):
        assert not hasattr(screen_sessions, name), name
    assert not hasattr(screening_engine, "build_line_bucket_packs")
    assert not hasattr(screening_engine, "build_line_stock_bodies")
    assert not hasattr(telegram_cat_marks, "load_sticker_ids")
    assert not (ROOT / "telegram_cat_sticker_ids.json").exists()
    assert not hasattr(WayneTelegramBot, "_persist_bucket_line_pack")
    assert not hasattr(WayneTelegramBot, "_cat_sticker_id")
    assert not hasattr(WayneTelegramBot, "_track_line_pack_status")
    src = (ROOT / "screening_engine.py").read_text(encoding="utf-8")
    assert "傳到 LINE" not in src
    assert "傳 {label} 到 LINE" not in src
