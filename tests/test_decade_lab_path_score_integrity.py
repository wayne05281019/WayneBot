# -*- coding: utf-8 -*-
import json
from pathlib import Path

from scripts.decade_lab_path_forecast import _next_gates, _oos_holdout, _sample_audit
from scripts.decade_lab_path_score_integrity import run_integrity


def _mk(n: int):
    rows = []
    for i in range(n):
        day = f"2026{1 + i // 28:02d}{(i % 28) + 1:02d}"
        rows.append(
            {
                "as_of": day,
                "bias": "up" if i % 2 == 0 else "down",
                "amp_class": "small" if i % 5 == 0 else "mid",
                "verdict": "對得上往上" if i % 3 else "偏了沒往上：x",
                "amp_verdict": (
                    "幅度對得上：估+1 實+1" if i % 2 == 0 else "幅度偏了：估+1 實+3"
                ),
            }
        )
    return rows


def test_sealed_oos_refuses_thin_sample():
    thin = _oos_holdout(_mk(24), holdout_n=20, sealed=True)
    assert thin["ok"] is False
    assert thin["sealed_ok"] is False
    assert thin["holdout_n"] == 0
    assert "不准縮窗" in thin["reason_zh"]


def test_sealed_oos_ok_when_thick():
    # need holdout 20 + in_sample 20 = 40
    thick = _oos_holdout(_mk(40), holdout_n=20, sealed=True)
    assert thick["ok"] is True
    assert thick["sealed_ok"] is True
    assert thick["holdout_n"] == 20
    assert thick["in_sample"]["n"] == 20


def test_legacy_unsealed_still_shrinks():
    legacy = _oos_holdout(_mk(12), holdout_n=5, sealed=False)
    assert legacy["ok"] is True
    assert legacy["holdout_n"] == 3
    assert legacy["sealed_ok"] is False


def test_next_gates_forbid_dir100():
    by_amp = {
        "micro": {"n": 0, "hit": 0, "miss": 0, "hit_rate": None},
        "small": {"n": 5, "hit": 2, "miss": 3, "hit_rate": 0.4},
        "mid": {"n": 7, "hit": 7, "miss": 0, "hit_rate": 1.0},
        "large": {"n": 12, "hit": 12, "miss": 0, "hit_rate": 1.0},
    }
    oos = _oos_holdout(_mk(24), holdout_n=20, sealed=True)
    audit = _sample_audit(
        wrote=5419,
        range_n=5395,
        insuff_n=0,
        soft_range_n=1,
        dir_n=24,
        hit_rate=1.0,
        by_amp_class=by_amp,
        oos=oos,
    )
    gates = _next_gates(audit, oos)
    assert gates["forbid_dir100_claim"] is True
    assert gates["integrity_ok"] is False
    assert gates["phone_sync"] == "blocked"
    ids = {x["id"]: x["ok"] for x in gates["require"]}
    assert ids["small_amp_n20"] is False
    assert ids["oos_sealed_n20"] is False
    assert ids["wave_neurons_match"] is False


def test_run_integrity_writes_latest():
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "docs" / "expert_notes" / "飆客" / "decade_lab"
    summary = json.loads((out_dir / "path_forecast_summary.json").read_text(encoding="utf-8"))
    # 用現況檔跑一次（離線）
    out = run_integrity()
    assert out["track"] == "path_score_integrity_v1"
    assert out["phone_sync"] == "blocked"
    assert out["WAVE_NEURONS_MATCH"] is False
    assert out["gate_integrity"] is False
    assert out["replace"] is False
    assert out["next_variant"]["variant"] == "path_score_integrity_vnext_walkforward"
    assert "forbid_claim_zh" in out["honest_vs_published"]
    latest = out_dir / "path_score_integrity_latest.json"
    assert latest.is_file()
    blob = json.loads(latest.read_text(encoding="utf-8"))
    assert blob["sample_audit"]["integrity_ok"] is False
    # summary 應掛上 integrity 指標
    summary2 = json.loads((out_dir / "path_forecast_summary.json").read_text(encoding="utf-8"))
    assert "next_gates" in summary2
    assert summary2.get("gate_integrity") is False
    assert summary2["path_score_integrity"]["track"] == "path_score_integrity_v1"
    # 不應把舊 dir 滿寫成可上話筒
    assert summary2["phone_sync"] == "blocked"
    # 母檔方向命中率＝封印後誠實數（31/45），不准再鎖死假 1.0
    hr = float(summary.get("hit_rate_directional") or 0)
    assert abs(hr - (31 / 45)) < 1e-9
    assert 0.0 < hr < 1.0
