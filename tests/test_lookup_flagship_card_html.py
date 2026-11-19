# -*- coding: utf-8 -*-
"""查股旗艦卡：上市／興櫃雙模式對齊 mock 結構（真庫數字）。"""
from __future__ import annotations

import os

import pytest

from lookup_flagship_card_html import build_flagship_payload, payload_to_card, render_flagship_html


DB = os.environ.get("WAYNE_DB_PATH") or "data/wayne_market.db"


@pytest.mark.skipif(not os.path.exists(DB), reason="no local wayne_market.db")
def test_flagship_2383_listed_shape():
    p = build_flagship_payload(DB, "2383", as_of="20261118")
    assert not p["emerging"]
    assert p["close"] and p["close"] > 0
    assert any(t == "上市" for _, t in p["pills"])
    assert any("CCL" in t for _, t in p["pills"])
    assert "需" in p["rev_line"] and "(" in p["rev_line"]
    # 不准「需 需」；門檻應蓋住近月營收溫和成長（≥約 265 億帶）
    assert "需需" not in p["rev_line"]
    assert "需 需" not in render_flagship_html(p)
    rev_gate = p["rev_line"].split(" / ", 1)[1].split("(")[0]
    assert "需" in rev_gate
    # 抽出門檻數字
    import re

    m = re.search(r"([\d.]+)\s*億", rev_gate)
    assert m and float(m.group(1)) >= 260.0
    assert p["tgt_n"] != "—" and p["tgt_c"] != "—"

    def _num(s: str) -> float:
        return float(str(s).replace(",", ""))

    labels = [m["label"] for m in p["marks"]]
    assert "半年低" in labels
    assert "川寶" not in str(p.get("peers_raw"))
    assert "殖利率" in p["stat4"][2][0]
    assert p["stat4"][2][1] != "—（無底）"  # 官方有殖利率就應顯示
    html = render_flagship_html(p)
    assert "台光電" in html
    assert "未來 12 個月滾動本益比" in html
    assert "股價位置與防線" in html
    assert "川寶" not in html
    # 模板不再重複加「需」
    assert " / 需 需" not in html
    assert "今年合理" in html and "明年" in html
    assert "正常" not in html and "保守" not in html
    assert 'class="eps-pct"' in html
    assert "融資・10日籌碼與關鍵日" in html
    assert "外資10日" in html
    # 事件日：官方未來法說，否則法定財報期限（不准發明日期）
    assert re.search(r"｜(法說 |股東會 |年報 |財報 |Q\d財報 )\d{4}/\d{2}/\d{2}", p["extra_val"])
    assert "💡 策略提示：" in html
    assert "大量撐" in p["tip"]
    # 4 格微光膠囊：回檔為負 → 綠（跌）色塊
    assert p["stat4"][0][2] == "dn"
    assert 'class="m4-box tint-green"' in html
    card = payload_to_card(p)
    assert card["action_callout"] == p["tip"]
    assert len(card["m4_tints"]) == 4 and card["m4_tints"][0] == "tint-green"


def test_next_event_label_falls_back_to_report_deadline(tmp_path):
    import sqlite3

    from lookup_flagship_card_html import _next_event_label

    db = str(tmp_path / "e.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE company_events (stock_id TEXT, event_date TEXT, kind TEXT, title TEXT, source TEXT)"
    )
    con.execute("INSERT INTO company_events VALUES ('2383','20261103','法說','','')")
    con.commit()
    con.close()
    assert _next_event_label(db, "2383", "20261118") == "年報期限 2027/03/31"
    assert _next_event_label(db, "2383", "20261101") == "法說 2026/11/03"
    assert _next_event_label(db, "9999", "20260601") == "Q2財報期限 2026/08/14"


def test_extra_strip_keeps_annual_report_label():
    """法定期限標「前」時，年報不准縮成泛稱「財報」。"""
    import re

    def _phone_ev(ev: str) -> str:
        return re.sub(
            r"^(年報|Q\d財報)期限 (\S+)$",
            lambda m: f"{m.group(1)} {m.group(2)}前",
            ev,
        )

    assert _phone_ev("年報期限 2027/03/31") == "年報 2027/03/31前"
    assert _phone_ev("Q3財報期限 2026/11/14") == "Q3財報 2026/11/14前"
    assert "財報 2027" not in _phone_ev("年報期限 2027/03/31")


