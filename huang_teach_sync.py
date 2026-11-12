"""台北 14:30：去黃培碩當日片學習／吸收；再依時間與飆大對質。

節奏（使用者鎖死）：
- 開市日台北 14:30 去黃那邊抓片→學習→吸收（60分方法）
- 飆大發文在黃片之前 → 用黃來「驗證」飆大已說的
- 飆大發文在黃片之後 → 拿來「比對」黃剛吸收的
- 話筒價位仍跟飆大口頭；近／超近 60 分只畫大C（C1–C4）；遠窗日K
- 不是買訊；不寄話筒推播
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.huang_teach")

TAIPEI = ZoneInfo("Asia/Taipei")
PIPELINE_PREFIX = "huang-teach-"
# 台北 14:30 準點；補跑到 15:20 前仍算這檔
SLOT_MINUTE = 14 * 60 + 30
CATCHUP_UNTIL = 15 * 60 + 20
# 黃片預設對照時刻＝當日 14:30（去學習那一刻）；有 hint 可覆寫
DEFAULT_VIDEO_HM = "1430"


def _ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def pipeline_key(ymd: str) -> str:
    return f"{PIPELINE_PREFIX}{str(ymd or '').strip()}"


def ensure_tables(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS huang_teach_runs (
                as_of TEXT NOT NULL PRIMARY KEY,
                status TEXT NOT NULL,
                video_id TEXT DEFAULT '',
                video_title TEXT DEFAULT '',
                note TEXT DEFAULT '',
                paint_ok INTEGER DEFAULT 0,
                mode TEXT DEFAULT '',
                verify_n INTEGER DEFAULT 0,
                compare_n INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )
        cols = {
            str(r[1])
            for r in conn.execute("PRAGMA table_info(huang_teach_runs)").fetchall()
        }
        for col, decl in (
            ("mode", "TEXT DEFAULT ''"),
            ("verify_n", "INTEGER DEFAULT 0"),
            ("compare_n", "INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE huang_teach_runs ADD COLUMN {col} {decl}")
        conn.commit()
    finally:
        conn.close()


def _stamp() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _already_success(db_path: str, ymd: str) -> bool:
    key = pipeline_key(ymd)
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT status FROM pipeline_runs WHERE run_date=?", (key,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row and str(row[0] or "") == "success")


def _mark_pipeline(db_path: str, ymd: str, status: str, notes: str) -> None:
    key = pipeline_key(ymd)
    try:
        from wayne_db import connect

        conn = connect(db_path)
    except Exception:
        conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs "
            "(run_date, status, notes, finished_at) VALUES (?, ?, ?, ?)",
            (key, status, (notes or "")[:500], _stamp()),
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_run(db_path: str, row: Dict[str, Any]) -> None:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO huang_teach_runs(
                as_of, status, video_id, video_title, note, paint_ok,
                mode, verify_n, compare_n, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(as_of) DO UPDATE SET
                status=excluded.status,
                video_id=excluded.video_id,
                video_title=excluded.video_title,
                note=excluded.note,
                paint_ok=excluded.paint_ok,
                mode=excluded.mode,
                verify_n=excluded.verify_n,
                compare_n=excluded.compare_n,
                updated_at=excluded.updated_at
            """,
            (
                str(row.get("as_of") or ""),
                str(row.get("status") or ""),
                str(row.get("video_id") or ""),
                str(row.get("video_title") or ""),
                str(row.get("note") or "")[:800],
                1 if row.get("paint_ok") else 0,
                str(row.get("mode") or ""),
                int(row.get("verify_n") or 0),
                int(row.get("compare_n") or 0),
                _stamp(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _hm_norm(raw: Any) -> str:
    t = re.sub(r"\D", "", str(raw or ""))
    if len(t) >= 4:
        return t[:4]
    if len(t) == 3:
        return t.zfill(4)
    return ""


def resolve_huang_video_hm(hint: Dict[str, str], *, as_of_ymd: str) -> str:
    """黃片對照時刻（台北 HHMM）。預設 1430＝去學習的準點；hint 可覆寫。"""
    for key in ("video_hm", "hm", "time"):
        hm = _hm_norm(hint.get(key))
        if hm:
            return hm
    title = str(hint.get("video_title") or "")
    m = re.search(r"(?<!\d)([01]?\d|2[0-3])[:：]?([0-5]\d)(?!\d)", title)
    if m:
        return f"{int(m.group(1)):02d}{int(m.group(2)):02d}"
    _ = as_of_ymd
    return DEFAULT_VIDEO_HM


def classify_biaoke_vs_huang(
    db_path: str,
    as_of_ymd: str,
    *,
    video_hm: str = DEFAULT_VIDEO_HM,
) -> Dict[str, Any]:
    """當日飆大文 vs 黃片時刻：在前＝verify，在後＝compare。

    只數他自己的公開文（biaoke_posts）；空庫＝兩邊都 0。
    """
    ymd = str(as_of_ymd or "").strip()
    hm = _hm_norm(video_hm) or DEFAULT_VIDEO_HM
    out: Dict[str, Any] = {
        "video_hm": hm,
        "verify_n": 0,
        "compare_n": 0,
        "mode": "absorb",
        "verify_ids": [],
        "compare_ids": [],
    }
    if not ymd or not os.path.isfile(db_path):
        return out
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            rows = conn.execute(
                "SELECT id, time, substr(text,1,80) FROM biaoke_posts "
                "WHERE date=? ORDER BY time, id",
                (ymd,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return out
    verify_ids: List[str] = []
    compare_ids: List[str] = []
    for pid, tm, _snip in rows:
        phm = _hm_norm(tm)
        if not phm:
            continue
        if phm < hm:
            verify_ids.append(str(pid))
        else:
            compare_ids.append(str(pid))
    out["verify_n"] = len(verify_ids)
    out["compare_n"] = len(compare_ids)
    out["verify_ids"] = verify_ids[:12]
    out["compare_ids"] = compare_ids[:12]
    if verify_ids and compare_ids:
        out["mode"] = "verify+compare"
    elif verify_ids:
        out["mode"] = "verify"
    elif compare_ids:
        out["mode"] = "compare"
    else:
        out["mode"] = "absorb"
    return out


def _is_open_day(dt: datetime, db_path: str) -> bool:
    try:
        from trading_calendar import is_tw_open_calendar_day

        return bool(is_tw_open_calendar_day(dt.strftime("%Y%m%d")))
    except Exception:
        try:
            from tw_holidays import closed_tw_session

            return closed_tw_session(now=dt, db_path=db_path) is None and dt.weekday() < 5
        except Exception:
            return dt.weekday() < 5


def find_huang_video_hint(
    as_of_ymd: str,
    *,
    db_path: str = "",
    fetch_youtube: bool = True,
) -> Dict[str, str]:
    """找當日黃培碩片提示：優先 YouTube RSS 自動抓；再 env／本機快取。

    不准假造 file id。影音全文：Drive ``MMDD黃培碩.mp4`` 或 HUANG_YT_COOKIES；
    沒影音仍用標題教法標籤。看影片＝影格＋口播。
    """
    out = {"video_id": "", "video_title": "", "source": ""}
    ymd = str(as_of_ymd or "").strip()
    # 1) YouTube RSS＋Drive／cookies 影音（不靠使用者每天貼）
    if ymd and db_path:
        try:
            from huang_youtube import discover_day_video, resolve_drive_file_id

            want_media = bool(
                (os.getenv("HUANG_YT_COOKIES") or os.getenv("YTDLP_COOKIES") or "").strip()
                or resolve_drive_file_id(ymd)
                or (os.getenv("HUANG_LOCAL_VIDEO") or "").strip()
            )
            yt = discover_day_video(
                db_path,
                ymd,
                fetch=bool(fetch_youtube),
                want_transcript=want_media,
            )
            if yt.get("video_id") or yt.get("video_title"):
                out = {
                    "video_id": str(yt.get("video_id") or ""),
                    "video_title": str(yt.get("video_title") or ""),
                    "source": str(yt.get("source") or "youtube_rss"),
                }
                tags = yt.get("teach_tags") or []
                if tags:
                    out["teach_tags"] = ",".join(str(x) for x in tags)
                if yt.get("transcript_status"):
                    out["transcript_status"] = str(yt.get("transcript_status") or "")
                if yt.get("visual_status"):
                    out["visual_status"] = str(yt.get("visual_status") or "")
                if yt.get("drive_file_id"):
                    out["drive_file_id"] = str(yt.get("drive_file_id") or "")
                levels = yt.get("levels") or []
                if levels:
                    out["levels"] = ",".join(str(x) for x in levels)
                return out
        except Exception:
            logger.exception("huang_teach：YouTube／Drive 自動抓片略過")

    vid = (os.getenv("HUANG_TEACH_VIDEO_ID") or "").strip()
    title = (os.getenv("HUANG_TEACH_VIDEO_TITLE") or "").strip()
    if vid and title:
        if ymd and (ymd in title or f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" in title):
            return {"video_id": vid, "video_title": title, "source": "env"}
        if not ymd:
            return {"video_id": vid, "video_title": title, "source": "env"}
    # 本機／artifact 旁註（agent 抓片後可落這檔）
    hint_paths = (
        os.path.join("data", "huang_teach_hint.json"),
        os.path.join("/opt/cursor/artifacts", f"huang-hint-{ymd}.json"),
        os.path.join("/opt/cursor/artifacts", "huang-oral-chart-pair.md"),
    )
    for hp in hint_paths:
        if not os.path.isfile(hp):
            continue
        try:
            if hp.endswith(".json"):
                raw = json.loads(open(hp, encoding="utf-8").read())
                t = str(raw.get("video_title") or raw.get("title") or "")
                i = str(raw.get("video_id") or raw.get("fileId") or "")
                if ymd and t and ymd not in t and f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" not in t:
                    continue
                if i or t:
                    return {
                        "video_id": i,
                        "video_title": t,
                        "source": f"file:{os.path.basename(hp)}",
                    }
            else:
                # markdown 對讀：有當日字樣就算有材料
                text = open(hp, encoding="utf-8").read()
                if ymd and ymd not in text and f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" not in text:
                    # 允許口播對讀檔只寫 2026-11-10 格式
                    dash = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                    if dash not in text:
                        continue
                m = re.search(r"Drive\s+([A-Za-z0-9_-]{20,})", text)
                return {
                    "video_id": m.group(1) if m else "",
                    "video_title": "huang-oral-chart-pair",
                    "source": "oral_pair_md",
                }
        except Exception:
            logger.debug("huang hint 讀取略過 %s", hp, exc_info=True)
    return out


def run_huang_teach_sync(
    db_path: Optional[str] = None,
    *,
    skip_if_done: bool = True,
    now: Optional[datetime] = None,
    force_paint: bool = True,
) -> Dict[str, Any]:
    """開市日 14:30：吸收黃培碩；飆大在前＝驗證、在後＝比對；再重渲教導窗。非買訊。"""
    from config import get_db_path

    path = str(db_path or get_db_path() or "").strip()
    out: Dict[str, Any] = {
        "ok": False,
        "skipped": "",
        "as_of": "",
        "paint_ok": False,
        "video_id": "",
        "status": "",
        "mode": "",
        "verify_n": 0,
        "compare_n": 0,
    }
    if not path:
        out["skipped"] = "no_db"
        return out
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    ymd = _ymd(dt)
    out["as_of"] = ymd
    if not _is_open_day(dt, path):
        out["skipped"] = "closed"
        out["status"] = "closed"
        return out
    ensure_tables(path)
    if skip_if_done and _already_success(path, ymd):
        out["skipped"] = "done"
        out["status"] = "done"
        out["ok"] = True
        return out

    # 先吸飆大庫，才能依發文時刻分驗證／比對
    try:
        from biaoke_ingest import run_biaoke_ingest_quiet

        run_biaoke_ingest_quiet()
    except Exception:
        logger.exception("huang_teach：飆大匯入略過（不擋吸收）")

    hint = find_huang_video_hint(ymd, db_path=path, fetch_youtube=True)
    out["video_id"] = hint.get("video_id") or ""
    video_hm = resolve_huang_video_hm(hint, as_of_ymd=ymd)
    timing = classify_biaoke_vs_huang(path, ymd, video_hm=video_hm)
    out["mode"] = str(timing.get("mode") or "absorb")
    out["verify_n"] = int(timing.get("verify_n") or 0)
    out["compare_n"] = int(timing.get("compare_n") or 0)

    note_bits = [
        "14:30吸收黃培碩（60分方法）；非買訊",
        f"video_hm={video_hm}",
        f"mode={out['mode']}",
        f"verify_n={out['verify_n']}",
        f"compare_n={out['compare_n']}",
        f"hint={hint.get('source') or 'none'}",
    ]
    if hint.get("teach_tags"):
        note_bits.append(f"teach_tags={hint.get('teach_tags')}")
    if hint.get("transcript_status"):
        note_bits.append(f"transcript={hint.get('transcript_status')}")
    if out["verify_n"]:
        note_bits.append("飆大在前→用黃驗證")
    if out["compare_n"]:
        note_bits.append("飆大在後→與黃比對")
    if hint.get("video_title"):
        note_bits.append(f"title={hint.get('video_title')[:80]}")

    paint_ok = False
    if force_paint:
        try:
            from biaoke_level_learn import paint_open_day_hypothesis

            painted = paint_open_day_hypothesis(path, force=True, panels="trio") or {}
            paint_ok = bool(painted.get("ok") or painted.get("far_path") or painted.get("path"))
            if painted.get("slot_id"):
                note_bits.append(f"slot={painted.get('slot_id')}")
        except Exception:
            logger.exception("huang_teach：教導三窗重渲失敗")
            paint_ok = False

    out["paint_ok"] = paint_ok
    status = "success" if paint_ok else "paint_failed"
    if not hint.get("video_id") and not hint.get("video_title"):
        note_bits.append("no_video_yet")
        if paint_ok:
            status = "success"
        else:
            status = "pending_no_video"
    out["status"] = status
    _upsert_run(
        path,
        {
            "as_of": ymd,
            "status": status,
            "video_id": hint.get("video_id") or "",
            "video_title": hint.get("video_title") or "",
            "note": "；".join(note_bits),
            "paint_ok": paint_ok,
            "mode": out["mode"],
            "verify_n": out["verify_n"],
            "compare_n": out["compare_n"],
        },
    )
    _mark_pipeline(path, ymd, status if status == "success" else "error", "；".join(note_bits))
    out["ok"] = status == "success"
    return out


def due_for_catchup(now: Optional[datetime] = None) -> bool:
    """補跑門檻：開市日已過 14:30 且未滿 CATCHUP_UNTIL（之後仍可 skip_if_done 補）。"""
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    mins = dt.hour * 60 + dt.minute
    return mins >= SLOT_MINUTE
