# -*- coding: utf-8 -*-
"""介紹圖兩張版、興櫃不印假法人+0、山太士圖下四顆一排。"""
from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile

import pytest

from bot_servers import HELP_TOPICS, WayneTelegramBot
from wayne_db import ensure_core_schema, payload_is_emerging


def test_payload_is_emerging_covers_universe_and_source():
    assert payload_is_emerging({"universe": "EM"})
    assert payload_is_emerging({"market": "興櫃"})
    assert payload_is_emerging({"quote_source": "emerging_quotes"})
    assert not payload_is_emerging({"market": "TW"})


def test_emerging_screen_card_omits_fake_chip_zeros():
    from screening_engine import _stock_card_html

    html = _stock_card_html(
        {
            "stock_id": "3595",
            "stock_name": "山太士",
            "universe": "EM",
            "close": 12.3,
            "volume": 88,
            "q60r": 1.35,
            "pct_change": 1.2,
            "foreign_net": 0,
            "trust_net": 0,
            "dealer_net": 0,
        },
        1,
        show_line_link=False,
    )
    assert "量能" in html
    assert "量比" in html
    assert "法人" not in html
    assert "外資+0" not in html


def test_line_block_omits_emerging_chips():
    from line_share_format import format_line_stock_block

    block = format_line_stock_block(
        {
            "stock_id": "3595",
            "stock_name": "山太士",
            "universe": "EM",
            "close": 12.3,
            "volume": 88,
            "q60r": 1.35,
            "pct_change": 1.2,
            "foreign_net": 0,
            "trust_net": 0,
            "dealer_net": 0,
        },
        1,
    )
    assert "法人" not in block
    assert "外資+0" not in block
    assert "量比" in block


def test_chip_tape_reads_emerging_quotes_not_listed_collision(tmp_path):
    from chip_tape import build_tape, last_complete_chip_nets
    from emerging_quotes import ensure_emerging_table, upsert_emerging_rows

    path = str(tmp_path / "t.db")
    ensure_core_schema(path)
    ensure_emerging_table(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?, '', 1, 't')",
        ("3595", "山太士", "EM", "STOCK"),
    )
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260908", "3595", "撞號", "TW", 99, 99, 99, 99, 1, 1, 0, 99, 775, 0, 0),
    )
    conn.commit()
    conn.close()
    for i, vol in enumerate([10, 12, 11, 13, 20, 18, 22, 30], start=1):
        d = f"202608{i:02d}"
        upsert_emerging_rows(
            path,
            d,
            [
                {
                    "stock_id": "3595",
                    "stock_name": "山太士",
                    "market": "EM",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5 + i * 0.1,
                    "volume": vol,
                    "turnover_k": vol * 10,
                    "pct_change": 1.0,
                    "avg_price": 10.5,
                    "source": "tpex_esb_csv",
                }
            ],
        )
    tape = build_tape(path, "3595", merge_live=False) or {}
    assert tape.get("emerging") is True
    assert tape.get("has_chips") is False
    assert tape.get("volume", {}).get("line")
    assert last_complete_chip_nets(path, "3595") is None
    assert abs(float(tape["last"]["volume"]) - 30) < 1e-6


def test_em_hub_has_kline_and_nav():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._hub_keyboard("3595", em=True)
    assert len(kb.inline_keyboard) == 2
    labels0 = [b.text for b in kb.inline_keyboard[0]]
    labels1 = [b.text for b in kb.inline_keyboard[1]]
    assert "導航圖" in labels0
    assert "產業" in labels0
    assert labels1 == ["觀察", "記買入", "說明"]


def test_listed_hub_has_nav_button():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._hub_keyboard("2330")
    labels = [b.text for r in kb.inline_keyboard for b in r]
    assert "導航圖" in labels
    nav = next(b for r in kb.inline_keyboard for b in r if b.text == "導航圖")
    assert nav.callback_data is None
    assert (nav.url or "").endswith("/k/2330?n=180")
    assert all(len(r) <= 3 for r in kb.inline_keyboard)


def test_lookup_album_has_no_lecture_caption():
    src = inspect.getsource(WayneTelegramBot._send_lookup_album)
    assert "介紹／決策／導航" not in src
    assert "點任一張縮圖放大" not in src
    locked = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "點縮圖可放大" not in locked
    assert "網頁走勢" not in locked
    assert 'kind_labels = {"glance": "介紹圖", "card": "決策卡"}' in locked
    hub = inspect.getsource(WayneTelegramBot._hub_keyboard)
    assert 'callback_data=f"g:{c}"' in hub


def test_help_says_two_images():
    guide = HELP_TOPICS["guide"]
    assert "一次出兩張圖" in guide
    assert "一次出三張圖" not in guide
    assert "導航圖" in HELP_TOPICS["stock"]
    assert "上半資訊" in guide
    assert "下半180日高低導航" in guide
    assert "下半日K" not in guide
    blob = "\n".join(HELP_TOPICS[k] for k in ("guide", "pick", "stock", "portfolio", "ai", "streak"))
    assert "介紹圖／決策卡／導航圖" not in blob
    assert "一次出三張圖" not in blob


