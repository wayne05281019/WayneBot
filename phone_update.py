"""手機 Telegram 更新說明：人話講「現在在忙什麼／這次改了什麼」。

程式代碼只留在 /health，不准貼到偉權／哥哥手機。
開機若落在排程重窗（例如 16:30 融合），優先講當下忙碌，不准推內部說明句。
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from typing import Optional

UPDATE_DONE = "更新完成"
UPDATE_START = "正在更新"
_NOTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phone_update_note.txt")
_COMMIT_PREFIX = re.compile(
    r"^(feat|fix|docs|test|chore|refactor|perf|build|ci)(\([^)]+\))?:\s*",
    re.I,
)
_HEX = re.compile(r"\b[0-9a-f]{12,}\b", re.I)
# 把「通知機制本身」寫進話筒＝沒人看得懂；這類一律當無效
_META_NOTE = re.compile(
    r"(正在更新什麼|再說更新完成|開機推.{0,4}正在更新|就緒再推|"
    r"開機會先說|兩支話筒各收開始|同\s*SHA\s*不)",
    re.I,
)

# 台北時段 → 話筒等侯句（以此類推；超過 80 字會被裁）
# (start_min, end_min exclusive, note)
_SCHEDULE_WAIT_WINDOWS: tuple[tuple[int, int, str], ...] = (
    # 00:50–01:20 隔日盤後彙整（前一日開市）
    (
        50,
        1 * 60 + 20,
        "隔日盤後彙整進行中，官方柱與飆大資料正在入庫，請稍候",
    ),
    # 06:20–07:00 早報
    (
        6 * 60 + 20,
        7 * 60,
        "開市日早報正在整理勝率買點與大量圖，請稍候",
    ),
    # 12:40–13:05 尾盤比價
    (
        12 * 60 + 40,
        13 * 60 + 5,
        "尾盤雙時段比價正在整理，請稍候",
    ),
    # 16:25–17:00 盤後融合（使用者鎖例句）
    (
        16 * 60 + 25,
        17 * 60,
        "盤後資料正在下載融合中，請耐心等待資料彙整入庫完成，謝謝",
    ),
    # 17:35–18:05／18:45–19:15／22:25–22:55 盤後彙整
    (
        17 * 60 + 35,
        18 * 60 + 5,
        "盤後彙整進行中，官方柱與飆大資料正在入庫，請稍候",
    ),
    (
        18 * 60 + 45,
        19 * 60 + 15,
        "盤後彙整進行中，官方柱與飆大資料正在入庫，請稍候",
    ),
    (
        22 * 60 + 25,
        22 * 60 + 55,
        "盤後彙整進行中，官方柱與飆大資料正在入庫，請稍候",
    ),
    # 20:00–20:30 晚間 AI
    (
        20 * 60,
        20 * 60 + 30,
        "晚間模擬倉正在依收盤更新，請稍候",
    ),
    # 21:00–21:30 勝率落檔
    (
        21 * 60,
        21 * 60 + 30,
        "勝率買點名單正在盤後掃描落檔，請稍候",
    ),
)


def phone_git_sha() -> str:
    """Render／GHA 注入的 commit。不 import main，避免 bot 啟動環狀依賴。"""
    for key in ("RENDER_GIT_COMMIT", "GITHUB_SHA"):
        raw = (os.getenv(key) or "").strip()
        if raw:
            return raw[:40]
    return ""


def _has_han(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _is_meta_update_note(text: str) -> bool:
    """在講通知怎麼講／開機流程＝不准當話筒口語。"""
    t = str(text or "").strip()
    if not t:
        return False
    if _META_NOTE.search(t):
        return True
    if t in (UPDATE_START, UPDATE_DONE, f"{UPDATE_START}：", f"{UPDATE_START}:"):
        return True
    return False


def _clean_note(raw: str) -> str:
    t = str(raw or "").replace("\r", "").split("\n", 1)[0].strip()
    t = _COMMIT_PREFIX.sub("", t).strip()
    if t.lower().startswith("merge "):
        return ""
    t = _HEX.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" ，,")
    t = t[:80]
    if _is_meta_update_note(t):
        return ""
    return t


def _taipei_now(now: Optional[datetime] = None) -> Optional[datetime]:
    if now is not None:
        return now
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Taipei"))
    except Exception:
        return None


def _schedule_window_on_open_day(dt: datetime, *, lo: int) -> bool:
    """排程等候句只在「真的會跑那檔」的日子說。

    - 一般重窗（早報／尾盤／16:30 融合／盤後彙整／晚間／勝率）：當日台股開市日
    - 隔日 00:50–01:20 彙整：前一個日曆日是開市日（週末／國定假不准套這句）
    不准只看時鐘就在週六講「盤後融合中」。
    """
    try:
        from datetime import timedelta

        from trading_calendar import is_tw_open_calendar_day
    except Exception:
        return False
    try:
        ymd = dt.strftime("%Y%m%d")
    except Exception:
        return False
    # 隔日凌晨窗：對齊「前一日開市才有」
    if int(lo) < 6 * 60:
        prev = (dt - timedelta(days=1)).strftime("%Y%m%d")
        return bool(is_tw_open_calendar_day(prev))
    return bool(is_tw_open_calendar_day(ymd))


def phone_schedule_wait_note(now: Optional[datetime] = None) -> str:
    """開機／更新落在排程重窗時，用人話講正在忙什麼（台北時區）。

    非開市日（週末／國定假）即使撞到 16:25–17:00 時鐘窗，也不准講盤後融合。
    """
    dt = _taipei_now(now)
    if dt is None:
        return ""
    try:
        mins = int(dt.hour) * 60 + int(dt.minute)
    except Exception:
        return ""
    for lo, hi, text in _SCHEDULE_WAIT_WINDOWS:
        if lo <= mins < hi:
            if not _schedule_window_on_open_day(dt, lo=lo):
                return ""
            return _clean_note(text)
    return ""


def _git_head_note() -> str:
    """這次合進的最後一筆非 merge 標題＝真口語來源。"""
    try:
        raw = subprocess.check_output(
            ["git", "log", "-1", "--format=%s", "--no-merges"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            timeout=2,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return _clean_note(raw)
    except Exception:
        return ""


def _file_note() -> str:
    try:
        with open(_NOTE_FILE, encoding="utf-8") as f:
            return _clean_note(f.readline())
    except Exception:
        return ""


def phone_update_note(now: Optional[datetime] = None) -> str:
    """這次更新在講什麼。

    優先序：排程重窗等候句 → 環境變數 → 本趟 git 標題 → 檔案備援。
    16:30 融合窗優先講「盤後資料正在下載融合中…」（使用者鎖）。
    """
    sched = phone_schedule_wait_note(now=now)
    if sched and _has_han(sched):
        return sched
    env = _clean_note(os.getenv("WAYNE_UPDATE_NOTE") or "")
    if env and _has_han(env):
        return env
    git_note = _git_head_note()
    if git_note and _has_han(git_note):
        return git_note
    file_note = _file_note()
    if file_note and _has_han(file_note):
        return file_note
    return ""


def phone_update_title(note: str | None = None, *, now: Optional[datetime] = None) -> str:
    """手機第一行：這次改了什麼／正在忙什麼。"""
    if note is not None:
        return _clean_note(note)
    return _clean_note(phone_update_note(now=now))


def phone_update_lines(
    sha: str | None = None, *, note: str | None = None, now: Optional[datetime] = None
) -> list[str]:
    _ = sha
    title = phone_update_title(note, now=now)
    if title.endswith("完成") or title.endswith("謝謝"):
        # 等候句本身已收尾 → 不再疊「更新完成」
        return [title] if title else [UPDATE_DONE]
    lines: list[str] = []
    if title:
        lines.append(title)
    lines.append(UPDATE_DONE)
    return lines


def phone_update_starting(
    sha: str | None = None, *, note: str | None = None, now: Optional[datetime] = None
) -> str:
    """偉權／哥哥手機：開機／部署開始更新。不准貼程式代碼。

    排程重窗句本身已是完整人話 → 直接寄，不再加「正在更新：」前綴。
    沒有可懂口語 → 只回「正在更新」。
    """
    _ = sha
    title = phone_update_title(note, now=now)
    if not title:
        return UPDATE_START
    if title.startswith(UPDATE_START):
        return title[:80]
    # 等候句已含「請稍候／謝謝」→ 整句當訊息
    if "請" in title or title.endswith("謝謝"):
        return title[:80]
    return f"{UPDATE_START}：{title}"[:80]


def phone_update_notice(
    sha: str, *, note: str | None = None, now: Optional[datetime] = None
) -> str:
    """偉權／哥哥手機：這次改了什麼＋更新完成。不准貼程式代碼。"""
    return "\n".join(phone_update_lines(sha, note=note, now=now))


def phone_code_reply(sha: str | None = None) -> str:
    """打「代碼」也只回口語更新，不回 SHA。"""
    return phone_update_notice(sha if sha is not None else phone_git_sha() or "")


def phone_health_fields(sha: str | None = None, *, updating: bool = False) -> dict:
    """畫面 /health 另留 git_sha 給核對；手機文案不含這欄。"""
    full = str(sha if sha is not None else phone_git_sha() or "").strip()[:40]
    return {
        "git_sha": full,
        "update": UPDATE_START if updating else UPDATE_DONE,
        "update_note": phone_update_title(),
    }
