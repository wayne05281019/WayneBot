# -*- coding: utf-8 -*-
"""BK-VERIFY：三層鏈／位碰／試標段自測＋§13 再生鍵。"""
from __future__ import annotations

import json
from pathlib import Path

import observe_verify as ov

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual" / "cases"
OUT = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"


def test_score_level_incomplete_bar_is_open():
    bars = [
        {"date": "20260101", "open": 100, "high": 101, "low": 99, "close": 100, "ohlc_complete": True},
        {"date": "20260102", "open": 100, "high": 100, "low": 100, "close": 100, "ohlc_complete": False},
        {"date": "20260103", "open": 100, "high": 102, "low": 98, "close": 101, "ohlc_complete": True},
    ]
    verd, ok = ov.score_level_vs_fwd(99.0, "break", bars, 0, fwd=2, tol_pct=0.0)
    assert verd == "未完" and ok is None


def test_score_level_break_hit():
    bars = [
        {"date": "20260101", "open": 100, "high": 101, "low": 99, "close": 100, "ohlc_complete": True},
        {"date": "20260102", "open": 100, "high": 102, "low": 95, "close": 96, "ohlc_complete": True},
        {"date": "20260103", "open": 96, "high": 97, "low": 94, "close": 95, "ohlc_complete": True},
    ]
    verd, ok = ov.score_level_vs_fwd(98.0, "break", bars, 0, fwd=2, tol_pct=0.0)
    assert verd == "對" and ok is True


def test_empty_levels_skipped():
    row = ov.grade_level_touch_case(
        {"case_id": "e", "track": "level_touch", "as_of": "20260101", "levels": []},
        [{"date": "20260101", "open": 1, "high": 1, "low": 1, "close": 1, "ohlc_complete": True}],
    )
    assert row["verdict"] == "空名單"
    assert row["ok"] is None
    scored = ov.score_rows([row])
    assert scored["n_decided"] == 0
    assert scored["empty_skipped"] == 1


def test_segment_bias_fixture_m3_hit():
    case = json.loads((CASES / "case_segment_bias_20261120.json").read_text(encoding="utf-8"))
    row = ov.grade_segment_bias_case(case)
    assert row["verdict"] == "對"
    assert row["ok"] is True
    assert row["preferred"] == "M3_seek_37837_continue"
    # W4 應否決（偏）
    w4 = next(p for p in row["paths"] if p["id"] == "W4_reclaim_418_427_band")
    assert w4["ok"] is False


def test_miss_analysis_hook_and_next_variant():
    case = {
        "case_id": "seg_miss",
        "track": "segment_bias",
        "as_of": "20261120",
        "preferred": "W4_reclaim_418_427_band",
        "official_bar": {
            "open": 37646.13,
            "high": 37646.13,
            "low": 35738.68,
            "close": 36033.29,
        },
        "paths": [
            {
                "id": "W4_reclaim_418_427_band",
                "levels": {"lo": 41800.0, "hi": 42700.0},
                "segments_provisional": [],
            }
        ],
    }
    row = ov.grade_segment_bias_case(case)
    assert row["verdict"] == "偏"
    assert row["ok"] is False
    miss = row["miss_analysis"]
    assert miss["next_variant"] == ov.VARIANT_NEXT
    assert "不准混" in miss["mix_forbidden_zh"]
    assert miss["case_id"] == "seg_miss"


def test_chain_trio_with_embedded_bars():
    case = {
        "case_id": "chain_embed",
        "track": "chain_trio",
        "as_of": "20261105",
        "expect_chain": "down",
        "overnight": {"regime": "risk_off", "sox_pct": -9.9, "nq_f_pct": None},
        "tx_bar": {"open": 43013.0, "high": 43114.0, "low": 41666.0, "close": 41915.0},
        "twii_bar": {"open": 42666.13, "high": 42873.81, "low": 41513.57, "close": 41574.72},
    }
    row = ov.grade_chain_trio_case(
        case, overnight_map={}, tx_regular=[], twii=[]
    )
    assert row["verdict"] == "對"
    assert row["ok"] is True
    assert row["layers"]["night_bias"] == "down"


def test_variant_keys_distinct_section13():
    assert ov.VARIANT_CURRENT == "bk_verify_v1_trio_level_seg"
    assert ov.VARIANT_NEXT == "bk_verify_v2_chain_sox_strict"
    assert ov.VARIANT_NEXT_PHONE == "bk_verify_v3_phone_brief_stamp"
    assert ov.VARIANT_CURRENT != ov.VARIANT_NEXT
    assert ov.VARIANT_NEXT != ov.VARIANT_NEXT_PHONE
    assert ov.PHONE_SYNC == "blocked"
    assert ov.PHONE_DISCLAIMER == "試標・推論／非他原文・非買訊・對質未過閘"


