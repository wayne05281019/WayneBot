"""黃培碩 YouTube／Drive：開市日自動抓最新影音（不靠使用者每天貼）。

做法：
- 公開 RSS（channel_id 固定）每天列片→落庫→回傳當日 hint 給 huang_teach_sync
- 標題／摘要先吸收；完整影音優先雲端硬碟 ``MMDD黃培碩.mp4``（gdown）→抽影格＋whisper
- YouTube 完整影音需 HUANG_YT_COOKIES 才准 yt-dlp；yt-dlp≥2026.10.26 才能破 SABR（舊版雲端 IP 403）
- 看影片＝影格＋口播；不准只當標題／不准假造 video_id
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
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.huang_youtube")

TAIPEI = ZoneInfo("Asia/Taipei")
HUANG_YT_CHANNEL_ID = "UCq8cveuaw5Ztv44nw2txiIg"
HUANG_YT_RSS = (
    f"https://www.youtube.com/feeds/videos.xml?channel_id={HUANG_YT_CHANNEL_ID}"
)
# 雲端硬碟「黃培碩每日影音」資料夾（agent 建；可被 HUANG_DRIVE_FOLDER_ID 覆寫）
HUANG_DRIVE_FOLDER_ID_DEFAULT = "1JkZ3P_AjAq4QigGplenKZ4o5CNaUvtfR"
# 已驗證可 gdown 的歷史片（不用每天問）
HUANG_DRIVE_KNOWN_IDS = {
    "20261110": "1m5GHbPCxjWZz5NHHdHgtzOJiITUeDj9I",
    "20261111": "1efllG90yQBmFPC-3yFuba2TxW0FLA2jh",
    "20261112": "12_RN9rsLBKjzbKNihFa5NceSGCJeWlm_",
}
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
# 影格／口播也掃數字位階
_LEVEL_RE = re.compile(r"(?<!\d)(3[5-9]\d{3}|4[0-9]\d{3}|5[0-2]\d{3})(?!\d)")


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
                drive_file_id TEXT DEFAULT '',
                visual_status TEXT DEFAULT '',
                frames_json TEXT DEFAULT '[]',
                levels_json TEXT DEFAULT '[]',
                raw_json TEXT DEFAULT '',
                fetched_at TEXT NOT NULL
            );
            """
        )
        # 舊庫補欄
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(huang_youtube_videos)").fetchall()
        }
        for col, typ in (
            ("drive_file_id", "TEXT DEFAULT ''"),
            ("visual_status", "TEXT DEFAULT ''"),
            ("frames_json", "TEXT DEFAULT '[]'"),
            ("levels_json", "TEXT DEFAULT '[]'"),
        ):
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE huang_youtube_videos ADD COLUMN {col} {typ}"
                )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_huang_yt_asof "
            "ON huang_youtube_videos(as_of);"
        )
        conn.commit()
    finally:
        conn.close()


def drive_folder_id() -> str:
    return (
        os.getenv("HUANG_DRIVE_FOLDER_ID") or HUANG_DRIVE_FOLDER_ID_DEFAULT or ""
    ).strip()


def parse_drive_name_ymd(name: str) -> str:
    """``1111黃培碩.mp4``／``20261111黃培碩.mp4`` → YYYYMMDD；認不出＝空。"""
    base = os.path.basename(str(name or "")).strip()
    m = re.match(r"^(20\d{2})(\d{2})(\d{2}).*黃培碩", base)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m = re.match(r"^(\d{2})(\d{2}).*黃培碩", base)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            # 年：台北今／去年（跨年 12→1）
            now = datetime.now(TAIPEI)
            year = now.year
            try:
                cand = datetime(year, mm, dd, tzinfo=TAIPEI)
            except ValueError:
                return ""
            if cand.date() > now.date():
                year -= 1
            return f"{year:04d}{mm:02d}{dd:02d}"
    return ""


