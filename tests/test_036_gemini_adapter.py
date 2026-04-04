from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent.llm as llm
import media.vision as vision


class _DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = "ok"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise llm.requests.HTTPError("boom")

    def json(self):
        return self._payload


def _dummy_llm_response(text: str):
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_chat_once_gemini_text_request(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "gemini")
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_ADAPTER", raising=False)
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("PROVIDER_GEMINI_BASE_URL", raising=False)

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _DummyResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Все добре."}],
                            "role": "model",
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)

    response = llm.chat_once(
        [
            {"role": "system", "content": "Ти котик."},
            {"role": "user", "content": "Привіт"},
            {"role": "assistant", "content": "Няв."},
            {"role": "user", "content": "Як справи?"},
        ],
        capability="chat_final",
        temperature=0.1,
        max_tokens=77,
    )

    assert (
        captured["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert captured["headers"]["x-goog-api-key"] == "gemini-key"
    assert captured["json"]["systemInstruction"]["parts"][0]["text"] == "Ти котик."
    assert captured["json"]["contents"] == [
        {"role": "user", "parts": [{"text": "Привіт"}]},
        {"role": "model", "parts": [{"text": "Няв."}]},
        {"role": "user", "parts": [{"text": "Як справи?"}]},
    ]
    assert captured["json"]["generationConfig"] == {
        "temperature": 0.1,
        "maxOutputTokens": 77,
        "thinkingConfig": {"thinkingBudget": 0},
    }
    assert captured["timeout"] == 45
    assert response.choices[0].message.content == "Все добре."


def test_chat_once_gemini_image_request(monkeypatch):
    monkeypatch.setenv("CAPABILITY_VISION_IMAGE_PROVIDER", "gemini")
    monkeypatch.delenv("CAPABILITY_VISION_IMAGE_ADAPTER", raising=False)
    monkeypatch.setenv("CAPABILITY_VISION_IMAGE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gemini-key")

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "На зображенні кіт."}],
                            "role": "model",
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)

    response = llm.chat_once(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Що тут?"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,ZmFrZQ==",
                        },
                    },
                ],
            }
        ],
        capability="vision_image",
        temperature=0,
    )

    parts = captured["json"]["contents"][0]["parts"]
    assert parts[0] == {"text": "Що тут?"}
    assert parts[1] == {
        "inline_data": {
            "mime_type": "image/png",
            "data": "ZmFrZQ==",
        }
    }
    assert response.choices[0].message.content == "На зображенні кіт."


def test_chat_once_gemini_rejects_tools(monkeypatch):
    monkeypatch.setenv("CAPABILITY_AGENT_REASONING_PROVIDER", "gemini")
    monkeypatch.delenv("CAPABILITY_AGENT_REASONING_ADAPTER", raising=False)
    monkeypatch.setenv("CAPABILITY_AGENT_REASONING_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gemini-key")

    with pytest.raises(RuntimeError, match="does not yet support tool"):
        llm.chat_once(
            [{"role": "user", "content": "hi"}],
            capability="agent_reasoning",
            tools=[{"type": "function", "function": {"name": "search_web"}}],
        )


def test_describe_images_uses_capability_binding_without_model_override(
    monkeypatch, tmp_path
):
    image = tmp_path / "img.jpg"
    image.write_bytes(b"fake-jpg")

    captured = {}

    def fake_chat_once(
        messages,
        tools=None,
        use_reasoning=False,
        model=None,
        temperature=0.2,
        capability="chat_final",
        **kwargs,
    ):
        captured["messages"] = messages
        captured["tools"] = tools
        captured["use_reasoning"] = use_reasoning
        captured["model"] = model
        captured["temperature"] = temperature
        captured["capability"] = capability
        captured["kwargs"] = kwargs
        return _dummy_llm_response("Опис")

    monkeypatch.setattr(vision, "chat_once", fake_chat_once)

    result = vision.describe_images([str(image)], task_hint="Поясни мем")

    assert result == "Опис"
    assert captured["model"] is None
    assert captured["capability"] == "vision_image"
    assert captured["temperature"] == 0.2
    assert captured["kwargs"]["max_tokens"] == 400
    assert captured["messages"][0] == {"role": "system", "content": "Поясни мем"}
    user_parts = captured["messages"][1]["content"]
    assert user_parts[0]["type"] == "text"
    assert user_parts[1]["type"] == "image_url"
