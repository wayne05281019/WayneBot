# -*- coding: utf-8 -*-
"""飆大即時對話線：有金鑰走 chat completions，pytest 預設不打外網。"""
from unittest.mock import patch

from biaoke_live import (
    live_configured,
    live_enabled,
    live_endpoint,
    live_model,
    live_reply,
    live_key,
)


def test_pytest_does_not_enable_live_without_flag(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("WAYNE_BIAOKE_LIVE_TEST", raising=False)
    assert live_key() == "gsk_test"
    assert not live_enabled()
    assert live_reply(":memory:", "2330") == ""


def test_groq_key_picks_groq_chat(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("WAYNE_BIAOKE_LLM_KEY", raising=False)
    monkeypatch.delenv("WAYNE_BIAOKE_LLM_URL", raising=False)
    monkeypatch.delenv("WAYNE_BIAOKE_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WAYNE_STT_KEY", raising=False)
    assert live_enabled()
    assert live_endpoint().startswith("https://api.groq.com")
    assert live_model() == "openai/gpt-oss-120b"


def test_live_reply_posts_chat_and_escapes(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")

    class _Res:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "勤誠量先價行 <b>不是買訊</b>"}}
                ]
            }

    with patch("biaoke_live.requests.post", return_value=_Res()) as post:
        html = live_reply(":memory:", "勤誠怎麼看", [{"ask": "大盤", "answer": "費半先行"}])
    assert "勤誠量先價行" in html
    assert "<b>" not in html
    assert "&lt;b&gt;" in html
    kwargs = post.call_args.kwargs
    assert post.call_args.args[0].startswith("https://api.groq.com")
    body = kwargs["json"]
    assert body["messages"][0]["role"] == "system"
    assert "認可" in body["messages"][0]["content"]
    assert "課綱" in body["messages"][0]["content"]
    assert body["messages"][-1]["content"] == "勤誠怎麼看"
    assert any(m.get("content") == "大盤" for m in body["messages"])


def test_answer_biaoke_uses_live_when_flagged(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    from biaoke_brain import answer_biaoke

    with patch("biaoke_live.live_reply", return_value="即時：夜盤先看"):
        html = answer_biaoke(":memory:", "大概何時止跌")
    assert html == "即時：夜盤先看"
    assert "這不是買訊" not in html


def test_live_reply_keeps_paragraphs(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")

    class _Res:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "先看夜盤。\n\n費半還在掉。"}}
                ]
            }

    with patch("biaoke_live.requests.post", return_value=_Res()):
        html = live_reply(":memory:", "大概何時止跌")
    assert "先看夜盤。" in html
    assert "\n\n" in html
    assert "費半還在掉。" in html


def test_live_retries_next_groq_model(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("WAYNE_BIAOKE_LLM_MODEL", raising=False)

    class _Miss:
        status_code = 404

        def raise_for_status(self):
            raise AssertionError("404 不該 raise 到呼叫端")

        def json(self):
            return {}

    class _Hit:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "在，你說。"}}]}

    with patch("biaoke_live.requests.post", side_effect=[_Miss(), _Hit()]) as post:
        html = live_reply(":memory:", "你好")
    assert html == "在，你說。"
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["json"]["model"] == "openai/gpt-oss-120b"
    assert post.call_args_list[1].kwargs["json"]["model"] == "openai/gpt-oss-20b"


def test_live_grounding_includes_method_notes(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")

    class _Res:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "洗盤不是出貨。"}}]}

    with patch("biaoke_live.requests.post", return_value=_Res()) as post:
        html = live_reply(":memory:", "洗盤跟出貨怎麼分")
    assert "洗盤不是出貨" in html
    sys_msg = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "方法" in sys_msg
    assert "2024-07-08" in sys_msg
    assert "語料" not in sys_msg
    assert "認可" in sys_msg


def test_live_notes_always_has_latest_posts_and_replies():
    from biaoke_desk import load_corpus_cache_clear
    from biaoke_live import live_notes

    load_corpus_cache_clear()
    note = live_notes("", "可以使用嗎")
    assert "46506" in note
    assert "45839" in note
    assert "最新發文" in note
    assert "最新樓下" in note
    assert "禁止 17000" in note
    wave = live_notes("", "目前大盤是屬於哪個位階 以波浪來看的話")
    assert "細微波" in wave or "48218" in wave
    assert "45839" in wave
    assert "時間線" in wave
    from unittest.mock import patch

    with patch("biaoke_audit.format_audit", return_value="三遍交叉：指紋全同。不是買訊。"):
        audit = live_notes("", "要做三次並交叉比對全部資料一字不漏")
    assert "三遍交叉" in audit
    assert "指紋全同" in audit


def test_live_notes_reverse_think_emc_hold():
    from biaoke_desk import load_corpus_cache_clear
    from biaoke_live import live_notes, SYSTEM

    assert "反向" in SYSTEM
    assert "產業趨勢" in SYSTEM
    assert "買跌不買漲" in SYSTEM
    assert "只講飆客" in SYSTEM or "路人發文不是重點" in SYSTEM
    assert "模糊的精確" in SYSTEM
    assert "波浪沒辦法" in SYSTEM or "沒講完的輔助" in SYSTEM
    assert "融會貫通" in SYSTEM
    assert "自問" in SYSTEM
    assert "不是介紹圖" in SYSTEM
    assert "出貨" in SYSTEM
    assert "量先價行" in SYSTEM
    assert "不是15分" in SYSTEM
    assert "F10" in SYSTEM
    assert "聯發科" in SYSTEM
    assert "尚未納入 F 系列" in SYSTEM
    assert "抱著波段賺更多" in SYSTEM
    load_corpus_cache_clear()
    note = live_notes("", "台光電 7 月抄底為什麼能抱到明年")
    assert "方法" in note
    assert "2026-04-16" in note
    assert "3930" in note
    assert "產業趨勢" in note
    mtk = live_notes("", "聯發科他有看好嗎")
    assert "2454" in mtk
    assert "IC 設計主線" in mtk
    assert "4/16" in mtk


def test_live_reply_system_forbids_invented_index(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")

    class _Res:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "夜盤先看 46506。"}}]}

    with patch("biaoke_live.requests.post", return_value=_Res()) as post:
        live_reply(":memory:", "目前大盤是屬於哪個位階 以波浪來看的話")
    sys_msg = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "46506" in sys_msg
    assert "45839" in sys_msg
    assert "禁止" in sys_msg
    assert "客服腔" in sys_msg
    assert post.call_args.kwargs["json"]["temperature"] == 0.2


def test_live_configured_ignores_pytest_flag(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("WAYNE_BIAOKE_LIVE_TEST", raising=False)
    assert live_configured() is True
    assert not live_enabled()


def test_live_retries_on_network_error(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("WAYNE_BIAOKE_LLM_MODEL", raising=False)

    class _Hit:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "在，你說。"}}]}

    with patch(
        "biaoke_live.requests.post",
        side_effect=[RuntimeError("timeout"), _Hit()],
    ) as post:
        html = live_reply(":memory:", "你好")
    assert html == "在，你說。"
    assert post.call_count == 2


def test_answer_biaoke_live_miss_does_not_dump_lecture(monkeypatch):
    monkeypatch.setenv("WAYNE_BIAOKE_LIVE_TEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    from biaoke_brain import LIVE_MISS, answer_biaoke

    with patch("biaoke_live.live_reply", return_value=""):
        html = answer_biaoke(":memory:", "勤誠怎麼看")
    assert html == LIVE_MISS
    assert "量先價行" not in html
    assert "課綱" not in html