def drive_file_ids_map() -> Dict[str, str]:
    """ymd → Drive file id。env ``HUANG_DRIVE_FILE_IDS``＝``20261111=id,20261112=id``。"""
    out = dict(HUANG_DRIVE_KNOWN_IDS)
    raw = (os.getenv("HUANG_DRIVE_FILE_IDS") or "").strip()
    if raw:
        try:
            if raw.startswith("{"):
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        kk = str(k).strip()
                        vv = str(v).strip()
                        if kk and vv:
                            out[kk] = vv
            else:
                for part in raw.split(","):
                    part = part.strip()
                    if "=" not in part:
                        continue
                    k, v = part.split("=", 1)
                    kk, vv = k.strip(), v.strip()
                    if kk and vv:
                        out[kk] = vv
        except Exception:
            logger.exception("huang_youtube：解析 HUANG_DRIVE_FILE_IDS 失敗")
    return out


def resolve_drive_file_id(as_of_ymd: str) -> str:
    ymd = str(as_of_ymd or "").strip()
    if not ymd:
        return ""
    return str(drive_file_ids_map().get(ymd) or "").strip()


def extract_levels_from_text(*parts: str) -> List[str]:
    seen: List[str] = []
    for p in parts:
        for m in _LEVEL_RE.findall(str(p or "")):
            if m not in seen:
                seen.append(m)
    return seen


def gdown_drive_mp4(file_id: str, dest_path: str) -> bool:
    """用 gdown 抓 Drive mp4（anyone／已授權）。失敗不假造。"""
    fid = str(file_id or "").strip()
    dest = str(dest_path or "").strip()
    if not fid or not dest:
        return False
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    gdown_bin = os.getenv("GDOWN_BIN") or "gdown"
    url = f"https://drive.google.com/uc?id={fid}"
    try:
        subprocess.run(
            [gdown_bin, "--fuzzy", "-O", dest, url],
            check=True,
            capture_output=True,
            timeout=1800,
        )
    except Exception:
        logger.exception("huang_youtube：gdown 失敗 file_id=%s", fid)
        return False
    return os.path.isfile(dest) and os.path.getsize(dest) > 1_000_000


def extract_video_frames(
    video_path: str,
    frames_dir: str,
    *,
    start_sec: int = 60,
    duration_sec: int = 25 * 60,
    every_sec: int = 90,
    max_frames: int = 20,
) -> List[str]:
    """從影音抽影格（要看畫面，不只聽口播）。回傳檔名清單。"""
    src = str(video_path or "").strip()
    out_dir = str(frames_dir or "").strip()
    if not src or not os.path.isfile(src) or not out_dir:
        return []
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "f_%03d.jpg")
    vf = f"fps=1/{max(int(every_sec), 30)},scale=1280:-1"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(int(start_sec)),
                "-i",
                src,
                "-t",
                str(int(duration_sec)),
                "-vf",
                vf,
                "-frames:v",
                str(int(max_frames)),
                "-q:v",
                "3",
                pattern,
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
    except Exception:
        logger.exception("huang_youtube：抽影格失敗 path=%s", src)
        return []
    names = sorted(
        n for n in os.listdir(out_dir) if n.startswith("f_") and n.endswith(".jpg")
    )
    return names[: int(max_frames)]


def whisper_local_media(
    media_path: str,
    *,
    max_seconds: int = 25 * 60,
) -> Dict[str, str]:
    """本機 ffmpeg→whisper；media 可為 mp4／wav／m4a。"""
    src = str(media_path or "").strip()
    out = {"transcript": "", "transcript_status": "no_media"}
    if not src or not os.path.isfile(src):
        return out
    whisper_bin = os.getenv("HUANG_WHISPER_BIN") or "whisper"
    with tempfile.TemporaryDirectory(prefix="huang-whisper-") as td:
        clipped = os.path.join(td, "clip.wav")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    src,
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
                timeout=600,
            )
        except Exception:
            logger.exception("huang_youtube：whisper 前 ffmpeg 失敗")
            out["transcript_status"] = "ffmpeg_failed"
            return out
        try:
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


