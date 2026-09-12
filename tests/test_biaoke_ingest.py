# -*- coding: utf-8 -*-
"""飆大公開頁匯入：只解析 HTML，不碰 token。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_ingest import (
    SESSION_EVERY_SEC,
    AFTER_EVERY_SEC,
    AFTER_UNTIL_HOUR,
    NIGHT_EVERY_SEC,
    ingest_public_posts,
    parse_article_html,
    parse_author_replies,
    parse_api_author_replies,
    parse_display_time,
    parse_published,
    parse_user_article_ids,
    poll_wait_seconds,
    fetch_author_replies_api,
)


def test_parse_published_taipei():
    date, tm = parse_published("2026-9-10T9:51:28+08:00")
    assert date == "2026-09-10"
    assert tm == "09:51"


def test_parse_user_ids_keeps_order():
    html = (
        '<script>window.__NUXT__=(function(){return {articles:['
        '{id:"184499206",creatorId:r,x:1},'
        '{id:"184431393",creatorId:r,x:2}'
        ']}})</script>'
    )
    assert parse_user_article_ids(html) == ["184499206", "184431393"]


def test_parse_user_ids_href_only_is_not_enough():
    html = (
        '<a href="/forum/article/184556007">sidebar</a>'
        '<a href="/forum/article/184499206">maybe</a>'
        '<div>期股多空雙飆客</div>'
    )
    assert parse_user_article_ids(html) == []


def test_parse_user_ids_skips_other_people_and_utm_links():
    html = (
        '<script>window.__NUXT__=(function(){return {articles:['
        '{id:"184499206",creatorId:r,x:1},'
        '{id:"184431393",creatorId:r,x:2},'
        '{id:"184523396",creatorId:$,x:3}'
        ']}})</script>'
        '<a href="https://www.cmoney.tw/forum/article/184482173?utm_source=forum_app">other</a>'
    )
    assert parse_user_article_ids(html) == ["184499206", "184431393"]


def test_parse_article_html_body_and_tags():
    html = """
    <meta name="author" content="期股多空雙飆客">
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


def test_parse_article_html_rejects_other_author_even_if_sidebar_names_him():
    html = """
    <meta name="author" content="價值筆記">
    <meta property="article:published_time" content="2026-9-12T0:31:00+08:00">
    <article>
      <div>期股多空雙飆客</div>
      <div>1. 不追求買在最低點，而是追求「模糊的精確」</div>
      <div>安全邊際、估值位階、沉澱帶。</div>
    </article>
    """
    assert parse_article_html("999000111", html) is None
    from biaoke_ingest import is_biaoke_voice

    assert not is_biaoke_voice("1. 不追求買在最低點，而是追求「模糊的精確」 安全邊際")
    assert is_biaoke_voice("1. 台指期夜盤15分鐘線細微波修正走了5段")


def test_ingest_hook_is_on_product_clocks():
    import inspect
    import main

    src = inspect.getsource(main.run_scheduled_job)
    assert "run_biaoke_ingest_quiet" in src
    assert 'kind in ("morning", "midday", "fuse", "evening")' in src
    boot = inspect.getsource(main.run_web)
    assert "start_biaoke_poller" in boot
    assert "restore_universe_if_wiped" in boot
    assert "seed_biaoke_archive" in boot
    assert "link_biaoke_db" in boot
    assert "walk_biaoke_posts" in boot
    assert "enqueue_missing_quote_months" in boot
    assert "start_quote_month_backfill" in boot
    assert SESSION_EVERY_SEC == 10 * 60
    assert AFTER_EVERY_SEC == 1 * 60 * 60
    assert AFTER_UNTIL_HOUR == 3


def test_poll_wait_session_after_night():
    tz = ZoneInfo("Asia/Taipei")
    wed = datetime(2026, 9, 9, 10, 30, tzinfo=tz)
    assert poll_wait_seconds(wed) == SESSION_EVERY_SEC
    after = datetime(2026, 9, 9, 16, 40, tzinfo=tz)
    assert poll_wait_seconds(after) == AFTER_EVERY_SEC
    night = datetime(2026, 9, 9, 23, 10, tzinfo=tz)
    assert poll_wait_seconds(night) == AFTER_EVERY_SEC
    dawn = datetime(2026, 9, 10, 2, 0, tzinfo=tz)
    assert poll_wait_seconds(dawn) == AFTER_EVERY_SEC
    late_night = datetime(2026, 9, 10, 0, 50, tzinfo=tz)
    assert poll_wait_seconds(late_night) == AFTER_EVERY_SEC
    after_one = datetime(2026, 9, 10, 1, 20, tzinfo=tz)
    assert poll_wait_seconds(after_one) == AFTER_EVERY_SEC
    after_three = datetime(2026, 9, 10, 3, 0, tzinfo=tz)
    assert poll_wait_seconds(after_three) == 6 * 60 * 60
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


