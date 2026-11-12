"""黃培碩 YouTube RSS 每日自動抓片（不靠使用者貼連結）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
 xmlns:media="http://search.yahoo.com/mrss/"
 xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>yt:video:AAA11111111</id>
  <yt:videoId>AAA11111111</yt:videoId>
  <title>期股戰</title>
  <published>2026-11-11T08:00:00+00:00</published>
  <media:group><media:description>short</media:description></media:group>
 </entry>
 <entry>
  <id>yt:video:Nlflr2-PJFU</id>
  <yt:videoId>Nlflr2-PJFU</yt:videoId>
  <title>會打第二支腳嗎？3段或5段式修正？20261111 黃培碩 分析師 運達證券投顧</title>
  <published>2026-11-11T09:00:00+00:00</published>
  <media:group><media:description>desc</media:description></media:group>
 </entry>
 <entry>
  <id>yt:video:UT2NBDSu6PI</id>
  <yt:videoId>UT2NBDSu6PI</yt:videoId>
  <title>殺低又追高？操作節奏勿亂！20261112 黃培碩 分析師 運達證券投顧</title>
  <published>2026-11-12T09:00:00+00:00</published>
  <media:group><media:description>x</media:description></media:group>
 </entry>
</feed>
"""


def test_parse_and_pick_prefers_dated_title():
    from huang_youtube import extract_teach_tags, parse_rss_xml, pick_day_video

    rows = parse_rss_xml(SAMPLE_RSS)
    assert len(rows) == 3
    day = pick_day_video(rows, "20261111")
    assert day["video_id"] == "Nlflr2-PJFU"
    assert "第二支腳" in day["title"]
    tags = extract_teach_tags(day["title"])
    assert "second_foot" in tags
    assert "fifth_leg" in tags or "three_leg" in tags


def test_discover_stores_and_hint(tmp_path, monkeypatch):
    import huang_youtube as hy
    from huang_teach_sync import find_huang_video_hint

    db = str(tmp_path / "t.db")
    monkeypatch.setattr(hy, "fetch_rss", lambda **kw: hy.parse_rss_xml(SAMPLE_RSS))
    got = hy.discover_day_video(db, "20261112", fetch=True, want_transcript=False)
    assert got["video_id"] == "UT2NBDSu6PI"
    assert got["source"] == "youtube_rss"
    hint = find_huang_video_hint("20261112", db_path=db, fetch_youtube=True)
    assert hint["video_id"] == "UT2NBDSu6PI"
    assert "20261112" in hint["video_title"]
    assert hint["source"] == "youtube_rss"
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM huang_youtube_videos").fetchone()[0]
    conn.close()
    assert n >= 3


def test_channel_id_locked():
    from huang_youtube import HUANG_YT_CHANNEL_ID, HUANG_YT_RSS

    assert HUANG_YT_CHANNEL_ID == "UCq8cveuaw5Ztv44nw2txiIg"
    assert HUANG_YT_CHANNEL_ID in HUANG_YT_RSS
