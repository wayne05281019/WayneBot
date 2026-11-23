# -*- coding: utf-8 -*-
"""BK-PHONE：觀測手冊槽＋波浪位階警語／介面穩定。"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from observe_manual import (
    OBSERVE_PHONE_DISCLAIMER,
    format_wave_observe_slot,
    load_mission_lock_blurb,
    load_observe_atoms,
    load_observe_chain,
    merge_wave_phone_html,
    missing_manual_files,
)


def test_disclaimer_locked():
    assert OBSERVE_PHONE_DISCLAIMER == "試標・推論／非他原文・非買訊・對質未過閘"


def test_slot_placeholder_without_atoms(tmp_path: Path):
    slot = format_wave_observe_slot(root=tmp_path)
    assert "觀測手冊摘要／今日觀測" in slot
    assert OBSERVE_PHONE_DISCLAIMER in slot
    assert "三層鏈" in slot
    assert "觀測原子" in slot
    assert "黃金買點" in slot
    # 不准離開敘事／買訊語氣
    assert "離開" not in slot or "離開敘事" not in slot


def test_slot_reads_atoms_and_chain(tmp_path: Path):
    (tmp_path / "observe_atoms.json").write_text(
        json.dumps(
            {
                "atoms": [
                    {"title": "鐵律", "summary": "1–4 不重疊"},
                    {"title": "SOX", "text": "費半連動確認"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "observe_chain.json").write_text(
        json.dumps(
            {
                "steps": [
                    {"label": "夜盤", "check": "e-mini 方向"},
                    {"label": "早盤 TX", "note": "確認夜盤"},
                    {"label": "現貨加權", "text": "驗證＋SOX"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    atoms = load_observe_atoms(root=tmp_path)
    chain = load_observe_chain(root=tmp_path)
    assert atoms["ok"] and len(atoms["atoms"]) == 2
    assert chain["ok"] and len(chain["steps"]) == 3
    slot = format_wave_observe_slot(root=tmp_path)
    assert "1–4 不重疊" in slot
    assert "夜盤" in slot
    assert OBSERVE_PHONE_DISCLAIMER in slot
    # 原子／鏈齊了就不報那兩檔；MISSION_LOCK 可另放
    miss = missing_manual_files(root=tmp_path)
    assert "observe_atoms.json" not in miss
    assert "observe_chain.json" not in miss


def test_merge_includes_brief_and_slot():
    html = merge_wave_phone_html("<b>波浪位階・預估・非買訊</b>\n目前落在：測試")
    assert "波浪位階" in html
    assert "觀測手冊摘要／今日觀測" in html
    assert OBSERVE_PHONE_DISCLAIMER in html


def test_mission_lock_blurb_from_repo():
    blurb = load_mission_lock_blurb()
    assert "TX" in blurb or "夜盤" in blurb


def test_wave_status_cmd_wires_observe_slot():
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot.wave_status_cmd)
    assert "merge_wave_phone_html" in src
    assert "試標・推論／非他原文・非買訊・對質未過閘" in src
    # 先文後圖：合槽後再送三窗
    assert src.index("merge_wave_phone_html") < src.index("_send_market_wave_charts")
    assert "leave_zero" not in src.lower() or "黃金" not in src
