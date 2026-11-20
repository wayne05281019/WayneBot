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
    # 測 RSS 路徑：不准被本機／Drive 已知 id 拐去 ingest（CI 無 ffmpeg）
    monkeypatch.setattr(hy, "resolve_drive_file_id", lambda *_a, **_k: "")
    monkeypatch.delenv("HUANG_LOCAL_VIDEO", raising=False)
    monkeypatch.setattr(hy, "_should_ingest_media", lambda *_a, **_k: False)
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


def test_cookies_path_accepts_inline_netscape(tmp_path, monkeypatch):
    from huang_youtube import cookies_path

    cookie_file = tmp_path / "c.txt"
    monkeypatch.setenv("HUANG_YT_COOKIES_TMP", str(cookie_file))
    monkeypatch.setenv(
        "HUANG_YT_COOKIES",
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tA\tB\n",
    )
    path = cookies_path()
    assert path == str(cookie_file)
    assert cookie_file.is_file()
    assert "youtube.com" in cookie_file.read_text(encoding="utf-8")


def test_cookies_path_rejects_missing_probe_path(monkeypatch):
    from huang_youtube import cookies_path, youtube_cookies_ready

    monkeypatch.setenv("HUANG_YT_COOKIES", "/tmp/huang_yt_cookies_probe.txt")
    assert cookies_path() == ""
    st = youtube_cookies_ready()
    assert st["ready"] is False
    assert st["env_set"] is True


def test_parse_drive_name_and_known_ids():
    from huang_youtube import (
        HUANG_DRIVE_FOLDER_ID_DEFAULT,
        extract_levels_from_text,
        parse_drive_name_ymd,
        resolve_drive_file_id,
    )

    assert parse_drive_name_ymd("1111黃培碩.mp4").endswith("1111")
    assert parse_drive_name_ymd("20261112黃培碩.mp4") == "20261112"
    assert parse_drive_name_ymd("雜檔.txt") == ""
    assert resolve_drive_file_id("20261111") == "1efllG90yQBmFPC-3yFuba2TxW0FLA2jh"
    assert resolve_drive_file_id("20261112") == "12_RN9rsLBKjzbKNihFa5NceSGCJeWlm_"
    assert resolve_drive_file_id("20261116") == "1XR0XMswvMqEvro2cTHikMKKFCKDVQYAW"
    assert resolve_drive_file_id("20261117") == "1XDz4PwErKq5se_NtFJ12REb1eznJ16vS"
    assert resolve_drive_file_id("20261118") == "11VxUW3rSDVGDdhgY0_nqtBM7drSA9dj-"
    assert resolve_drive_file_id("20261119") == "1CMs7WKU3dVhquVCaQiz2QZIadP29llKV"
    assert resolve_drive_file_id("20261120") == "1uMrzOIM-w5fNfXR6gqzyamZNP52eBMPY"
    assert HUANG_DRIVE_FOLDER_ID_DEFAULT.startswith("1")
    assert "37837" in extract_levels_from_text("低點 37837 與 42471")


def test_20261120_title_and_oral_teach_tags():
    """20261120：標題三段／五段＋大盤口播＋≈01:46 台積電五段非第二隻腳。"""
    import json
    from pathlib import Path

    from huang_youtube import extract_teach_tags, parse_rss_xml, pick_day_video

    title = "台積電強於大盤！三段式 vs. 五段式 20261120 黃培碩 分析師 運達證券投顧"
    tags = extract_teach_tags(title)
    assert "three_leg" in tags
    assert "fifth_leg" in tags
    oral = "大盤為什麼不是下降趨勢？他認為是打第二隻腳。目前變成大盤五段式。"
    oral_tags = extract_teach_tags(oral)
    assert "not_downtrend" in oral_tags
    assert "second_foot" in oral_tags
    assert "fifth_leg" in oral_tags
    absorb = json.loads(
        Path("docs/expert_notes/飆客/decade_lab/huang_oral_absorb_20261120.json").read_text(
            encoding="utf-8"
        )
    )
    mv = absorb.get("market_verdict_zh") or {}
    assert "不是第二隻腳" in str(mv.get("now") or "")
    assert "第五" in str(mv.get("now") or "")
    clips = absorb.get("clips") or []
    assert any(c.get("subject") == "TWII" for c in clips)
    clip146 = next(c for c in clips if str(c.get("t_mmss") or "").startswith("~01:46"))
    assert clip146.get("subject") == "TWII"
    assert "second_foot" in (clip146.get("denies_tags") or [])
    assert "台積電" not in str(clip146.get("subject_zh") or "") or "大盤" in str(
        clip146.get("subject_zh") or ""
    )
    sample = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
 xmlns:media="http://search.yahoo.com/mrss/"
 xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>yt:video:rgE0ghdg1Hk</id>
  <yt:videoId>rgE0ghdg1Hk</yt:videoId>
  <title>期股戰</title>
  <published>2026-11-20T07:33:55+00:00</published>
  <media:group><media:description></media:description></media:group>
 </entry>
 <entry>
  <id>yt:video:G9uSEfcljWQ</id>
  <yt:videoId>G9uSEfcljWQ</yt:videoId>
  <title>{title}</title>
  <published>2026-11-20T07:18:07+00:00</published>
  <media:group><media:description>x</media:description></media:group>
 </entry>
</feed>
"""
    day = pick_day_video(parse_rss_xml(sample), "20261120")
    assert day["video_id"] == "G9uSEfcljWQ"
    assert "20261120" in day["title"]


def test_vtt_to_text_strips_timestamps(tmp_path):
    from huang_youtube import _vtt_to_text

    p = tmp_path / "a.zh-TW.vtt"
    p.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n第二支腳\n\n"
        "00:00:03.000 --> 00:00:05.000\n第二支腳\n\n"
        "00:00:05.000 --> 00:00:07.000\n低點 37837\n",
        encoding="utf-8",
    )
    text = _vtt_to_text(str(p))
    assert "第二支腳" in text
    assert "37837" in text
    assert "-->" not in text
    assert text.count("第二支腳") == 1


def test_discover_prefers_local_mp4_for_visual(tmp_path, monkeypatch):
    import huang_youtube as hy

    db = str(tmp_path / "t.db")
    fake_mp4 = tmp_path / "v.mp4"
    fake_mp4.write_bytes(b"\x00" * 1_500_000)

    monkeypatch.setattr(hy, "fetch_rss", lambda **kw: hy.parse_rss_xml(SAMPLE_RSS))
    monkeypatch.setenv("HUANG_LOCAL_VIDEO", str(fake_mp4))

    def _fake_ingest(path, **kw):
        assert path == str(fake_mp4)
        return {
            "transcript": "第二支腳 37837 禮物",
            "transcript_status": "whisper_ok",
            "visual_status": "frames_ok",
            "frames": ["f_001.jpg"],
            "frames_dir": str(tmp_path / "frames"),
            "levels": ["37837"],
        }

    monkeypatch.setattr(hy, "ingest_local_video", _fake_ingest)
    got = hy.discover_day_video(db, "20261111", fetch=True, want_transcript=True)
    assert got["source"] == "local_mp4"
    assert got["visual_status"] == "frames_ok"
    assert got["transcript_status"] == "whisper_ok"
    assert "37837" in (got.get("levels") or [])
    loaded = hy.load_day_video(db, "20261111")
    assert "第二支腳" in (loaded.get("transcript") or "")
    assert loaded.get("visual_status") == "frames_ok"
