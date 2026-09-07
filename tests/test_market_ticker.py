# -*- coding: utf-8 -*-
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

from market_ticker import (
    TICKER_FRAMES,
    TICKER_H,
    TICKER_W,
    collect_ticker,
    render_ticker_gif,
    ticker_plain,
    ticker_slot,
)

TW = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")


def test_ticker_slot_windows():
    assert ticker_slot(datetime(2026, 9, 8, 10, 0, tzinfo=TW)) == "tw_open"
    assert ticker_slot(datetime(2026, 9, 8, 14, 0, tzinfo=TW)) == "asia_pm"
    assert ticker_slot(datetime(2026, 9, 8, 17, 30, tzinfo=TW)) == "us_pre"
    # 週二凌晨＝美股週一現金盤
    assert ticker_slot(datetime(2026, 9, 8, 1, 22, tzinfo=TW)) == "us_night"
    # 週六白天美股已收
    assert ticker_slot(datetime(2026, 9, 5, 12, 0, tzinfo=TW)) == "weekend"


def test_collect_omits_missing_and_keeps_tw(tmp_path):
    snap = {"close": 47326.27, "chg1_pct": 1.67, "futures": {"close": 47470, "pct_change": 0.3}}
    live = {"close": 47326.27, "pct_change": 1.67}
    now = datetime(2026, 9, 8, 10, 5, tzinfo=TW)
    bundle = collect_ticker(str(tmp_path / "x.db"), live=live, snap=snap, now=now, yahoo=False)
    assert bundle["slot"] == "tw_open"
    names = [x["name"] for x in bundle["items"]]
    assert "此刻" in names
    assert bundle["clock"] == "10:05:00"
    assert "加權" in names
    assert "台指期" in names
    assert "日經" not in names  # yahoo=False 不編造
    plain = ticker_plain(bundle)
    assert "台股開盤" in plain
    assert "47,326" in plain
    assert "10:05:00" in plain


def test_live_otc_and_tx_preferred(tmp_path):
    snap = {"close": 1.0, "chg1_pct": 0.0, "futures": {"close": 1, "pct_change": 0.0}}
    live = {"close": 47326.27, "pct_change": 1.67}
    otc = {"close": 409.33, "pct_change": 1.70}
    tx = {"close": 47470.0, "pct_change": 1.63}
    now = datetime(2026, 9, 8, 10, 5, tzinfo=TW)
    bundle = collect_ticker(
        str(tmp_path / "x.db"),
        live=live,
        snap=snap,
        now=now,
        yahoo=False,
        live_otc=otc,
        live_tx=tx,
    )
    text = ticker_plain(bundle)
    assert "櫃買 409.3" in text
    assert "47,470" in text
    assert "台指期 1" not in text


def test_pick_tx_front_month_by_volume():
    from market_ticker import pick_tx_quote_row

    rows = [
        {"SymbolID": "TXF-S", "CLastPrice": "47326", "CTotalVolume": "99999"},
        {"SymbolID": "TXFI6-F", "CLastPrice": "47470", "CTotalVolume": "80000", "CDiffRate": "1.63"},
        {"SymbolID": "TXFJ6-F", "CLastPrice": "47667", "CTotalVolume": "1200", "CDiffRate": "1.67"},
        {"SymbolID": "TXFI6-M", "CLastPrice": "47333", "CTotalVolume": "5000", "CDiffRate": "-0.20"},
    ]
    day = pick_tx_quote_row(rows, night=False)
    assert day["SymbolID"] == "TXFI6-F"
    night = pick_tx_quote_row(rows, night=True)
    assert night["SymbolID"] == "TXFI6-M"


def test_spark_prefers_last_minute_bar():
    from market_ticker import _quote_from_spark_block

    q = _quote_from_spark_block(
        {
            "symbol": "^N225",
            "close": [100.0, None, 110.0],
            "fulldayPrice": 99.0,
            "fulldayChangePercent": -1.0,
            "previousClose": 100.0,
            "chartPreviousClose": 100.0,
        },
        "^N225",
    )
    assert q["px"] == 110.0
    assert abs(q["pct"] - 10.0) < 0.01


