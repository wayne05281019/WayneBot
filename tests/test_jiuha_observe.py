# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jiuha_observe import (
    DESK_LAYERS,
    PRINCIPLES,
    align_post_to_bar,
    compute_daily_structure,
    extract_mentioned_levels,
    render_daily_markdown,
)


def test_principles_have_evidence():
    assert len(PRINCIPLES) >= 10
    ids = {p["id"] for p in PRINCIPLES}
    assert "P11_domestic_etf_regime" in ids
    for p in PRINCIPLES:
        assert p["id"] and p["title"] and p["rule"]
        assert p["evidence"], p["id"]


def test_desk_layers_l0_to_l5():
    assert [x["id"] for x in DESK_LAYERS] == [
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
    ]
    assert "存活" in DESK_LAYERS[0]["title"]


def test_extract_levels_and_align():
    text = "日 K 頸線 44,332，當天最高 44,525，收盤跌回"
    levels = extract_mentioned_levels(text)
    assert 44332.0 in levels
    assert 44525.0 in levels
    bars = [
        type("B", (), {})(),
    ]
    # use real Bar via align helper structure
    from jiuha_observe import Bar

    twii = [
        Bar("20261112", 44000, 44525, 42943, 43100, 1.5e7),
        Bar("20261111", 43000, 44000, 42800, 43900, 1.2e7),
    ]
    post = {
        "article_id": "188588578",
        "title": "頸線",
        "asof": "20261112",
        "text": text,
    }
    row = align_post_to_bar(post, twii)
    assert row["bar_date"] == "20261112"
    assert any(h.get("inside_bar") for h in row["level_hits"])


def test_daily_structure_from_market_db():
    db = Path("/workspace/data/wayne_market.db")
    if not db.is_file():
        return
    pack = compute_daily_structure(str(db), asof="20261120")
    assert pack.get("ok") is True
    assert pack.get("asof") == "20261120"
    assert pack.get("not_buy_signal") is True
    md = render_daily_markdown(pack)
    assert "非買訊" in md
    assert "重點觀察" in md
