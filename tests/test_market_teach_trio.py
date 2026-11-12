# -*- coding: utf-8 -*-
"""大盤遠／近／超近：第1張必遠窗；話筒一律 force 重渲；缺遠窗不准只出近窗。"""
from __future__ import annotations

import os
from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock

from bot_servers import WayneTelegramBot


def _png(path: str, w: int = 1200, h: int = 700) -> None:
    """產足夠大的假 PNG（過 _png_looks_ok 的 8KB／480×280 閘）。"""
    from PIL import Image
    import numpy as np

    # 雜訊圖才壓不小；單色會遠低於 8KB
    arr = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
    Image.fromarray(arr, mode="RGB").save(path, format="PNG", compress_level=1)


def test_market_teach_stored_reuse_requires_tip_match():
    """活畫失敗回退存檔：as_of 夠還要 tip 一口對；缺 tip／價差不准混舊戳。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "compute_teach_tip_snapshot" in src
    assert "teach_tip_snapshots_match" in src
    assert "_stored_reuse_ok" in src
    assert "and _stored_asof_ok():" not in src
    assert "and _stored_reuse_ok():" in src


def test_merge_market_teach_kit_fills_missing_far_and_micro(tmp_path):
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    near = tmp_path / "near.png"
    far = tmp_path / "far.png"
    micro = tmp_path / "micro.png"
    _png(str(near))
    _png(str(far))
    _png(str(micro))
    painted = {"near_path": str(near), "far_path": "", "micro_path": ""}
    stored = {
        "far_path": str(far),
        "near_path": str(tmp_path / "old-near.png"),
        "micro_path": str(micro),
        "thesis": "stored",
    }
    merged = bot._merge_market_teach_kit(painted, stored)
    assert merged["near_path"] == str(near)
    assert merged["far_path"] == str(far)
    assert merged["micro_path"] == str(micro)


def test_market_wave_sends_numbered_trio_far_first(tmp_path, monkeypatch):
    """話筒查一律 force 重渲；第1張遠窗→近→超近逐張，caption 標第N張。"""
    import asyncio

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "m.db")
    bot.charts_dir = str(tmp_path)
    bot._uid_from_message = lambda _m: "1"
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    bot._stop_plain_wait = AsyncMock()
    bot._safe_edit_text = AsyncMock()
    bot._prepare_lookup_album_photo = lambda p, *a, **k: p

    near = tmp_path / "near.png"
    far = tmp_path / "far.png"
    micro = tmp_path / "micro.png"
    near2 = tmp_path / "near2.png"
    far2 = tmp_path / "far2.png"
    micro2 = tmp_path / "micro2.png"
    _png(str(near))
    _png(str(far))
    _png(str(micro))
    _png(str(near2))
    _png(str(far2))
    _png(str(micro2))
    assert bot._market_teach_path_ok(str(far))

    paint_calls = {"n": 0}

    def _paint(*_a, **_k):
        paint_calls["n"] += 1
        return {
            "ok": True,
            "far_path": str(far2),
            "near_path": str(near2),
            "micro_path": str(micro2),
            "us_path": "",
            "thesis": "fresh",
            "as_of": "20261030",
        }

    def _submit(fn):
        out = Future()
        out.set_result(fn())
        return out

    monkeypatch.setattr(
        "biaoke_level_learn.latest_teach_kit",
        lambda *_a, **_k: {
            "far_path": str(far),
            "near_path": str(near),
            "micro_path": str(micro),
            "us_path": "",
            "thesis": "t",
            "as_of": "20261029",
        },
    )
    monkeypatch.setattr("biaoke_level_learn.paint_open_day_hypothesis", _paint)
    monkeypatch.setattr("biaoke_level_learn.prepare_wave_live_pack", lambda *_a, **_k: {
        "thesis": "fresh",
        "chart_as_of": "20261030",
        "query_at": "2026-10-30T12:00:00+08:00",
    })
    monkeypatch.setattr("wayne_navigator.submit_mpl_paint", _submit)
    monkeypatch.setattr(
        "biaoke_level_learn._wave_now_ladder",
        lambda *_a, **_k: {"one_line": "層級一句", "now_line": ""},
    )
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda: False)
    monkeypatch.setattr("config.skip_chart_warmup", lambda: False)

    msg = MagicMock()
    msg.reply_media_group = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.reply_text = AsyncMock()

    asyncio.run(bot._send_market_wave_charts(msg, uid="1"))
    assert paint_calls["n"] >= 1
    assert msg.reply_media_group.await_count == 0
    assert msg.reply_photo.await_count == 3
    # 送出的是 force 重渲後的新檔，不准偷懶送舊存
    sent_paths = []
    for call in msg.reply_photo.await_args_list:
        photo = call.kwargs.get("photo")
        sent_paths.append(getattr(photo, "name", None) or str(photo))
    assert any("far2" in str(p) for p in sent_paths)
    caps = []
    for call in msg.reply_photo.await_args_list:
        caps.append(call.kwargs.get("caption") or "")
    assert "第1張・遠窗" in caps[0]
    assert "第2張・近窗" in caps[1]
    assert "第3張・超近窗" in caps[2]
    # 三張 caption 都要有查詢當下台北時間
    for c in caps:
        assert "查詢 " in c and "台北" in c


def test_market_wave_blocks_near_if_far_missing(tmp_path, monkeypatch):
    """遠窗缺且重渲失敗：白話停，不准只出近窗。"""
    import asyncio

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "m.db")
    bot.charts_dir = str(tmp_path)
    bot._uid_from_message = lambda _m: "1"
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    bot._stop_plain_wait = AsyncMock()
    bot._safe_edit_text = AsyncMock()
    bot._prepare_lookup_album_photo = lambda p, *a, **k: p
    bot._retry_market_far_paint = AsyncMock(return_value="")

    near = tmp_path / "near.png"
    micro = tmp_path / "micro.png"
    _png(str(near))
    _png(str(micro))

    from concurrent.futures import Future

    fut = Future()
    fut.set_result(
        {
            "ok": True,
            "near_path": str(near),
            "far_path": "",
            "micro_path": str(micro),
            "us_path": "",
            "thesis": "t",
            "as_of": "20261031",
        }
    )
    monkeypatch.setattr("wayne_navigator.submit_mpl_paint", lambda fn: fut)
    monkeypatch.setattr(
        "biaoke_level_learn.latest_teach_kit",
        lambda *_a, **_k: {
            "far_path": "",
            "near_path": str(near),
            "micro_path": str(micro),
            "us_path": "",
            "thesis": "t",
            "as_of": "20261031",
        },
    )
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda: True)
    monkeypatch.setattr("config.skip_chart_warmup", lambda: False)
    monkeypatch.setattr(
        "biaoke_level_learn.prepare_wave_live_pack",
        lambda *_a, **_k: {"thesis": "t"},
    )
    monkeypatch.setattr(
        "biaoke_level_learn._wave_now_ladder",
        lambda *_a, **_k: {"one_line": "", "now_line": ""},
    )
    monkeypatch.setattr(
        "biaoke_level_learn.paint_open_day_hypothesis",
        lambda *_a, **_k: {
            "ok": True,
            "near_path": str(near),
            "far_path": "",
            "micro_path": str(micro),
            "us_path": "",
            "thesis": "t",
            "as_of": "20261031",
        },
    )

    msg = MagicMock()
    msg.reply_photo = AsyncMock()
    msg.reply_text = AsyncMock()
    asyncio.run(bot._send_market_wave_charts(msg, uid="1"))
    assert msg.reply_photo.await_count == 0
    assert msg.reply_text.await_count >= 1
    assert "遠窗" in (msg.reply_text.await_args.args[0] if msg.reply_text.await_args.args else "")


def test_market_page_sends_teach_before_session_cards():
    import inspect

    src = inspect.getsource(WayneTelegramBot._send_market_page)
    # v34：教具改走波浪位階；大盤頁不再先送三張
    assert "_send_market_wave_charts" not in src
    assert "_send_market_session_cards" in src
    from bot_servers import MENU_BTN_WAVE_STATUS

    assert MENU_BTN_WAVE_STATUS == "波浪位階"


def test_market_wave_phone_paint_uses_trio_panels_only():
    """話筒：prep-once＋遠→近→超近單窗 paint；send∥next；不准整包 full／外圍。"""
    import inspect

    wave = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "prepare_wave_live_pack" in wave
    assert '_paint_panel("far")' in wave or "_paint_panel('far')" in wave
    assert 'panels="near"' in wave or "panels='near'" in wave
    assert 'panels="micro"' in wave or "panels='micro'" in wave
    assert "force=True" in wave
    assert "_market_teach_paint_lock" in wave
    # 送遠時已開近窗 paint（send∥paint）
    assert wave.index('panels="near"') < wave.index("_send_market_teach_one")
    assert wave.index('panels="near"') < wave.index('panels="micro"')
    assert "submit_mpl_paint" in wave
    assert 'panels="full"' not in wave and "panels='full'" not in wave
    assert 'panels="trio"' not in wave and "panels='trio'" not in wave
    from biaoke_level_learn import (
        paint_open_day_hypothesis,
        maybe_paint_open_day_after_ingest,
        prepare_wave_live_pack,
    )

    src = inspect.getsource(paint_open_day_hypothesis)
    assert 'panels: str = "full"' in src
    assert 'mode == "full"' in src
    assert "_render_us_compare_dark" in src
    assert "_render_tx60_png" in src
    prep_src = inspect.getsource(prepare_wave_live_pack)
    assert "prepare_wave_live_pack" in inspect.getsource(prepare_wave_live_pack)
    assert "_ensure_teach_index_bars" in prep_src
    # 晚上波浪：費半 force 重抓＋電子夜盤 live_tx
    assert "_ensure_paint_live_sox" in prep_src
    assert "_tx_night_session_live" in prep_src
    assert "_ensure_paint_live_tx" in prep_src
    assert "_fill_live_twii_when_official_lags" in prep_src
    # 遠窗電子盤缺 cap 當日列必補；三窗 tip 同口凍結
    assert "_ensure_latest_tx_night_row" in prep_src
    assert "teach_tip" in prep_src
    assert "compute_teach_tip_snapshot" in prep_src
    # 排程／ingest 鉤子仍預設 full（不傳 panels）
    maybe = inspect.getsource(maybe_paint_open_day_after_ingest)
    assert "paint_open_day_hypothesis(db_path, force=force)" in maybe
    assert 'panels="trio"' not in maybe


def test_market_wave_send_overlaps_next_paint_contract():
    """遠送出前已 submit 近窗；近送出前已 submit 超近；仍單 worker。"""
    import inspect

    from wayne_navigator import _MPL_PAINT_EXECUTOR

    wave = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    # 近窗 fut 在送遠窗之前；超近在近窗 panels 之後
    assert wave.index('panels="near"') < wave.index("_send_market_teach_one")
    assert wave.index('panels="near"') < wave.index('panels="micro"')
    assert getattr(_MPL_PAINT_EXECUTOR, "_max_workers", 1) == 1
