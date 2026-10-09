# -*- coding: utf-8 -*-
"""買點箭同帶精準度量：過關前 promote_ready=False；不改買訊公式。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from buy_arrow_quant import (
    KIND,
    TAG_ALL,
    TAG_FIRST,
    TAG_FOLLOW,
    band_role_map,
    gate_status,
    persist_scores,
    promote_ready,
    recompute_rates,
    score_stock_day,
)
import wayne_navigator as wn


def test_band_role_matches_nav_fade_alphas():
    idxs = [10, 11, 12, 50, 51, 80]
    roles = band_role_map(idxs)
    alphas = wn._nav_buy_arrow_alphas(idxs)
    assert roles[10] == TAG_FIRST
    assert roles[11] == TAG_FOLLOW
    assert roles[12] == TAG_FOLLOW
    assert roles[50] == TAG_FIRST
    assert roles[51] == TAG_FOLLOW
    assert roles[80] == TAG_FIRST
    # 首根清楚、後續淡＝同一段定義
    assert alphas[10][0] == wn._NAV_BUY_ARROW_ALPHA_FIRST
    assert alphas[11][0] == wn._NAV_BUY_ARROW_ALPHA_FOLLOW


def test_gate_closed_until_evidence(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    open(db, "a").close()
    st = gate_status(db, horizon=5)
    assert st["promote_ready"] is False
    assert st["n_ok"] is False
    assert promote_ready(db) is False
    assert "不准改" in st["note"] or "還沒過關" in st["note"]
    assert st["min_unique_days"] >= 20


def test_score_persists_first_and_all_tags(tmp_path, monkeypatch):
    """用 stub 畫標：當日是同帶後續 → 應同時寫 all_painted＋band_follow。"""
    last = datetime(2026, 9, 17)
    rows = []
    for i in range(70):
        d = (last - timedelta(days=69 - i)).strftime("%Y%m%d")
        px = 100.0 + i * 0.1
        rows.append(
            {
                "date": d,
                "stock_id": "2330",
                "stock_name": "台積電",
                "open": px,
                "high": px + 1,
                "low": px - 1,
                "close": px,
                "volume": 5000,
            }
        )
    # 補未來柱讓 h1／h5 可結
    for i in range(1, 12):
        d = (last + timedelta(days=i)).strftime("%Y%m%d")
        rows.append(
            {
                "date": d,
                "stock_id": "2330",
                "stock_name": "台積電",
                "open": 110.0,
                "high": 111.0,
                "low": 109.0,
                "close": 110.5,
                "volume": 5000,
            }
        )
    df = pd.DataFrame(rows)

    def _fake_paint(hist):
        # 倒數第 2、最後一根（截至 as_of）連續＝首＋後續；as_of 當天＝follow
        n = len(hist)
        return [n - 2, n - 1]

    monkeypatch.setattr("buy_arrow_quant.painted_buy_indices", _fake_paint)
    scored = score_stock_day(df, as_of="20260917")
    tags = {r["tag"] for r in scored}
    assert TAG_ALL in tags
    assert TAG_FOLLOW in tags
    assert TAG_FIRST not in tags
    assert all(r["kind"] == KIND for r in scored)
    db = str(tmp_path / "m.db")
    open(db, "a").close()
    n = persist_scores(db, scored)
    assert n > 0
    rates = recompute_rates(db)
    assert any(k.startswith(TAG_FOLLOW) for k in rates)
    assert any(k.startswith(TAG_ALL) for k in rates)
