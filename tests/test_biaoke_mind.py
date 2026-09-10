# -*- coding: utf-8 -*-
"""飆大課綱：三百語料／一百判斷／三百官方 K。不是 700 顆按鈕。"""
from __future__ import annotations

import pytest

from biaoke_archive import load_bundled_archive
from biaoke_brain import DISCLAIMER, OFFTOPIC, answer_biaoke
from biaoke_desk import format_biaoke_welcome_html
from biaoke_mind import (
    corpus_curriculum,
    follow_up_ask,
    format_methods_html,
    k_curriculum,
    method_curriculum,
)


def test_welcome_says_compile_not_menu():
    html = format_biaoke_welcome_html()
    assert "直接打字" in html
    assert "問一檔" not in html
    assert "彙整" in DISCLAIMER


def test_method_curriculum_is_100_and_answers():
    asks = method_curriculum()
    assert len(asks) >= 100
    assert len(set(asks)) == len(asks)
    for q in asks:
        body = format_methods_html(q)
        assert body, q
        assert "海選" not in body or "不" in body
    html = answer_biaoke(":memory:", "量先價行怎麼看")
    assert "這不是買訊" in html
    assert "爆大量" in html
    html2 = answer_biaoke(":memory:", "大概何時止跌")
    assert "不猜日曆" in html2 or "費半" in html2
    assert "這不是買訊" in html2


def test_corpus_curriculum_has_300_from_1709():
    blob = load_bundled_archive()
    asks = corpus_curriculum(blob.get("posts") or [], limit=300)
    assert len(asks) >= 300
    sample = [a for a in asks if "勤誠" in a or "智原" in a or "散熱" in a]
    assert sample


def test_follow_up_uses_history_per_turn():
    hist = [{"ask": "勤誠", "answer": "語料有勤誠"}]
    assert "勤誠" in follow_up_ask("那怎麼看", hist)
    assert follow_up_ask("藝舍-KY", hist) == "藝舍-KY"


def test_offtopic_still_refused():
    assert answer_biaoke(":memory:", "今晚吃什麼") == OFFTOPIC
    assert "買訊" not in OFFTOPIC


def test_compile_mentions_this_brain():
    assert "彙整" in DISCLAIMER


@pytest.mark.production_db
def test_k_curriculum_300_unnamed_on_production_db():
    from tests.conftest import require_production_db

    db = require_production_db()
    import sqlite3

    blob = load_bundled_archive()
    named = []
    for p in blob.get("posts") or []:
        named.extend(p.get("tags") or [])
        named.append(p.get("text") or "")
    conn = sqlite3.connect(db)
    rows = conn.execute(
        """
        SELECT stock_id, stock_name FROM daily_quotes
        WHERE date=(SELECT MAX(date) FROM daily_quotes)
        ORDER BY volume DESC
        """
    ).fetchall()
    conn.close()
    cases = k_curriculum(named, rows, limit=300)
    assert len(cases) >= 300
    from biaoke_brain import overlay_stock, volume_first_price, load_bars

    sid, name = cases[0]
    bars = load_bars(db, sid)
    st = volume_first_price(bars)
    html = overlay_stock({"stock_id": sid, "stock_name": name}, st, in_corpus=False)
    assert "語料從頭到尾沒點名" in html
    assert "買訊" not in html or "不是" in html

