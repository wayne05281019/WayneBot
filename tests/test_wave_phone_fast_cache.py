# -*- coding: utf-8 -*-
"""波浪位階出圖加速：流水線記憶＋三窗磁碟／記憶快取直送。"""
from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from biaoke_level_learn import (
    clear_wave_phone_caches,
    remember_wave_kit_paths,
    teach_kit_reusable_for_phone,
    teach_tip_snapshots_match,
)
from bot_servers import WayneTelegramBot


def _tip(tw=28000.0, sox=5000.0, tx=28000.0, ymd="20261121"):
    return {
        "tw_asof": ymd,
        "tw_close": tw,
        "tw_live": 0,
        "sox_asof": ymd,
        "sox_close": sox,
        "sox_live": 0,
        "tx_asof": ymd,
        "tx_close": tx,
        "tx_live": 0,
    }


def _touch_png(path: Path, nbytes: int = 9000) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n" + b"0" * nbytes)
    return str(path)


def test_teach_kit_reusable_disk_and_mem(tmp_path: Path):
    clear_wave_phone_caches()
    tip = _tip()
    far = _touch_png(tmp_path / "far.png")
    near = _touch_png(tmp_path / "near.png")
    micro = _touch_png(tmp_path / "micro.png")
    stored = {
        "far_path": far,
        "near_path": near,
        "micro_path": micro,
        "thesis": "測試題旨",
        "as_of": "20261121",
        "teach_tip": tip,
    }
    assert teach_tip_snapshots_match(tip, tip)
    hit = teach_kit_reusable_for_phone(stored, tip, db_path=str(tmp_path / "x.db"))
    assert hit["ok"] is True
    assert hit["reason"] == "disk_hit"
    assert hit["far_path"] == far

    # 記憶快取：同 tip 應 mem_hit
    mem = teach_kit_reusable_for_phone(
        {"teach_tip": {}}, tip, db_path=str(tmp_path / "x.db")
    )
    assert mem["ok"] is True
    assert mem["reason"] == "mem_hit"
    assert mem["from_mem"] is True

    # tip 漂價 → 不准复用
    clear_wave_phone_caches()
    drifted = dict(tip)
    drifted["tw_close"] = float(tip["tw_close"]) + 50.0
    miss = teach_kit_reusable_for_phone(stored, drifted, db_path=str(tmp_path / "x.db"))
    assert miss["ok"] is False
    assert miss["reason"] == "tip_mismatch"


def test_send_market_wave_charts_cache_skips_paint(tmp_path: Path):
    """tip 同口＋三窗齊 → 不准 submit 活畫。"""
    clear_wave_phone_caches()
    tip = _tip()
    far = _touch_png(tmp_path / "f.png")
    near = _touch_png(tmp_path / "n.png")
    micro = _touch_png(tmp_path / "m.png")
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "wave.db")
    bot._market_teach_paint_lock = asyncio.Lock()
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.reply_html = AsyncMock()

    paint_calls: list = []

    def _paint(*_a, **_k):
        paint_calls.append(1)
        return {}

    async def _await_paint(fut, *_a, **_k):
        return await asyncio.wrap_future(fut) if hasattr(fut, "result") else {}

    with patch(
        "biaoke_level_learn.latest_teach_kit",
        return_value={
            "far_path": far,
            "near_path": near,
            "micro_path": micro,
            "thesis": "t",
            "as_of": "20261121",
            "teach_tip": tip,
        },
    ), patch(
        "biaoke_level_learn.compute_teach_tip_snapshot", return_value=tip
    ), patch(
        "biaoke_level_learn.ensure_teach_tip_preflight",
        return_value={"ok": True, "tip": tip, "fails": []},
    ), patch(
        "biaoke_level_learn.paint_open_day_hypothesis", side_effect=_paint
    ), patch(
        "biaoke_level_learn._wave_now_ladder",
        return_value={"now": "C3", "one_line": "測試", "now_line": "落在「C3」"},
    ), patch(
        "wayne_navigator.submit_mpl_paint",
        side_effect=lambda fn: (__import__("concurrent.futures").Future()),
    ), patch.object(
        bot, "_start_plain_wait", new_callable=AsyncMock, return_value=(None, None, None)
    ), patch.object(
        bot, "_stop_plain_wait", new_callable=AsyncMock
    ), patch.object(
        bot, "_safe_edit_text", new_callable=AsyncMock
    ), patch.object(
        bot, "_market_teach_path_ok", side_effect=lambda p: bool(p) and Path(p).is_file()
    ), patch.object(
        bot, "_png_looks_ok", return_value=True
    ), patch.object(
        bot, "_prepare_lookup_album_photo", side_effect=lambda p: p
    ), patch.object(
        bot, "_uid_from_message", return_value="1"
    ), patch(
        "config.skip_chart_warmup", return_value=False
    ):
        asyncio.run(
            bot._send_market_wave_charts(
                msg,
                uid="1",
                pack={"thesis": "t", "chart_as_of": "20261121", "teach_tip": tip},
                wait_title="波浪位階進行中",
            )
        )
    assert paint_calls == [], f"快取命中仍活畫：{paint_calls}"
    assert msg.reply_photo.await_count >= 3


