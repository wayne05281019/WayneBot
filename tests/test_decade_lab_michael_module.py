# -*- coding: utf-8 -*-
from scripts.decade_lab_michael_module import snapshot_michael_factors


def _series_below_ma60_then_gap_south():
    """造 70 根緩跌＋末根 gap_south，讓 MA60 與下影條件可觸發。"""
    twii = {}
    days = []
    px = 22000.0
    # 假日曆：連續 YYYYMMDD（測試用）
    y, m, d = 2025, 1, 1
    for i in range(70):
        day = f"{y}{m:02d}{d:02d}"
        days.append(day)
        px = 22000 - i * 15
        twii[day] = {
            "open": px,
            "high": px + 40,
            "low": px - 30,
            "close": px - 5,
            "ret": -0.1,
            "ret_ok": True,
        }
        d += 1
        if d > 28:
            d = 1
            m += 1
            if m > 12:
                m = 1
                y += 1
    # prior strong
    prev = days[-2]
    twii[prev]["ret"] = 1.8
    # gap south with deep lower wick, close weak
    last = days[-1]
    base = twii[prev]["close"]
    twii[last] = {
        "open": base * 1.01,
        "high": base * 1.012,
        "low": base * 0.96,  # deep wick
        "close": base * 0.985,
        "ret": -1.2,
        "ret_ok": True,
    }
    return twii, days, last


def test_michael_gap_south_and_bounds():
    twii = {}
    for i, d in enumerate(
        [
            "20260102",
            "20260103",
            "20260106",
            "20260107",
            "20260108",
            "20260109",
            "20260110",
            "20260113",
            "20260114",
            "20260115",
            "20260116",
        ]
    ):
        base = 20000 + i * 10
        twii[d] = {
            "open": base,
            "high": base + 80,
            "low": base - 40,
            "close": base + 20,
            "ret": 0.5,
            "ret_ok": True,
        }
    twii["20260115"]["ret"] = 1.8
    twii["20260115"]["close"] = 20180
    twii["20260116"] = {
        "open": 20400,
        "high": 20420,
        "low": 20050,
        "close": 20080,
        "ret": -0.5,
        "ret_ok": True,
    }
    days = sorted(twii)
    f, _m = snapshot_michael_factors(
        twii=twii,
        tx_reg={},
        tx_night={"20260116": 1.2},
        sox={"20260115": {"ret": -2.0, "close": 100, "ret_ok": True}},
        tw_days=days,
        as_of="20260116",
    )
    assert f.get("michael_gap_south") is True
    assert "michael_bound_hi" in f
    assert f.get("michael_gap_south_intraday_down") is True


def test_michael_hard_bounce_variant():
    twii, days, last = _series_below_ma60_then_gap_south()
    f, _m = snapshot_michael_factors(
        twii=twii,
        tx_reg={},
        tx_night={},
        sox={days[-2]: {"ret": -0.2, "close": 1, "ret_ok": True}},
        tw_days=days,
        as_of=last,
        foreign_z=0.2,
    )
    assert f.get("michael_gap_south") is True
    # 季線下＋深下影 → bounce 硬閘變體
    assert f.get("michael_below_ma60") is True
    assert float(f.get("michael_lower_wick") or 0) >= 0.30
    assert f.get("michael_gap_south_bounce") is True
    assert f.get("michael_gap_south_fx_ok") is True
    assert f.get("michael_gap_south_fx_ma") is True  # 外資＋季線下


def test_michael_fx_ma_needs_ma60_or_wick():
    """裸外資仍記 fx_ok；fx_ma 要季線下或下影。"""
    twii = {}
    days = []
    y, m, d = 2025, 1, 1
    for i in range(70):
        day = f"{y}{m:02d}{d:02d}"
        days.append(day)
        px = 24000 + i * 20
        twii[day] = {
            "open": px,
            "high": px + 30,
            "low": px - 10,
            "close": px + 5,
            "ret": 0.2,
            "ret_ok": True,
        }
        d += 1
        if d > 28:
            d = 1
            m += 1
    prev = days[-2]
    last = days[-1]
    base = twii[prev]["close"]
    twii[last] = {
        "open": base * 1.01,
        "high": base * 1.011,
        "low": base * 1.005,
        "close": base * 1.006,
        "ret": -0.4,
        "ret_ok": True,
    }
    f, _ = snapshot_michael_factors(
        twii=twii,
        tx_reg={},
        tx_night={},
        sox={},
        tw_days=days,
        as_of=last,
        foreign_z=0.5,
    )
    assert f.get("michael_gap_south") is True
    assert f.get("michael_gap_south_fx_ok") is True
    assert f.get("michael_below_ma60") is False
    assert float(f.get("michael_lower_wick") or 0) < 0.25
    assert f.get("michael_gap_south_fx_ma") is False


def test_michael_intraday_not_confused_with_fwd3_in_votes(tmp_path, monkeypatch):
    """檢測方法分軌：當日空旗標不准混進 path 三日票。"""
    import json
    from scripts import decade_lab_michael_module as mm

    out = tmp_path / "michael_quant_latest.json"
    out.write_text(
        json.dumps(
            {
                "flags": [
                    {
                        "flag": "michael_gap_south_bounce",
                        "n": 32,
                        "vote": 1.2,
                        "edge3": 1.2,
                        "gate": "hard",
                    },
                    {
                        "flag": "michael_gap_south_intraday_down",
                        "n": 185,
                        "vote": -0.8,
                        "edge3": -0.8,
                        "gate": "hard",
                        "horizon": "same_day_open_close",
                        "path_vote": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mm, "OUT_DIR", tmp_path)
    votes = mm.load_michael_votes()
    assert "michael_gap_south_bounce" in votes
    assert "michael_gap_south_intraday_down" not in votes