def test_glance_combo_canvas_matches_card_width():
    from wayne_navigator import (
        CARD_FIG_W,
        CARD_PNG_DPI,
        GLANCE_FIG_H,
        GLANCE_FIG_W,
        GLANCE_PNG_DPI,
        _paint_nav_on_axes,
        render_first_glance_png,
    )

    assert GLANCE_FIG_W == CARD_FIG_W
    assert GLANCE_PNG_DPI == CARD_PNG_DPI
    assert GLANCE_FIG_H < 16
    src = inspect.getsource(render_first_glance_png)
    assert "_paint_nav_on_axes" in src
    assert "compact=True" in src
    assert "_draw_glance_daily_k" not in src
    assert "_draw_mini_candle" not in src
    assert "_pack_badge_rows" in src
    assert "limit = 58.0" not in src
    assert "has_chips" in src
    assert "horizon_low_cells" in src
    assert 'card.get("dist_l480")' not in src
    assert "height_ratios=(5.15, 0.95, 1.55)" in src
    assert "_glance_kv_pill" in src
    from wayne_navigator import _paint_close_right

    close_src = inspect.getsource(_paint_close_right)
    assert "price_h * 0.24" in close_src
    assert "price_h * 0.46" not in close_src
    assert "_price_badge_row_y" in src
    from wayne_navigator import _price_badge_row_y

    by = _price_badge_row_y(1.0, 0, 3.05, 0.95)
    assert abs(by - (1.0 + 1.35)) < 1e-9
    by1 = _price_badge_row_y(1.0, 1, 3.05, 0.95)
    assert by1 > by
    from wayne_navigator import _pack_badge_rows

    four = [("a", 12.0), ("b", 12.0), ("c", 12.0), ("d", 12.0)]
    packed = _pack_badge_rows(four)
    assert [len(r) for r in packed] == [2, 2]
    assert [b for b, _w in packed[1]] == ["a", "b"]
    assert [b for b, _w in packed[0]] == ["c", "d"]
    one = _pack_badge_rows([("只一顆", 14.0)])
    assert len(one) == 1 and len(one[0]) == 1
    from wayne_navigator import render_decision_card_png

    assert "_price_badge_row_y" in inspect.getsource(render_decision_card_png)
    src_nav = inspect.getsource(_paint_nav_on_axes)
    assert 'ax_sig.set_ylabel("")' in src_nav
    assert "labelbottom=False" in src_nav
    from wayne_navigator import _CARD, _glance_kv_pill, _profit_heat_draw, _wcag

    bg, fg = _glance_kv_pill(*_profit_heat_draw(0.0, None, _CARD["white"]))
    assert bg == _CARD["pill_lo"]
    assert fg == _CARD["white"]
    assert _wcag(fg, bg) >= 4.5


def test_vol_rank_lr_lines_splits_window():
    from wayne_navigator import _vol_rank_lr_lines

    assert _vol_rank_lr_lines("120日第 103 名") == ("第 103 名", "120日")
    assert _vol_rank_lr_lines("60日第7 · 120日第25") == ("60日第7", "120日第25")
    assert _vol_rank_lr_lines("—") == ("—", None)


def test_fmt_dist_omits_nan():
    from wayne_navigator import _fmt_dist, _fmt_dist_short, horizon_low_cells

    assert "nan" not in _fmt_dist(float("nan")).lower()
    assert "nan" not in _fmt_dist_short(float("nan")).lower()
    cells = horizon_low_cells(
        {
            "l120": 1256.63,
            "dist_l120": 24.5,
            "l240": 1256.63,
            "dist_l240": 24.5,
            "l480": float("nan"),
            "dist_l480": float("nan"),
        }
    )
    assert [c[0] for c in cells] == ["120低", "240低"]


def test_emerging_snapshot_refuses_fake_chip_streaks():
    from buy_streak import MARKET_EM, load_snapshot

    with pytest.raises(ValueError, match="no official chip"):
        load_snapshot(":memory:", "foreign", MARKET_EM)


def test_streak_start_goes_to_listed_kind():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._actor_key = MagicMock(return_value="1:1")
    msg = MagicMock()
    msg.reply_html = AsyncMock()

    asyncio.run(bot._start_buy_streak(msg, "1"))
    assert bot._pending["1:1"] == "fbuy:kind:ALL"
    html = msg.reply_html.await_args.args[0]
    assert "外資" in html and "投信" in html
    assert "先選" not in html or "興櫃沒有" in html
    markup = msg.reply_html.await_args.kwargs["reply_markup"]
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert labels[:3] == ["外資", "投信", "外資+投信"]
    assert "興櫃" not in labels
    assert not getattr(markup, "keyboard", None)
    assert msg.reply_html.await_count == 1
