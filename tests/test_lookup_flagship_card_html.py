# -*- coding: utf-8 -*-
"""查股旗艦卡：上市／興櫃雙模式對齊 mock 結構（真庫數字）。"""
from __future__ import annotations

import os

import pytest

from lookup_flagship_card_html import build_flagship_payload, render_flagship_html


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

    assert _num(p["tgt_n"]) >= _num(p["tgt_c"])
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


@pytest.mark.skipif(not os.path.exists(DB), reason="no local wayne_market.db")
def test_flagship_3595_emerging_platform_break():
    p = build_flagship_payload(DB, "3595", as_of="20261118")
    assert p["emerging"]
    assert p["close"] and p["close"] > 0
    # 上一根柱低／高＝前波平台／前高壓（20261113 低561 高636）
    marks = {m["label"]: m["value"] for m in p["marks"]}
    assert marks.get("前波平台") == pytest.approx(561.0)
    assert marks.get("前高壓") == pytest.approx(636.0)
    assert marks.get("現增暫定") == pytest.approx(400.0)
    assert p["broke"] is True
    assert "破撐" in p["sr_text"]
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

    assert _num(p["tgt_n"]) >= _num(p["tgt_c"])
    assert _num(p["tgt_n"]) >= 500  # 不准再算出比現價低一大截的 176
    html = render_flagship_html(p)
    assert "山太士" in html
    assert "興櫃防線與流動性警示" in html
    assert "▲破撐" in html
    assert "需 需" not in html
    assert "已出Q3" in html or "已出 Q3" in html
    assert "台光電" not in html  # 同族不串錯
