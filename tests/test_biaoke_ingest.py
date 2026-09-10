# -*- coding: utf-8 -*-
"""飆大公開頁匯入：只解析 HTML，不碰 token。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_ingest import (
    SESSION_EVERY_SEC,
    AFTER_EVERY_SEC,
    NIGHT_EVERY_SEC,
    ingest_public_posts,
    parse_article_html,
    parse_author_replies,
    parse_display_time,
    parse_published,
    parse_user_article_ids,
    poll_wait_seconds,
)


def test_parse_published_taipei():
    date, tm = parse_published("2026-9-10T9:51:28+08:00")
    assert date == "2026-09-10"
    assert tm == "09:51"


def test_parse_user_ids_keeps_order():
    html = (
        '<a href="/forum/article/184499206">x</a>'
        '<a href="/forum/article/184431393">y</a>'
        '<a href="/forum/article/184499206">dup</a>'
    )
    assert parse_user_article_ids(html) == ["184499206", "184431393"]


def test_parse_article_html_body_and_tags():
    html = """
    <meta property="article:published_time" content="2026-9-10T9:51:28+08:00">
    <meta property="article:tag" content="3017奇鋐">
    <meta property="article:tag" content="TWA00加權指數">
    <article>
      <div>期股多空雙飆客</div>
      <div>追蹤</div>
      <div>1.台指期連續盤，細微波這兩天開始進行abc修正。</div>
      <div>2.目前台股長線主流股族群目前就是散熱族群最為強勢。</div>
      <div>查看 222 則留言...</div>
      <div>這行不該進來</div>
    </article>
    """
    row = parse_article_html("184499206", html)
    assert row is not None
    assert row["id"] == "184499206"
    assert row["date"] == "2026-09-10"
    assert row["time"] == "09:51"
    assert "奇鋐" in row["tags"]
    assert "加權指數" not in row["tags"]
    assert "散熱族群" in row["text"]
    assert "這行不該進來" not in row["text"]
    assert "查看" not in row["text"]


def test_ingest_hook_is_on_product_clocks():
    import inspect
    import main

    src = inspect.getsource(main.run_scheduled_job)
    assert "run_biaoke_ingest_quiet" in src
    assert 'kind in ("morning", "midday", "fuse", "evening")' in src
    boot = inspect.getsource(main.run_web)
    assert "start_biaoke_poller" in boot


def test_poll_wait_session_after_night():
    tz = ZoneInfo("Asia/Taipei")
    wed = datetime(2026, 9, 9, 10, 30, tzinfo=tz)
    assert poll_wait_seconds(wed) == SESSION_EVERY_SEC
    after = datetime(2026, 9, 9, 16, 40, tzinfo=tz)
    assert poll_wait_seconds(after) == AFTER_EVERY_SEC
    night = datetime(2026, 9, 9, 23, 10, tzinfo=tz)
    assert poll_wait_seconds(night) == NIGHT_EVERY_SEC
    sat = datetime(2026, 9, 12, 10, 30, tzinfo=tz)
    assert poll_wait_seconds(sat) == NIGHT_EVERY_SEC


def test_parse_display_yesterday():
    now = datetime(2026, 9, 10, 11, 34, tzinfo=ZoneInfo("Asia/Taipei"))
    d, t = parse_display_time("昨天 10:23", now=now)
    assert d == "2026-09-09"
    assert t == "10:23"


def test_parse_author_replies_layer1_and_layer2_skips_bystander():
    html = """
    <div class="articleContent__baseCont">
      <a href="/forum/user/25263">期股多空雙飆客</a>
      <div>1.台指期連續盤主文不要當留言。</div>
    </div>
    <div class="articleComment">
      <a href="/forum/user/111">路人甲</a>
      <div class="articleComment__content">謝謝飆大分享，光通訊真的很考驗心性</div>
      <span>昨天 10:27</span>
    </div>
    <div class="articleReply">
      <a href="/forum/user/25263">期股多空雙飆客</a>
      <div class="articleReply__content">記憶體 我有看中一檔 完全用技術分析搭配基本面選出來，昨天已經開始介入</div>
      <span>昨天 10:23</span>
      <div class="articleReply nested">
        <a href="/forum/user/25263">期股多空雙飆客</a>
        <div class="articleReply__content">但絕對不是南亞科、華邦電</div>
        <span>昨天 10:24</span>
      </div>
    </div>
    """
    now = datetime(2026, 9, 10, 11, 34, tzinfo=ZoneInfo("Asia/Taipei"))
    rows = parse_author_replies(html, parent_id="184431393", now=now)
    texts = " ".join(r["text"] for r in rows)
    assert "看中一檔" in texts
    assert "不是南亞科" in texts
    assert "光通訊真的很考驗" not in texts
    assert "台指期連續盤主文" not in texts
    layers = {r["layer"] for r in rows}
    assert 1 in layers and 2 in layers
    assert all(r["kind"] == "reply" and r["parent"] == "184431393" for r in rows)


def test_merge_reply_into_corpus(tmp_path):
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

    path = str(tmp_path / "corpus.json")
    stats = ingest_public_posts(path, session=_Fake(), max_ids=3, refresh_latest=2)
    assert stats["ok"]
    assert stats["added"] >= 1
    import json
    blob = json.loads(open(path, encoding="utf-8").read())
    kinds = {p.get("kind") or "post" for p in blob["posts"]}
    assert "reply" in kinds
    texts = " ".join(p.get("text") or "" for p in blob["posts"])
    assert "看中一檔" in texts
    assert "Bearer" not in open("biaoke_ingest.py", encoding="utf-8").read() or "不准放 Bearer" in open("biaoke_ingest.py", encoding="utf-8").read()



def test_parse_published_taipei():
    date, tm = parse_published("2026-9-10T9:51:28+08:00")
    assert date == "2026-09-10"
    assert tm == "09:51"


def test_parse_user_ids_keeps_order():
    html = (
        '<a href="/forum/article/184499206">x</a>'
        '<a href="/forum/article/184431393">y</a>'
        '<a href="/forum/article/184499206">dup</a>'
    )
    assert parse_user_article_ids(html) == ["184499206", "184431393"]


def test_parse_article_html_body_and_tags():
    html = """
    <meta property="article:published_time" content="2026-9-10T9:51:28+08:00">
    <meta property="article:tag" content="3017奇鋐">
    <meta property="article:tag" content="TWA00加權指數">
    <article>
      <div>期股多空雙飆客</div>
      <div>追蹤</div>
      <div>1.台指期連續盤，細微波這兩天開始進行abc修正。</div>
      <div>2.目前台股長線主流股族群目前就是散熱族群最為強勢。</div>
      <div>查看 222 則留言...</div>
      <div>這行不該進來</div>
    </article>
    """
    row = parse_article_html("184499206", html)
    assert row is not None
    assert row["id"] == "184499206"
    assert row["date"] == "2026-09-10"
    assert row["time"] == "09:51"
    assert "奇鋐" in row["tags"]
    assert "加權指數" not in row["tags"]
    assert "散熱族群" in row["text"]
    assert "這行不該進來" not in row["text"]
    assert "查看" not in row["text"]


def test_ingest_hook_is_on_product_clocks():
    import inspect
    import main

    src = inspect.getsource(main.run_scheduled_job)
    assert "run_biaoke_ingest_quiet" in src
    assert 'kind in ("morning", "midday", "fuse", "evening")' in src
