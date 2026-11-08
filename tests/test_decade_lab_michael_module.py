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
    assert f.get("michael_gap_south_below_ma60") is True  # 擴大軟閘母體


def test_michael_crash_bounce_tail_flags():
    """急跌反彈切片旗標：破位＋寬震盪＋昨跌深。"""
    twii = {}
    days = []
    y, m, d = 2025, 1, 1
    # 前 60 日緩跌建季線；近 10 日高低拉開 ≥3% 寬震盪
    px = 22000.0
    for i in range(70):
        day = f"{y}{m:02d}{d:02d}"
        days.append(day)
        if i < 60:
            hi, lo, c = px + 40, px - 40, px
            ret = -0.05
            px *= 0.999
        else:
            # 寬幅震盪帶
            hi, lo = 21500.0, 20500.0
            c = 21000.0 + (i - 60) * 20
            ret = 0.2
        twii[day] = {
            "open": c,
            "high": hi,
            "low": lo,
            "close": c,
            "ret": ret,
            "ret_ok": True,
        }
        d += 1
        if d > 28:
            d = 1
            m += 1
            if m > 12:
                m = 1
                y += 1
    prev = days[-2]
    last = days[-1]
    twii[prev]["ret"] = -3.5
    twii[prev]["close"] = 20900.0
    twii[last] = {
        "open": 20800.0,
        "high": 20850.0,
        "low": 20300.0,
        "close": 20400.0,  # 破近窗低 20500
        "ret": -2.4,
        "ret_ok": True,
    }
    f, _ = snapshot_michael_factors(
        twii=twii,
        tx_reg={},
        tx_night={},
        sox={prev: {"ret": -3.2}},
        tw_days=days,
        as_of=last,
        foreign_z=0.0,
    )
    assert f.get("michael_break_lower") is True
    assert f.get("michael_wide_chop") is True
    assert float(f.get("michael_prior_ret") or 0) <= -3.0
    assert f.get("michael_crash_bounce_tail") is True


def test_michael_failed_south_after_strong():
    """昨強＋gap_south 但當日收紅＝向南失敗（三日回歸變體）。"""
    twii, days, last = _series_below_ma60_then_gap_south()
    # 改成當日收紅（開高後收在開盤之上）
    prev = days[-2]
    base = twii[prev]["close"]
    twii[prev]["ret"] = 1.8
    twii[last] = {
        "open": base * 0.99,  # gap down after strong
        "high": base * 1.02,
        "low": base * 0.985,
        "close": base * 1.01,  # 收紅
        "ret": 0.5,
        "ret_ok": True,
    }
    f, _ = snapshot_michael_factors(
        twii=twii,
        tx_reg={},
        tx_night={},
        sox={},
        tw_days=days,
        as_of=last,
        foreign_z=0.0,
    )
    assert f.get("michael_gap_south") is True
    assert f.get("michael_failed_south_after_strong") is True
    assert f.get("michael_gap_south_intraday_down") is False


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


def test_michael_strong_pick_and_conf2_flags():
    """近窗教學：強摘陷阱＋15K連2日線代理。"""
    twii = {}
    days = []
    y, m, d = 2025, 3, 1
    px = 20000.0
    for i in range(14):
        day = f"{y}{m:02d}{d:02d}"
        days.append(day)
        px = 20000 + i * 20
        twii[day] = {
            "open": px - 10,
            "high": px + 30,
            "low": px - 40,
            "close": px,
            "ret": 0.3,
            "ret_ok": True,
        }
        d += 1
        if d > 28:
            d = 1
            m += 1
    # 昨強漲
    prev = days[-2]
    twii[prev]["ret"] = 2.5
    twii[prev]["close"] = twii[prev]["open"] + 80
    # 今弱收＝強摘陷阱
    last = days[-1]
    base = twii[prev]["close"]
    twii[last] = {
        "open": base + 10,
        "high": base + 20,
        "low": base - 50,
        "close": base - 5,
        "ret": -0.4,
        "ret_ok": True,
    }
    f, _m = snapshot_michael_factors(
        twii=twii,
        tx_reg={},
        tx_night={},
        sox={},
        tw_days=days,
        as_of=last,
    )
    assert f.get("michael_strong_pick_trap") is True
    assert f.get("michael_conf2_ma10") is False

    # 另造連2收紅站均：前段低、末兩根明顯在均上收紅
    for i, day in enumerate(days[:-2]):
        twii[day]["close"] = 19000 + i
        twii[day]["open"] = 19000 + i - 5
        twii[day]["high"] = 19000 + i + 10
        twii[day]["low"] = 19000 + i - 20
        twii[day]["ret"] = 0.1
    twii[days[-2]] = {
        "open": 20000,
        "high": 20200,
        "low": 19950,
        "close": 20150,
        "ret": 0.8,
        "ret_ok": True,
    }
    twii[days[-1]] = {
        "open": 20160,
        "high": 20350,
        "low": 20100,
        "close": 20300,
        "ret": 0.7,
        "ret_ok": True,
    }
    f2, _m2 = snapshot_michael_factors(
        twii=twii,
        tx_reg={},
        tx_night={},
        sox={},
        tw_days=days,
        as_of=days[-1],
    )
    assert f2.get("michael_conf2_ma10") is True
