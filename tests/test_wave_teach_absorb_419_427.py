"""11/12 飆大點名低點帶 41900～42700 必須落進 absorb／forward（非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"


def _load(name: str) -> dict:
    return json.loads((LAB / name).read_text(encoding="utf-8"))


def test_absorb_has_t11_named_bottom_band():
    d = _load("wave_teach_absorb_20261112.json")
    methods = {m["id"]: m for m in d["today_teach_methods"]}
    assert "T11_named_bottom_band_419_427" in methods
    band = methods["T11_named_bottom_band_419_427"]["band"]
    assert band["lo"] == 41900.0 and band["hi"] == 42700.0
    assert d.get("buy_signal") is False
    assert d.get("phone_sync") == "blocked"
    texts = " ".join(x.get("text", "") for x in d["source"]["self_replies_key"])
    assert "41900~42700" in texts or "41900～42700" in texts


def test_absorb_has_i8_vol_cluster_infer():
    d = _load("wave_teach_absorb_20261112.json")
    inf = {i["id"]: i for i in d["infer_first_then_verify"]["inferences"]}
    assert "I8_bottom_band_vol_cluster" in inf
    assert inf["I8_bottom_band_vol_cluster"].get("not_buy_signal") is True
    latest = _load("wave_teach_absorb_latest.json")
    assert any(
        i.get("id") == "I8_bottom_band_vol_cluster"
        for i in latest["infer_first_then_verify"]["inferences"]
    )


def test_forward_has_n4_band_path():
    d = _load("wave_forward_infer_20261113.json")
    paths = {p["id"]: p for p in d["paths"]}
    assert "N4_test_419_427_vol_band" in paths
    assert paths["N4_test_419_427_vol_band"]["levels"]["band_lo"] == 41900.0
    assert paths["N4_test_419_427_vol_band"]["levels"]["band_hi"] == 42700.0
    assert d.get("preferred_infer") == "I8_bottom_band_vol_cluster"
    assert d.get("phone_sync") == "blocked"
    assert d.get("not_buy_signal") is True
