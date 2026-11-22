"""11/16 飆大：波浪4帶 41800～42700＋細微C・1 4重疊 → 三窗題旨／標線（非買訊）。"""

from __future__ import annotations


def test_looks_like_level_wave4_band():
    from biaoke_level_learn import looks_like_level_now

    assert looks_like_level_now(
        "大盤已經到41800~42700區間了，也就是回測上漲小5波結束回測波浪4的點位區間了。"
        "台指期是還沒跌完"
    )


def test_wave4_oral_snip_has_band_and_c14():
    from biaoke_level_learn import (
        _WAVE4_BAND_418_427_ORAL_SNIP,
        _parse_retest_band_lo_hi,
        _text_has_micro_c_14_overlap,
        _text_has_wave4_band_418_427,
        _text_denies_second_foot_38000,
    )

    snip = _WAVE4_BAND_418_427_ORAL_SNIP
    assert _text_has_wave4_band_418_427(snip)
    assert _text_has_micro_c_14_overlap(snip)
    assert _text_denies_second_foot_38000(snip)
    assert _parse_retest_band_lo_hi(snip) == (41800.0, 42700.0)


def test_wave4_overrides_419_band_in_parse_order():
    from biaoke_level_learn import (
        _LOW_BAND_419_427_ORAL_SNIP,
        _WAVE4_BAND_418_427_ORAL_SNIP,
        _parse_retest_band_lo_hi,
    )

    blob = f"{_LOW_BAND_419_427_ORAL_SNIP} {_WAVE4_BAND_418_427_ORAL_SNIP}"
    assert _parse_retest_band_lo_hi(blob) == (41800.0, 42700.0)


def test_wave4_band_painter_wired_on_trio():
    import inspect

    import biaoke_level_learn as m

    assert hasattr(m, "_paint_wave4_retest_band")
    near = inspect.getsource(m._render_twii_live_dark)
    # 超近窗薄包一層 → 實際畫在 _render_twii_c_wave_60_dark
    micro = inspect.getsource(m._render_twii_c_wave_60_dark)
    far = inspect.getsource(m._render_twii_far_dark)
    assert "_paint_wave4_retest_band" in near
    assert "_paint_wave4_retest_band" in micro
    assert "_paint_wave4_retest_band" in far


def test_wave4_ladder_and_preds_from_live_db():
    from datetime import datetime
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import _build_live_pack, _wave_now_ladder

    db = Path(__file__).resolve().parents[1] / "data" / "wayne_market.db"
    if not db.is_file():
        import pytest

        pytest.skip("no local wayne_market.db")
    # 題旨 cap 跟加權已收／最新他文走；庫內若已有 11/20 修正目標，後文壓前文＝波浪4不再當令
    now = datetime(2026, 11, 16, 13, 20, tzinfo=ZoneInfo("Asia/Taipei"))
    pack = _build_live_pack(str(db), now=now)
    thesis = str(pack.get("thesis") or "")
    wait = str(pack.get("wait_struct") or "")
    ladder = _wave_now_ladder(pack)
    if "修正目標35000" in thesis or "35000～35500" in thesis:
        assert "波浪4帶" not in thesis
        assert "35,000" in wait and "35,500" in wait
        assert "非買訊" in wait
        assert "修正目標35000～35500" in str(ladder.get("chain") or "")
        assert "波浪4帶" not in str(ladder.get("one_line") or "")
        return
    assert "波浪4帶" in thesis
    assert "41,800" in wait and "42,700" in wait
    assert "1 4重疊" in wait
    assert "非買訊" in wait
    roles = {
        str(r.get("role")): float(r.get("level"))
        for r in ((pack.get("pred_levels") or {}).get("tw") or [])
    }
    assert abs(roles.get("回測最低", 0) - 41800.0) < 0.6
    assert abs(roles.get("回測平均", 0) - 42250.0) < 0.6
    assert abs(roles.get("回測上沿", 0) - 42700.0) < 0.6
    assert "波浪4帶" in str(ladder.get("chain") or "")
    assert "波浪4帶" in str(ladder.get("one_line") or "")
    assert "止跌確認・已過C3下降壓" not in str(ladder.get("one_line") or "")
    assert "細微C" in str(ladder.get("chain") or "") or "1 4重疊" in str(
        ladder.get("oral_now") or ladder.get("now_line") or ladder.get("teach_box") or ""
    )
