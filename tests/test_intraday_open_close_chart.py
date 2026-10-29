# -*- coding: utf-8 -*-
"""當天走勢圖（查股第 5 張）正式入口：市場解析／缺路徑不上假圖／接線存在。"""
from __future__ import annotations

import inspect
import os

from bot_servers import WayneTelegramBot, _LOOKUP_CHART_KINDS
from intraday_open_close_chart import (
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
