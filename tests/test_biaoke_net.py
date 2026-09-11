# -*- coding: utf-8 -*-
"""飆大公開文底圖是完整主文＋樓中樓，不是 520 篇種子。"""
from biaoke_brain import match_posts
from biaoke_desk import load_corpus
from biaoke_net import related_posts


def test_load_corpus_uses_full_archive_not_seed_520():
    from biaoke_archive import ARCHIVE_BASELINE_N

    blob = load_corpus(None)
    assert int(blob.get("n") or 0) >= ARCHIVE_BASELINE_N
    assert int(blob.get("n") or 0) >= 1709
    assert int(blob.get("replies") or 0) >= 1300
    assert str(blob.get("from") or "").startswith("2023-12")
    assert any(
        str(p.get("date") or "") == "2023-12-04" and "智原" in str(p.get("text") or "")
        for p in blob["posts"]
    )
    desk = open("biaoke_desk.py", encoding="utf-8").read()
    assert "copy.deepcopy(_load_seed())" not in desk
    assert "不要退回 520" in desk


def test_match_posts_walks_neighbors_not_the_whole_pile():
    hits = match_posts("智原")
    assert hits
    assert len(hits) <= 4
    assert any("智原" in str(p.get("text") or "") for p in hits)
    wash = match_posts("洗盤跟出貨")
    assert 1 <= len(wash) <= 4
    assert any("洗盤" in str(p.get("text") or "") for p in wash)
    blob = load_corpus(None)
    rel = related_posts("南亞科洗盤", blob["posts"], limit=6)
    assert len(rel) <= 6
    joined = " ".join(str(p.get("text") or "") + " ".join(str(t) for t in (p.get("tags") or [])) for p in rel)
    assert "南亞科" in joined or "2408" in joined
    assert "洗盤" in joined
    assert "語料" not in joined