def test_spark_uses_fullday_when_no_bars():
    from market_ticker import _quote_from_spark_block

    q = _quote_from_spark_block(
        {
            "symbol": "ES=F",
            "close": None,
            "fulldayPrice": 7722.0,
            "fulldayChangePercent": -0.422,
            "previousClose": 7754.75,
        },
        "ES=F",
    )
    assert q["px"] == 7722.0
    assert abs(q["pct"] + 0.422) < 0.001


def test_us_pre_does_not_invent_futures():
    now = datetime(2026, 9, 8, 17, 0, tzinfo=TW)
    bundle = collect_ticker(None, snap={"close": 100.0, "chg1_pct": 0.0}, now=now, yahoo=False)
    assert bundle["slot"] == "us_pre"
    names = [x["name"] for x in bundle["items"]]
    assert "標普期" not in names
    assert "那斯達克期" not in names


def test_render_gif_scrolls(tmp_path):
    bundle = {
        "title": "台股開盤",
        "items": [
            {"name": "加權", "text": "加權 47,326 +1.67%", "pct": 1.67},
            {"name": "台指期", "text": "台指期 47,470 +0.30%", "pct": 0.3},
            {"name": "日經", "text": "日經 38,000 -0.40%", "pct": -0.4},
            {"name": "韓國", "text": "韓國 2,550 +0.20%", "pct": 0.2},
            {"name": "滬指", "text": "滬指 3,100 +0.10%", "pct": 0.1},
        ],
    }
    path = str(tmp_path / "ticker.gif")
    out = render_ticker_gif(bundle, path)
    assert out == path
    with Image.open(path) as im:
        assert im.format == "GIF"
        assert im.size == (TICKER_W, TICKER_H)
        n = getattr(im, "n_frames", 1)
        assert n >= 8
        assert n == TICKER_FRAMES
    assert (tmp_path / "ticker.gif").stat().st_size > 2000


def test_ticker_keyboard_refresh_and_skip_mock():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._ticker_keyboard()
    labels = [b.text for row in kb.inline_keyboard for b in row]
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "刷新跑馬燈" in labels
    assert "tk:r" in cbs
    bot._ticker_refresh_task = {}
    bot._schedule_ticker_refresh(type("M", (), {"message_id": "x", "chat_id": 1})())
def test_render_gif_full_width_always_scrolls(tmp_path):
    """短字也要整條從最左捲到最右，不能停在靜態一幀。"""
    bundle = {
        "title": "台股開盤",
        "items": [{"name": "加權", "text": "加權 47,326 +1.67%", "pct": 1.67}],
    }
    path = str(tmp_path / "short.gif")
    render_ticker_gif(bundle, path)
    with Image.open(path) as im:
        assert im.size == (TICKER_W, TICKER_H)
        n = getattr(im, "n_frames", 1)
        assert n == TICKER_FRAMES
        im.seek(0)
        first = im.convert("RGB").tobytes()
        left = im.convert("RGB").getpixel((6, 1))
        right = im.convert("RGB").getpixel((TICKER_W - 8, 1))
        assert left[2] >= 180 and right[2] >= 180
        im.seek(n // 2)
        mid = im.convert("RGB").tobytes()
        assert first != mid


def test_ticker_refresh_loop_keeps_editing_until_rounds(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import WayneTelegramBot

    monkeypatch.setenv("WAYNE_TICKER_REFRESH_ROUNDS", "2")
    monkeypatch.setenv("WAYNE_TICKER_REFRESH_SEC", "4")
    gif = str(tmp_path / "t.gif")
    render_ticker_gif(
        {
            "title": "台股開盤",
            "items": [{"name": "加權", "text": "加權 1 +0.10%", "pct": 0.1}],
        },
        gif,
    )
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "x.db")
    bot._ticker_refresh_task = {"1:9": None}
    anim = MagicMock()
    anim.message_id = 9
    anim.chat_id = 1
    anim.edit_media = AsyncMock()

    async def _run():
        with patch("asyncio.sleep", new=AsyncMock()), patch(
            "live_quote.fetch_mis_index_quote", return_value={"close": 1.0, "pct_change": 0.1}
        ), patch(
            "taiwan_market.analyze_taiwan_market",
            return_value={"close": 1.0, "chg1_pct": 0.1},
        ), patch(
            "market_ticker.build_market_ticker",
            return_value={"gif": gif},
        ):
            await bot._ticker_refresh_loop(anim, "1:9")

    asyncio.run(_run())
    assert anim.edit_media.await_count == 2
    assert "1:9" not in bot._ticker_refresh_task
