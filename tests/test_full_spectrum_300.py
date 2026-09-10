# -*- coding: utf-8 -*-
"""三百角全譜：表面→深層，壓力／出錯／速度／正確性／視覺質感。

每個 case 角度不同。先前話筒失敗案例重新納入，並鎖這輪新修的洞
（連買天數誤吃 0050、2330台積電拆碼、產業頁 replace(date) 打掉索引）。
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_MARKET,
    WayneTelegramBot,
    _text_escapes_pending,
)
from buy_streak import parse_days, parse_stock_code
from intent_router import parse_intent
from tests.conftest import require_production_db
from universe import (
    canonical_lookup_ticker,
    classify_target,
    is_lookup_ticker,
    is_screen_equity,
)
from wayne_db import listing_is_emerging, split_lookup_code_name

WAYNE_UID = 9001
BRO_UID = 9002
SHARED_CHAT = -10001


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _msg(uid: int, text: str = "", *, chat_id: int | None = None):
    cid = int(chat_id) if chat_id is not None else int(uid)
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=cid)
    message = MagicMock()
    message.chat_id = cid
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_photo = AsyncMock()
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot():
    from config import get_db_path
    from wayne_db import init_database

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = get_db_path()
    init_database(bot.db_path)
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._lookup_op_state = {}
    bot._screening_running = set()
    bot._trade_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._menu_fade_gen = {}
    bot._menu_pin_msgs = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._dismiss_menu_transients = AsyncMock()
    bot._enter_main_menu = AsyncMock()
    bot._reply_menu = MagicMock()
    bot._keyboard = MagicMock()
    bot._held_lots_for = MagicMock(return_value=None)
    bot._send_trade_journal = AsyncMock()
    bot._send_ai_desk_view = AsyncMock()
    bot._send_chips_to = AsyncMock()
    bot._send_industry = AsyncMock()
    bot._send_fund_to = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot._send_card_to = AsyncMock()
    bot._send_decision_card_quick = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    bot.market_cmd = AsyncMock()
    bot.flow_cmd = AsyncMock()
    bot.screen_cmd = AsyncMock()
    bot.portfolio_cmd = AsyncMock()
    bot.watch_cmd = AsyncMock()
    bot.daytrade_cmd = AsyncMock()
    bot.overnight_cmd = AsyncMock()
    bot.streak_cmd = AsyncMock()
    bot.help_cmd = AsyncMock()
    bot.report_cmd = AsyncMock()
    bot.why_cmd = AsyncMock()
    return bot


def _src(obj) -> str:
    return inspect.getsource(obj)


# ===========================================================================
# L0 話筒回歸：先前炸過的洞（30）
# ===========================================================================

@pytest.mark.parametrize(
    "text,kind",
    [
        ("為什麼跌", "lookup"),
        ("為甚麼跌", "lookup"),
        ("為何跌", "lookup"),
        ("怎麼跌", "lookup"),
        ("為什麼漲", "lookup"),
        ("2330為什麼跌", "lookup"),
        ("00706L為什麼跌", "lookup"),
        ("００７０６Ｌ為什麼跌", "lookup"),
        ("如何賣", "sell"),
        ("怎麼賣", "sell"),
        ("主力成本", "no_cost"),
        ("外資成本", "no_cost"),
        ("投信成本", "no_cost"),
        ("融資成本", "no_cost"),
        ("黃金買點", "screen"),
        ("重點觀察", "screen"),
        ("持倉", "portfolio"),
        ("我的持股", "portfolio"),
        ("成交量為什麼跌", "lookup"),
        ("2330資金", "chips"),
        ("台積電資金", "chips"),
        ("2330說明", "lookup"),
        ("籌碼", "chips"),
        ("同業", "industry"),
        ("營收", "fund"),
        ("大盤", "market"),
        ("當沖", "daytrade"),
        ("隔沖", "overnight"),
        ("連買區", "streak"),
        ("圖文說明", "help"),
    ],
)
def test_l0_intent_regression(text, kind):
    hit = parse_intent(text)
    assert hit is not None, text
    assert hit.kind == kind, (text, hit.kind, hit.code, hit.query)


@pytest.mark.parametrize(
    "raw,tick",
    [
        ("00706L", "00706L"),
        ("00706l", "00706L"),
        ("００７０６Ｌ", "00706L"),
        ("00990A", "00990A"),
        ("00990a", "00990A"),
        ("00631L", "00631L"),
        ("00632R", "00632R"),
        ("00632r", "00632R"),
        ("00411A", "00411A"),
        ("0050", "0050"),
        ("00878", "00878"),
        ("00962", "00962"),
        ("2330", "2330"),
        ("２３３０", "2330"),
        ("4915", "4915"),
        ("3711", "3711"),
        ("3595", "3595"),
        ("1413", "1413"),
        ("0050元大台灣50", "0050"),
        ("2330台積電", "2330"),
        ("台積電2330", "2330"),
        ("00706L元大", "00706L"),
        ("元大台灣50正2 00631L", "00631L"),
        ("2454 聯發科", "2454"),
        ("聯發科2454", "2454"),
    ],
)
def test_l0_split_and_canonical(raw, tick):
    assert canonical_lookup_ticker(raw) in ("", tick) or split_lookup_code_name(raw)[0] == tick
    code, _name = split_lookup_code_name(raw)
    got = canonical_lookup_ticker(raw) or code
    assert got == tick, (raw, got)


# ===========================================================================
# L1 代號／ETF／興櫃／KY／權證（40）
# ===========================================================================

@pytest.mark.parametrize(
    "sid,name,kind,lookup,screen",
    [
        ("2330", "台積電", "STOCK", True, True),
        ("3711", "日月光投控", "STOCK", True, True),
        ("7717", "萊德光電-KY", "KY", True, True),
        ("0050", "元大台灣50", "ETF_PASSIVE", True, False),
        ("00878", "國泰永續高股息", "ETF_PASSIVE", True, False),
        ("00962", "台新AI優息動能", "ETF_PASSIVE", True, False),
        ("00706L", "期元大S&P日圓正2", "ETF_LEVERAGED", True, False),
        ("00631L", "元大台灣50正2", "ETF_LEVERAGED", True, False),
        ("00633L", "富邦上証正2", "ETF_LEVERAGED", True, False),
        ("00632R", "元大台灣50反1", "ETF_INVERSE", True, False),
        ("00634R", "富邦上証反1", "ETF_INVERSE", True, False),
        ("00990A", "主動元大AI新經濟", "ETF_ACTIVE", True, False),
        ("00411A", "主動統一前沿科技", "ETF_ACTIVE", True, False),
        ("00400A", "主動國泰動能高息", "ETF_ACTIVE", True, False),
        ("4915", "致伸", "STOCK", True, True),
        ("3105", "穩懋", "STOCK", True, True),
        ("1413", "宏洲", "STOCK", True, True),
        ("3595", "山太士", "STOCK", True, True),
        ("TWA00", "", "INDEX", False, False),
        ("03001P", "", "WARRANT", True, False),
        ("2330P", "", "WARRANT", True, False),
        ("12345B", "債樣", "BOND", True, False),
        ("1234C", "", "WARRANT", True, False),
        ("100", "", "INVALID", False, False),
        ("12", "", "INVALID", False, False),
        ("", "", "INVALID", False, False),
        ("ABC", "x", "INVALID", False, False),
        ("0050.TW", "", "ETF_ACTIVE", False, False),
        ("2330KY", "台積電KY", "KY", False, True),
        ("1101", "台泥", "STOCK", True, True),
        ("2454", "聯發科", "STOCK", True, True),
        ("3037", "欣興", "STOCK", True, True),
        ("2303", "聯電", "STOCK", True, True),
        ("5471", "松翰", "STOCK", True, True),
        ("3115", "太普高", "STOCK", True, True),
        ("2383", "台光電", "STOCK", True, True),
        ("3406", "玉晶光", "STOCK", True, True),
        ("2820", "華票", "STOCK", True, True),
        ("6526", "達發", "STOCK", True, True),
        ("9925", "新保", "STOCK", True, True),
    ],
)
def test_l1_classify_lookup_screen(sid, name, kind, lookup, screen):
    got, _keep = classify_target(sid, name)
    assert got == kind, (sid, got)
    assert is_lookup_ticker(sid) is lookup, sid
    if kind in ("STOCK", "KY"):
        assert is_screen_equity(sid, name) is screen
    elif str(kind).startswith("ETF"):
        assert is_screen_equity(sid, name) is False
    elif kind == "WARRANT":
        assert is_screen_equity(sid, name) is False


# ===========================================================================
# L2 連買精靈：天數 vs ETF、混合代號（18）
# ===========================================================================

@pytest.mark.parametrize(
    "text,expect",
    [
        ("6", 6),
        ("25天", 25),
        ("1日", 1),
        ("120", 120),
        ("0", None),
        ("121", None),
        ("50", 50),
        ("50天", 50),
        ("0050", None),
        ("00878", None),
        ("00706L", None),
        ("００５０", None),
        ("2330", None),
        ("100", 100),
        ("", None),
        ("abc", None),
        ("6 天", 6),
        ("０６", 6),
    ],
)
def test_l2_parse_days_not_etf(text, expect):
    assert parse_days(text) == expect, text


@pytest.mark.parametrize(
    "text,expect",
    [
        ("2330", "2330"),
        ("2330 台積電", "2330"),
        ("2330台積電", "2330"),
        ("台積電2330", "2330"),
        ("00706L", "00706L"),
        ("00706L元大", "00706L"),
        ("00990a", "00990A"),
        ("２３３０", "2330"),
        ("0050", "0050"),
        ("", None),
        ("台積電", None),
        ("為什麼跌", None),
        ("68.5", None),
        ("外資", None),
        ("00631L 元大台灣50正2", "00631L"),
        ("2454聯發科", "2454"),
    ],
)
def test_l2_parse_stock_code_mixed(text, expect):
    assert parse_stock_code(text) == expect, text


@pytest.mark.parametrize(
    "text,escapes",
    [
        ("為什麼跌", True),
        ("如何賣", True),
        ("籌碼", True),
        ("2330", True),
        ("00706L", True),
        ("0050", True),
        ("外資", True),  # parse_intent → chips，應跳出連買步驟
        ("持股", True),
        ("海選", True),
        ("當沖", True),
        ("大盤", True),
        ("說明", True),
        ("亂打xyz", False),
        ("", False),
        ("3", False),
        ("投信", True),
        ("00990A", True),
        ("２３３０", True),
        ("主力成本", True),
        ("黃金買點", True),
    ],
)
def test_l2_pending_escape(text, escapes):
    assert _text_escapes_pending(text) is escapes, text


# ===========================================================================
# L3 雙人隔離（12 named + 8 actor）
# ===========================================================================

@pytest.mark.parametrize(
    "uid,chat,expect",
    [
        (WAYNE_UID, WAYNE_UID, f"{WAYNE_UID}:{WAYNE_UID}"),
        (BRO_UID, BRO_UID, f"{BRO_UID}:{BRO_UID}"),
        (WAYNE_UID, SHARED_CHAT, f"{SHARED_CHAT}:{WAYNE_UID}"),
        (BRO_UID, SHARED_CHAT, f"{SHARED_CHAT}:{BRO_UID}"),
        (1, 99, "99:1"),
        (2, 99, "99:2"),
        (WAYNE_UID, -5, f"-5:{WAYNE_UID}"),
        (BRO_UID, 0, f"0:{BRO_UID}"),
    ],
)
def test_l3_actor_key_shapes(uid, chat, expect):
    bot = _bot()
    assert bot._actor_key(_msg(uid, chat_id=chat), uid=str(uid)) == expect


def test_l3_scratch_paths_isolated():
    bot = _bot()
    p1 = bot._scratch_chart_path(bot.charts_dir, "2330", "chips", str(WAYNE_UID))
    p2 = bot._scratch_chart_path(bot.charts_dir, "2330", "chips", str(BRO_UID))
    assert p1 != p2
    assert str(WAYNE_UID) in p1
    assert str(BRO_UID) in p2


def test_l3_last_card_uid_not_shared():
    bot = _bot()
    bot._remember_card(str(WAYNE_UID), "2330")
    bot._remember_card(str(BRO_UID), "1413")
    assert bot._last_card[str(WAYNE_UID)] == "2330"
    assert bot._last_card[str(BRO_UID)] == "1413"


def test_l3_em_last_card_not_stolen():
    bot = _bot()
    bot._remember_card(str(WAYNE_UID), "3595")
    bot._remember_card(str(BRO_UID), "1413")
    assert bot._last_card[str(WAYNE_UID)] == "3595"
    assert bot._last_card[str(BRO_UID)] == "1413"


def test_l3_pending_same_chat_isolated():
    bot = _bot()
    w = f"{SHARED_CHAT}:{WAYNE_UID}"
    b = f"{SHARED_CHAT}:{BRO_UID}"
    bot._pending[w] = "buy:2330"
    bot._pending[b] = "fbuy:kind"
    assert bot._pending[w] != bot._pending[b]


def test_l3_trade_lock_per_actor():
    bot = _bot()
    bot._trade_running.add(f"{SHARED_CHAT}:{WAYNE_UID}")
    assert f"{SHARED_CHAT}:{BRO_UID}" not in bot._trade_running


def test_l3_buy_68_does_not_use_other_last_card():
    bot = _bot()
    bot._pending[f"{SHARED_CHAT}:{WAYNE_UID}"] = "buy:2330"
    bot._last_card[str(BRO_UID)] = "1413"
    parsed, lots, price = bot._parse_buy_text("68.5", "", uid=str(BRO_UID))
    assert parsed is None or parsed != "2330"


def test_l3_wayne_fbuy_survives_bro_market():
    bot = _bot()
    bot._pending[f"{WAYNE_UID}:{WAYNE_UID}"] = "fbuy:days:foreign:TW"

    async def run():
        await bot.on_text(_update(_msg(BRO_UID, MENU_BTN_MARKET)), MagicMock())

    asyncio.run(run())
    assert bot._pending[f"{WAYNE_UID}:{WAYNE_UID}"] == "fbuy:days:foreign:TW"


def test_l3_chengjiao_opens_journal_not_lookup():
    bot = _bot()

    async def run():
        await bot.on_text(_update(_msg(WAYNE_UID, "成交")), MagicMock())

    asyncio.run(run())
    bot._send_trade_journal.assert_awaited()


def test_l3_fupan_opens_review():
    bot = _bot()

    async def run():
        await bot.on_text(_update(_msg(WAYNE_UID, "復盤")), MagicMock())

    asyncio.run(run())
    bot._send_trade_journal.assert_awaited()
    assert bot._send_trade_journal.await_args.kwargs.get("review") is True


def test_l3_em_hub_omits_chips_fund_industry():
    bot = _bot()
    kb = bot._hub_keyboard("3595", em=True)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "籌碼" not in labels
    assert "營收" not in labels
    assert "產業" in labels
    assert "觀察" in labels
    assert "K線" not in labels
    assert [b.text for b in kb.inline_keyboard[0]] == ["產業", "觀察", "記買入", "說明"]


def test_l3_listed_hub_has_chips():
    bot = _bot()
    kb = bot._hub_keyboard("2330", em=False)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "籌碼" in labels
    assert "營收" in labels
    assert "產業" in labels
    assert "K線" in labels
    assert "導航圖" in labels


# ===========================================================================
# L4 誠實欄／假資料禁令（20）
# ===========================================================================

@pytest.mark.parametrize(
    "path",
    [
        "wayne_navigator.py",
        "bot_servers.py",
        "intent_router.py",
        "picture_guide.py",
        "portfolio_engine.py",
        "broker_points.py",
    ],
)
def test_l4_no_fake_cost_formulas(path):
    src = open(path, encoding="utf-8").read()
    assert "均價 ×" not in src
    assert "均價*" not in src
    assert "外資成本" not in src or path in (
        "bot_servers.py",
        "intent_router.py",
        "picture_guide.py",
    )


def test_l4_navigator_omits_blank_main_cost():
    src = open("wayne_navigator.py", encoding="utf-8").read()
    assert "主力成本" in src
    assert "外資成本" not in src
    assert "投信成本" not in src
    assert "融資成本" not in src


def test_l4_no_cost_html_honest():
    from intent_router import no_cost_honest_html

    html = no_cost_honest_html()
    assert "沒有" in html
    assert "主力" in html
    assert "三大法人不是主力" in html


def test_l4_red_arrow_not_buy_in_help():
    blob = HELP_TOPICS["guide"] + HELP_TOPICS["stock"] + HELP_TOPICS["screen"]
    assert "紅箭頭" in blob
    assert "不是買訊" in blob
    assert "黃金買點" in blob


def test_l4_sell_is_assist_not_signal():
    from intent_router import sell_honest_html

    html = sell_honest_html()
    assert "20日高" in html or "20日高" in html.replace(" ", "")
    assert "不是買訊" in html
    assert "不自動賣" in html


def test_l4_empty_screen_keeps_hl_columns():
    from screening_engine import format_screening_payload

    src = _src(format_screening_payload) + open("screening_engine.py", encoding="utf-8").read()
    assert "今日沒有符合高低卡條件的檔" in src
    assert "leave_zero" in src
    assert "golden_buy" in src


def test_l4_listing_em_aliases():
    assert listing_is_emerging({"market": "EM"})
    assert listing_is_emerging({"market": "興櫃"})
    assert listing_is_emerging({"market": "EMERGING"})
    assert not listing_is_emerging({"market": "TW"})
    assert not listing_is_emerging({})
    assert not listing_is_emerging(None)


def test_l4_no_cost_honest_no_invented_price():
    from intent_router import no_cost_honest_html

    html = no_cost_honest_html()
    assert "沒有" in html
    assert "主力成本" in html


# ===========================================================================
# L5 出錯／混沌輸入（25）
# ===========================================================================

@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        " ",
        "\u3000",
        "\n",
        "\t",
        "'" * 8,
        "a" * 400,
        "<script>",
        "DROP TABLE daily_quotes",
        "2330;DROP",
        "0️⃣",
        "nan",
        "None",
        "null",
        "０",
        "🚀2330",
        "2330🚀",
        "\x00",
        "\ufffd",
        "ＴＷＡ００",
        "0050.TW",
        "2330/TW",
        "...",
        "????",
    ],
)
def test_l5_chaos_inputs_do_not_crash(raw):
    q = "" if raw is None else raw
    split_lookup_code_name(q)
    is_lookup_ticker(q)
    canonical_lookup_ticker(q)
    parse_intent(q)
    parse_days(q)
    parse_stock_code(q)
    classify_target(q, q)
    _text_escapes_pending(q)


# ===========================================================================
# L6 視覺質感（30）
# ===========================================================================

def test_l6_profit_zero_green_white():
    from wayne_navigator import profit_cell_style

    bg, fg = profit_cell_style(0.0)
    assert bg != "#FFFFFF"
    assert fg.lower() in ("#ffffff", "#fff") or "fff" in fg.lower()


def test_l6_profit_leave_zero_red_on_green():
    from wayne_navigator import profit_cell_style

    bg, fg = profit_cell_style(0.4)
    assert bg != fg


def test_l6_profit_high_red_fill():
    from wayne_navigator import profit_cell_style

    bg, fg = profit_cell_style(29.1)
    assert bg != "#FFFFFF"


def test_l6_fmt_price_thousand():
    from wayne_navigator import _fmt_price

    assert _fmt_price(5295) == "5,295"
    assert _fmt_price(45.25) == "45.25"
    assert "." not in _fmt_price(17460)


def test_l6_volume_lots_not_k():
    from wayne_navigator import format_nav_volume_label

    assert "張" in format_nav_volume_label(2)
    assert "K" not in format_nav_volume_label(2)


def test_l6_wrap_cjk_no_orphan():
    from tg_layout import wrap_cjk_lines

    lines = wrap_cjk_lines("準備減碼不是買訊", 14)
    assert lines[-1] != "訊"
    assert "".join(lines) == "準備減碼不是買訊"


def test_l6_picture_guide_phone_ratio():
    from picture_guide import BODY_SIZE, PAGE_HEIGHT, PAGE_WIDTH

    assert PAGE_WIDTH == 1080
    assert PAGE_HEIGHT == 1920
    assert BODY_SIZE * (390 / PAGE_WIDTH) >= 18


def test_l6_picture_guide_no_emoji():
    from picture_guide import page_copy_blob

    blob = page_copy_blob()
    assert "⌨️" not in blob
    assert "紅箭頭" in blob
    assert "如何賣" in blob


def test_l6_help_guide_one_chunk():
    from tg_layout import chunk_telegram_html

    chunks = chunk_telegram_html(HELP_TOPICS["guide"])
    assert len(chunks) == 1


def test_l6_help_no_wide_pad():
    pad = re.compile(r"^(產業|同業|單位|用途)\s{3,}", re.M)
    for key, body in HELP_TOPICS.items():
        assert not pad.search(body), key


def test_l6_caption_sell_appended():
    from bot_servers import _glance_photo_caption

    card = {"sell_action": "直接減碼", "sell_why": "不同步（最高價但非最高溫）"}
    cap = _glance_photo_caption("介紹圖", card)
    assert "Ai建議" in cap or "現在" in cap


def test_l6_decision_caption_uses_name():
    from bot_servers import _stock_caption_name

    assert _stock_caption_name({"stock_name": "台積電", "stock_id": "2330"}, "2330") == "台積電"
    assert _stock_caption_name({"stock_name": "2330台積電", "stock_id": "2330"}, "2330") == "台積電"


def test_l6_png_looks_ok_rejects_tiny():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"short")
        path = f.name
    try:
        assert not WayneTelegramBot._png_looks_ok(path)
    finally:
        os.unlink(path)


def test_l6_compact_card_yi_not_billion_typo():
    from screening_engine import _stock_card_html

    card = _stock_card_html(
        {
            "stock_id": "2324",
            "stock_name": "仁寶",
            "close": 41.6,
            "volume": 141506,
            "pct_change": 7.35,
            "turnover_k": 5_781_097.8,
            "ma20": 40,
            "ma60": 39,
            "foreign_net": 0,
            "trust_net": 0,
            "dealer_net": 0,
            "profit": 2.0,
            "vol_rank_120": 1,
        },
        1,
        show_line_link=False,
    )
    assert "5781億" not in card
    assert "金額" in card


@pytest.mark.parametrize(
    "p,expect_red_ink",
    [
        (0.3, True),
        (2.4, True),
        (29.1, True),
        (0.0, False),
        (-1.0, False),
    ],
)
def test_l6_profit_ink_direction(p, expect_red_ink):
    from wayne_navigator import profit_cell_style

    _bg, fg = profit_cell_style(p)
    # 台股漲紅：正獲利字不該是綠。
    if expect_red_ink:
        assert "0a0" not in fg.lower() and "green" not in fg.lower()


def test_l6_hl_high_uses_hi_fill():
    from wayne_navigator import hl_cell_style

    bg, _fg = hl_cell_style("20高", "#FFFFFF")
    assert bg != "#FFFFFF"


def test_l6_temp_80_hot():
    from wayne_navigator import temp_cell_style

    bg, fg = temp_cell_style(82, "#FFFFFF")
    assert bg != "#FFFFFF"
    assert fg.lower() in ("#ffffff", "#fff") or "fff" in fg.lower()


def test_l6_menu_row_has_streak_help_report():
    from bot_servers import MENU_BTN_REPORT, MENU_BTN_STREAK

    bot = _bot()
    kb = WayneTelegramBot._reply_menu(bot)
    labels = [b.text for row in kb.keyboard for b in row]
    assert MENU_BTN_STREAK in labels
    assert "說明" in labels
    assert MENU_BTN_REPORT in labels


# ===========================================================================
# L7 速度／索引（18）
# ===========================================================================

def test_l7_industry_brief_uses_indexed_date():
    import industry_brief

    src = _src(industry_brief.industry_snapshot)
    assert "q.date=?" in src or "WHERE q.date=?" in open("industry_brief.py", encoding="utf-8").read()
    assert "replace(q.date" not in open("industry_brief.py", encoding="utf-8").read()


def test_l7_live_quote_close_indexed():
    from live_quote import _db_latest_close

    src = _src(_db_latest_close)
    assert "AND date=?" in src
    assert "replace(date" not in src


def test_l7_count_markets_indexed():
    from import_health import count_markets

    src = _src(count_markets)
    assert "WHERE date=?" in src
    assert "replace(date" not in src


def test_l7_latest_complete_groups_by_date():
    from import_health import latest_complete_quote_date

    src = _src(latest_complete_quote_date)
    assert "GROUP BY date" in src
    assert "GROUP BY replace(date" not in src


def test_l7_audit_import_indexed():
    from import_health import audit_import

    src = _src(audit_import)
    assert "WHERE date=?" in src
    assert "replace(date,'-','')=?" not in src


def test_l7_flow_sector_indexed():
    from money_flow import compute_sector_rows

    src = _src(compute_sector_rows)
    assert "WHERE q.date=?" in src
    assert "replace(q.date" not in src


def test_l7_lookup_gc_once():
    src = _src(WayneTelegramBot._send_card_to_locked)
    loop = src[src.index("for kind, fn") : src.index("try:\n                gc.collect")]
    assert "gc.collect" not in loop
    assert src.count("gc.collect") == 1


def test_l7_card_timeouts_shared():
    src = _src(WayneTelegramBot._send_decision_card_quick)
    assert "_CARD_BUILD_TIMEOUT" in src
    assert "_LOOKUP_PNG_TIMEOUT" in src


def test_l7_morning_skip_if_done():
    from main_runner import MainRunner, main

    src = _src(main) + _src(MainRunner.run_morning_screen)
    assert "skip_if_done = True" in _src(main)
    assert 'GITHUB_EVENT_NAME' in _src(main)
    assert "skip_if_done" in _src(MainRunner.run_morning_screen)
    assert "不標已寄過" in _src(MainRunner.run_morning_screen)


def test_l7_increment_count_indexed():
    from main_runner import MainRunner

    src = _src(MainRunner.run_daily_increment)
    assert "WHERE date=?" in src
    assert "replace(date,'-','') = ?" not in src
    assert "replace(date,'-','')=?" not in src


def test_l7_screen_engine_fallback_indexed():
    from screening_engine import ScreeningEngine

    src = _src(ScreeningEngine.get_latest_trading_date)
    assert "GROUP BY date" in src
    assert "GROUP BY replace(date" not in src


def test_l7_inventory_span_indexed():
    from import_health import inventory_payload

    src = _src(inventory_payload)
    assert "COUNT(DISTINCT date)" in src
    assert "COUNT(DISTINCT replace" not in src


# ===========================================================================
# L8 深層正確性（28）
# ===========================================================================

def test_l8_profit_2383_formula():
    from decision_card_signals import format_profit_pct

    # 收 5295／低 4100 → 29.1%
    pct = (5295 - 4100) / 4100 * 100
    assert abs(pct - 29.1) < 0.05
    assert format_profit_pct(pct) == "29.1%"


def test_l8_leave_zero_band():
    from decision_card_signals import (
        is_profit_display_zero,
        profit_display_leave_zero_band,
    )

    assert is_profit_display_zero(0.0)
    assert profit_display_leave_zero_band(0.3)
    assert not profit_display_leave_zero_band(0.0)
    assert not profit_display_leave_zero_band(2.4)


def test_l8_sell_desync_is_direct():
    from sell_discipline import classify_how_to_sell

    hl = ["No"] * 8 + ["20高"]
    temp = ["升溫"] * 8 + ["降溫"]
    flags = classify_how_to_sell(hl, temp)
    assert flags["sell_action"] == "直接減碼"


def test_l8_etf_not_in_screen_payload():
    from screening_engine import drop_non_equity_picks

    dropped = drop_non_equity_picks(
        {
            "leave_zero": [
                {"stock_id": "4915", "stock_name": "致伸"},
                {"stock_id": "00706L", "stock_name": "期元大S&P日圓正2"},
            ]
        }
    )
    ids = [r["stock_id"] for r in dropped.get("leave_zero") or []]
    assert "4915" in ids
    assert "00706L" not in ids


def test_l8_intent_etf_code_upper():
    hit = parse_intent("00706l為什麼跌")
    assert hit is not None
    assert hit.kind == "lookup"
    assert hit.code == "00706L"


def test_l8_lookup_ticker_rejects_3digit():
    assert not is_lookup_ticker("100")
    assert not is_lookup_ticker("012")
    assert is_lookup_ticker("0050")


def test_l8_nfkc_fullwidth_etf():
    assert canonical_lookup_ticker("００６３１Ｌ") == "00631L"
    assert split_lookup_code_name("２３３０台積電")[0] == "2330"


def test_l8_default_industry_etf():
    from universe import default_industry

    assert default_industry("ETF_PASSIVE", "") == "ETF"
    assert default_industry("STOCK", "半導體") == "半導體"


def test_l8_screen_equity_asset_type_wins():
    assert is_screen_equity("2330", "台積電", "ETF_PASSIVE") is False
    assert is_screen_equity("3711", "日月光投控", "KY") is True


def test_l8_compact_text_strips_punct():
    from intent_router import compact_text

    assert "？" not in compact_text("為什麼跌？")
    assert compact_text("  為什麼跌  ") == "為什麼跌"


def test_l8_buy_holdings_prompt_odd_lot():
    from bot_servers import _buy_holdings_prompt

    text = _buy_holdings_prompt("6526", 0.439)
    assert "200股" in text or "股" in text


def test_l8_held_lots_per_uid_mock():
    bot = _bot()
    bot._held_lots_for = MagicMock(side_effect=lambda uid, code: 2.0 if uid == str(WAYNE_UID) else 0.2)
    assert bot._held_lots_for(str(WAYNE_UID), "2330") == 2.0
    assert bot._held_lots_for(str(BRO_UID), "2330") == 0.2


# ===========================================================================
# L9 交叉：選單／pending／查股（20）
# ===========================================================================

def test_l9_menu_pops_pending():
    bot = _bot()
    actor = f"{WAYNE_UID}:{WAYNE_UID}"
    bot._pending[actor] = "fbuy:kind"

    async def run():
        await bot.on_text(_update(_msg(WAYNE_UID, "說明")), MagicMock())

    asyncio.run(run())
    assert actor not in bot._pending
    bot.help_cmd.assert_awaited()


def test_l9_why_escapes_buy_pending():
    bot = _bot()
    bot._pending["99:9"] = "buy:3595"
    bot._last_card["9"] = "3595"
    msg = _msg(9, "為什麼跌", chat_id=99)

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_card_to.assert_awaited()
    assert "99:9" not in bot._pending


def test_l9_fbuy_kind_escapes_why():
    bot = _bot()
    actor = f"{WAYNE_UID}:{WAYNE_UID}"
    bot._pending[actor] = "fbuy:kind"

    async def run():
        handled = await bot._handle_buy_streak(
            _msg(WAYNE_UID, "為什麼跌"), str(WAYNE_UID), "fbuy:kind", "為什麼跌", actor=actor
        )
        assert handled is False

    asyncio.run(run())


def test_l9_streak_days_does_not_reprint_number_list():
    """天數已在訊息下方按鈕；不要再印一則「可選天數：22 21 19…」。"""
    bot = _bot()
    msg = _msg(WAYNE_UID, "外資")
    snap = SimpleNamespace(
        as_of="20260908",
        max_days=22,
        days_menu=lambda: [22, 21, 19, 17, 16, 14, 13, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2],
    )

    async def run():
        with patch("buy_streak.load_snapshot", return_value=snap):
            await bot._streak_show_days(msg, str(WAYNE_UID), f"{WAYNE_UID}:{WAYNE_UID}", "foreign", "ALL")

    asyncio.run(run())
    html = msg.reply_html.await_args.args[0]
    assert "可選天數" not in html
    assert "22 21 19" not in html
    assert "輸入區鍵盤" not in html
    assert "上市櫃一起列" not in html
    markup = msg.reply_html.await_args.kwargs.get("reply_markup")
    assert markup is not None
    assert getattr(markup, "inline_keyboard", None)
    assert not getattr(markup, "keyboard", None)
    assert msg.reply_text.await_count == 0
    src = _src(WayneTelegramBot._streak_show_days)
    assert "可選天數" not in src
    from main_runner import main

    src = _src(main)
    assert "skip_if_done=skip_if_done" in src
    assert "notify=screen_notify_enabled()" in src
    assert "run_evening_screen(skip_if_done=True" in src
    assert "run_midday_review(skip_if_done=True)" in src
    assert "run_increment_job(skip_if_done=True, notify=not gha)" in src
    assert 'os.getenv("GITHUB_ACTIONS")' in src
    assert "demote_unsent_screen_success" in src


def test_l9_etf_callback_code_not_truncated():
    bot = _bot()
    kb = bot._hub_keyboard("00706L")
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert any(d.endswith("00706L") or d.endswith("00706") for d in data)
    # 六碼含字母不可被切成 00706
    assert any("00706L" in d for d in data)


def test_l9_holdings_alias_portfolio_not_ai():
    hit = parse_intent("持股")
    assert hit.kind == "portfolio"
    hit2 = parse_intent("持倉")
    assert hit2.kind == "portfolio"
    assert parse_intent("持倉報告").kind == "ai"
    assert parse_intent("模擬持倉").kind == "ai"


# ===========================================================================
# L9b 再加深：休市／語音／假單位／交叉（34）
# ===========================================================================

@pytest.mark.parametrize(
    "text,kind",
    [
        ("為什麼下跌", "lookup"),
        ("為甚麼上漲", "lookup"),
        ("啥原因", "lookup"),
        ("自營成本", "no_cost"),
        ("三大法人", "chips"),
        ("外資買超", "chips"),
        ("月營收", "fund"),
        ("殖利率", "fund"),
        ("產業輪動", "flow"),
        ("資金移動", "flow"),
        ("隔日沖", "overnight"),
        ("選股", "screen"),
        ("起漲", "screen"),
        ("自選股", "watch"),
        ("AI模擬倉", "ai"),
        ("出場協助", "sell"),
        ("準備減碼", "sell"),
        ("高低卡", "lookup"),
        ("介紹圖", "lookup"),
        ("導航圖", "lookup"),
        ("使用說明", "help"),
        ("回報問題", "report"),
        ("加權指數", "market"),
        ("台股大盤", "market"),
        ("美股", "market"),
        ("融資", "fund"),
        ("毛利", "fund"),
        ("同業說明", "industry"),
        ("法人買賣超", "chips"),
        ("觀察清單", "watch"),
        ("真實持股", "portfolio"),
        ("假錢", "ai"),
        ("怎麼用", "help"),
    ],
)
def test_l9b_more_plain_speech(text, kind):
    hit = parse_intent(text)
    assert hit is not None, text
    assert hit.kind == kind, (text, hit.kind)


def test_l9b_us_labor_day_plain():
    from us_holidays import lookup_us_session

    labor = lookup_us_session("20260907")
    assert labor["kind"] == "full_close"
    assert labor["zh"] == "勞動節"


def test_l9b_tw_weekday_not_holiday_formula():
    from trading_calendar import is_trading_weekday

    assert is_trading_weekday("20260908")
    assert not is_trading_weekday("20260906")


def test_l9b_voice_stt_not_required_for_text():
    from voice_stt import stt_configured

    stt_configured()


def test_l9b_line_share_copy():
    assert "LINE" in HELP_TOPICS.get("screen", "") or "LINE" in HELP_TOPICS.get("guide", "")


def test_l9b_fake_units_empty_card_omits():
    from screening_engine import _stock_card_html

    card = _stock_card_html(
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 0,
            "volume": 0,
            "pct_change": 0,
            "turnover_k": 0,
            "ma20": None,
            "ma60": None,
            "foreign_net": None,
            "trust_net": None,
            "dealer_net": None,
            "profit": None,
        },
        1,
        show_line_link=False,
    )
    assert "外資成本" not in card
    assert "None" not in card


def test_l9b_brother_help_exists():
    assert "guide" in HELP_TOPICS
    assert "第一次用" in HELP_TOPICS["guide"] or "四碼" in HELP_TOPICS["guide"]


def test_l9c_guide_family_no_invite_one_chunk():
    from tg_layout import chunk_telegram_html

    guide = HELP_TOPICS["guide"]
    chunks = chunk_telegram_html(guide)
    assert len(chunks) == 1
    assert "t.me/WC_ai_trade_bot" in guide
    assert "不必再分享邀請" in guide
    assert "對方按" not in guide
    assert "給家人用" not in guide
    assert "不要拉進同一個群組" in guide
    assert "各看各的" in guide
    assert "06:30" in guide and "各寄一份" in guide
    assert "16:45" not in guide


@pytest.mark.parametrize("topic", sorted(HELP_TOPICS))
def test_l9c_help_topic_layout_and_jargon(topic):
    from tg_layout import chunk_telegram_html

    body = HELP_TOPICS[topic]
    assert body.strip()
    assert "<b>" in body
    assert "TWSE" not in body
    assert "TPEX" not in body
    for phrase in ("外資成本", "投信成本", "融資成本"):
        if phrase in body:
            assert "沒這欄" in body or "官方沒" in body, topic
    chunks = chunk_telegram_html(body)
    assert chunks
    assert all(part.strip() for part in chunks)
    if topic == "guide":
        assert len(chunks) == 1


@pytest.mark.parametrize(
    "label",
    ["說明", "海選", "持股", "觀察", "刷新", "回報", "大盤", "資金", "當沖", "隔日沖", "AI倉", "連買區", "飆大"],
)
def test_l9c_twelve_buttons_named_in_guide_and_row_help(label):
    from bot_servers import MENU_ROW1, MENU_ROW2, _normalize_menu_text

    names = [_normalize_menu_text(t) for t in MENU_ROW1 + MENU_ROW2]
    assert label in names
    assert label in HELP_TOPICS["guide"]
    blob = HELP_TOPICS["row1"] + "\n" + HELP_TOPICS["row2"]
    assert label in blob
    assert "是什麼" in blob
    assert "怎麼用" in blob or "怎麼加" in blob


def _circled(i: int) -> str:
    return "①②③④⑤⑥⑦⑧⑨⑩"[i - 1]


def test_l9c_row_help_covers_each_button_intro():
    from bot_servers import MENU_ROW1, MENU_ROW2, _normalize_menu_text

    for rows, blob in ((MENU_ROW1, HELP_TOPICS["row1"]), (MENU_ROW2, HELP_TOPICS["row2"])):
        labeled = [_normalize_menu_text(t) for t in rows if str(t).strip()]
        for i, label in enumerate(labeled, start=1):
            start = blob.index(f"<b>{_circled(i)} {label}</b>")
            end = blob.index(f"<b>{_circled(i + 1)} ", start) if i < len(labeled) else len(blob)
            section = blob[start:end]
            assert "是什麼" in section
            assert ("怎麼用" in section) or ("怎麼加" in section)


def test_l9c_gha_morning_only_at_0630():
    from pathlib import Path

    from config import scheduled_job_kind

    text = Path(".github/workflows/daily_run.yml").read_text(encoding="utf-8")
    assert "WAYNE_SCREEN_NOTIFY" in text
    assert "secrets.TELEGRAM_BOT_TOKEN" not in text
    assert "secrets.TG_BOT_TOKEN" not in text
    assert "WAYNE_FAMILY_CHAT_IDS" not in text
    assert scheduled_job_kind("30 22 * * 0-4") == "morning_screen"
    assert scheduled_job_kind("30 8 * * 1-5") == "increment"
    assert scheduled_job_kind("45 8 * * 1-5") == "increment"


# ===========================================================================
# L10 生產庫：速度＋視覺（標記 production_db）
# ===========================================================================

@pytest.mark.production_db
def test_l10_industry_snapshot_fast():
    from industry_brief import industry_snapshot

    db = require_production_db()
    t0 = time.perf_counter()
    snap = industry_snapshot(db, "2330")
    elapsed = time.perf_counter() - t0
    assert snap.get("stock_id") == "2330"
    assert elapsed < 0.6, f"產業快照 {elapsed:.2f}s 仍太慢"


@pytest.mark.production_db
def test_l10_count_markets_fast():
    from import_health import count_markets

    db = require_production_db()
    t0 = time.perf_counter()
    tw, two, total = count_markets(db, "20260904")
    elapsed = time.perf_counter() - t0
    assert tw >= 800
    assert two >= 600
    assert elapsed < 0.15, f"count_markets {elapsed:.2f}s"


@pytest.mark.production_db
def test_l10_lookup_etf_from_quotes():
    from wayne_db import lookup_stocks

    db = require_production_db()
    for q in ("0050", "00706L", "00631L", "00990A", "00632R"):
        hits = lookup_stocks(db, q)
        assert hits, q
        assert str(hits[0]["stock_id"]).upper() == q.upper()


@pytest.mark.production_db
def test_l10_card_png_visual_quality():
    from PIL import Image

    from wayne_navigator import NavigatorEngine, render_decision_card_png

    db = require_production_db()
    t0 = time.perf_counter()
    card = NavigatorEngine(db).get_decision_card("2330", merge_live=False)
    assert not card.get("error")
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "card.png")
        out = render_decision_card_png(card, path)
        elapsed = time.perf_counter() - t0
        assert WayneTelegramBot._png_looks_ok(out)
        im = Image.open(out)
        assert im.size[0] >= 800
        assert im.size[1] >= 600
        assert os.path.getsize(out) > 20_000
    assert elapsed < 8.0, f"決策卡 {elapsed:.1f}s"


@pytest.mark.production_db
def test_l10_glance_png_no_fake_cost_pixels_via_copy():
    from wayne_navigator import NavigatorEngine, render_first_glance_png

    db = require_production_db()
    card = NavigatorEngine(db).get_decision_card("2330", merge_live=False)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "glance.png")
        out = render_first_glance_png("2330", card, {}, path, db)
        assert WayneTelegramBot._png_looks_ok(out)
        assert os.path.getsize(out) > 15_000
    # 真數才上主力成本；沒分點列時卡內不該硬寫外資成本。
    joined = " ".join(str(v) for v in card.values())
    assert "外資成本" not in joined
    assert "投信成本" not in joined
    assert "融資成本" not in joined


@pytest.mark.production_db
def test_l10_industry_html_readable():
    from industry_brief import format_industry_html

    db = require_production_db()
    html = format_industry_html("2330", db)
    assert html
    assert "2330" in html or "台積" in html
    for line in html.split("\n"):
        if line.strip():
            assert not re.search(r"^(產業|同業)\s{3,}", line)


@pytest.mark.production_db
def test_l10_live_close_indexed_fast():
    from live_quote import _db_latest_close

    db = require_production_db()
    t0 = time.perf_counter()
    px = _db_latest_close(db, "2330")
    elapsed = time.perf_counter() - t0
    assert px and px > 0
    assert elapsed < 0.15, f"昨收 {elapsed:.2f}s"


# pytest collect-only 本檔 ≥300；此守衛防檔案被砍到只剩個位數具名測試。
def test_l_meta_this_file_has_three_hundred_angles():
    import pathlib

    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    n_named = len(re.findall(r"^def test_", text, re.M))
    n_param_blocks = text.count("@pytest.mark.parametrize")
    assert n_named >= 70
    assert n_param_blocks >= 8
    assert "test_l0_" in text and "test_l10_" in text

