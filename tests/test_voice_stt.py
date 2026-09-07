# -*- coding: utf-8 -*-
"""語音聽寫：金鑰／端點／沒金鑰不假裝聽懂。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from voice_stt import (
    SttNotConfigured,
    audio_suffix,
    heard_html,
    stt_configured,
    stt_endpoint,
    stt_missing_html,
    stt_model,
    transcribe_audio,
)


@pytest.fixture
def no_stt_keys(monkeypatch):
    monkeypatch.delenv("WAYNE_STT_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WAYNE_STT_URL", raising=False)
    monkeypatch.delenv("WAYNE_STT_MODEL", raising=False)


def test_not_configured_without_keys(no_stt_keys):
    assert not stt_configured()
    with pytest.raises(SttNotConfigured):
        transcribe_audio("/tmp/nope.ogg")
    html = stt_missing_html()
    assert "還沒接金鑰" in html
    assert "OPENAI_API_KEY" in html
    assert "假裝" in html


def test_groq_key_picks_groq_endpoint(no_stt_keys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert stt_configured()
    assert stt_endpoint().startswith("https://api.groq.com")
    assert stt_model() == "whisper-large-v3"


def test_openai_key_picks_openai_endpoint(no_stt_keys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert stt_endpoint().startswith("https://api.openai.com")
    assert stt_model() == "whisper-1"


def test_explicit_url_and_model(no_stt_keys, monkeypatch):
    monkeypatch.setenv("WAYNE_STT_KEY", "abc")
    monkeypatch.setenv("WAYNE_STT_URL", "https://example.test/v1/audio/transcriptions")
    monkeypatch.setenv("WAYNE_STT_MODEL", "whisper-large-v3-turbo")
    assert stt_endpoint() == "https://example.test/v1/audio/transcriptions"
    assert stt_model() == "whisper-large-v3-turbo"


def test_audio_suffix_from_mime_and_name():
    assert audio_suffix(SimpleNamespace(file_name="a.mp3", mime_type="")) == ".mp3"
    assert audio_suffix(SimpleNamespace(file_name="", mime_type="audio/mp4")) == ".m4a"
    assert audio_suffix(SimpleNamespace(file_name="v.ogg", mime_type="audio/ogg")) == ".ogg"


def test_heard_html_escapes():
    html = heard_html("<script>x</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert html.startswith("聽到：")


def test_transcribe_posts_multipart(no_stt_keys, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"ogg")
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b'{"text":"ok"}'
    resp.json.return_value = {"text": "  為什麼跌  "}
    with patch("voice_stt.requests.post", return_value=resp) as post:
        text = transcribe_audio(str(path))
    assert text == "為什麼跌"
    _args, kwargs = post.call_args
    assert kwargs["data"]["language"] == "zh"
    assert kwargs["data"]["model"] == "whisper-1"
    assert "Authorization" in kwargs["headers"]


def test_transcribe_http_error(no_stt_keys, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    path = Path(tmp_path) / "voice.ogg"
    path.write_bytes(b"ogg")
    resp = MagicMock()
    resp.status_code = 401
    resp.content = b"no"
    resp.raise_for_status.side_effect = requests.HTTPError("401")
    with patch("voice_stt.requests.post", return_value=resp):
        with pytest.raises(requests.HTTPError):
            transcribe_audio(str(path))