def test_forward_pe_is_price_over_rolling_eps():
    """未來12月滾動本益比＝現價／(今年EPS×剩餘月權重＋明年EPS×已過月權重)。"""
    from datetime import date

    from lookup_flagship_card_html import calc_forward_12m_eps

    # 11 月：剩餘 2／12 今年、10／12 明年
    fwd = calc_forward_12m_eps(2.52, 2.77, date(2026, 11, 18))
    assert fwd == 2.73
    assert round(22.90 / fwd, 1) == 8.4


def test_strategy_tip_buy_only_from_quantified_signal():
    from lookup_flagship_card_html import _strategy_tip

    base = dict(emerging=False, support=3690.0, thr=None, chip_f=["N"] * 5)
    assert "買點成立" in _strategy_tip(broke=False, buy_sig="leave_zero", **base)
    assert "買點成立" in _strategy_tip(broke=False, buy_sig="red_arrow", **base)
    no_sig = _strategy_tip(broke=False, buy_sig=None, **base)
    assert "買點成立" not in no_sig and "高低卡買點" in no_sig


@pytest.mark.skipif(not os.path.exists(DB), reason="no local wayne_market.db")
def test_star_buy_requires_signal_not_just_above_support(monkeypatch):
    import lookup_flagship_card_html as m

    monkeypatch.setattr(m, "_buy_signal", lambda *a, **k: None)
    p = m.build_flagship_payload(DB, "2317", as_of="20261118")
    assert p["status_label"] != "可買" and p["icon"] != "★"
    monkeypatch.setattr(m, "_buy_signal", lambda *a, **k: "leave_zero")
    p = m.build_flagship_payload(DB, "2317", as_of="20261118")
    assert p["status_label"] == "可買" and "買點成立" in p["tip"]


@pytest.mark.skipif(not os.path.exists(DB), reason="no local wayne_market.db")
def test_flagship_3595_emerging_platform_break():
    import sqlite3

    from lookup_flagship_card_html import _prior_platform

    as_of = "20261118"
    p = build_flagship_payload(DB, "3595", as_of=as_of)
    assert p["emerging"]
    assert p["close"] and p["close"] > 0
    # 前波平台／前高壓＝as_of 當下上一根官方柱低／高（庫會往後補柱，不准寫死舊日）
    con = sqlite3.connect(DB)
    try:
        bars = con.execute(
            """
            SELECT date, high, low, close, volume FROM emerging_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
              AND close>0 ORDER BY date ASC
            """,
            ("3595", as_of),
        ).fetchall()
    finally:
        con.close()
    plat_lo, plat_hi = _prior_platform(bars)
    assert plat_lo is not None and plat_hi is not None
    marks = {m["label"]: m["value"] for m in p["marks"]}
    assert marks.get("前波平台") == pytest.approx(plat_lo)
    assert marks.get("前高壓") == pytest.approx(plat_hi)
    assert marks.get("現增暫定") == pytest.approx(400.0)
    expect_broke = float(p["close"]) < float(plat_lo)
    assert p["broke"] is expect_broke
    if expect_broke:
        assert "破撐" in p["sr_text"]
    else:
        assert "破撐" not in p["sr_text"]
    assert any("興櫃" in t for _, t in p["pills"])
    assert "先進封裝" in p["peer_k"] or any("先進封裝" in t for _, t in p["pills"])
    assert "一元" not in p["bl_bottom"]
    assert "現增暫定 400" in p["bl_bottom"] or "現增暫定 400.0" in p["bl_bottom"]
    assert "4.68" in p["bl_bottom"]
    assert p["eps_e"] == pytest.approx(5.99)
    assert "Q3" in (p.get("eps_q_line") or "") or "2.97" in (p.get("eps_q_line") or "")
    assert "2027/01" in str((p.get("regime") or {}).get("right") or "")
    # 年底門檻約 1.05 億帶
    assert "1.05" in p["rev_line"] or "1.0" in p["rev_line"]
    assert p["pe_line"] != "—倍"
    def _num(s: str) -> float:
        return float(str(s).replace(",", ""))

    # 已核定 overlay 目標約 570；不准再掉回舊 bug 176 或純滾動估的偏低假目標
    assert _num(p["tgt_n"]) >= 500
    html = render_flagship_html(p)
    assert "山太士" in html
    assert "興櫃防線與流動性警示" in html
    if expect_broke:
        assert "▲破撐" in html
    assert "需 需" not in html
    assert "今年合理" in html and "明年" in html
    assert "正常" not in html and "保守" not in html
    assert "已出Q3" in p["eps_k"]
    assert "台光電" not in html  # 同族不串錯
    assert "興櫃量能與進度" in html
    assert "現增" in html
    assert p["extra_val"].endswith("｜預計上櫃 2027/01")
    assert p["tip"] == "興櫃量小價差大，緊盯 11–12 月營收過 1.05 億門檻"
    assert 'class="callout-bar is-em"' in html
    assert payload_to_card(p)["m4_tints"][3] == "tint-amber"


