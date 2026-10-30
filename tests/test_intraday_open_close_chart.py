# -*- coding: utf-8 -*-
"""當天走勢圖（查股第 5 張）正式入口：市場解析／缺路徑不上假圖／接線存在。"""
from __future__ import annotations

import inspect
import os

from bot_servers import WayneTelegramBot, _LOOKUP_CHART_KINDS
from intraday_open_close_chart import (
    _CHART_LABEL_FS_SCALE,
    _GRID_FS_SCALE,
    _chart_label_fs,
    _grid_fs,
    _paint_smart_level_labels,
    _y_price_tick_band,
    resolve_intraday_asof_ymd,
    resolve_intraday_market,
    render_lookup_intraday_result,
)


def test_lookup_chart_kinds_include_intraday():
    assert "intraday" in _LOOKUP_CHART_KINDS


def test_send_card_wires_fifth_intraday():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "_intraday_item" in src
    assert "render_lookup_intraday_result" in src
    assert 'render_plan_kinds = ("card", "glance", "struct", "vol", "intraday")' in src
    # 第 5 張不掛 hub
    assert src.index("_intraday_item") > src.index("_vol_item")
    assert "當天走勢" in src


def test_progress_mentions_intraday():
    txt = WayneTelegramBot._chart_progress_text(
        12, sent=["card", "glance", "struct", "vol"], current="intraday"
    )
    assert "當天走勢" in txt


def test_resolve_market_from_hits_em():
    assert (
        resolve_intraday_market(
            "3595", hits=[{"stock_id": "3595", "market": "EM"}]
        )
        == "EM"
    )


def test_resolve_market_from_hits_two():
    assert (
        resolve_intraday_market(
            "6274", hits=[{"stock_id": "6274", "market": "TWO"}]
        )
        == "TWO"
    )


def test_resolve_asof_ymd_prefer():
    assert resolve_intraday_asof_ymd(prefer="2026-10-29") == "20261029"


def test_render_lookup_empty_without_series(tmp_path):
    """無真官方／分時 → 回空，不准假圖。"""
    out = os.path.join(tmp_path, "x.png")
    path, cap = render_lookup_intraday_result(
        "0000",
        "無此檔",
        db_path=os.path.join(tmp_path, "missing.db"),
        save_path=out,
        market="TW",
        asof_ymd="20261029",
    )
    assert path == ""
    assert cap == ""
    assert not os.path.isfile(out)


def test_prefer_asof_does_not_fallback_previous_day(tmp_path, monkeypatch):
    """高低卡指定日缺路徑 → 回空；不准默默退前一開市日換成錯日戳。"""
    calls: list[str] = []

    def _fake_build(sid, name, mkt, db_path=None, ymd=None):
        calls.append(str(ymd or ""))
        return None

    monkeypatch.setattr(
        "intraday_open_close_chart.build_series", _fake_build
    )
    out = os.path.join(tmp_path, "prefer.png")
    path, cap = render_lookup_intraday_result(
        "8234",
        "新漢",
        db_path=os.path.join(tmp_path, "x.db"),
        save_path=out,
        market="TWO",
        asof_ymd="20261030",
        card={"latest_date": "20261030"},
    )
    assert path == ""
    assert cap == ""
    assert calls == ["20261030"]


def test_send_card_passes_card_asof_to_intraday():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "latest_date" in src
    assert "asof_ymd=asof or None" in src
    assert "series is None and not prefer" in inspect.getsource(
        render_lookup_intraday_result
    )


def test_grid_a_chart_label_b_scales():
    """十二宮格 A(+30%)；走勢圖智能標 B(+50%)；頭欄不准吃這兩條。"""
    assert abs(_GRID_FS_SCALE - 1.30) < 1e-9
    assert abs(_CHART_LABEL_FS_SCALE - 1.50) < 1e-9
    assert abs(_grid_fs(10) - 13.0) < 1e-9
    assert abs(_chart_label_fs(10) - 15.0) < 1e-9
    src = inspect.getsource(_paint_smart_level_labels)
    assert "_y_price_tick_band" in src
    assert "tick_band" in src
    assert "tick_clear_x" in src
    assert "_chart_label_fs" in src
    assert "_grid_fs(9.5)" in inspect.getsource(
        __import__("intraday_open_close_chart", fromlist=["_paint_quote_grid"])._paint_quote_grid
    )


def test_y_price_tick_band_covers_left_gutter():
    class _Ax:
        def get_xlim(self):
            return (0.0, 270.0)

        def get_ylim(self):
            return (58.0, 61.5)

    band = _y_price_tick_band(_Ax(), x_span=270.0, y_span=3.5)
    assert band[0] == 0.0
    # 開盤貼左後禁區極窄，不准再吃進圖內
    assert 0.0 <= band[1] <= 3.0
    assert band[2] == 58.0
    assert band[3] == 61.5


def test_x_label_pad_keeps_open_near_price_ticks():
    """開盤貼軸左；股價刻度畫在軸外，不准再留左 gutter 空白。"""
    import inspect as _ins

    src = _ins.getsource(
        __import__("intraday_open_close_chart", fromlist=["render_path"]).render_path
    )
    assert "x_label_pad = 0.0" in src
    assert "0.125" not in src.split("x_label_pad", 1)[-1][:160]
    assert "-0.012" in src
    assert 'ha="right"' in src
