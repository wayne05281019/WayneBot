"""11/20 飆大：修正目標 35000～35500 → 三窗題旨／標線（非買訊；壓波浪4／下降壓）。"""

from __future__ import annotations


def test_text_has_target_350_355():
    from biaoke_level_learn import (
        _TARGET_350_355_ORAL_SNIP,
        _text_has_target_350_355,
        _text_has_wave4_band_418_427,
    )

    snip = _TARGET_350_355_ORAL_SNIP
    assert _text_has_target_350_355(snip)
    assert not _text_has_wave4_band_418_427(snip)
    assert not _text_has_target_350_355("今天聊天氣很好")
    assert _text_has_target_350_355(
        "目前我看到的大盤要修正到35000~35500之間，真正的低點會在35000~35500之間"
    )


def test_target_overrides_wave4_in_thesis_branch():
    from biaoke_level_learn import (
        _TARGET_350_355_ORAL_SNIP,
        _WAVE4_BAND_418_427_ORAL_SNIP,
        _text_has_target_350_355,
        _text_has_wave4_band_418_427,
    )

    blob = f"{_WAVE4_BAND_418_427_ORAL_SNIP} {_TARGET_350_355_ORAL_SNIP}"
    assert _text_has_target_350_355(blob)
    assert _text_has_wave4_band_418_427(blob)


def test_target_band_painter_wired_on_trio():
    import inspect

    import biaoke_level_learn as m

    assert hasattr(m, "_paint_target_350_355_band")
    near = inspect.getsource(m._render_twii_live_dark)
    micro = inspect.getsource(m._render_twii_c_wave_60_dark)
    far = inspect.getsource(m._render_twii_far_dark)
    assert "_paint_target_350_355_band" in near
    assert "_paint_target_350_355_band" in micro
    assert "_paint_target_350_355_band" in far
    # 當令時波浪4帶 paint 必須可跳過
    w4 = inspect.getsource(m._paint_wave4_retest_band)
    assert "_text_has_target_350_355" in w4


def test_target_ladder_and_preds_from_live_db():
    from datetime import datetime
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import _active_oral_now_line, _build_live_pack, _wave_now_ladder
    from biaoke_digest import format_teach_brief

    db = Path(__file__).resolve().parents[1] / "data" / "wayne_market.db"
    if not db.is_file():
        import pytest

        pytest.skip("no local wayne_market.db")
    now = datetime(2026, 11, 22, 17, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    pack = _build_live_pack(str(db), now=now)
    thesis = str(pack.get("thesis") or "")
    wait = str(pack.get("wait_struct") or "")
    assert "修正目標35000" in thesis or "35000～35500" in thesis
    assert "波浪4帶" not in thesis
    assert "35,000" in wait and "35,500" in wait
    assert "非買訊" in wait
    oral = _active_oral_now_line(pack)
    assert "修正目標" in oral
    assert "絕對不破週五低37837" not in oral
    roles = {
        str(r.get("role")): float(r.get("level"))
        for r in ((pack.get("pred_levels") or {}).get("tw") or [])
    }
    assert abs(roles.get("修正目標下沿", 0) - 35000.0) < 0.6
    assert abs(roles.get("修正目標上沿", 0) - 35500.0) < 0.6
    tags = {
        str(r.get("role")): str(r.get("tag") or "")
        for r in ((pack.get("pred_levels") or {}).get("tw") or [])
    }
    if "五波末／週五低" in tags:
        assert tags["五波末／週五低"] == "已測破"
    ladder = _wave_now_ladder(pack)
    assert "修正目標35000～35500" in str(ladder.get("chain") or "")
    assert "波浪4帶" not in str(ladder.get("one_line") or "")
    brief = format_teach_brief(str(db), pack)
    assert "35000" in brief and "35500" in brief
    assert "波浪4帶" not in brief
    assert "絕對不破" not in brief


def test_focus_skips_stale_pressure_when_target_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_digest import _apply_pressure_break_oral_to_board

    clock = datetime(2026, 11, 22, 18, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    board = "唯一錯誤 就是這次反彈是小時線是5波推升結構"
    blob = (
        "目前我看到的大盤要修正到35000~35500之間。"
        "真正的低點會在35000~35500之間。"
    )
    out = _apply_pressure_break_oral_to_board(
        board, blob=blob, db_path="", now=clock
    )
    assert "下降壓力線" not in out
    assert "唯一錯誤" in out
