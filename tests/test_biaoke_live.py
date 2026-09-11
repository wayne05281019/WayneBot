# -*- coding: utf-8 -*-
"""飆大即時對話線：有金鑰走 chat completions，pytest 預設不打外網。"""
from unittest.mock import patch

from biaoke_live import live_enabled, live_endpoint, live_model, live_reply, live_key


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