def test_parse_author_replies_keeps_nested_inside_bystander_with_chart():
    html = """
    <div class="articleComment">
      <a href="/forum/user/111">路人甲</a>
      <div class="articleComment__content">如果大盤測48218失敗怎麼辦</div>
      <span>昨天 13:00</span>
      <div class="articleReply nested">
        <a href="/forum/user/25263">期股多空雙飆客</a>
        <div class="articleReply__content">如果大盤測48218失敗很難</div>
        <img src="https://image.cmoney.tw/attachment/post/1789000000/chart.png">
        <span>昨天 13:07</span>
      </div>
    </div>
    """
    now = datetime(2026, 9, 10, 14, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    rows = parse_author_replies(html, parent_id="184499206", now=now)
    assert len(rows) == 1
    assert rows[0]["layer"] == 2
    assert "48218失敗很難" in rows[0]["text"]
    assert "附圖：" in rows[0]["text"]
    assert "chart.png" in rows[0]["text"]
    assert "怎麼辦" not in rows[0]["text"]


def test_parse_author_replies_skips_css_noise():
    html = """
    <div class="articleReply">
      <a href="/forum/user/25263">期股多空雙飆客</a>
      <div class="articleReply__content">.articleVirtualItem{padding-top:12px}</div>
      <span>昨天 13:07</span>
    </div>
    <div class="articleReply">
      <a href="/forum/user/25263">期股多空雙飆客</a>
      <div>查看 231 則留言...</div>
    </div>
    """
    now = datetime(2026, 9, 10, 14, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    rows = parse_author_replies(html, parent_id="184499206", now=now)
    assert rows == []


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
                r.text = (
                    '<script>window.__NUXT__=(function(){return {articles:['
                    '{id:"184431393",creatorId:r,x:1}'
                    ']}})</script>'
                )
            else:
                r.text = """
                <meta name="author" content="期股多空雙飆客">
                <meta property="article:published_time" content="2026-9-9T9:08:00+08:00">
                <meta property="article:tag" content="記憶體">
                <article>
                  <div>期股多空雙飆客</div>
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
    assert int(stats["n"]) >= 1709
    assert stats["added"] + stats["updated"] + stats["replies"] >= 1
    import json
    blob = json.loads(open(path, encoding="utf-8").read())
    kinds = {p.get("kind") or "post" for p in blob["posts"]}
    assert "reply" in kinds
    texts = " ".join(p.get("text") or "" for p in blob["posts"])
    assert "看中一檔" in texts
    assert "智原" in texts
    assert int(blob.get("n") or 0) >= 1709
    ingest_src = open("biaoke_ingest.py", encoding="utf-8").read()
    assert "Bearer" not in ingest_src or "不准放 Bearer" in ingest_src
    assert "corpus_path or _INDEX" not in ingest_src
    assert "seed_biaoke_archive" in ingest_src


def test_parse_api_author_replies_keeps_nested_under_bystander():
    payload = [
        {
            "id": "c1",
            "memberId": 111,
            "nickname": "楓糖ouo",
            "content": {"text": "感謝飆大~"},
            "createTime": "2026-09-11T03:55:32Z",
        },
        {
            "id": "c2",
            "memberId": 14444662,
            "nickname": "Lucky911",
            "content": {
                "text": "謝謝飆大分享！\n耐心等待行情後續發展。相信機會是留給有耐心的人。"
            },
            "createTime": "2026-09-11T03:52:29Z",
            "replyCount": 1,
            "replies": [
                {
                    "id": "c2r1",
                    "memberId": 25263,
                    "nickname": "期股多空雙飆客",
                    "content": {
                        "text": "「耐心等待行情後續發展。相信機會是留給有耐心的人。」 Yes"
                    },
                    "createTime": "2026-09-11T03:53:00Z",
                }
            ],
        },
    ]
    rows = parse_api_author_replies(payload, parent_id="184526608")
    texts = " ".join(r["text"] for r in rows)
    assert "Yes" in texts
    assert "感謝飆大" not in texts
    assert all(r["kind"] == "reply" and r["parent"] == "184526608" for r in rows)
    assert any(r["layer"] == 2 for r in rows)
    assert all(r["id"].startswith("184526608:c") for r in rows)


def test_cmoney_comment_api_skipped_without_env_token(monkeypatch):
    monkeypatch.delenv("CMONEY_AUTH_TOKEN", raising=False)
    from config import get_cmoney_auth_token
    from biaoke_ingest import fetch_author_replies_api

    assert get_cmoney_auth_token() == ""
    assert fetch_author_replies_api("184526608") == []


def test_fetch_author_replies_api_uses_user_script_urls(monkeypatch):
    monkeypatch.setenv("CMONEY_AUTH_TOKEN", "test-token-not-real")
    seen = []

    class _Fake:
        def get(self, url, headers=None, timeout=12):
            seen.append((url, (headers or {}).get("authorization"), (headers or {}).get("x-version")))

            class R:
                status_code = 200

                def json(self):
                    if "/Comments" in url and "/Comment/" not in url:
                        return [
                            {
                                "id": "c2",
                                "memberId": 14444662,
                                "nickname": "Lucky911",
                                "content": {"text": "謝謝飆大分享"},
                                "replyCount": 1,
                                "replies": [],
                            }
                        ]
                    return [
                        {
                            "id": "c2r1",
                            "memberId": 25263,
                            "nickname": "期股多空雙飆客",
                            "content": {"text": "「耐心等待行情後續發展。」 Yes"},
                        }
                    ]

            return R()

    rows = fetch_author_replies_api("184526608", session=_Fake())
    assert any("/Comments?startCommentIndex=0&fetch=-100" in u for u, *_ in seen)
    assert any("/Comment/c2/Replies?fetch=-50" in u for u, *_ in seen)
    assert seen[0][1] == "Bearer test-token-not-real"
    assert seen[0][2] == "2.0"
    texts = " ".join(r["text"] for r in rows)
    assert "Yes" in texts
    assert "謝謝飆大分享" not in texts
    import inspect
    from biaoke_desk import load_corpus
    from biaoke_ingest import ingest_public_posts

    src = inspect.getsource(ingest_public_posts)
    assert "_INDEX" not in src
    assert "seed_biaoke_archive" in src
    assert "run_quote_month_backfill" in src
    assert "fetch_missing=False" in src
    desk = inspect.getsource(load_corpus)
    assert "copy.deepcopy(_load_seed())" not in desk
    assert "不要退回 520" in desk
