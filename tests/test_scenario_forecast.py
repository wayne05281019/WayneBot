# -*- coding: utf-8 -*-
"""情境預估：VEGAS／浪號情境／獨立附加／非買訊。"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import WayneTelegramBot
from scenario_forecast_chart import (
    build_scenario_meta,
    dodge_label_ys,
    format_scenario_caption,
    infer_dc_wave_scenario,
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
        if i < 80:
            price = 160 - i * 0.4
        else:
            price = 128 + (i - 80) * 0.35
        hi = price + 2.5
        lo = price - 2.0
        if i in (40, 70):
            hi = price + 8
        rows.append(
            {
                "date": f"2025{((i // 20) % 12) + 1:02d}{(i % 20) + 1:02d}",
                "stock_name": "測",
                "open": price - 0.5,
                "high": hi,
                "low": lo,
                "close": price,
                "volume": 1000 + i,
            }
        )
    from datetime import date, timedelta

    d0 = date(2025, 1, 2)
    out = []
    for i, r in enumerate(rows):
        d = d0 + timedelta(days=i)
        while d.weekday() >= 5:
            d += timedelta(days=1)
            d0 = d
        r = dict(r)
        r["date"] = d.strftime("%Y%m%d")
        out.append(r)
        d0 = d
    return out


def _impulse_rows(n: int = 120):
    """人造上升 1–2–3–4–5 樞紐，供浪號推導。"""
    from datetime import date, timedelta

    # 價位骨架（索引約略）
    path = []
    # start low
    for i in range(n):
        if i < 10:
            c = 100 + i * 0.2
        elif i < 25:  # wave1 up
            c = 102 + (i - 10) * 2.0
        elif i < 40:  # wave2 down
            c = 132 - (i - 25) * 1.1
        elif i < 65:  # wave3 up
            c = 115 + (i - 40) * 2.4
        elif i < 80:  # wave4 down
            c = 175 - (i - 65) * 1.2
        else:  # wave5 up / after
            c = 157 + (i - 80) * 1.5
        path.append(c)
    d0 = date(2025, 2, 3)
    rows = []
    for i, c in enumerate(path):
        d = d0 + timedelta(days=i)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        hi = c + 3.0
        lo = c - 3.0
        # plant clear pivots
        if i == 10:
            lo = c - 1.0
        if i == 24:
            hi = c + 6.0
        if i == 39:
            lo = c - 5.0
        if i == 64:
            hi = c + 8.0
        if i == 79:
            lo = c - 5.0
        if i == n - 5:
            hi = c + 6.0
        rows.append(
            {
                "date": d.strftime("%Y%m%d"),
                "stock_name": "浪測",
                "open": c - 0.5,
                "high": hi,
                "low": lo,
                "close": c,
                "volume": 2000 + i,
            }
        )
        d0 = d
    return rows


def test_ema_and_caption_not_buy_signal():
    closes = [100 + i * 0.1 for i in range(200)]
    e = _ema(closes, 12)
    assert len(e) == 200
    assert e[-1] > e[0]
    cap = format_scenario_caption(
        "3035",
        "智原",
        {
            "caption_bits": ["隧道之上", "浪號(1)(2)(3)"],
            "wave": {
                "bubble": "情境預估：已標(1)(2)，虛線(3)(4)(5)（不保證・不是買訊）"
            },
        },
    )
    assert "不保證" in cap and "不是買訊" in cap
    assert "(3)" in cap or "(1)" in cap


def test_desc_press_and_ladders_geometry():
    rows = _synth_rows(160)
    meta = build_scenario_meta(rows)
    assert "vegas" in meta
    press = infer_desc_press(rows)
    ladders = infer_prior_high_ladders(rows, max_n=3)
    assert isinstance(press, dict)
    assert isinstance(ladders, list)
    assert len(ladders) <= 3
    for lad in ladders:
        assert float(rows[-1]["close"]) < float(lad["price"]) * 0.995 + 1e-9


def test_dc_wave_labels_and_projection():
    rows = _impulse_rows(120)
    ladders = [{"price": 220.0}, {"price": 250.0}, {"price": 280.0}]
    wave = infer_dc_wave_scenario(rows, ladders)
    assert wave, "應推得出浪情境"
    labs = set(wave.get("labels") or [])
    assert "(1)" in labs and "(2)" in labs
    # 至少有已走或虛線延伸到 3/4/5 族
    assert any(x in labs for x in ("(3)", "(4)", "(5)"))
    assert "不保證" in str(wave.get("bubble") or "")
    assert "不是買訊" in str(wave.get("bubble") or "")
    # 虛線點存在或已完整
    assert wave.get("path_done")
    meta = build_scenario_meta(rows)
    cap = format_scenario_caption("4927", "泰鼎-KY", meta)
    assert "不是買訊" in cap and "不保證" in cap


def test_snap_support_band_and_ending_fifth():
    from scenario_forecast_chart import (
        _snap_support_band_price,
        _ending_fifth_band,
        _retarget_first_equal_peak,
        _wave_node,
    )

    # 長下影：釘實體／心理關，不釘 2090
    rows = [
        {
            "date": "20260825",
            "open": 2180.0,
            "high": 2210.0,
            "low": 2090.0,
            "close": 2195.0,
        }
    ]
    assert _snap_support_band_price(rows, 0, 2090.0) == 2200.0
    # 無長下影：保留極值
    rows2 = [
        {
            "date": "20260331",
            "open": 836.0,
            "high": 855.0,
            "low": 821.0,
            "close": 821.0,
        }
    ]
    assert _snap_support_band_price(rows2, 0, 821.0) == 821.0
    lo, hi = _ending_fifth_band(1450.0)
    assert abs(lo - 1450.0 * 0.995) < 1e-6
    assert 1520 <= hi <= 1540
    # 同價再測：首峰優先
    work = [
        {"i": 10, "kind": "H", "price": 1245.0},
        {"i": 40, "kind": "L", "price": 800.0},
        {"i": 70, "kind": "H", "price": 1245.0},
        {"i": 100, "kind": "L", "price": 821.0},
    ]
    lows = [700.0] * 120
    lows[5] = 620.0
    rows_n = [{"date": f"2025{i:04d}", "low": lows[i]} for i in range(120)]
    start = {"i": 40.0, "price": 800.0, "kind": "L", "date": "x"}
    confirmed = [
        _wave_node("(1)", 70, 1245.0, "H", projected=False, date="0116"),
        _wave_node("(2)", 100, 821.0, "L", projected=False, date="0331"),
    ]
    ns, nc = _retarget_first_equal_peak(work, start, confirmed, lows, rows_n)
    assert abs(float(nc[0]["i"]) - 10.0) < 0.1
    assert float(ns["i"]) < 10.0


def test_scenario_paths_ladder_fallback_no_wave():
    """無浪骨架時仍可畫階梯；避讓可用。"""
    rows = _synth_rows(180)
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
    placed = dodge_label_ys(
        [(10.0, 100.0, "a"), (11.0, 100.5, "b"), (12.0, 200.0, "c")],
        min_gap=5.0,
    )
    assert placed[0][1] == 100.0
    assert placed[1][1] >= 105.0
    assert placed[2][1] >= placed[1][1] + 5.0


def test_hub_and_callback_wiring_isolated():
    hub = inspect.getsource(WayneTelegramBot._hub_keyboard)
    assert 'callback_data=f"sf:{c}"' in hub
    assert "情境預估" in hub
    src = inspect.getsource(WayneTelegramBot._send_scenario_forecast)
    assert "情境預估進行中" in src
    assert "WAYNE_SCENARIO_FORECAST_TIMEOUT" in src
    assert "情境預估暫略" in src
    assert "leave_zero" not in src
    assert "不是買訊" in src
    # 盤中與圖一二三四同源：決策卡真報價疊縮圖末日 K／趨勢
    assert "merge_live=True" in src
    assert "overlay_live_face_from_card" in inspect.getsource(render_scenario_forecast)
    # 僅此子鈕放寬浪號；仍釘 A+B+C
    assert "不准擋查股" in src or "A+B+C" in src
    cb = inspect.getsource(WayneTelegramBot._on_callback_bound)
    assert 'startswith("sf:")' in cb
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
    assert isinstance(meta, dict)
