"""黃培碩 YouTube：開市日自動抓最新片（不靠使用者貼連結）。

做法：
- 公開 RSS（channel_id 固定）每天列片→落庫→回傳當日 hint 給 huang_teach_sync
- 標題／摘要先吸收（可核對關鍵句）；完整口播需 HUANG_YT_COOKIES 才准 yt-dlp＋本機 whisper
- 不准假造 video_id；沒片＝空 hint
- 非買訊；不寄話筒
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.huang_youtube")

TAIPEI = ZoneInfo("Asia/Taipei")
HUANG_YT_CHANNEL_ID = "UCq8cveuaw5Ztv44nw2txiIg"
HUANG_YT_RSS = (
    f"https://www.youtube.com/feeds/videos.xml?channel_id={HUANG_YT_CHANNEL_ID}"
)
_ATOM = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}

# 標題教法關鍵（先吸收；口播再補）
_TEACH_PATTERNS = (
    (r"第二[支隻]腳", "second_foot"),
    (r"第五[波腳段]|[五5]\s*段", "fifth_leg"),
    (r"[三3]\s*段", "three_leg"),
    (r"次級\s*4|次級四", "subwave4"),
    (r"第四大波|第四波", "wave4_major"),
    (r"0\s*\.?\s*6\s*18|0\s*\.?\s*6xx|黃金切割", "fib618"),
    (r"禮物", "gift"),
    (r"斜率", "slope"),
)


def ensure_tables(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS huang_youtube_videos (
                video_id TEXT NOT NULL PRIMARY KEY,
                as_of TEXT NOT NULL,
                published TEXT DEFAULT '',
                title TEXT DEFAULT '',
                description TEXT DEFAULT '',
                source TEXT DEFAULT 'rss',
                teach_tags_json TEXT DEFAULT '[]',
                transcript TEXT DEFAULT '',
                transcript_status TEXT DEFAULT '',
                raw_json TEXT DEFAULT '',
                fetched_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_huang_yt_asof "
            "ON huang_youtube_videos(as_of);"
        )
        conn.commit()
    finally:
        conn.close()


def _stamp() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd_from_published(published: str) -> str:
    """RSS published（通常 UTC）→ 台北交易日 YYYYMMDD。"""
    raw = str(published or "").strip()
    if not raw:
        return ""
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TAIPEI).strftime("%Y%m%d")
    except Exception:
        m = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", raw)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"
        return ""


def ymd_in_title(title: str) -> str:
    t = str(title or "")
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", t)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    return ""


def extract_teach_tags(title: str, description: str = "") -> List[str]:
    text = f"{title or ''}\n{description or ''}"
    out: List[str] = []
    for pat, tag in _TEACH_PATTERNS:
        if re.search(pat, text):
            out.append(tag)
    return out


def parse_rss_xml(xml_text: str) -> List[Dict[str, str]]:
    root = ET.fromstring(xml_text)
    rows: List[Dict[str, str]] = []
    for entry in root.findall("atom:entry", _ATOM):
        title_el = entry.find("atom:title", _ATOM)
        vid_el = entry.find("yt:videoId", _ATOM)
        pub_el = entry.find("atom:published", _ATOM)
        desc_el = entry.find("media:group/media:description", _ATOM)
        vid = (vid_el.text if vid_el is not None else "") or ""
        title = (title_el.text if title_el is not None else "") or ""
        published = (pub_el.text if pub_el is not None else "") or ""
        desc = (desc_el.text if desc_el is not None else "") or ""
        if not vid:
            continue
        rows.append(
            {
                "video_id": vid.strip(),
                "title": title.strip(),
                "published": published.strip(),
                "description": desc.strip(),
                "as_of": ymd_in_title(title) or _ymd_from_published(published),
            }
        )
    return rows


def fetch_rss(*, timeout: float = 20.0) -> List[Dict[str, str]]:
    req = urllib.request.Request(
        HUANG_YT_RSS,
        headers={"User-Agent": "WayneBot-huang-youtube/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    return parse_rss_xml(raw)


def _title_score(title: str, as_of_ymd: str) -> int:
    """同日多片：有日期＋長標題（正式解盤）優於短『期股戰』。"""
    t = str(title or "")
    score = len(t)
    if ymd_in_title(t) == as_of_ymd:
        score += 1000
    if "期股戰" == t.strip():
        score -= 500
    if "黃培碩" in t or "分析師" in t:
        score += 50
    return score


def pick_day_video(entries: List[Dict[str, str]], as_of_ymd: str) -> Dict[str, str]:
    ymd = str(as_of_ymd or "").strip()
    cands = [e for e in entries if str(e.get("as_of") or "") == ymd]
    if not cands:
        return {}
    best = max(cands, key=lambda e: _title_score(str(e.get("title") or ""), ymd))
    return dict(best)


def upsert_video(db_path: str, row: Dict[str, Any]) -> None:
    ensure_tables(db_path)
    tags = row.get("teach_tags")
    if tags is None:
        tags = extract_teach_tags(str(row.get("title") or ""), str(row.get("description") or ""))
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO huang_youtube_videos(
                video_id, as_of, published, title, description, source,
                teach_tags_json, transcript, transcript_status, raw_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                as_of=excluded.as_of,
                published=excluded.published,
                title=excluded.title,
                description=excluded.description,
                source=excluded.source,
                teach_tags_json=excluded.teach_tags_json,
                transcript=CASE
                    WHEN length(excluded.transcript)>0 THEN excluded.transcript
                    ELSE huang_youtube_videos.transcript END,
                transcript_status=CASE
                    WHEN length(excluded.transcript)>0 THEN excluded.transcript_status
                    WHEN excluded.transcript_status!='' THEN excluded.transcript_status
                    ELSE huang_youtube_videos.transcript_status END,
                raw_json=excluded.raw_json,
                fetched_at=excluded.fetched_at
            """,
            (
                str(row.get("video_id") or ""),
                str(row.get("as_of") or ""),
                str(row.get("published") or ""),
                str(row.get("title") or ""),
                str(row.get("description") or "")[:4000],
                str(row.get("source") or "rss"),
                json.dumps(list(tags), ensure_ascii=False),
                str(row.get("transcript") or ""),
                str(row.get("transcript_status") or ""),
                str(row.get("raw_json") or "")[:8000],
                _stamp(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_day_video(db_path: str, as_of_ymd: str) -> Dict[str, Any]:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        rows = conn.execute(
            "SELECT video_id, as_of, published, title, description, source, "
            "teach_tags_json, transcript, transcript_status FROM huang_youtube_videos "
            "WHERE as_of=? ORDER BY length(title) DESC",
            (str(as_of_ymd or "").strip(),),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {}
    # 同日多列：標題分最高者
    best = max(
        rows,
        key=lambda r: _title_score(str(r[3] or ""), str(as_of_ymd or "")),
    )
    tags: List[str] = []
    try:
        tags = list(json.loads(best[6] or "[]"))
    except Exception:
        tags = []
    return {
        "video_id": best[0] or "",
        "as_of": best[1] or "",
        "published": best[2] or "",
        "title": best[3] or "",
        "description": best[4] or "",
        "source": best[5] or "",
        "teach_tags": tags,
        "transcript": best[7] or "",
        "transcript_status": best[8] or "",
    }


def cookies_path() -> str:
    return (
        os.getenv("HUANG_YT_COOKIES")
        or os.getenv("YTDLP_COOKIES")
        or os.getenv("YOUTUBE_COOKIES")
        or ""
    ).strip()


def try_transcribe_video(video_id: str, *, max_seconds: int = 25 * 60) -> Dict[str, str]:
    """可選：有 cookies 才 yt-dlp 抓音訊＋本機 whisper。失敗不假造。"""
    vid = str(video_id or "").strip()
    out = {"transcript": "", "transcript_status": "skipped_no_cookies"}
    if not vid:
        return out
    cookies = cookies_path()
    if not cookies or not os.path.isfile(cookies):
        return out
    ytdlp = os.getenv("YTDLP_BIN") or "yt-dlp"
    whisper_bin = os.getenv("HUANG_WHISPER_BIN") or "whisper"
    url = f"https://www.youtube.com/watch?v={vid}"
    with tempfile.TemporaryDirectory(prefix="huang-yt-") as td:
        out_tmpl = os.path.join(td, "audio.%(ext)s")
        cmd = [
            ytdlp,
            "-f",
            "bestaudio/best",
            "--cookies",
            cookies,
            "--no-playlist",
            "-o",
            out_tmpl,
            url,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        except Exception:
            logger.exception("huang_youtube：yt-dlp 失敗 video_id=%s", vid)
            out["transcript_status"] = "ytdlp_failed"
            return out
        audio = ""
        for name in os.listdir(td):
            if name.startswith("audio."):
                audio = os.path.join(td, name)
                break
        if not audio:
            out["transcript_status"] = "no_audio"
            return out
        # 截斷過長音訊（省資源）
        clipped = os.path.join(td, "clip.wav")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    audio,
                    "-t",
                    str(int(max_seconds)),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    clipped,
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
        except Exception:
            logger.exception("huang_youtube：ffmpeg 失敗")
            out["transcript_status"] = "ffmpeg_failed"
            return out
        try:
            # 本機 whisper CLI；輸出 txt 到同目錄
            subprocess.run(
                [
                    whisper_bin,
                    clipped,
                    "--language",
                    "zh",
                    "--model",
                    os.getenv("HUANG_WHISPER_MODEL") or "base",
                    "--output_format",
                    "txt",
                    "--output_dir",
                    td,
                ],
                check=True,
                capture_output=True,
                timeout=1800,
            )
            txt_path = os.path.join(td, "clip.txt")
            if os.path.isfile(txt_path):
                text = open(txt_path, encoding="utf-8").read().strip()
                out["transcript"] = text
                out["transcript_status"] = "whisper_ok" if text else "whisper_empty"
                return out
        except Exception:
            logger.exception("huang_youtube：whisper 失敗")
            out["transcript_status"] = "whisper_failed"
            return out
    out["transcript_status"] = "unknown"
    return out


def discover_day_video(
    db_path: str,
    as_of_ymd: str,
    *,
    fetch: bool = True,
    want_transcript: bool = False,
) -> Dict[str, Any]:
    """抓／選當日黃片；寫庫；回 hint 形狀給 teach sync。"""
    ymd = str(as_of_ymd or "").strip()
    out: Dict[str, Any] = {
        "video_id": "",
        "video_title": "",
        "source": "",
        "as_of": ymd,
        "teach_tags": [],
        "transcript_status": "",
    }
    if not ymd or not db_path:
        return out
    ensure_tables(db_path)
    picked: Dict[str, str] = {}
    if fetch:
        try:
            entries = fetch_rss()
            for e in entries:
                e = dict(e)
                e["teach_tags"] = extract_teach_tags(e.get("title") or "", e.get("description") or "")
                e["source"] = "rss"
                e["raw_json"] = json.dumps(
                    {"published": e.get("published"), "title": e.get("title")},
                    ensure_ascii=False,
                )
                upsert_video(db_path, e)
            picked = pick_day_video(entries, ymd)
        except Exception:
            logger.exception("huang_youtube：RSS 失敗 as_of=%s", ymd)
    if not picked:
        loaded = load_day_video(db_path, ymd)
        if loaded.get("video_id"):
            out.update(
                {
                    "video_id": loaded.get("video_id") or "",
                    "video_title": loaded.get("title") or "",
                    "source": f"db:{loaded.get('source') or 'cache'}",
                    "teach_tags": list(loaded.get("teach_tags") or []),
                    "transcript_status": loaded.get("transcript_status") or "",
                }
            )
            return out
        return out

    tags = extract_teach_tags(picked.get("title") or "", picked.get("description") or "")
    row: Dict[str, Any] = {
        **picked,
        "teach_tags": tags,
        "source": "rss",
        "transcript": "",
        "transcript_status": "title_only",
    }
    if want_transcript and cookies_path():
        tr = try_transcribe_video(str(picked.get("video_id") or ""))
        row["transcript"] = tr.get("transcript") or ""
        row["transcript_status"] = tr.get("transcript_status") or "title_only"
    upsert_video(db_path, row)
    out.update(
        {
            "video_id": picked.get("video_id") or "",
            "video_title": picked.get("title") or "",
            "source": "youtube_rss",
            "teach_tags": tags,
            "transcript_status": row.get("transcript_status") or "",
        }
    )
    return out
