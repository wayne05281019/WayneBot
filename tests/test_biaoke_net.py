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
    assert str(blob.get("to") or "") >= "2026-09-14"
    assert any("46506" in str(p.get("text") or "") for p in blob["posts"])
    desk = open("biaoke_desk.py", encoding="utf-8").read()
    assert "copy.deepcopy(_load_seed())" not in desk
    assert "不要退回 520" in desk


def test_keys_split_glued_name_and_method():
    from biaoke_net import _keys

    keys = _keys("南亞科洗盤")
    assert "南亞科" in keys
    assert any("洗盤" in k for k in keys)


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
    zhi = match_posts("智原", limit=6)
    dates = {str(p.get("date") or "") for p in zhi}
    assert any(d.startswith("2023-12") for d in dates)
    assert any(d.startswith("2026-") for d in dates)
    assert any("3035" in (p.get("_sids") or []) for p in zhi)


def test_related_posts_do_not_score_bystander_quote():
    posts = [
        {
            "id": "r1",
            "kind": "reply",
            "date": "2026-09-14",
            "tags": [],
            "text": "「要買南亞科」沒有不太妙，目前測底",
        },
        {
            "id": "p1",
            "kind": "post",
            "date": "2026-09-14",
            "tags": [],
            "text": "目前已經到本波指數修正的末端",
        },
    ]
    rel = related_posts("南亞科", posts, limit=4)
    assert all(str(p.get("id")) != "r1" for p in rel)


def test_ask_stock_keys_talk_core_and_ticker():
    from biaoke_net import _ask_stock_keys

    keys, sids = _ask_stock_keys("你怎麼看智邦")
    assert "智邦" in keys
    assert "2345" in sids or "智邦" in keys
    keys2, sids2 = _ask_stock_keys("2345")
    assert "2345" in sids2
    assert "2345" in keys2


def test_related_posts_ticker_hits_name_only_self_reply():
    """樓下只寫「智邦」時，問 2345 也要對到作者自回，不准被「前高2345」帶走。"""
    posts = [
        {
            "id": "main",
            "kind": "post",
            "date": "2026-10-08",
            "tags": ["大立光"],
            "text": "從台指期連續盤很明顯，回測完成就再拉出一波漲勢。",
        },
        {
            "id": "main:c1",
            "kind": "reply",
            "parent": "main",
            "date": "2026-10-08",
            "tags": [],
            "text": "買光聖不如買聯亞，最穩健且剛剛才在底部整理完成，未來的漲幅空間我比較有把握，就是智邦，他應該會漲到過年前，最後倒的一檔長線龍頭股，但他的缺點就是資金效率不好。",
        },
        {
            "id": "main:c2",
            "kind": "reply",
            "parent": "main",
            "date": "2026-10-09",
            "tags": [],
            "text": "下星期會找一天我對目前選股看法，且可將智邦做為防禦性長線股的原因看法",
        },
        {
            "id": "old",
            "kind": "post",
            "date": "2026-05-18",
            "tags": ["台積電"],
            "text": "台積電目前幾乎已經90%確認開始橫盤整理，如果突破前高2345，也是B波假突破成分居高。",
        },
    ]
    for ask in ("智邦", "2345", "你怎麼看智邦"):
        rel = related_posts(ask, posts, limit=4)
        joined = " ".join(str(p.get("text") or "") for p in rel)
        assert "智邦" in joined, ask
        assert any("過年前" in str(p.get("text") or "") or "防禦性" in str(p.get("text") or "") for p in rel), ask
        assert all("突破前高2345" not in str(p.get("text") or "") for p in rel), ask


def test_extract_mentions_skips_price_like_ticker():
    from biaoke_link import extract_mentions

    hits = extract_mentions("台積電如果突破前高2345，也是B波假突破")
    assert all(h.get("stock_id") != "2345" for h in hits)
    hits2 = extract_mentions("就是智邦，他應該會漲到過年前")
    assert any(h.get("stock_id") == "2345" for h in hits2)
