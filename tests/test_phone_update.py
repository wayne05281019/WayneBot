# -*- coding: utf-8 -*-
"""手機與畫面同一份國字更新說明。"""
from phone_update import (
    UPDATE_DONE,
    phone_code_reply,
    phone_health_fields,
    phone_update_note,
    phone_update_notice,
    phone_update_title,
)


def test_update_note_is_feature_name():
    note = phone_update_note()
    assert note
    assert any("\u4e00" <= ch <= "\u9fff" for ch in note)
    assert "feat:" not in note.lower()
    assert "," not in note
    title = phone_update_title()
    assert title.endswith("的更新")
    assert title == "洞燭每檔寫清買或不買的更新"


def test_notice_and_health_share_chinese_and_sha(monkeypatch):
    monkeypatch.setenv("WAYNE_UPDATE_NOTE", "龍頭股標籤")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    note = phone_update_note()
    assert note == "龍頭股標籤"
    assert phone_update_title() == "龍頭股標籤的更新"
    text = phone_update_notice("ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    assert text.splitlines() == [
        "龍頭股標籤的更新",
        UPDATE_DONE,
        "git_sha ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991",
    ]
    assert phone_code_reply() == text
    health = phone_health_fields()
    assert health["update"] == UPDATE_DONE
    assert health["update_note"] == "龍頭股標籤的更新"
    assert health["git_sha"] == "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991"
    assert UPDATE_DONE in text
    assert "龍頭股標籤的更新" in text


def test_title_does_not_double_suffix():
    assert phone_update_title("海選股名旁五角星的更新") == "海選股名旁五角星的更新"