def test_phone_stamp_ok_clean():
    case = json.loads((CASES / "case_phone_stamp_ok.json").read_text(encoding="utf-8"))
    row = ov.grade_phone_stamp_case(case)
    assert row["verdict"] == "對"
    assert row["ok"] is True
    assert row["violations"] == []
    assert row["phone_sync"] == "blocked"
    assert row["buy_signal"] is False


def test_phone_stamp_backflow_detected():
    case = json.loads((CASES / "case_phone_stamp_backflow.json").read_text(encoding="utf-8"))
    row = ov.grade_phone_stamp_case(case)
    assert row["verdict"] == "對"  # 偵測器抓到預期違規＝本題對
    assert row["ok"] is True
    assert "backflow" in row["found_codes"]
    assert "miss_analysis" not in row


def test_phone_stamp_layer_and_futures_and_invent():
    for name, code in (
        ("case_phone_stamp_layer_skip.json", "layer_order"),
        ("case_phone_stamp_futures_spot.json", "futures_spot_mix"),
        ("case_phone_stamp_invent_level.json", "invented_level"),
    ):
        case = json.loads((CASES / name).read_text(encoding="utf-8"))
        row = ov.grade_phone_stamp_case(case)
        assert row["ok"] is True, name
        assert code in row["found_codes"], (name, row["found_codes"])


def test_phone_stamp_buy_sync_disclaimer_leak():
    case = json.loads((CASES / "case_phone_stamp_buy_leak.json").read_text(encoding="utf-8"))
    row = ov.grade_phone_stamp_case(case)
    assert row["ok"] is True
    for code in ("buy_signal_leak", "phone_sync_leak", "missing_disclaimer"):
        assert code in row["found_codes"]


def test_phone_stamp_miss_when_detector_blind():
    """預期有 backflow 卻給乾淨 stamp → 偏＋miss_analysis→v3。"""
    case = {
        "case_id": "phone_blind",
        "track": "phone_stamp",
        "as_of": "20261105",
        "expect_ok": False,
        "expect_violations": ["backflow"],
        "his_levels": [41760.0],
        "brief": "乾淨",
        "observe_slot": ov.PHONE_DISCLAIMER,
        "stamp": {
            "disclaimer_present": True,
            "phone_sync": "blocked",
            "buy_signal": False,
            "layers_order": ["L1", "L2", "L3"],
            "layer1_hypothesis": "bias_down",
            "layer2_verdict": "confirm",
            "layer3_verdict": "pending",
            "named_levels": [{"level": 41760.0, "source": "oral"}],
        },
    }
    row = ov.grade_phone_stamp_case(case)
    assert row["verdict"] == "偏"
    assert row["ok"] is False
    miss = row["miss_analysis"]
    assert miss["next_variant"] == ov.VARIANT_NEXT_PHONE
    assert miss["not_buy_signal"] is True
    assert "backflow" in (miss.get("which_segment_broke") or "")


def test_phone_stamp_empty_skip():
    row = ov.grade_phone_stamp_case(
        {"case_id": "phone_empty", "track": "phone_stamp", "as_of": "20261105"}
    )
    assert row["verdict"] == "空名單"
    assert row["ok"] is None


def test_run_suite_writes_verify_latest(tmp_path: Path):
    out = tmp_path / "out"
    cases = tmp_path / "cases"
    cases.mkdir()
    # 最小可跑：segment（嵌官方柱）＋空名單
    (cases / "a.json").write_text(
        (CASES / "case_segment_bias_20261120.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (cases / "b.json").write_text(
        (CASES / "case_empty_skip.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # 不准依賴 CI／本機是否有完整 wayne_market.db（smoke 常缺 index_daily）
    summary = ov.run_suite(
        db_path=tmp_path / "missing_wayne_market.db",
        cases_dir=cases,
        out_dir=out,
        write=True,
    )
    assert summary["phone_sync"] == "blocked"
    assert summary["buy_signal"] is False
    assert summary["current_variant"] == ov.VARIANT_CURRENT
    assert summary["next_variant"]["variant"] == ov.VARIANT_NEXT
    assert summary["next_variant"]["parallel_next"]["variant"] == ov.VARIANT_NEXT_PHONE
    assert summary["next_variant_phone"] == ov.VARIANT_NEXT_PHONE
    assert (out / "verify_latest.json").is_file()
    assert (out / "verify_latest.md").is_file()
    blob = json.loads((out / "verify_latest.json").read_text(encoding="utf-8"))
    assert "mix_forbidden_zh" in blob
    assert blob["gate"]["replace"] is False
    assert blob["phone_sync"] == "blocked"
