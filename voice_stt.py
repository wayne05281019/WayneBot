"""Telegram 語音 → 文字。只做聽寫，不編新聞、不改策略。

聽寫走 OpenAI 相容 /audio/transcriptions（OPENAI_API_KEY 或 GROQ_API_KEY 或 WAYNE_STT_KEY）。
沒金鑰就不假裝聽懂。
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("WayneBot.VoiceSTT")

_OPENAI_STT = "https://api.openai.com/v1/audio/transcriptions"
_GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MAX_SEC = 45
STT_MAX_BYTES = 8 * 1024 * 1024


class SttNotConfigured(RuntimeError):
    """雲端沒有聽寫金鑰。"""


def stt_key() -> str:
    return (
        os.getenv("WAYNE_STT_KEY")
        or os.getenv("GROQ_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()


def stt_configured() -> bool:
    return bool(stt_key())


def stt_endpoint() -> str:
    url = (os.getenv("WAYNE_STT_URL") or "").strip()
    if url:
        return url
    if (os.getenv("GROQ_API_KEY") or "").strip() and not (os.getenv("WAYNE_STT_KEY") or "").strip():
        if not (os.getenv("OPENAI_API_KEY") or "").strip():
            return _GROQ_STT
    key = stt_key()
    if key.startswith("gsk_"):
        return _GROQ_STT
    return _OPENAI_STT


def stt_model() -> str:
    raw = (os.getenv("WAYNE_STT_MODEL") or "").strip()
    if raw:
        return raw
    if stt_endpoint().startswith("https://api.groq.com"):
        return "whisper-large-v3"
    return "whisper-1"


def stt_missing_html() -> str:
    return (
        "語音聽寫<b>還沒接金鑰</b>，現在聽不懂。\n"
        "請在雲端設定 <code>OPENAI_API_KEY</code> 或 <code>GROQ_API_KEY</code>（或 <code>WAYNE_STT_KEY</code>）。\n"
        "沒金鑰不會假裝聽懂。按了飆大也可以先<b>打字</b>問，例如「勤誠怎麼看」。"
    )


def transcribe_audio(path: str, *, timeout: float = 45.0) -> str:
    """把語音檔聽成中文。失敗就丟例外；沒金鑰丟 SttNotConfigured。"""
    key = stt_key()
    if not key:
        raise SttNotConfigured("no stt key")
    if not path or not os.path.isfile(path):
        return ""
    url = stt_endpoint()
    model = stt_model()
    with open(path, "rb") as fh:
        files = {"file": (os.path.basename(path) or "voice.ogg", fh, "application/octet-stream")}
        data = {"model": model, "language": "zh", "response_format": "json"}
        headers = {"Authorization": f"Bearer {key}"}
        try:
            resp = requests.post(
                url, headers=headers, files=files, data=data, timeout=timeout
            )
        except Exception:
            logger.debug("聽寫連線失敗", exc_info=True)
            raise
    if resp.status_code >= 400:
        logger.info("聽寫 HTTP %s", resp.status_code)
        resp.raise_for_status()
    payload = resp.json() if resp.content else {}
    text = str((payload or {}).get("text") or "").strip()
    return text


def heard_html(text: str) -> str:
    from tg_layout import html_escape

    shown = html_escape((text or "").strip()[:80])
    return f"聽到：<b>{shown}</b>"


def audio_suffix(voice) -> str:
    name = (getattr(voice, "file_name", None) or "").lower()
    mime = (getattr(voice, "mime_type", None) or "").lower()
    if name.endswith(".mp3") or "mpeg" in mime:
        return ".mp3"
    if name.endswith(".m4a") or "mp4" in mime:
        return ".m4a"
    if name.endswith(".wav") or "wav" in mime:
        return ".wav"
    return ".ogg"
