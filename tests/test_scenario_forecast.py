# -*- coding: utf-8 -*-
"""情境預估相位一：可重算層、無浪號、獨立附加、非買訊。"""
from __future__ import annotations

import asyncio
import inspect
import os
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import WayneTelegramBot
from scenario_forecast_chart import (
    build_scenario_meta,
    dodge_label_ys,
    format_scenario_caption,
    infer_desc_press,
    infer_prior_high_ladders,
    infer_scenario_paths,
    render_scenario_forecast,
    _ema,
)


def _synth_rows(n: int = 180):
    rows = []
    price = 100.0
    for i in range(n):
        # gentle down then up with lower highs early
        if i < 80:
            price = 160 - i * 0.4
        else:
            price = 128 + (i - 80) * 0.35
        hi = price + 2.5
        lo = price - 2.0
        # plant pivot highs for desc press
        if i in (40, 70):
            hi = price + 8
        rows.append(
            {
                "date": f"20260{(i // 28) + 1:02d}{(i % 28) + 1:02d}"[:8]
                if False
                else f"2025{((i // 20) % 12) + 1:02d}{(i % 20) + 1:02d}",
                "stock_name": "測",
                "open": price - 0.5,
                "high": hi,
                "low": lo,
                "close": price,
                "volume": 1000 + i,
            }
        )
    # fix dates properly ascending
    from datetime import date, timedelta

    d0 = date(2025, 1, 2)
    out = []
    for i, r in enumerate(rows):
        d = d0 + timedelta(days=i)
        # skip weekends lightly
        while d.weekday() >= 5:
            d += timedelta(days=1)
            d0 = d
        r = dict(r)
        r["date"] = d.strftime("%Y%m%d")
        out.append(r)
        d0 = d
    return out


def test_ema_and_caption_no_wave_words():
    closes = [100 + i * 0.1 for i in range(200)]
    e = _ema(closes, 12)
    assert len(e) == 200
    assert e[-1] > e[0]
    cap = format_scenario_caption("3035", "智原", {"caption_bits": ["隧道之上", "候選 227"]})
    assert "不保證" in cap and "不是買訊" in cap
    assert "波5" not in cap and "艾略特" not in cap


def test_desc_press_and_ladders_geometry():
    rows = _synth_rows(160)
    meta = build_scenario_meta(rows)
    assert "vegas" in meta
    # may or may not find press depending on pivots; ladders optional
    press = infer_desc_press(rows)
    ladders = infer_prior_high_ladders(rows, max_n=3)
    assert isinstance(press, dict)
    assert isinstance(ladders, list)
    assert len(ladders) <= 3
    for lad in ladders:
        assert float(rows[-1]["close"]) < float(lad["price"]) * 0.995 + 1e-9


def test_scenario_paths_ladder_no_wave_labels():
    """相位 1.5：虛線階梯 2～3 條；不標 1–5／abc。"""
    rows = _synth_rows(180)
    # 把收盤壓在最低樞紐高之下，確保有前高候選
    last = float(rows[-1]["close"])
    for r in rows[-5:]:
        r["close"] = last * 0.85
        r["high"] = max(r["high"], last * 0.86)
    ladders = [
        {"price": last * 1.05},
        {"price": last * 1.12},
        {"price": last * 1.20},
    ]
    paths = infer_scenario_paths(rows, ladders, n_bars=len(rows), max_paths=3)
    assert 2 <= len(paths) <= 3
    banned = ("波5", "波4", "艾略特", "(1)", "(2)", "(3)", "(4)", "(5)", "abc", "浪")
    for p in paths:
        assert len(p.get("points") or []) >= 3
        assert p.get("steps")
        blob = str(p) + str(p.get("tip") or "")
        for b in banned:
            assert b not in blob
        for st in p["steps"]:
            assert "from" in st and "to" in st and "gap" in st
            assert "→" in str(st.get("label") or "")
    placed = dodge_label_ys(
        [(10.0, 100.0, "a"), (11.0, 100.5, "b"), (12.0, 200.0, "c")],
        min_gap=5.0,
    )
    assert placed[0][1] == 100.0
    assert placed[1][1] >= 105.0
    assert placed[2][1] >= placed[1][1] + 5.0
    meta = build_scenario_meta(rows)
    cap = format_scenario_caption("3081", "聯亞", meta)
    assert "不保證" in cap and "不是買訊" in cap
    for b in ("波5", "艾略特", "(3)", "(5)"):
        assert b not in cap


def test_hub_and_callback_wiring_isolated():
    hub = inspect.getsource(WayneTelegramBot._hub_keyboard)
    assert 'callback_data=f"sf:{c}"' in hub
    assert "情境預估" in hub
    src = inspect.getsource(WayneTelegramBot._send_scenario_forecast)
    assert "情境預估進行中" in src
    assert "WAYNE_SCENARIO_FORECAST_TIMEOUT" in src
    assert "情境預估暫略" in src
    assert "leave_zero" not in src
    assert "波5" not in src
    cb = inspect.getsource(WayneTelegramBot._on_callback_bound)
    assert 'startswith("sf:")' in cb
    # failure must not raise out of callback path
    assert "情境預估 callback 失敗" in cb or "情境預估暫略" in cb


def test_silent_catalog_has_scenario_kind():
    from button_silent_verify import BUTTON_CATALOG, CLASS_LOOKUP

    rows = [r for r in BUTTON_CATALOG if "scenario_forecast" in (r.get("kinds") or ())]
    assert rows
    assert rows[0]["class"] == CLASS_LOOKUP
    assert "不是選股" in (rows[0].get("note") or "")


def test_send_scenario_forecast_failure_does_not_raise():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot.charts_dir = tempfile.mkdtemp()
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    msg.reply_photo = AsyncMock()
    bot._uid_from_message = MagicMock(return_value="1")
    bot._hub_keyboard = MagicMock(return_value=None)
    bot._hit_is_emerging = MagicMock(return_value=False)
    bot._start_plain_wait = AsyncMock(return_value=(None, None, None))
    bot._stop_plain_wait = AsyncMock()
    bot._scratch_chart_path = MagicMock(return_value=os.path.join(bot.charts_dir, "x.png"))
    bot._png_looks_ok = MagicMock(return_value=False)
    bot._prepare_lookup_album_photo = MagicMock(side_effect=lambda p, *a, **k: p)
    bot._reply_lookup_photo = AsyncMock(return_value=False)

    async def _run():
        with patch("bot_servers.lookup_stocks", return_value=[{"stock_id": "3035"}]):
            with patch("wayne_navigator.submit_mpl_paint") as smp:
                from concurrent.futures import Future

                bad = Future()
                bad.set_exception(RuntimeError("boom"))
                smp.return_value = bad
                await bot._send_scenario_forecast(msg, "3035", "1")

    asyncio.run(_run())
    assert msg.reply_text.await_count >= 1
    text = msg.reply_text.await_args.args[0]
    assert "暫略" in text
    assert "不是買訊" in text


@pytest.mark.production_db
def test_render_3035_smoke(tmp_path, production_db):
    out = str(tmp_path / "3035-scenario.png")
    path, cap, meta = render_scenario_forecast("3035", production_db, out)
    assert path and os.path.isfile(path)
    assert os.path.getsize(path) > 20_000
    assert "不保證" in cap and "不是買訊" in cap
    for bad in ("波5", "波4", "艾略特", "(3)", "(4)", "(5)", "虛浪"):
        assert bad not in cap
    assert isinstance(meta, dict)
