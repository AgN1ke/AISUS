from core.provider_registry import resolve_provider_binding


def test_resolve_provider_binding_legacy_defaults(monkeypatch):
    monkeypatch.delenv("DEFAULT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_PROVIDER", raising=False)
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_ADAPTER", raising=False)
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "legacy-model")

    binding = resolve_provider_binding("chat_final")

    assert binding.provider == "openai"
    assert binding.adapter == "openai_chat"
    assert binding.model == "legacy-model"
    assert binding.api_key == "legacy-key"
    assert binding.base_url == "https://legacy.example/v1"


def test_resolve_provider_binding_capability_specific_provider(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "deepseek")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_ADAPTER", "openai_chat")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "deepseek-chat")
    monkeypatch.setenv("PROVIDER_DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("PROVIDER_DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    binding = resolve_provider_binding("chat_final")

    assert binding.provider == "deepseek"
    assert binding.adapter == "openai_chat"
    assert binding.model == "deepseek-chat"
    assert binding.api_key == "deepseek-key"
    assert binding.base_url == "https://api.deepseek.com"


def test_resolve_provider_binding_uses_native_default_adapter_for_gemini(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_VISION_IMAGE_PROVIDER", "gemini")
    monkeypatch.delenv("CAPABILITY_VISION_IMAGE_ADAPTER", raising=False)
    monkeypatch.setenv("CAPABILITY_VISION_IMAGE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gemini-key")

    binding = resolve_provider_binding("vision_image")

    assert binding.provider == "gemini"
    assert binding.adapter == "gemini_generate_content"
    assert binding.model == "gemini-2.5-flash"
    assert binding.api_key == "gemini-key"


def test_chat_once_uses_capability_provider_binding(monkeypatch):
    import agent.llm as llm

    monkeypatch.setenv("CAPABILITY_SEARCH_QUERY_COMPOSER_PROVIDER", "deepseek")
    monkeypatch.setenv("CAPABILITY_SEARCH_QUERY_COMPOSER_MODEL", "deepseek-chat")
    monkeypatch.setenv("PROVIDER_DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("PROVIDER_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm.clear_llm_client_cache()

    captured = {}

    class DummyClient:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            captured["request_kwargs"] = kwargs

            class _Obj:
                pass

            obj = _Obj()
            msg = _Obj()
            msg.content = "ok"
            msg.tool_calls = None
            choice = _Obj()
            choice.message = msg
            obj.choices = [choice]
            return obj

    def fake_get_llm_client(provider, api_key, base_url=None):
        captured["client_kwargs"] = {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
        }
        return DummyClient()

    monkeypatch.setattr(llm, "get_llm_client", fake_get_llm_client)

    llm.chat_once(
        [{"role": "user", "content": "test"}],
        capability="search_query_composer",
        temperature=0,
    )

    assert captured["client_kwargs"] == {
        "provider": "deepseek",
        "api_key": "deepseek-key",
        "base_url": "https://api.deepseek.com",
    }
    assert captured["request_kwargs"]["model"] == "deepseek-chat"