def ingest_local_video(
    video_path: str,
    *,
    work_dir: str = "",
    want_whisper: bool = True,
    want_frames: bool = True,
) -> Dict[str, Any]:
    """讀本機 mp4：抽影格＋口播。畫面數字從檔名／之後 OCR 欄位擴；先留影格路徑。"""
    src = str(video_path or "").strip()
    out: Dict[str, Any] = {
        "transcript": "",
        "transcript_status": "",
        "visual_status": "",
        "frames": [],
        "frames_dir": "",
        "levels": [],
    }
    if not src or not os.path.isfile(src):
        out["transcript_status"] = "no_file"
        out["visual_status"] = "no_file"
        return out
    root = str(work_dir or "").strip() or os.path.join(
        tempfile.gettempdir(), "huang-ingest"
    )
    os.makedirs(root, exist_ok=True)
    frames_dir = os.path.join(root, "frames")
    if want_frames:
        names = extract_video_frames(src, frames_dir)
        out["frames"] = names
        out["frames_dir"] = frames_dir if names else ""
        out["visual_status"] = "frames_ok" if names else "frames_empty"
    else:
        out["visual_status"] = "skipped"
    if want_whisper:
        tr = whisper_local_media(src)
        out["transcript"] = tr.get("transcript") or ""
        out["transcript_status"] = tr.get("transcript_status") or ""
        out["levels"] = extract_levels_from_text(out["transcript"])
    else:
        out["transcript_status"] = "skipped"
    return out


def ingest_drive_video(
    as_of_ymd: str,
    *,
    file_id: str = "",
    work_dir: str = "",
    want_whisper: bool = True,
    want_frames: bool = True,
) -> Dict[str, Any]:
    """Drive file id → 本機 mp4 → 影格＋口播。"""
    ymd = str(as_of_ymd or "").strip()
    fid = str(file_id or "").strip() or resolve_drive_file_id(ymd)
    out: Dict[str, Any] = {
        "drive_file_id": fid,
        "as_of": ymd,
        "local_path": "",
        "transcript": "",
        "transcript_status": "no_drive_id",
        "visual_status": "no_drive_id",
        "frames": [],
        "frames_dir": "",
        "levels": [],
    }
    if not fid:
        return out
    root = str(work_dir or "").strip() or os.path.join(
        tempfile.gettempdir(), f"huang-drive-{ymd or fid[:8]}"
    )
    os.makedirs(root, exist_ok=True)
    dest = os.path.join(root, f"{ymd or 'video'}.mp4")
    if not (os.path.isfile(dest) and os.path.getsize(dest) > 1_000_000):
        if not gdown_drive_mp4(fid, dest):
            out["transcript_status"] = "gdown_failed"
            out["visual_status"] = "gdown_failed"
            return out
    out["local_path"] = dest
    got = ingest_local_video(
        dest,
        work_dir=root,
        want_whisper=want_whisper,
        want_frames=want_frames,
    )
    out.update(got)
    out["drive_file_id"] = fid
    out["as_of"] = ymd
    out["local_path"] = dest
    return out


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
    frames = row.get("frames")
    if frames is None:
        try:
            frames = json.loads(str(row.get("frames_json") or "[]"))
        except Exception:
            frames = []
    levels = row.get("levels")
    if levels is None:
        try:
            levels = json.loads(str(row.get("levels_json") or "[]"))
        except Exception:
            levels = []
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO huang_youtube_videos(
                video_id, as_of, published, title, description, source,
                teach_tags_json, transcript, transcript_status,
                drive_file_id, visual_status, frames_json, levels_json,
                raw_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                drive_file_id=CASE
                    WHEN length(excluded.drive_file_id)>0 THEN excluded.drive_file_id
                    ELSE huang_youtube_videos.drive_file_id END,
                visual_status=CASE
                    WHEN length(excluded.visual_status)>0 THEN excluded.visual_status
                    ELSE huang_youtube_videos.visual_status END,
                frames_json=CASE
                    WHEN length(excluded.frames_json)>2 THEN excluded.frames_json
                    ELSE huang_youtube_videos.frames_json END,
                levels_json=CASE
                    WHEN length(excluded.levels_json)>2 THEN excluded.levels_json
                    ELSE huang_youtube_videos.levels_json END,
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
                str(row.get("drive_file_id") or ""),
                str(row.get("visual_status") or ""),
                json.dumps(list(frames or []), ensure_ascii=False),
                json.dumps(list(levels or []), ensure_ascii=False),
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
            "teach_tags_json, transcript, transcript_status, "
            "drive_file_id, visual_status, frames_json, levels_json "
            "FROM huang_youtube_videos "
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
    frames: List[str] = []
    levels: List[str] = []
    try:
        frames = list(json.loads(best[11] or "[]"))
    except Exception:
        frames = []
    try:
        levels = list(json.loads(best[12] or "[]"))
    except Exception:
        levels = []
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
        "drive_file_id": best[9] or "",
        "visual_status": best[10] or "",
        "frames": frames,
        "levels": levels,
    }


