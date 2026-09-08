# -*- coding: utf-8 -*-
from telegram import InlineKeyboardButton

from bot_servers import WayneTelegramBot
from telegram_cat_marks import ANIM_KEYS, ensure_mark_gif, render_pulse_gif


def test_only_entry_buckets_get_pulse_gif(tmp_path):
    path = str(tmp_path / "pulse.gif")
    out = render_pulse_gif("sprout", (60, 170, 90), path)
    assert out == path
    assert tmp_path.joinpath("pulse.gif").stat().st_size > 800
    assert ANIM_KEYS == frozenset({"leave_zero", "golden_buy"})
    assert ensure_mark_gif("select_01") == ""
    assert ensure_mark_gif("leave_zero") == ""
    assert ensure_mark_gif("golden_buy") == ""


def test_hub_keyboard_skips_non_http_urls():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._hub_keyboard(
        "2330",
        news={"label": "報導12↑", "url": "javascript:alert(1)"},
    )
    urls = [b.url for r in kb.inline_keyboard for b in r if getattr(b, "url", None)]
    assert all((u or "").startswith("http") for u in urls)
    labels = [b.text for r in kb.inline_keyboard for b in r]
    assert "報導12↑" not in labels


def test_hub_news_url_button_on_top():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    news = {
        "label": "報導12↑",
        "url": "https://news.google.com/search?q=2330",
    }
    kb = bot._hub_keyboard("2330", news=news)
    rows = kb.inline_keyboard
    assert rows[0][0].text == "產業"
    assert isinstance(rows[0][1], InlineKeyboardButton)
    assert rows[0][1].text == "報導12↑"
    assert (rows[0][1].url or "").startswith("https://news.google.com")
    assert any(b.text == "K線" for b in rows[0])
    kline = next(b for b in rows[0] if b.text == "K線")
    assert (kline.url or "").endswith("/k/2330")
    texts = [b.text for r in rows for b in r]
    assert "籌碼" in texts and "產業" in texts


def test_em_hub_has_industry_omits_chips():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._hub_keyboard("3595", em=True)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "產業" in texts
    assert "籌碼" not in texts
    assert "營收" not in texts
    assert "K線" not in texts
    assert [b.text for b in kb.inline_keyboard[0]] == ["產業", "觀察", "記買入", "說明"]
