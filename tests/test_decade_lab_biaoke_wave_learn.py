# -*- coding: utf-8 -*-
from scripts.decade_lab_biaoke_wave_learn import _five_tags, WAVE_NEURONS_MATCH
from scripts.decade_lab_wave8_dual import snapshot_wave_asof, _pivots


def test_five_tags_detect_wave_and_fractal():
    tags = _five_tags("細微波碎形線確認，量價結構與關鍵K都到了，平台頸線觀察")
    assert "wave" in tags
    assert "vol" in tags or "morph" in tags


def test_wave_neurons_blocked():
    assert WAVE_NEURONS_MATCH is False


def test_snapshot_wave_asof_smoke():
    bars = []
    px = 100.0
    for i in range(80):
        ymd = f"{20240101 + i}"
        px = px + (1.5 if (i // 5) % 2 == 0 else -1.0)
        bars.append({"date": ymd, "open": px, "high": px + 1, "low": px - 1, "close": px, "volume": 1})
    piv = _pivots(bars, look=2)
    out = snapshot_wave_asof(bars, piv, bars[-1]["date"])
    assert "bias" in out
    assert out.get("phone_sync") == "blocked" or out.get("ok") in {True, False}