def test_wave_charts_source_has_cache_fast_path():
    src = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "teach_kit_reusable_for_phone" in src
    assert "快取三窗直送" in src
    assert "remember_wave_kit_paths" in src
    # 冷路徑仍 force 活畫；暖路徑在 paint_lock 之前 return
    assert "force=True" in src
    assert src.index("teach_kit_reusable_for_phone") < src.index("async with paint_lock")


def test_pipeline_memo_helpers_exported():
    from biaoke_level_learn import (
        clear_wave_phone_caches,
        run_teach_trio_preflight_pipeline,
    )

    src = inspect.getsource(run_teach_trio_preflight_pipeline)
    assert "from_cache" in src
    assert "00_pipe_cache" in src or "_WAVE_PIPE_MEMO" in src
    clear_wave_phone_caches()


def test_pipeline_cache_hit_skips_full_prep(monkeypatch, tmp_path: Path):
    """同 tip 容差內 → from_cache，不准再跑 01 ensure。"""
    import biaoke_level_learn as m

    clear_wave_phone_caches()
    tip = _tip()
    pack = {"thesis": "cache-test", "teach_tip": tip, "chart_as_of": "20261121"}
    db = str(tmp_path / "p.db")
    with m._WAVE_PHONE_MEMO_LOCK:
        m._WAVE_PIPE_MEMO["at"] = time.monotonic()
        m._WAVE_PIPE_MEMO["db"] = db
        m._WAVE_PIPE_MEMO["tip_fp"] = m._teach_tip_fingerprint(tip)
        m._WAVE_PIPE_MEMO["result"] = {
            "ok": True,
            "pack": pack,
            "gate": {"ok": True, "fails": []},
            "steps": [{"id": "08_stamp_gate", "ok": True, "detail": ""}],
            "sox_degraded": False,
            "fail_bits": [],
            "checked_at": "x",
            "from_cache": False,
        }

    calls = {"ensure": 0}

    def _boom(*_a, **_k):
        calls["ensure"] += 1
        raise AssertionError("cache hit 不准跑 ensure")

    monkeypatch.setattr(m, "_force_refill_twii_daily_to_target", _boom)
    monkeypatch.setattr(m, "_ensure_teach_index_bars", _boom)
    monkeypatch.setattr(
        m,
        "compute_teach_tip_snapshot",
        lambda *_a, **_k: dict(tip),
    )
    monkeypatch.setattr(m, "teach_tip_snapshots_match", lambda a, b, **_k: True)
    monkeypatch.setattr(m, "_wave_session_live_now", lambda *_a, **_k: False)

    t0 = time.perf_counter()
    out = m.run_teach_trio_preflight_pipeline(db)
    dt = time.perf_counter() - t0
    assert out.get("from_cache") is True
    assert out.get("ok") is True
    assert calls["ensure"] == 0
    assert dt < 0.2, f"流水線記憶命中應 <0.2s，實際 {dt:.3f}s"
    assert any(
        s.get("id") == "00_pipe_cache" for s in (out.get("steps") or [])
    )


@pytest.mark.parametrize("reason", ["disk_hit", "mem_hit"])
def test_remember_then_reuse_speed(tmp_path: Path, reason: str):
    """量測級：記憶命中應遠快於重算路徑標記。"""
    clear_wave_phone_caches()
    tip = _tip()
    far = _touch_png(tmp_path / f"{reason}-f.png")
    near = _touch_png(tmp_path / f"{reason}-n.png")
    micro = _touch_png(tmp_path / f"{reason}-m.png")
    db = str(tmp_path / "x.db")
    if reason == "disk_hit":
        stored = {
            "far_path": far,
            "near_path": near,
            "micro_path": micro,
            "teach_tip": tip,
            "thesis": "x",
            "as_of": "20261121",
        }
        t0 = time.perf_counter()
        hit = teach_kit_reusable_for_phone(stored, tip, db_path=db)
        dt = time.perf_counter() - t0
    else:
        remember_wave_kit_paths(
            db,
            {
                "far_path": far,
                "near_path": near,
                "micro_path": micro,
                "thesis": "x",
                "as_of": "20261121",
                "teach_tip": tip,
            },
            tip=tip,
        )
        t0 = time.perf_counter()
        hit = teach_kit_reusable_for_phone({}, tip, db_path=db)
        dt = time.perf_counter() - t0
    assert hit["ok"] and hit["reason"] == reason
    # CI runner 偶發 >50ms；記憶命中仍須遠快於重算（放寬到 150ms）
    assert dt < 0.15, f"{reason} 應 <150ms，實際 {dt:.4f}s"
