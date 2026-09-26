# -*- coding: utf-8 -*-
"""GHA 與 Render 碟不同：防雙寄靠 WAYNE_SCREEN_NOTIFY=0。"""
import os

import pytest

import config


def test_assert_gha_screen_muted_ok_when_notify_off(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "0")
    config.assert_gha_screen_muted()


def test_assert_gha_screen_muted_raises_when_notify_on(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    with pytest.raises(RuntimeError, match="GHA 禁止寄海選"):
        config.assert_gha_screen_muted()


def test_assert_gha_noop_outside_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    config.assert_gha_screen_muted()


def test_daily_run_yml_locks_notify_zero():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".github", "workflows", "daily_run.yml")
    text = open(path, encoding="utf-8").read()
    assert 'WAYNE_SCREEN_NOTIFY: "0"' in text
    assert "確認 GHA 不寄海選" in text


def test_main_runner_calls_assert_gha():
    import inspect

    from main_runner import main

    src = inspect.getsource(main)
    assert "assert_gha_screen_muted" in src