def cookies_path() -> str:
    """回傳可用的 cookies 檔路徑。

    支援：
    - 環境變數是既有檔路徑
    - 環境變數直接是 Netscape cookies 內容（Render Secret 常這樣放）→ 寫入暫存檔
    不准把 cookies 貼進 git／聊天。
    """
    raw = (
        os.getenv("HUANG_YT_COOKIES")
        or os.getenv("YTDLP_COOKIES")
        or os.getenv("YOUTUBE_COOKIES")
        or ""
    ).strip()
    if not raw:
        return ""
    if os.path.isfile(raw):
        return raw
    # 內嵌 cookies 文本
    if ("# Netscape" in raw) or ("\t" in raw and "youtube.com" in raw):
        path = os.getenv("HUANG_YT_COOKIES_TMP") or "/tmp/huang_yt_cookies.txt"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(raw if raw.endswith("\n") else raw + "\n")
            os.chmod(path, 0o600)
            return path
        except Exception:
            logger.exception("huang_youtube：寫入 cookies 暫存失敗")
            return ""
    return ""


def _vtt_to_text(vtt_path: str) -> str:
    """極簡 VTT→純文字（去時間碼／重複列）。"""
    if not vtt_path or not os.path.isfile(vtt_path):
        return ""
    lines: List[str] = []
    seen = set()
    try:
        raw = open(vtt_path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("WEBVTT") or s.startswith("NOTE") or "-->" in s:
            continue
        if re.match(r"^\d+$", s):
            continue
        s = re.sub(r"<[^>]+>", "", s).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        lines.append(s)
    return "\n".join(lines).strip()


def try_fetch_youtube_captions(video_id: str, *, dest_dir: str = "") -> Dict[str, str]:
    """有 cookies：yt-dlp 拉自動／手動字幕（不重、Render 可先靠這層讀口播）。"""
    vid = str(video_id or "").strip()
    out = {"transcript": "", "transcript_status": "skipped_no_cookies", "path": ""}
    if not vid:
        return out
    cookies = cookies_path()
    if not cookies or not os.path.isfile(cookies):
        return out
    ytdlp = os.getenv("YTDLP_BIN") or "yt-dlp"
    url = f"https://www.youtube.com/watch?v={vid}"
    td = str(dest_dir or "").strip() or tempfile.mkdtemp(prefix="huang-cap-")
    os.makedirs(td, exist_ok=True)
    out_tmpl = os.path.join(td, "cap")
    cmd = [
        ytdlp,
        "--skip-download",
        "--write-auto-sub",
        "--write-sub",
        "--sub-langs",
        "zh-TW,zh-Hant,zh-Hans,zh,en",
        "--sub-format",
        "vtt",
        "--cookies",
        cookies,
        "--no-playlist",
        "-o",
        out_tmpl,
        url,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except Exception:
        logger.exception("huang_youtube：字幕抓取失敗 video_id=%s", vid)
        out["transcript_status"] = "captions_failed"
        return out
    vtts = sorted(
        os.path.join(td, n) for n in os.listdir(td) if n.endswith(".vtt")
    )
    # 優先 zh
    vtts.sort(key=lambda p: (0 if "zh" in os.path.basename(p).lower() else 1, p))
    for vp in vtts:
        text = _vtt_to_text(vp)
        if text:
            out["transcript"] = text
            out["transcript_status"] = "captions_ok"
            out["path"] = vp
            return out
    out["transcript_status"] = "captions_empty"
    return out


def try_fetch_youtube_video(
    video_id: str,
    *,
    dest_dir: str = "",
    want_video: bool = True,
) -> Dict[str, str]:
    """有 cookies 才 yt-dlp。優先整段影音（可看畫面）；失敗再退音訊。"""
    vid = str(video_id or "").strip()
    out = {"path": "", "status": "skipped_no_cookies", "kind": ""}
    if not vid:
        return out
    cookies = cookies_path()
    if not cookies or not os.path.isfile(cookies):
        return out
    ytdlp = os.getenv("YTDLP_BIN") or "yt-dlp"
    url = f"https://www.youtube.com/watch?v={vid}"
    td = str(dest_dir or "").strip() or tempfile.mkdtemp(prefix="huang-yt-")
    os.makedirs(td, exist_ok=True)
    fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]/best" if want_video else "bestaudio/best"
    out_tmpl = os.path.join(td, "media.%(ext)s")
    cmd = [
        ytdlp,
        "-f",
        fmt,
        "--cookies",
        cookies,
        "--no-playlist",
        "--merge-output-format",
        "mp4",
        "-o",
        out_tmpl,
        url,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
    except Exception:
        logger.exception("huang_youtube：yt-dlp 失敗 video_id=%s", vid)
        out["status"] = "ytdlp_failed"
        return out
    media = ""
    for name in os.listdir(td):
        if name.startswith("media."):
            media = os.path.join(td, name)
            break
    if not media:
        out["status"] = "no_media"
        return out
    out["path"] = media
    out["status"] = "ok"
    out["kind"] = "video" if media.endswith((".mp4", ".mkv", ".webm")) else "audio"
    return out


def try_transcribe_video(video_id: str, *, max_seconds: int = 25 * 60) -> Dict[str, Any]:
    """有 cookies：先字幕口播，再下影音抽影格；本機有 whisper 才補口播。失敗不假造。"""
    vid = str(video_id or "").strip()
    out: Dict[str, Any] = {
        "transcript": "",
        "transcript_status": "skipped_no_cookies",
        "visual_status": "",
        "frames": [],
        "levels": [],
    }
    if not vid:
        return out
    with tempfile.TemporaryDirectory(prefix="huang-yt-") as td:
        cap = try_fetch_youtube_captions(vid, dest_dir=td)
        if cap.get("transcript"):
            out["transcript"] = cap["transcript"]
            out["transcript_status"] = cap.get("transcript_status") or "captions_ok"
            out["levels"] = extract_levels_from_text(out["transcript"])

        fetched = try_fetch_youtube_video(vid, dest_dir=td, want_video=True)
        if fetched.get("status") != "ok" or not fetched.get("path"):
            if out["transcript"]:
                out["visual_status"] = str(fetched.get("status") or "ytdlp_failed")
                return out
            out["transcript_status"] = str(fetched.get("status") or "ytdlp_failed")
            out["visual_status"] = out["transcript_status"]
            return out

        # 畫面一定要抽；口播：已有字幕就略過 whisper（Render 通常沒裝）
        want_whisper = (not out["transcript"]) and bool(
            (os.getenv("HUANG_WHISPER_BIN") or "").strip()
            or os.path.isfile("/home/ubuntu/.local/bin/whisper")
        )
        got = ingest_local_video(
            str(fetched["path"]),
            work_dir=td,
            want_whisper=want_whisper,
            want_frames=True,
        )
        out["visual_status"] = got.get("visual_status") or ""
        out["frames"] = list(got.get("frames") or [])
        if want_whisper and got.get("transcript"):
            out["transcript"] = got.get("transcript") or ""
            out["transcript_status"] = got.get("transcript_status") or ""
            out["levels"] = list(
                dict.fromkeys(
                    list(out.get("levels") or [])
                    + list(got.get("levels") or [])
                    + extract_levels_from_text(out["transcript"])
                )
            )
        elif out["transcript"]:
            out["levels"] = list(
                dict.fromkeys(
                    list(out.get("levels") or []) + extract_levels_from_text(out["transcript"])
                )
            )
        elif got.get("transcript_status"):
            out["transcript_status"] = got.get("transcript_status") or out["transcript_status"]
        _ = max_seconds  # 相容舊呼叫
        return out


def _should_ingest_media(want_transcript: bool, as_of_ymd: str) -> bool:
    if want_transcript:
        return True
    # 有 Drive 檔或 cookies → 自動挖影音（不用等旗標）
    if resolve_drive_file_id(as_of_ymd):
        return True
    if cookies_path():
        return True
    # 本機已有快取片
    for p in (
        os.getenv("HUANG_LOCAL_VIDEO") or "",
        f"/tmp/huang{as_of_ymd[-4:]}.mp4" if len(as_of_ymd) >= 8 else "",
        f"/tmp/huang{as_of_ymd}.mp4",
    ):
        if p and os.path.isfile(p) and os.path.getsize(p) > 1_000_000:
            return True
    return False


def discover_day_video(
    db_path: str,
    as_of_ymd: str,
    *,
    fetch: bool = True,
    want_transcript: bool = False,
) -> Dict[str, Any]:
    """抓／選當日黃片；寫庫；回 hint 形狀給 teach sync。

    影音優先序：本機快取 → Drive ``MMDD黃培碩.mp4`` → YouTube cookies yt-dlp。
    都要抽影格（看畫面）＋whisper（口播）；只有標題不算看過影片。
    """
    ymd = str(as_of_ymd or "").strip()
    out: Dict[str, Any] = {
        "video_id": "",
        "video_title": "",
        "source": "",
        "as_of": ymd,
        "teach_tags": [],
        "transcript_status": "",
        "visual_status": "",
        "drive_file_id": "",
        "levels": [],
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
                    "visual_status": loaded.get("visual_status") or "",
                    "drive_file_id": loaded.get("drive_file_id") or "",
                    "levels": list(loaded.get("levels") or []),
                }
            )
            # 庫內尚無口播／影格且今日可 ingest → 補挖
            need = (not loaded.get("transcript")) or (
                str(loaded.get("visual_status") or "") not in ("frames_ok",)
            )
            if need and _should_ingest_media(want_transcript, ymd):
                picked = {
                    "video_id": str(loaded.get("video_id") or ""),
                    "title": str(loaded.get("title") or ""),
                    "as_of": ymd,
                    "published": str(loaded.get("published") or ""),
                    "description": str(loaded.get("description") or ""),
                }
            else:
                return out
        else:
            # 無 RSS 列仍可只靠 Drive 當日檔
            if not resolve_drive_file_id(ymd):
                return out
            picked = {
                "video_id": f"drive:{resolve_drive_file_id(ymd)}",
                "title": f"{ymd[4:]}黃培碩",
                "as_of": ymd,
                "published": "",
                "description": "",
            }

    tags = extract_teach_tags(picked.get("title") or "", picked.get("description") or "")
    row: Dict[str, Any] = {
        **picked,
        "teach_tags": tags,
        "source": "rss",
        "transcript": "",
        "transcript_status": "title_only",
        "visual_status": "title_only",
        "drive_file_id": "",
        "frames": [],
        "levels": [],
    }

    if _should_ingest_media(want_transcript, ymd):
        media_done = False
        # 1) 本機快取
        local_cands = [
            (os.getenv("HUANG_LOCAL_VIDEO") or "").strip(),
            f"/tmp/huang{ymd[-4:]}.mp4",
            f"/tmp/huang{ymd}.mp4",
            f"/tmp/huang{ymd[-4:]}/video.mp4",
        ]
        for lp in local_cands:
            if lp and os.path.isfile(lp) and os.path.getsize(lp) > 1_000_000:
                got = ingest_local_video(lp, work_dir=f"/tmp/huang-ingest-{ymd}")
                row["transcript"] = got.get("transcript") or ""
                row["transcript_status"] = got.get("transcript_status") or ""
                row["visual_status"] = got.get("visual_status") or ""
                row["frames"] = list(got.get("frames") or [])
                row["levels"] = list(got.get("levels") or [])
                row["source"] = "local_mp4"
                media_done = True
                break
        # 2) Drive
        if not media_done:
            fid = resolve_drive_file_id(ymd)
            if fid:
                got = ingest_drive_video(
                    ymd,
                    file_id=fid,
                    work_dir=f"/tmp/huang-drive-{ymd}",
                )
                row["drive_file_id"] = got.get("drive_file_id") or fid
                row["transcript"] = got.get("transcript") or ""
                row["transcript_status"] = got.get("transcript_status") or ""
                row["visual_status"] = got.get("visual_status") or ""
                row["frames"] = list(got.get("frames") or [])
                row["levels"] = list(got.get("levels") or [])
                if got.get("local_path"):
                    row["source"] = "drive_mp4"
                    media_done = str(got.get("transcript_status") or "").startswith(
                        "whisper"
                    ) or str(got.get("visual_status") or "") == "frames_ok"
                else:
                    row["source"] = "drive_miss"
        # 3) YouTube cookies
        if not media_done and cookies_path():
            tr = try_transcribe_video(str(picked.get("video_id") or ""))
            row["transcript"] = tr.get("transcript") or ""
            row["transcript_status"] = tr.get("transcript_status") or "title_only"
            row["visual_status"] = tr.get("visual_status") or ""
            row["frames"] = list(tr.get("frames") or [])
            row["levels"] = list(tr.get("levels") or [])
            if row["transcript"] or row["frames"]:
                row["source"] = "youtube_media"

    # 標題 tags 併入口播／位階
    if row.get("transcript"):
        tags = list(
            dict.fromkeys(
                tags
                + extract_teach_tags(str(row.get("transcript") or ""))
            )
        )
        row["teach_tags"] = tags
        more = extract_levels_from_text(str(row.get("transcript") or ""))
        row["levels"] = list(dict.fromkeys(list(row.get("levels") or []) + more))

    upsert_video(db_path, row)
    src_out = "youtube_rss"
    if row.get("source") in ("local_mp4", "drive_mp4", "youtube_media"):
        src_out = str(row.get("source"))
    elif row.get("source") == "drive_miss":
        src_out = "youtube_rss"
    out.update(
        {
            "video_id": picked.get("video_id") or "",
            "video_title": picked.get("title") or "",
            "source": src_out,
            "teach_tags": tags,
            "transcript_status": row.get("transcript_status") or "",
            "visual_status": row.get("visual_status") or "",
            "drive_file_id": row.get("drive_file_id") or "",
            "levels": list(row.get("levels") or []),
        }
    )
    return out