def test_chip_pills_use_full_foreign_streak_not_capped_at_5():
    """連買區查 20 天進旗艦卡：膠囊要寫完整天數，不准卡死近 5 格。"""
    from lookup_flagship_card_html import _chip_pills

    f5 = ["B", "B", "B", "B", "B"]
    t5 = ["N", "N", "N", "N", "N"]
    capped = _chip_pills(f5, t5)
    assert capped == [("pill-buy", "外資連買5日")]
    full = _chip_pills(f5, t5, foreign_buy_days=20, trust_buy_days=0)
    assert full == [("pill-buy", "外資連買20日")]


def test_eps_progress_pct_not_eaten_by_ellipsis():
    """今年賺錢進度％必須完整進 HTML，不准只剩 (71…。"""
    from lookup_flagship_card_html import fill_flagship_html

    card = {
        "status": "wait",
        "icon": "☆",
        "status_label": "等買點",
        "ticker": "2610",
        "name": "華航",
        "market_sector": "上市 · 航運",
        "price": "22.90",
        "change_pct": "▼ 0.87%",
        "is_up": False,
        "flow_pill": "籌碼中性",
        "regime_text": "資金水位中性",
        "regime_right": "USD/TWD 32.93",
        "eps_k": "今年賺錢進度",
        "eps_ytd": "1.8",
        "eps_est_yr": "2.5",
        "eps_pct": 71,
        "q4_progress": "10月✓ 11 12待補",
        "eps_latest_q": "0.72元",
        "pe_fwd12m": "8.4",
        "pe_note": "偏低",
        "pe_dot_pct": 14,
        "pe_min": "5x",
        "pe_mid": "17x",
        "pe_max": "29x",
        "target_norm": "63",
        "target_cons": "56.7",
        "foreign_5d": ["B"] * 5,
        "trust_5d": ["N"] * 5,
        "is_emerging": False,
        "emerging_note": "",
        "rev_now": "10月 221.6",
        "rev_gate": "239億",
        "rev_pct": 93,
        "support_ok": True,
        "support_text": "撐 22.15｜壓 23.5",
        "ruler_markers": [],
        "m4": [("60日回檔", "-3.4%", "dn")] * 4,
        "peer_chain": "航運",
        "peers": [{"name": "華航", "val": "8.4x"}],
        "moat_text": "航運",
        "risk_text": "景氣",
        "extra_title": "融資",
        "extra_val": "—",
        "action_callout": "先看高低卡",
        "m4_tints": ["tint-green"] * 4,
    }
    html = fill_flagship_html(card)
    assert "(71%)" in html
    assert "(71…" not in html and "(71..." not in html
    assert 'class="eps-pct"' in html


@pytest.mark.skipif(not os.path.exists(DB), reason="no local wayne_market.db")
def test_flagship_targets_keep_year_semantics_2610():
    """今年合理＝fair_year、明年＝target_next；不准因大小對調年標。"""
    from lookup_flagship_card_html import _soft_growth, build_flagship_payload
    import sqlite3

    p = build_flagship_payload(DB, "2610", as_of="20261118")
    con = sqlite3.connect(DB)
    try:
        soft = _soft_growth(con, "2610", close=p.get("close"), chain="航運", name="華航")
    finally:
        con.close()
    assert soft.get("fair") and soft.get("tgt")

    def _num(s: str) -> float:
        return float(str(s).replace(",", ""))

    assert _num(p["tgt_c"]) == pytest.approx(float(soft["fair"]), rel=0.02)
    assert _num(p["tgt_n"]) == pytest.approx(float(soft["tgt"]), rel=0.02)


def test_chip_capsule_note_counts_beyond_five(tmp_path):
    import sqlite3
    from datetime import date, timedelta

    from undervalue_growth import chip_capsule_note

    db = str(tmp_path / "c.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, foreign_net REAL, trust_net REAL)"
    )
    cur = date(2026, 11, 18)
    days = []
    for _ in range(20):
        days.append(cur.strftime("%Y%m%d"))
        cur -= timedelta(days=1)
        while cur.weekday() >= 5:
            cur -= timedelta(days=1)
    for day in days:
        con.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?)",
            ("7402", day, 10.0, 0.0),
        )
    con.commit()
    cap = chip_capsule_note(con, "7402", "20261118")
    con.close()
    assert cap["foreign_streak"] == 20
    assert "外資連買20日" in cap["capsule"]
