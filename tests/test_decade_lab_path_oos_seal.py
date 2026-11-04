# -*- coding: utf-8 -*-
from scripts.decade_lab_path_oos_seal import run


def test_path_oos_seal_run_writes_gate():
    out = run()
    assert out["not_buy_signal"] is True
    assert out["phone_sync"] == "blocked"
    assert out["next_key"] == "path_oos_seal_vnext"
    seal = out["seal"]
    assert "seal_ok" in seal
    # 現況摘要 scored≈24 → 封印未過；不准boast
    if (out.get("summary_directional_n") or 0) < 40:
        assert seal["seal_ok"] is False
    if out.get("summary_hit_rate_directional") == 1.0:
        assert out["boast_dir_100_blocked"] is True
