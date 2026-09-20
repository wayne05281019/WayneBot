# -*- coding: utf-8 -*-
"""飆大公開頁匯入：只解析 HTML，不碰 token。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_ingest import (
    SESSION_EVERY_SEC,
    AFTER_EVERY_SEC,
    AFTER_CLOSE_EVERY_SEC,
    AFTER_UNTIL_HOUR,
    NIGHT_EVERY_SEC,
    PREOPEN_EVERY_SEC,
    REFRESH_LATEST,
    REFRESH_PREOPEN,
    ingest_public_posts,
    in_preopen_window,
    parse_article_html,
    parse_author_replies,
    parse_api_author_replies,
    parse_api_thread,
    parse_display_time,
    parse_published,
    parse_user_article_ids,
    poll_wait_seconds,
    refresh_latest_now,
    fetch_author_replies_api,
    split_author_cite,
)


def test_parse_published_taipei():
    date, tm = parse_published("2026-9-10T9:51:28+08:00")
    assert date == "2026-09-10"
    assert tm == "09:51"
    date2, tm2 = parse_published("2026-9-15T9:2:53+08:00")
    assert date2 == "2026-09-15"
    assert tm2 == "09:02"


def test_split_author_cite_quote_is_bystander():
    cite, spoken = split_author_cite(
        '"感覺夜盤不太妙" 沒有不太妙，目前是對第五波再一次測底，不重要。'
    )
    assert cite == "感覺夜盤不太妙"
    assert spoken.startswith("沒有不太妙")
    cite2, spoken2 = split_author_cite("目前已經到本波指數修正的末端")
    assert cite2 == ""
    assert "末端" in spoken2
    cite3, spoken3 = split_author_cite("「感覺夜盤不太妙」沒有不太妙")
    assert cite3 == "感覺夜盤不太妙"
    assert spoken3.startswith("沒有不太妙")
    from biaoke_ingest import spoken_text

    assert "夜盤不太妙" not in spoken_text("「感覺夜盤不太妙」沒有不太妙")
    assert spoken_text("沒有不太妙") == "沒有不太妙"


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


def test_parse_user_ids_resolves_nuxt_minified_latest():
    html = (
        '<script>window.__NUXT__=(function(r,aP){return {articles:['
        '{id:aP,creatorId:r,x:1},'
        '{id:"184545002",creatorId:r,x:2},'
        '{id:"184553319",creatorId:o,x:3}'
        ']}}("25263","184578674"));</script>'
        '<a href="/forum/article/184578674">visible</a>'
    )
    assert parse_user_article_ids(html) == ["184578674", "184545002"]


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


def test_parse_article_skips_chart_unrelated_to_named_stock():
    html = """
    <meta name="author" content="期股多空雙飆客">
    <meta property="article:published_time" content="2024-3-20T10:24:00+08:00">
    <article>
      <div>期股多空雙飆客</div>
      <div>1.鴻海機器人概念股今天站上型態頸線。</div>
      <img src="https://image.cmoney.tw/attachment/message/1710000000/3e6b15a5-a550-4e9e-a9ea-9d4e20405a82.jpg">
    </article>
    """
    row = parse_article_html("160000001", html)
    assert row is not None
    assert "鴻海" in row["text"]
    assert "3e6b15a5-a550-4e9e-a9ea-9d4e20405a82" not in row["text"]


def test_parse_article_keeps_chart_when_named_stock_matches():
    html = """
    <meta name="author" content="期股多空雙飆客">
    <meta property="article:published_time" content="2024-4-16T10:27:00+08:00">
    <article>
      <div>期股多空雙飆客</div>
      <div>1.漢科先掛117-117.5兩個價位，先買1/3。</div>
      <img src="https://image.cmoney.tw/attachment/message/1713196800/b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6.jpg">
    </article>
    """
    row = parse_article_html("161186954", html)
    assert row is not None
    assert "先掛117-117.5" in row["text"]
    assert "b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6" in row["text"]


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


def test_parse_article_html_accepts_garbled_author_meta_if_body_is_his():
    from biaoke_ingest import decode_cmoney_html, parse_article_html

    html = (
        '<meta name="author" content="期股多空雙飆客">'
        '<meta property="article:published_time" content="2026-9-20T21:28:17+08:00">'
        "<article><div>期股多空雙飆客</div>"
        "<div>1.\t富喬：目前多頭結構勉強維持。</div></article>"
    )
    garbled_meta = html.replace(
        'content="期股多空雙飆客"',
        'content="' + "期股多空雙飆客".encode("utf-8").decode("ptcp154", errors="replace") + '"',
        1,
    )
    row = parse_article_html("184841864", garbled_meta)
    assert row is not None
    assert "富喬" in row["text"]
    assert decode_cmoney_html(html.encode("utf-8"), apparent="ptcp154").count("富喬") == 1


def test_ingest_hook_is_on_product_clocks():
    import inspect
    import main

    src = inspect.getsource(main.run_scheduled_job)
    assert "run_biaoke_ingest_quiet" in src
    assert 'kind in ("morning", "midday", "fuse", "evening", "typhoon")' in src
    boot = inspect.getsource(main.run_web)
    assert "start_biaoke_poller" in boot
    assert "restore_universe_if_wiped" in boot
    assert "seed_biaoke_archive" in boot
    assert "link_biaoke_db" in boot
    assert "walk_biaoke_posts" in boot
    assert "enqueue_missing_quote_months" in boot
    assert "start_quote_month_backfill" in boot
    assert SESSION_EVERY_SEC == 3 * 60
    assert AFTER_EVERY_SEC == 1 * 60 * 60
    assert PREOPEN_EVERY_SEC == 10 * 60
    assert AFTER_UNTIL_HOUR == 3
    assert REFRESH_LATEST == 2
    assert REFRESH_PREOPEN == 2
    ingest_src = open("biaoke_ingest.py", encoding="utf-8").read()
    assert "refresh_latest_now" in ingest_src
    assert "PREOPEN_EVERY_SEC" in ingest_src
    assert "refresh_after_market_fuse" in src


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
    assert poll_wait_seconds(after_three) == AFTER_EVERY_SEC
    sat = datetime(2026, 9, 12, 10, 30, tzinfo=tz)
    assert poll_wait_seconds(sat) == AFTER_EVERY_SEC
    hol = datetime(2026, 9, 25, 10, 30, tzinfo=tz)
    assert poll_wait_seconds(hol) == AFTER_EVERY_SEC
    dawn_open = datetime(2026, 9, 10, 4, 10, tzinfo=tz)
    assert poll_wait_seconds(dawn_open) == AFTER_EVERY_SEC


def test_poll_wait_preopen_five_minutes_and_old_replies():
    tz = ZoneInfo("Asia/Taipei")
    wed_pre = datetime(2026, 9, 9, 8, 0, tzinfo=tz)
    assert in_preopen_window(wed_pre) is True
    assert poll_wait_seconds(wed_pre) == PREOPEN_EVERY_SEC
    assert refresh_latest_now(wed_pre) == 2
    assert refresh_latest_now(wed_pre) == REFRESH_PREOPEN
    wed_mid = datetime(2026, 9, 9, 8, 30, tzinfo=tz)
    assert poll_wait_seconds(wed_mid) == PREOPEN_EVERY_SEC
    wed_last = datetime(2026, 9, 9, 8, 59, tzinfo=tz)
    assert poll_wait_seconds(wed_last) == 2 * 60
    before = datetime(2026, 9, 9, 7, 59, tzinfo=tz)
    assert in_preopen_window(before) is False
    assert poll_wait_seconds(before) == AFTER_EVERY_SEC
    assert refresh_latest_now(before) == REFRESH_LATEST
    open_bell = datetime(2026, 9, 9, 9, 0, tzinfo=tz)
    assert in_preopen_window(open_bell) is False
    assert poll_wait_seconds(open_bell) <= 60
    session_start = datetime(2026, 9, 9, 9, 1, tzinfo=tz)
    assert poll_wait_seconds(session_start) == SESSION_EVERY_SEC
    close_bell = datetime(2026, 9, 9, 13, 30, tzinfo=tz)
    assert poll_wait_seconds(close_bell) == SESSION_EVERY_SEC
    after_close = datetime(2026, 9, 9, 13, 31, tzinfo=tz)
    assert poll_wait_seconds(after_close) == AFTER_CLOSE_EVERY_SEC
    before_hourly = datetime(2026, 9, 9, 14, 50, tzinfo=tz)
    assert poll_wait_seconds(before_hourly) == AFTER_CLOSE_EVERY_SEC
    hourly = datetime(2026, 9, 9, 15, 0, tzinfo=tz)
    assert poll_wait_seconds(hourly) == AFTER_EVERY_SEC
    sat_pre = datetime(2026, 9, 12, 8, 30, tzinfo=tz)
    assert in_preopen_window(sat_pre) is False
    assert poll_wait_seconds(sat_pre) == AFTER_EVERY_SEC
    hol_pre = datetime(2026, 9, 25, 8, 30, tzinfo=tz)
    assert in_preopen_window(hol_pre) is False
    assert poll_wait_seconds(hol_pre) == AFTER_EVERY_SEC


def test_preopen_rereads_latest_two_threads(tmp_path, monkeypatch):
    """最近兩則討論串每次都重讀自回；前一篇主文 HTML 不重抓。"""
    monkeypatch.setenv("CMONEY_AUTH_TOKEN", "test-token-not-real")
    from biaoke_desk import load_corpus, upsert_biaoke_posts

    db = str(tmp_path / "w.db")
    nearest = "188800001"
    older = "188800002"
    upsert_biaoke_posts(
        db,
        [
            {
                "id": nearest,
                "date": "2026-09-12",
                "time": "15:00",
                "kind": "post",
                "tags": [],
                "text": "1.台指期連續盤主文最近一則。",
            },
            {
                "id": older,
                "date": "2026-09-11",
                "time": "15:00",
                "kind": "post",
                "tags": [],
                "text": "1.台指期連續盤主文更早一則。",
            },
        ],
    )
    seen_urls = []

    class _Fake:
        def get(self, url, timeout=12, headers=None):
            seen_urls.append(url)

            class R:
                encoding = "utf-8"
                apparent_encoding = "utf-8"
                text = ""
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    if f"Article/{older}/Comments" in url:
                        return [
                            {
                                "id": "old-r1",
                                "memberId": 25263,
                                "nickname": "期股多空雙飆客",
                                "content": {"text": "前一篇樓下補一句先看量價。"},
                            }
                        ]
                    return []

            r = R()
            if "user/25263" in url:
                r.text = (
                    '<script>window.__NUXT__=(function(){return {articles:['
                    f'{{id:"{nearest}",creatorId:r,x:1}},'
                    f'{{id:"{older}",creatorId:r,x:2}}'
                    "]}})</script>"
                )
            elif nearest in url and "/forum/article/" in url:
                r.text = f"""
                <meta name="author" content="期股多空雙飆客">
                <meta property="article:published_time" content="2026-9-12T15:00:00+08:00">
                <article>
                  <div>期股多空雙飆客</div>
                  <div>1.台指期連續盤主文最近一則。</div>
                  <div class="articleReply">
                    <a href="/forum/user/25263">期股多空雙飆客</a>
                    <div class="articleReply__content">明天大盤最好能漲至少500點以上，否則要小心C-2轉C-3先在下方留言告知。</div>
                    <span>昨天 11:53</span>
                    <div class="articleReply nested">
                      <a href="/forum/user/25263">期股多空雙飆客</a>
                      <div class="articleReply__content">這是第二層補一句先看量價。</div>
                      <span>昨天 11:54</span>
                    </div>
                  </div>
                </article>
                """
            elif older in url and "/forum/article/" in url:
                r.text = f"""
                <meta name="author" content="期股多空雙飆客">
                <meta property="article:published_time" content="2026-9-11T15:00:00+08:00">
                <article>
                  <div>期股多空雙飆客</div>
                  <div>1.台指期連續盤主文更早一則。</div>
                  <div class="articleReply">
                    <a href="/forum/user/25263">期股多空雙飆客</a>
                    <div class="articleReply__content">這則更早貼文樓下不該開盤前重讀。</div>
                    <span>昨天 10:00</span>
                  </div>
                </article>
                """
            return r

    stats = ingest_public_posts(
        db_path=db,
        session=_Fake(),
        max_ids=12,
        refresh_latest=REFRESH_PREOPEN,
    )
    assert stats["ok"]
    article_urls = [u for u in seen_urls if "/forum/article/" in u]
    assert any(nearest in u for u in article_urls)
    assert all(f"/forum/article/{older}" not in u for u in article_urls)
    assert any(f"Article/{older}/Comments" in u for u in seen_urls)
    fused = load_corpus(db)
    texts = " ".join(str(p.get("text") or "") for p in fused["posts"])
    assert "C-2轉C-3" in texts
    assert "第二層補一句" in texts
    assert "前一篇樓下補一句" in texts
    layers = {
        int(p.get("layer") or 0)
        for p in fused["posts"]
        if str(p.get("parent") or "") == nearest
    }
    assert 1 in layers and 2 in layers


def test_new_latest_post_also_rereads_previous_thread(tmp_path, monkeypatch):
    """最新一篇這次才第一次掃到：連前一篇樓下一起收。"""
    monkeypatch.setenv("CMONEY_AUTH_TOKEN", "test-token-not-real")
    from biaoke_desk import load_corpus, upsert_biaoke_posts

    db = str(tmp_path / "w.db")
    newest = "199900001"
    older = "199900002"
    upsert_biaoke_posts(
        db,
        [
            {
                "id": older,
                "date": "2026-09-11",
                "time": "15:00",
                "kind": "post",
                "tags": [],
                "text": "1.台指期連續盤主文更早一則。",
            }
        ],
    )
    seen_urls = []

    class _Fake:
        def get(self, url, timeout=12, headers=None):
            seen_urls.append(url)

            class R:
                encoding = "utf-8"
                apparent_encoding = "utf-8"
                text = ""
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    if f"Article/{older}/Comments" in url:
                        return [
                            {
                                "id": "old1",
                                "memberId": 25263,
                                "nickname": "期股多空雙飆客",
                                "content": {"text": "前一篇樓下補一句先看量價"},
                            }
                        ]
                    return []

            r = R()
            if "user/25263" in url:
                r.text = (
                    '<script>window.__NUXT__=(function(){return {articles:['
                    f'{{id:"{newest}",creatorId:r,x:1}},'
                    f'{{id:"{older}",creatorId:r,x:2}}'
                    "]}})</script>"
                )
            elif newest in url and "/forum/article/" in url:
                r.text = f"""
                <meta name="author" content="期股多空雙飆客">
                <meta property="article:published_time" content="2026-9-14T21:50:00+08:00">
                <article>
                  <div>期股多空雙飆客</div>
                  <div>1.台指期連續盤主文最新一則。</div>
                </article>
                """
            return r

    stats = ingest_public_posts(
        db_path=db, session=_Fake(), max_ids=12, refresh_latest=2
    )
    assert stats["ok"]
    fused = load_corpus(db)
    texts = " ".join(str(p.get("text") or "") for p in fused["posts"])
    assert "最新一則" in texts
    assert "前一篇樓下補一句" in texts
    assert any(f"Article/{older}/Comments" in u for u in seen_urls)


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


def test_parse_author_replies_name_in_bystander_body_is_not_him():
    html = """
    <div class="articleComment">
      <a href="/forum/user/111">路人甲</a>
      <div class="articleComment__content">期股多空雙飆客 你看夜盤不太妙嗎</div>
      <span>昨天 21:40</span>
    </div>
    <div class="articleReply">
      <a href="/forum/user/25263">期股多空雙飆客</a>
      <div class="articleReply__content">「感覺夜盤不太妙」沒有不太妙</div>
      <span>昨天 21:50</span>
    </div>
    """
    now = datetime(2026, 9, 14, 22, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    rows = parse_author_replies(html, parent_id="184578674", now=now)
    assert len(rows) == 1
    assert "沒有不太妙" in rows[0]["text"]
    assert "你看夜盤" not in rows[0]["text"]


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


def test_parse_api_author_replies_keeps_reply_inside_reply():
    payload = [
        {
            "id": "c1",
            "memberId": 111,
            "nickname": "路人甲",
            "content": {"text": "請問夜盤"},
            "replies": [
                {
                    "id": "c1r1",
                    "memberId": 222,
                    "nickname": "另一人",
                    "content": {"text": "跟著問"},
                    "replies": [
                        {
                            "id": "deep",
                            "memberId": 25263,
                            "nickname": "期股多空雙飆客",
                            "content": {"text": "沒有不太妙，短線築底"},
                        }
                    ],
                }
            ],
        }
    ]
    rows = parse_api_author_replies(payload, parent_id="184578674")
    assert len(rows) == 1
    assert rows[0]["layer"] == 3
    assert "短線築底" in rows[0]["text"]
    assert "請問夜盤" not in " ".join(r["text"] for r in rows)


def test_parse_api_author_replies_unwraps_nested_data():
    from biaoke_ingest import parse_api_author_replies

    payload = {
        "data": {
            "comments": [
                {
                    "id": "c9",
                    "memberId": 25263,
                    "nickname": "期股多空雙飆客",
                    "content": {"text": "夜盤先看有沒有過壓"},
                    "createTime": "2026-09-11T04:00:00Z",
                }
            ]
        }
    }
    rows = parse_api_author_replies(payload, parent_id="184526608")
    assert len(rows) == 1
    assert "過壓" in rows[0]["text"]


def test_parse_api_author_replies_keeps_layer1_c2_warning():
    payload = [
        {
            "id": "c-old",
            "memberId": 25263,
            "nickname": "期股多空雙飆客",
            "content": {
                "text": "明天大盤最好能漲至少500點以上，否則要小心C-2轉C-3先在下方留言告知。"
            },
            "createTime": "2026-03-13T03:53:00Z",
        },
        {
            "id": "c-bystander",
            "memberId": 111,
            "nickname": "路人甲",
            "content": {"text": "謝謝飆大提醒"},
            "createTime": "2026-03-13T04:00:00Z",
        },
    ]
    rows = parse_api_author_replies(payload, parent_id="170000001")
    assert len(rows) == 1
    assert rows[0]["layer"] == 1
    assert "C-2轉C-3" in rows[0]["text"]
    assert "謝謝飆大" not in rows[0]["text"]


def test_parse_api_author_replies_nickname_containing_him_is_not_him():
    payload = [
        {
            "id": "fan",
            "memberId": 999,
            "nickname": "期股多空雙飆客的學生",
            "content": {"text": "老師我覺得夜盤不太妙"},
            "createTime": "2026-09-14T13:40:00Z",
        },
        {
            "id": "him",
            "memberId": 25263,
            "nickname": "期股多空雙飆客",
            "content": {"text": "「感覺夜盤不太妙」沒有不太妙"},
            "createTime": "2026-09-14T13:50:00Z",
        },
    ]
    rows = parse_api_author_replies(payload, parent_id="184578674")
    assert len(rows) == 1
    assert rows[0]["id"].endswith("chim")
    assert "沒有不太妙" in rows[0]["text"]
    assert "老師我覺得" not in " ".join(r["text"] for r in rows)


def test_cmoney_token_strips_quotes_and_bearer(monkeypatch):
    monkeypatch.setenv("CMONEY_AUTH_TOKEN", '"Bearer abc.def"')
    from config import get_cmoney_auth_token

    assert get_cmoney_auth_token() == "abc.def"
    monkeypatch.setenv("CMONEY_AUTH_TOKEN", "Authorization: Bearer abc.def")
    assert get_cmoney_auth_token() == "abc.def"


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
                    if "/Article/184526608/Comments" in url:
                        return [
                            {
                                "id": "c2",
                                "memberId": 14444662,
                                "nickname": "Lucky911",
                                "content": {"text": "謝謝飆大分享"},
                                "replyCount": 1,
                                "commentCount": 1,
                                "replies": [],
                            }
                        ]
                    if "/Article/c2/Comments" in url:
                        return {
                            "comments": [
                                {
                                    "id": "c2r1",
                                    "memberId": 25263,
                                    "nickname": "期股多空雙飆客",
                                    "content": {
                                        "text": "「耐心等待行情後續發展。」 Yes"
                                    },
                                }
                            ],
                            "remainCount": 0,
                        }
                    return []

            return R()

    rows = fetch_author_replies_api("184526608", session=_Fake())
    assert any("/Comments?startCommentIndex=0&fetch=-100" in u for u, *_ in seen)
    assert any("/Article/c2/Comments?startCommentIndex=0&fetch=-50" in u for u, *_ in seen)
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
    assert "refresh_biaoke_minutes" in src
    assert "skipped_walk" in src
    desk = inspect.getsource(load_corpus)
    assert "copy.deepcopy(_load_seed())" not in desk
    assert "不要退回 520" in desk


def test_fetch_author_replies_api_guest_paginates_without_env(monkeypatch):
    monkeypatch.delenv("CMONEY_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("WAYNE_CMONEY_GUEST_TEST", "1")
    from biaoke_ingest import (
        GUEST_TOKEN_URL,
        _clear_guest_token_cache,
        comment_api_status,
        fetch_author_replies_api,
    )

    _clear_guest_token_cache()
    seen = []

    class _Fake:
        def post(self, url, data=None, headers=None, timeout=12):
            seen.append(("POST", url, dict(data or {})))

            class R:
                status_code = 200
                content = b'{"access_token":"guest-not-real","expires_in":3600}'

                def json(self):
                    return {"access_token": "guest-not-real", "expires_in": 3600}

            return R()

        def get(self, url, headers=None, timeout=12):
            seen.append(
                (
                    "GET",
                    url,
                    (headers or {}).get("authorization"),
                    (headers or {}).get("x-version"),
                )
            )

            class R:
                status_code = 200

                def json(self):
                    if "startCommentIndex=0" in url:
                        return {
                            "comments": [
                                {
                                    "id": "184578674-94",
                                    "memberId": 25263,
                                    "nickname": "期股多空雙飆客",
                                    "content": {
                                        "text": "PCB不要亂動，位階最低，未來漲勢大於等於光通訊"
                                    },
                                },
                                {
                                    "id": "c-bystander",
                                    "memberId": 111,
                                    "nickname": "路人甲",
                                    "content": {"text": "謝謝飆大"},
                                },
                            ],
                            "remainCount": 1,
                            "nextCommentIndex": 100,
                        }
                    if "startCommentIndex=100" in url:
                        return {
                            "comments": [
                                {
                                    "id": "184578674-97",
                                    "memberId": 25263,
                                    "nickname": "期股多空雙飆客",
                                    "content": {"text": "富喬再度回到支撐區"},
                                }
                            ],
                            "remainCount": 0,
                            "nextCommentIndex": 1,
                        }
                    return {"comments": [], "remainCount": 0}

            return R()

    rows = fetch_author_replies_api("184578674", session=_Fake())
    texts = " ".join(r["text"] for r in rows)
    posts = [item for item in seen if item[0] == "POST"]
    gets = [item for item in seen if item[0] == "GET"]
    assert any(item[1] == GUEST_TOKEN_URL for item in posts)
    assert any(item[2].get("grant_type") == "guest" for item in posts)
    assert any(
        "startCommentIndex=0&fetch=-100" in item[1] and item[2] == "Bearer guest-not-real"
        for item in gets
    )
    assert any("startCommentIndex=100" in item[1] for item in gets)
    assert "PCB不要亂動" in texts
    assert "富喬再度回到支撐區" in texts
    assert "謝謝飆大" not in texts
    assert len(rows) == 2
    assert comment_api_status()["http"] == 200
    _clear_guest_token_cache()


def test_fetch_author_replies_api_expired_env_falls_back_to_guest(monkeypatch):
    monkeypatch.setenv("CMONEY_AUTH_TOKEN", "expired-login-token")
    monkeypatch.setenv("WAYNE_CMONEY_GUEST_TEST", "1")
    from biaoke_ingest import _clear_guest_token_cache, fetch_author_replies_api

    _clear_guest_token_cache()
    used = []

    class _Fake:
        def post(self, url, data=None, headers=None, timeout=12):
            class R:
                status_code = 200
                content = b'{"access_token":"guest-ok","expires_in":60}'

                def json(self):
                    return {"access_token": "guest-ok", "expires_in": 60}

            return R()

        def get(self, url, headers=None, timeout=12):
            auth = (headers or {}).get("authorization")
            used.append(auth)

            class R:
                status_code = 200 if auth == "Bearer guest-ok" else 401
                content = b"{}"

                def json(self):
                    if self.status_code != 200:
                        return {}
                    return {
                        "comments": [
                            {
                                "id": "c1",
                                "memberId": 25263,
                                "nickname": "期股多空雙飆客",
                                "content": {"text": "PCB不要亂動，位階最低"},
                            }
                        ],
                        "remainCount": 0,
                    }

            return R()

    rows = fetch_author_replies_api("184578674", session=_Fake())
    assert used and used[0] == "Bearer guest-ok"
    assert "expired-login-token" not in used
    assert any("PCB不要亂動" in r["text"] for r in rows)
    _clear_guest_token_cache()


def test_parse_api_thread_keeps_bystander_and_his_nested_reply():
    payload = [
        {
            "id": "184601742-170",
            "memberId": 111,
            "nickname": "路人甲",
            "content": {"text": "今天健策跌停板 代表甚麼意思?"},
            "commentCount": 2,
            "replies": [
                {
                    "id": "184601742-170-1",
                    "memberId": 25263,
                    "nickname": "期股多空雙飆客",
                    "content": {"text": "當天無法判斷"},
                },
                {
                    "id": "184601742-170-2",
                    "memberId": 25263,
                    "nickname": "期股多空雙飆客",
                    "content": {"text": "現在跌停盡然能打開，主力實在有夠狠，我點到為止"},
                },
            ],
        }
    ]
    all_rows = parse_api_thread(payload, parent_id="184601742")
    byst = [r for r in all_rows if r["kind"] == "bystander"]
    auth = [r for r in all_rows if r["kind"] == "reply"]
    assert any("健策跌停" in r["text"] for r in byst)
    assert any("當天無法判斷" in r["text"] for r in auth)
    assert any("點到為止" in r["text"] for r in auth)
    assert all("健策跌停" not in r["text"] for r in auth)
    assert any("健策跌停" in str(r.get("reply_to_text") or "") for r in auth)
    only_him = parse_api_author_replies(payload, parent_id="184601742")
    assert all(r["kind"] == "reply" for r in only_him)
    assert not any("健策跌停" in r["text"] for r in only_him)
