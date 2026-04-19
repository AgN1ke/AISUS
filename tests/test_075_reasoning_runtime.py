from __future__ import annotations

from types import SimpleNamespace

import agent.llm as llm


def _dummy_response(text: str = "ok"):
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_openai_reasoning_uses_effort_and_max_completion_tokens(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_REASONING_ENABLED", "1")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_REASONING_EFFORT", "high")
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "test-key")

    captured = {}

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return _dummy_response()

    monkeypatch.setattr(llm, "get_llm_client", lambda *args, **kwargs: DummyClient())

    llm.chat_once(
        [{"role": "user", "content": "подумай глибше"}],
        capability="chat_final",
        use_reasoning=True,
        temperature=0.8,
        max_tokens=321,
    )

    assert captured["model"] == "gpt-5.4-mini"
    assert captured["reasoning"] == {"effort": "high"}
    assert captured["max_completion_tokens"] == 321
    assert "max_tokens" not in captured
    assert "temperature" not in captured


def test_openai_reasoning_gate_off_keeps_normal_request(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_REASONING_ENABLED", raising=False)
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "test-key")

    captured = {}

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return _dummy_response()

    monkeypatch.setattr(llm, "get_llm_client", lambda *args, **kwargs: DummyClient())

    llm.chat_once(
        [{"role": "user", "content": "подумай глибше"}],
        capability="chat_final",
        use_reasoning=True,
        temperature=0.6,
        max_tokens=123,
    )

    assert captured["model"] == "gpt-5.4-mini"
    assert captured["temperature"] == 0.6
    assert captured["max_tokens"] == 123
    assert "reasoning" not in captured
    assert "max_completion_tokens" not in captured


def test_deepseek_reasoning_switches_model(monkeypatch):
    monkeypatch.setenv("CAPABILITY_AGENT_REASONING_PROVIDER", "deepseek")
    monkeypatch.setenv("CAPABILITY_AGENT_REASONING_MODEL", "deepseek-chat")
    monkeypatch.setenv("CAPABILITY_AGENT_REASONING_REASONING_ENABLED", "1")
    monkeypatch.setenv("PROVIDER_DEEPSEEK_API_KEY", "test-key")

    captured = {}

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return _dummy_response()

    monkeypatch.setattr(llm, "get_llm_client", lambda *args, **kwargs: DummyClient())

    llm.chat_once(
        [{"role": "user", "content": "роздумай"}],
        capability="agent_reasoning",
        use_reasoning=True,
        temperature=0.4,
        max_tokens=222,
    )

    assert captured["model"] == "deepseek-reasoner"
    assert captured["max_tokens"] == 222
    assert "temperature" not in captured
    assert "reasoning" not in captured


def test_gemini_3_omits_thinking_config_without_reasoning(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "gemini")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gemini-key")

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        del url, headers, timeout
        captured["json"] = json
        return SimpleNamespace(
            status_code=200,
            text="ok",
            raise_for_status=lambda: None,
            json=lambda: {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "ok"}],
                            "role": "model",
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)

    llm.chat_once(
        [{"role": "user", "content": "hi"}],
        capability="chat_final",
        use_reasoning=False,
    )

    assert "thinkingConfig" not in captured["json"]["generationConfig"]


def test_gemini_3_reasoning_uses_effort_level(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "gemini")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_REASONING_ENABLED", "1")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_REASONING_EFFORT", "high")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gemini-key")

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        del url, headers, timeout
        captured["json"] = json
        return SimpleNamespace(
            status_code=200,
            text="ok",
            raise_for_status=lambda: None,
            json=lambda: {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "ok"}],
                            "role": "model",
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)

    llm.chat_once(
        [{"role": "user", "content": "подумай"}],
        capability="chat_final",
        use_reasoning=True,
    )

    assert captured["json"]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "high"
    }


def test_gemini_3_reasoning_none_falls_back_to_low(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "gemini")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_REASONING_ENABLED", "1")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_REASONING_EFFORT", "none")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gemini-key")

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        del url, headers, timeout
        captured["json"] = json
        return SimpleNamespace(
            status_code=200,
            text="ok",
            raise_for_status=lambda: None,
            json=lambda: {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "ok"}],
                            "role": "model",
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)

    llm.chat_once(
        [{"role": "user", "content": "запусти різонінг"}],
        capability="chat_final",
        use_reasoning=True,
    )

    assert captured["json"]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "low"
    }
