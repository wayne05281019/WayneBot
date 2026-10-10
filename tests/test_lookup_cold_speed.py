# -*- coding: utf-8 -*-
"""查股冷啟：少重壓 JPEG、預熱走 paint worker、TimedOut 不重送（不拉長 timeout）。"""
from __future__ import annotations

import inspect
import os
import tempfile

from bot_servers import WayneTelegramBot


def test_prepare_skips_reencode_when_png_named_jpeg():
    """savefig 直出 JPEG、路徑叫 .png → prepare 不准再壓成 .hq.jpg。"""
    from PIL import Image

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "card.png")
        Image.new("RGB", (800, 1200), (20, 30, 40)).save(
            path, "JPEG", quality=90, subsampling=0
        )
        with open(path, "rb") as f:
            assert f.read(3) == b"\xff\xd8\xff"
        out = WayneTelegramBot._prepare_lookup_album_photo(path, "card")
        assert out == path
        assert not os.path.isfile(path + ".hq.jpg")


def test_prepare_still_converts_true_png():
    from PIL import Image

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "true.png")
        Image.new("RGB", (640, 800), (245, 247, 250)).save(path, "PNG")
        out = WayneTelegramBot._prepare_lookup_album_photo(path, "card")
        assert out != path
        assert out.endswith(".hq.jpg")
        with Image.open(out) as im:
            assert im.format == "JPEG"
            assert im.size == (640, 800)


def test_boot_warmup_uses_paint_worker_not_bare_pack():
    import main as main_mod

    src = inspect.getsource(main_mod.run_web)
    assert "run_mpl_paint" in src
    assert "prewarm_card_fonts" in src
    assert "_tiny_agg" in src or "_boot_warm" in src
    # 不准再裸呼叫 render_stock_pack（繞過 worker 搶鎖）
    warm_block = src[src.index("def _warmup_charts") : src.index("chart-warmup")]
    assert "render_stock_pack" not in warm_block
    assert "run_mpl_paint" in warm_block


def test_lookup_timeouts_not_lengthened():
    import bot_servers as bs

    assert float(bs._CARD_BUILD_TIMEOUT) <= 90.0
    assert float(bs._CHART_RENDER_TIMEOUT) <= 120.0
    assert float(bs._LOOKUP_PNG_TIMEOUT) <= 120.0


def test_timedout_still_no_resend():
    src = inspect.getsource(WayneTelegramBot._reply_lookup_photo)
    assert "視同已送達" in src
    assert "for attempt in range(3)" not in src


def test_send_card_still_four_kinds_not_two_only():
    """使用者否決「查股只自動兩張」；冷啟加速不准改成兩張。"""
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert 'render_plan_kinds = ("card", "glance", "struct", "vol")' in src
    assert "_struct_item" in src
    assert "_vol_item" in src
