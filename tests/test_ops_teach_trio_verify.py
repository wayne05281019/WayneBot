# -*- coding: utf-8 -*-
"""POST /ops/teach-trio-verify：不搶 getUpdates，只驗 preflight＋渲圖結果。"""
from __future__ import annotations

import inspect

import main as main_mod
from biaoke_level_learn import ops_verify_teach_trio


def test_ops_teach_trio_route_wired():
    src = inspect.getsource(main_mod.HealthHandler.do_POST)
    assert "/ops/teach-trio-verify" in src
    assert "ops_verify_teach_trio" in src
    assert "不搶 getUpdates" in inspect.getsource(ops_verify_teach_trio) or (
        "getUpdates" in inspect.getsource(ops_verify_teach_trio)
    )


def test_ops_verify_teach_trio_helper_preflight_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "biaoke_level_learn.run_teach_trio_preflight_pipeline",
        lambda *_a, **_k: {"ok": False, "fail_bits": ["缺電子盤 tip"]},
    )
    out = ops_verify_teach_trio(str(tmp_path / "x.db"))
    assert out["ok"] is False
    assert out["stage"] == "preflight"
    assert "缺電子盤 tip" in (out.get("fail_bits") or [])


def test_ops_verify_teach_trio_helper_paint_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "biaoke_level_learn.run_teach_trio_preflight_pipeline",
        lambda *_a, **_k: {"ok": True, "pack": {"chart_as_of": "20261113"}},
    )
    monkeypatch.setattr(
        "biaoke_level_learn.compute_teach_tip_snapshot",
        lambda *_a, **_k: {
            "tw_asof": "20261113",
            "tw_close": 43675.0,
            "tx_asof": "20261113",
            "tx_close": 43706.0,
            "sox_asof": "20261113",
            "sox_close": 10146.0,
        },
    )

    def _paint(*_a, **_k):
        # 假路徑：bytes 檢查用真小檔
        d = tmp_path / "p"
        d.mkdir(exist_ok=True)
        paths = {}
        for name in ("far", "near", "micro"):
            p = d / f"{name}.png"
            p.write_bytes(b"0" * 5000)
            paths[f"{name}_path"] = str(p)
        return {"ok": True, "slot_id": "force-test", **paths}

    monkeypatch.setattr("biaoke_level_learn.paint_open_day_hypothesis", _paint)
    out = ops_verify_teach_trio(str(tmp_path / "x.db"))
    assert out["ok"] is True
    assert out["stage"] == "done"
    assert out["tip"]["tx_close"] == 43706.0
    assert out["bytes"]["micro_path"] >= 4000
