# -*- coding: utf-8 -*-
"""Cursor／本機不得用正式 token 搶 Render 的 getUpdates。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402


def test_cursor_cloud_skips_polling_even_without_flag(monkeypatch):
    monkeypatch.delenv("WAYNE_SKIP_POLLING", raising=False)
    monkeypatch.setenv("CURSOR_AGENT", "1")
    assert config.skip_telegram_polling() is True


def test_cursor_cloud_cannot_opt_into_polling(monkeypatch):
    monkeypatch.setenv("CURSOR_AGENT", "1")
    monkeypatch.setenv("WAYNE_SKIP_POLLING", "0")
    assert config.skip_telegram_polling() is True


def test_local_without_flag_still_can_poll(monkeypatch):
    monkeypatch.delenv("WAYNE_SKIP_POLLING", raising=False)
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert config.skip_telegram_polling() is False


def test_explicit_flag_skips_on_laptop(monkeypatch):
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    monkeypatch.setenv("WAYNE_SKIP_POLLING", "1")
    assert config.skip_telegram_polling() is True


def test_render_polls_by_default(monkeypatch):
    monkeypatch.delenv("WAYNE_SKIP_POLLING", raising=False)
    monkeypatch.delenv("CURSOR_AGENT", raising=False)
    monkeypatch.setenv("RENDER", "true")
    assert config.skip_telegram_polling() is False


def test_run_polling_refuses_without_calling_telegram(monkeypatch):
    monkeypatch.setenv("CURSOR_AGENT", "1")
    import bot_servers

    calls = []

    class _Boom:
        @staticmethod
        def builder():
            calls.append("builder")
            raise AssertionError("Cursor Cloud 不得建立 Application 去 getUpdates")

    class _Stub:
        token = "123:placeholder"

    monkeypatch.setattr(bot_servers, "TELEGRAM_AVAILABLE", True)
    monkeypatch.setattr(bot_servers, "Application", _Boom)
    bot_servers.WayneTelegramBot.run_polling(_Stub())
    assert calls == []
