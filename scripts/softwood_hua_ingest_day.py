#!/usr/bin/env python3
"""Softwood Hua（軟木華／阮慕驊）《財經一路發》單日 ingest。

優先：Firstory/iTunes 音檔 → whisper；有 cookies 再試 YouTube 字幕。
不准假造口播；失敗只寫 status。not_buy_signal；phone_sync blocked。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "expert_notes" / "軟木華" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
APPLE_PODCAST_ID = 1531106786
YTDLP = os.getenv("YTDLP_BIN") or "python3 -m yt_dlp"


def _asof_day(s: str) -> str:
    s = str(s or "").strip().replace("-", "")
    if len(s) == 8 and s.isdigit():
        return s
    raise SystemExit(f"bad --asof {s!r}; want YYYYMMDD")


def _dot_date(asof: str) -> str:
    return f"{asof[2:4]}.{asof[4:6]}.{asof[6:8]}"


def _cookies_path() -> str:
    for p in (
        os.getenv("SOFTWOOD_HUA_YT_COOKIES") or "",
        os.getenv("HUANG_YT_COOKIES") or "",
        "/tmp/huang_yt_cookies.txt",
    ):
        if p and os.path.isfile(p):
            return p
    return ""


def lookup_itunes_episode(asof: str) -> Optional[Dict[str, Any]]:
    """找 Apple Podcast 同日集（標題含 2026.11.20 形）。"""
    url = (
        f"https://itunes.apple.com/lookup?id={APPLE_PODCAST_ID}"
        f"&entity=podcastEpisode&limit=50"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "WayneBot-softwood-hua/1.0"})
    raw = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    needle = _dot_date(asof)
    needle2 = f"{asof[0:4]}.{asof[4:6]}.{asof[6:8]}"
    for r in raw.get("results") or []:
        if r.get("wrapperType") == "track" and r.get("kind") == "podcast":
            continue
        name = str(r.get("trackName") or "")
        if needle in name or needle2 in name or asof in name.replace(".", ""):
            return {
                "trackName": name,
                "episodeUrl": r.get("episodeUrl") or "",
                "releaseDate": r.get("releaseDate") or "",
                "description": (r.get("description") or "")[:2000],
            }
    return None


def download_mp3(url: str, dest: Path) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WayneBot-softwood-hua/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            dest.write_bytes(resp.read())
        return dest.is_file() and dest.stat().st_size > 1000
    except Exception as e:
        print(f"mp3_fail: {e}", file=sys.stderr)
        return False


def whisper_file(media: Path) -> Dict[str, str]:
    out = {"transcript": "", "transcript_status": "whisper_skipped"}
    whisper_bin = os.getenv("SOFTWOOD_HUA_WHISPER_BIN") or os.getenv("HUANG_WHISPER_BIN") or "whisper"
    model = os.getenv("SOFTWOOD_HUA_WHISPER_MODEL") or "base"
    with tempfile.TemporaryDirectory(prefix="softwood-whisper-") as td:
        cmd = [
            whisper_bin,
            str(media),
            "--model",
            model,
            "--language",
            "zh",
            "--output_dir",
            td,
            "--output_format",
            "txt",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
        except Exception as e:
            out["transcript_status"] = f"whisper_failed:{e}"
            return out
        txts = list(Path(td).glob("*.txt"))
        if not txts:
            out["transcript_status"] = "whisper_empty"
            return out
        text = txts[0].read_text(encoding="utf-8", errors="ignore").strip()
        out["transcript"] = text
        out["transcript_status"] = "whisper_ok" if text else "whisper_empty"
        return out


def try_youtube_captions(video_id: str, dest_dir: Path) -> Dict[str, str]:
    out = {"transcript": "", "transcript_status": "skipped_no_cookies", "path": ""}
    cookies = _cookies_path()
    if not cookies:
        return out
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(dest_dir / "cap")
    cmd = [
        *YTDLP.split(),
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
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except Exception:
        out["transcript_status"] = "captions_failed"
        return out
    vtts = sorted(dest_dir.glob("*.vtt"), key=lambda p: (0 if "zh" in p.name.lower() else 1, p.name))
    for vp in vtts:
        text = _vtt_to_text(vp)
        if text:
            out["transcript"] = text
            out["transcript_status"] = "captions_ok"
            out["path"] = str(vp)
            return out
    out["transcript_status"] = "captions_empty"
    return out


def _vtt_to_text(vtt_path: Path) -> str:
    seen = set()
    lines: List[str] = []
    try:
        raw = vtt_path.read_text(encoding="utf-8", errors="ignore")
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


def write_absorb(
    asof: str,
    video_id: str,
    transcript: str,
    transcript_status: str,
    episode: Optional[Dict[str, Any]],
) -> Path:
    DOC.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TAIPEI).isoformat(timespec="seconds")
    row: Dict[str, Any] = {
        "as_of": now,
        "as_of_day": asof,
        "tz": "Asia/Taipei",
        "track": "softwood_hua",
        "expert_zh": "軟木華",
        "expert_en": "Softwood Hua",
        "legal_name_zh": "阮慕驊",
        "phone_sync": "blocked",
        "buy_signal": False,
        "not_buy_signal": True,
        "certainty": False,
        "segment_numbers": "FORBIDDEN_for_stocks",
        "source": {
            "kind": "youtube_live_or_podcast",
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "podcast_episode": episode,
        },
        "ingest": {
            "transcript": transcript,
            "transcript_status": transcript_status,
            "do_not_invent_quotes": True,
        },
        "today_teach_methods": [],
        "criteria_today": {
            "hard_rules": [],
            "soft_opinions": [],
            "examples": [],
            "note_zh": (
                "transcript 已落地時：人工／下一輪抽取 hard/soft/examples；"
                "空 transcript 則保持空列表"
                if not transcript
                else "請下一輪依 transcript 抽取 hard_rules／soft_opinions／examples；不准發明"
            ),
        },
    }
    path = DOC / f"softwood_hua_oral_absorb_{asof}.json"
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = DOC / "softwood_hua_oral_absorb_latest.json"
    latest.write_text(
        json.dumps({**row, "points_to": path.name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True, help="YYYYMMDD Asia/Taipei")
    ap.add_argument("--video-id", default="", help="YouTube video_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asof = _asof_day(args.asof)
    video_id = str(args.video_id or "").strip()

    episode = lookup_itunes_episode(asof)
    transcript = ""
    status = "no_source"

    with tempfile.TemporaryDirectory(prefix="softwood-hua-") as td:
        td_path = Path(td)
        if episode and episode.get("episodeUrl"):
            mp3 = td_path / "ep.mp3"
            if download_mp3(str(episode["episodeUrl"]), mp3):
                wh = whisper_file(mp3)
                transcript = wh.get("transcript") or ""
                status = wh.get("transcript_status") or "whisper_unknown"
            else:
                status = "podcast_download_failed"
        else:
            status = "podcast_not_found"

        if not transcript and video_id:
            cap = try_youtube_captions(video_id, td_path / "caps")
            if cap.get("transcript"):
                transcript = cap["transcript"]
                status = cap.get("transcript_status") or "captions_ok"
            elif status.startswith("podcast"):
                status = f"{status}+{cap.get('transcript_status')}"

    if args.dry_run:
        print(
            json.dumps(
                {
                    "asof": asof,
                    "video_id": video_id,
                    "episode": episode,
                    "transcript_status": status,
                    "transcript_chars": len(transcript),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    path = write_absorb(asof, video_id, transcript, status, episode)
    print(f"wrote {path} status={status} chars={len(transcript)}")
    return 0 if transcript else 2


if __name__ == "__main__":
    raise SystemExit(main())
