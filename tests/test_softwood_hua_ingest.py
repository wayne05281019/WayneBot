"""Softwood Hua ingest helpers — no network in unit tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "scripts" / "softwood_hua_ingest_day.py"


def _load():
    spec = importlib.util.spec_from_file_location("softwood_hua_ingest_day", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_asof_and_dot_date():
    m = _load()
    assert m._asof_day("2026-11-20") == "20261120"
    assert m._asof_day("20261120") == "20261120"
    assert m._dot_date("20261120") == "26.11.20"
    with pytest.raises(SystemExit):
        m._asof_day("bad")


def test_vtt_to_text_dedupes():
    m = _load()
    vtt = Path("/tmp/softwood_hua_test.vtt")
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n你好\n\n00:00:02.000 --> 00:00:03.000\n你好\n\n00:00:03.000 --> 00:00:04.000\n軟木華\n",
        encoding="utf-8",
    )
    text = m._vtt_to_text(vtt)
    assert text == "你好\n軟木華"


def test_absorb_scaffold_marks_not_buy():
    import json

    p = ROOT / "docs" / "expert_notes" / "軟木華" / "decade_lab" / "softwood_hua_oral_absorb_20261120.json"
    row = json.loads(p.read_text(encoding="utf-8"))
    assert row["track"] == "softwood_hua"
    assert row["not_buy_signal"] is True
    assert row["phone_sync"] == "blocked"
    assert row["buy_signal"] is False
    assert row["criteria_today"]["hard_rules"] == []
    assert row["ingest"]["transcript"] == ""
    blob = json.dumps(row, ensure_ascii=False)
    assert "leave_zero" in blob  # lock text forbids changing it
    assert "不准改 leave_zero" in blob
    assert row.get("segment_numbers") == "FORBIDDEN_for_stocks"
