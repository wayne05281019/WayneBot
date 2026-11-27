"""林友銘 Drive 登錄骨架（獨立於 huang；非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_drive_ids_and_parse_name():
    from lin_youming import (
        LIN_DRIVE_FOLDER_ID_DEFAULT,
        LIN_DRIVE_KNOWN_IDS,
        drive_folder_id,
        extract_teach_tags,
        parse_drive_name_ymd,
        resolve_drive_file_id,
    )

    assert LIN_DRIVE_FOLDER_ID_DEFAULT == "1SIJ_PBvu6-Sck3YGMA0X9MUJM9Po0cKj"
    assert resolve_drive_file_id("20261126") == "1BIzlyfparN_OiSc6WWB-9bCfoWBpKBrw"
    assert LIN_DRIVE_KNOWN_IDS["20261126"] == "1BIzlyfparN_OiSc6WWB-9bCfoWBpKBrw"
    assert drive_folder_id() == LIN_DRIVE_FOLDER_ID_DEFAULT
    assert parse_drive_name_ymd("1126林友銘.mp4", year_hint=2026) == "20261126"
    tags = extract_teach_tags("反彈到0.382 0.618，C走1.382與1.618，奔走B，①④重疊③最短")
    assert "fib382" in tags
    assert "fib618" in tags
    assert "ext1382" in tags
    assert "ext1618" in tags
    assert "running_b" in tags
    assert "overlap_14" in tags
    assert "wave3_shortest" in tags


def test_absorb_notes_exist_and_not_buy_signal():
    notes = ROOT / "docs" / "expert_notes" / "林友銘"
    md = notes / "1126_absorb.md"
    js = notes / "1126_absorb.json"
    tr = notes / "1126_transcript.md"
    assert md.is_file()
    assert js.is_file()
    assert tr.is_file()
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data.get("buy_signal") is False
    assert data.get("not_buy_signal") is True
    assert data.get("phone_sync") == "blocked"
    assert data["source"]["drive_file_id"] == "1BIzlyfparN_OiSc6WWB-9bCfoWBpKBrw"
    assert 1.618 in data["fib_ratios_he_used"]["extension_c_of_a"]
    assert 0.618 in data["fib_ratios_he_used"]["retrace_bounce_mentioned_oral"]
    # 官方對質錨存在且閘門未過
    confront = data["official_ohlc_confront"]
    assert confront["bars"]["B_high"]["high"] > 49900
    assert confront["bars"]["C_low"]["low"] < 36000
    assert "n≥20" in confront["gate"] or "n_episode=1" in confront["gate"]


def test_not_mixed_into_huang_module():
    """林友銘路徑獨立；huang 已知 id 不含 1126林友銘。"""
    from huang_youtube import HUANG_DRIVE_KNOWN_IDS
    from lin_youming import LIN_DRIVE_KNOWN_IDS

    assert "1BIzlyfparN_OiSc6WWB-9bCfoWBpKBrw" not in HUANG_DRIVE_KNOWN_IDS.values()
    assert LIN_DRIVE_KNOWN_IDS["20261126"] == "1BIzlyfparN_OiSc6WWB-9bCfoWBpKBrw"
