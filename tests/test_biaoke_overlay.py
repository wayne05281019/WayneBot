# -*- coding: utf-8 -*-
"""飆大公開文：Drive 1709 底圖 + 同一顆行情庫 overlay。同一 id 以資料庫為準。"""
from __future__ import annotations

import json
import os
import sqlite3

from biaoke_desk import load_corpus, upsert_biaoke_posts
from biaoke_ingest import ingest_public_posts
from wayne_db import PRIVATE_USER_TABLES


class _Fake:
    def __init__(self):
        self.n = 0

    def get(self, url, timeout=12):
        self.n += 1

        class R:
            encoding = "utf-8"
            apparent_encoding = "utf-8"
            text = ""

            def raise_for_status(self):
                return None

        r = R()
        if "user/25263" in url:
            r.text = '<a href="/forum/article/184431393">x</a>'
        else:
            r.text = """
            <meta property="article:published_time" content="2026-9-9T9:08:00+08:00">
            <meta property="article:tag" content="記憶體">
            <article>
              <div>1.台指期連續盤主文。</div>
              <div class="articleReply">
                <a href="/forum/user/25263">期股多空雙飆客</a>
                <div class="articleReply__content">記憶體 我有看中一檔 昨天已經開始介入</div>
                <span>昨天 10:23</span>
              </div>
            </article>
            """
        return r


def test_biaoke_posts_not_private_user_table():
    assert "biaoke_posts" not in PRIVATE_USER_TABLES
    assert "biaoke_mentions" not in PRIVATE_USER_TABLES
    assert "biaoke_day_facts" not in PRIVATE_USER_TABLES
    assert "biaoke_claims" not in PRIVATE_USER_TABLES


def test_overlay_same_id_db_wins(tmp_path):
    db = str(tmp_path / "w.db")
    seed = load_corpus(None)
    first = next(p for p in seed["posts"] if p.get("id"))
    seed_id = str(first["id"])
    seed_text = str(first.get("text") or "")
    upsert_biaoke_posts(
        db,
        [
            {
                "id": seed_id,
                "date": "2026-09-10",
                "time": "09:00",
                "kind": "post",
                "tags": ["覆蓋"],
                "text": "資料庫這篇蓋過種子",
            }
        ],
    )
    fused = load_corpus(db)
    hit = next(p for p in fused["posts"] if str(p.get("id")) == seed_id)
    assert hit["text"] == "資料庫這篇蓋過種子"
    assert seed_text != hit["text"]


def test_overlay_new_id_is_visible(tmp_path):
    db = str(tmp_path / "w.db")
    n0 = int(load_corpus(None).get("n") or 0)
    upsert_biaoke_posts(
        db,
        [
            {
                "id": "999999001",
                "date": "2026-09-10",
                "time": "10:00",
                "kind": "post",
                "tags": ["測試新文"],
                "text": "盤中新抓的公開文只在資料庫",
            }
        ],
    )
    fused = load_corpus(db)
    assert int(fused["n"]) == n0 + 1
    assert any(str(p.get("id")) == "999999001" for p in fused["posts"])


def test_ingest_upserts_overlay_and_keeps_seed(tmp_path):
    db = str(tmp_path / "w.db")
    corpus = str(tmp_path / "c.json")
    seed_path = "docs/expert_notes/飆客/corpus_index.json"
    before = open(seed_path, "rb").read()
    stats = ingest_public_posts(
        corpus, db_path=db, session=_Fake(), max_ids=3, refresh_latest=2
    )
    after = open(seed_path, "rb").read()
    assert stats["ok"]
    assert int(stats["n"]) >= 1709
    assert stats["db"] >= 1
    assert os.path.isfile(corpus)
    blob = json.loads(open(corpus, encoding="utf-8").read())
    assert int(blob.get("n") or 0) >= 1709
    assert any("看中一檔" in (p.get("text") or "") for p in blob["posts"])
    assert any(
        str(p.get("date") or "") == "2023-12-04" and "智原" in str(p.get("text") or "")
        for p in blob["posts"]
    )
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM biaoke_posts").fetchone()[0]
    conn.close()
    assert n >= 1709
    assert before == after


def test_ingest_db_only_does_not_rewrite_git_seed(tmp_path):
    db = str(tmp_path / "w.db")
    seed_path = "docs/expert_notes/飆客/corpus_index.json"
    before = open(seed_path, "rb").read()
    stats = ingest_public_posts(db_path=db, session=_Fake(), max_ids=3, refresh_latest=2)
    after = open(seed_path, "rb").read()
    assert stats["ok"]
    assert int(stats["n"]) >= 1709
    assert stats["db"] >= 1
    assert before == after
    fused = load_corpus(db)
    assert int(fused["n"]) >= 1709
    assert str(fused.get("from") or "").startswith("2023-12")
    texts = " ".join(p.get("text") or "" for p in fused["posts"])
    assert "看中一檔" in texts
    assert "智原" in texts


def test_ingest_never_starts_from_520_or_empty_dump(tmp_path):
    """空 dump、甚至被指去寫 520 種子，融合仍從 1709 起算、種子 bytes 不變。"""
    from biaoke_archive import ARCHIVE_BASELINE_N

    db = str(tmp_path / "w.db")
    seed_path = "docs/expert_notes/飆客/corpus_index.json"
    before = open(seed_path, "rb").read()
    stats = ingest_public_posts(
        seed_path, db_path=db, session=_Fake(), max_ids=3, refresh_latest=2
    )
    after = open(seed_path, "rb").read()
    assert before == after
    assert stats["ok"]
    assert int(stats["n"]) >= ARCHIVE_BASELINE_N
    assert int(stats["n"]) >= 1709
    fused = load_corpus(db)
    assert int(fused["n"]) >= 1709
    assert any(
        str(p.get("date") or "") == "2023-12-04" and "智原" in str(p.get("text") or "")
        for p in fused["posts"]
    )
