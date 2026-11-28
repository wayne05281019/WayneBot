"""查股風險／高檔回檔臉：無假機率％、無發明頂價。"""
from __future__ import annotations


def test_high_zone_observe_and_levels():
    from lookup_risk_face import high_zone_observe_bits, lookup_risk_level

    card = {
        "gain_pct": 28.0,
        "hl": "20高",
        "k20_high_streak": 2,
        "close": 100,
        "high": 103,
        "sell_action": "",
        "stance": "漲多了，今天別追",
        "stance_kind": "avoid",
    }
    bits = high_zone_observe_bits(card)
    assert any("60低" in b for b in bits)
    assert any("20" in b for b in bits)
    assert lookup_risk_level(card, {"regime": "ok"}) in ("watch", "alert", "observe")

    sell = dict(card, sell_action="直接減碼")
    assert lookup_risk_level(sell, {"regime": "ok"}) == "alert"
    assert lookup_risk_level({"gain_pct": 1}, {"regime": "ok", "alert": False}) == "silent"


def test_build_lookup_risk_html_has_zone_not_fake_pct(monkeypatch):
    from lookup_risk_face import build_lookup_risk_html

    monkeypatch.setattr(
        "lookup_risk_face._env_bits",
        lambda db: {
            "regime": "caution",
            "sox_pct": -1.5,
            "alert": False,
            "night_line": "夜盤對照　費半-1.50%",
            "label": "隔夜偏空",
        },
    )
    monkeypatch.setattr("sell_discipline.attach_sell", lambda c: c)
    monkeypatch.setattr(
        "sell_discipline.sell_note_short",
        lambda c: "現在價到高了、熱度沒跟上，先出一點、不要追",
    )
    html = build_lookup_risk_html(
        "/tmp/x.db",
        {
            "stock_id": "2383",
            "sell_action": "直接減碼",
            "gain_pct": 29.1,
            "hl": "20高",
            "k20_high_streak": 1,
            "close": 500,
            "high": 520,
            "stance": "漲多了，今天別追",
            "stance_kind": "avoid",
        },
        code="2383",
    )
    assert "2383" in html
    assert "出場" in html
    assert "高檔／回檔" in html
    assert "假機率" in html or "非假機率" in html
    assert "發明" in html or "頂價" in html
    # 不准出現像「下跌機率 73%」這種假句
    assert "下跌機率" not in html
    assert "%" in html  # 費半／獲利事實％可以有


def test_huang_wave_progress_has_peak_pullback():
    import json
    from pathlib import Path

    data = json.loads(
        Path("docs/expert_notes/黃培碩/huang_days/_TEMPLATE.json").read_text(
            encoding="utf-8"
        )
    )
    wp = data["wave_progress"]
    assert "peak_claim" in wp
    assert "pullback_band" in wp
    assert "rebound_band" in wp
    assert "confront_peak_zh" in wp
