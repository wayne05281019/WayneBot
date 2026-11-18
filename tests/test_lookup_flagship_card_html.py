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
    assert p["tgt_n"] != "—" and p["tgt_c"] != "—"
    # 正常目標 ≥ 保守
    def _num(s: str) -> float:
        return float(str(s).replace(",", ""))

    assert _num(p["tgt_n"]) >= _num(p["tgt_c"])
    html = render_flagship_html(p)
    assert "台光電" in html
    assert "未來 12 個月滾動本益比" in html
    assert "股價位置與防線" in html


@pytest.mark.skipif(not os.path.exists(DB), reason="no local wayne_market.db")
def test_flagship_3595_emerging_platform_break():
    p = build_flagship_payload(DB, "3595", as_of="20261118")
    assert p["emerging"]
    assert p["close"] and p["close"] > 0
    # 上一根柱低／高＝前波平台／前高壓（20261113 低561 高636）
    marks = {m["label"]: m["value"] for m in p["marks"]}
    assert marks.get("前波平台") == pytest.approx(561.0)
    assert marks.get("前高壓") == pytest.approx(636.0)
    assert p["broke"] is True
    assert "破撐" in p["sr_text"]
    assert any("興櫃" in t for _, t in p["pills"])
    assert "先進封裝" in p["peer_k"] or any("先進封裝" in t for _, t in p["pills"])
    # 無現增庫時不准「一元」假字
    assert "一元" not in p["bl_bottom"]
    assert "現增暫定 —" in p["bl_bottom"]
    assert p["pe_line"] != "—倍"
    html = render_flagship_html(p)
    assert "山太士" in html
    assert "興櫃防線與流動性警示" in html
    assert "▲破撐" in html
