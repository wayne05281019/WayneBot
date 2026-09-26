"""手機 Telegram 更新說明：這次實際改了什麼，口語一句。

程式代碼只留在 /health，不准貼到偉權／哥哥手機。
"""
from __future__ import annotations

import os
import re
import subprocess

UPDATE_DONE = "更新完成"
_NOTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phone_update_note.txt")
_COMMIT_PREFIX = re.compile(
    r"^(feat|fix|docs|test|chore|refactor|perf|build|ci)(\([^)]+\))?:\s*",
    re.I,
)
_HEX = re.compile(r"\b[0-9a-f]{12,}\b", re.I)


def phone_git_sha() -> str:
    """Render／GHA 注入的 commit。不 import main，避免 bot 啟動環狀依賴。"""
    for key in ("RENDER_GIT_COMMIT", "GITHUB_SHA"):
        raw = (os.getenv(key) or "").strip()
        if raw:
            return raw[:40]
    return ""


def _has_han(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _clean_note(raw: str) -> str:
    t = str(raw or "").replace("\r", "").split("\n", 1)[0].strip()
    t = _COMMIT_PREFIX.sub("", t).strip()
    if t.lower().startswith("merge "):
        return ""
    t = _HEX.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" ，,")
    return t[:80]


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


def phone_update_note() -> str:
    """這次更新在講什麼。

    優先序：環境變數 → 本趟 git 標題 → 檔案備援。
    不准讓舊檔永遠蓋過新合進的真改動（否則每次 redeploy 都推同一句「飆大…」）。
    """
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


def phone_update_title(note: str | None = None) -> str:
    """手機第一行：這次改了什麼。"""
    return _clean_note(note if note is not None else phone_update_note())


def phone_update_lines(sha: str | None = None, *, note: str | None = None) -> list[str]:
    _ = sha
    title = phone_update_title(note)
    if title.endswith("完成"):
        return [title] if title else [UPDATE_DONE]
    lines: list[str] = []
    if title:
        lines.append(title)
    lines.append(UPDATE_DONE)
    return lines


def phone_update_notice(sha: str, *, note: str | None = None) -> str:
    """偉權／哥哥手機：這次改了什麼＋更新完成。不准貼程式代碼。"""
    return "\n".join(phone_update_lines(sha, note=note))


def phone_code_reply(sha: str | None = None) -> str:
    """打「代碼」也只回口語更新，不回 SHA。"""
    return phone_update_notice(sha if sha is not None else phone_git_sha() or "")


def phone_health_fields(sha: str | None = None) -> dict:
    """畫面 /health 另留 git_sha 給核對；手機文案不含這欄。"""
    full = str(sha if sha is not None else phone_git_sha() or "").strip()[:40]
    return {
        "git_sha": full,
        "update": UPDATE_DONE,
        "update_note": phone_update_title(),
    }
