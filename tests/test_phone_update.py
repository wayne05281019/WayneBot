# -*- coding: utf-8 -*-
"""手機與畫面同一份國字更新說明。"""
from phone_update import (
    UPDATE_DONE,
    phone_code_reply,
    phone_health_fields,
    phone_update_note,
    phone_update_notice,
)


def test_update_note_is_chinese():
    note = phone_update_note()
    assert note
    assert any("\u4e00" <= ch <= "\u9fff" for ch in note)
    assert "feat:" not in note.lower()
    assert "，" in note
    assert "," not in note


def test_notice_and_health_share_chinese_and_sha(monkeypatch):
    monkeypatch.setenv("WAYNE_UPDATE_NOTE", "這次更新改國字說明並標更新完成")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    note = phone_update_note()
    assert note == "這次更新改國字說明並標更新完成"
    text = phone_update_notice("ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    assert text.splitlines() == [
        UPDATE_DONE,
        note,
        "git_sha ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991",
    ]
    assert phone_code_reply() == text
    health = phone_health_fields()
    assert health["update"] == UPDATE_DONE
    assert health["update_note"] == note
    assert health["git_sha"] == "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991"
    assert UPDATE_DONE in text
    assert note in text
