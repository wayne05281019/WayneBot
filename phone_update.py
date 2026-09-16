"""手機 Telegram 與畫面 /health 同一份更新說明。

國字敘述這次改了什麼，並標「更新完成」。git_sha 與畫面同一串。
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
    return t[:80]


def phone_update_note() -> str:
    """這次更新的國字一句。檔案優先，沒有再讀 git 標題。"""
    env = _clean_note(os.getenv("WAYNE_UPDATE_NOTE") or "")
    if env and _has_han(env):
        return env
    try:
        with open(_NOTE_FILE, encoding="utf-8") as f:
            line = _clean_note(f.readline())
        if line and _has_han(line):
            return line
    except Exception:
        pass
    try:
        raw = subprocess.check_output(
            ["git", "log", "-1", "--format=%s", "--no-merges"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            timeout=2,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        line = _clean_note(raw)
        if line and _has_han(line):
            return line
    except Exception:
        pass
    return ""


def phone_update_lines(sha: str | None = None, *, note: str | None = None) -> list[str]:
    lines = [UPDATE_DONE]
    n = _clean_note(note if note is not None else phone_update_note())
    if n:
        lines.append(n)
    full = str(sha if sha is not None else phone_git_sha() or "").strip()[:40]
    if full:
        lines.append(f"git_sha {full}")
    return lines


def phone_update_notice(sha: str, *, note: str | None = None) -> str:
    """偉權／哥哥手機與畫面同一份：更新完成＋國字說明＋完整 SHA。"""
    return "\n".join(phone_update_lines(sha, note=note))


def phone_code_reply(sha: str | None = None) -> str:
    """隨時查目前這顆程式：與開機通知、/health 同一份國字＋代碼。"""
    return phone_update_notice(sha if sha is not None else phone_git_sha())


def phone_health_fields(sha: str | None = None) -> dict:
    """畫面 /health 與手機同一組欄。"""
    full = str(sha if sha is not None else phone_git_sha() or "").strip()[:40]
    return {
        "git_sha": full,
        "update": UPDATE_DONE,
        "update_note": phone_update_note(),
    }
