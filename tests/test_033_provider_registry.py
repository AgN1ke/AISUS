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


def test_resolve_provider_binding_prefers_keypool_key(monkeypatch):
    import asyncio
    import core.provider_registry as registry
    from billing.context import BillingContext
    from billing.runtime import use_billing_context
    from types import SimpleNamespace

    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_API_KEY", raising=False)
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(
        registry,
        "_run_async_sync",
        lambda coro: SimpleNamespace(api_key="pool-key", key_id=17, label="pool-a"),
    )

    async def _run():
        ctx = BillingContext(turn_id="t-1", account_id=1, chat_id=2, user_id=3)
        async with use_billing_context(ctx):
            return resolve_provider_binding("chat_final")

    binding = asyncio.run(_run())

    assert binding.api_key == "pool-key"
    assert binding.key_id == 17
    assert binding.key_label == "pool-a"
    assert binding.key_source == "keypool"


def test_resolve_provider_binding_skips_keypool_without_billing_context(monkeypatch):
    import core.provider_registry as registry

    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(
        registry,
        "_run_async_sync",
        lambda coro: (_ for _ in ()).throw(AssertionError("keypool should not run")),
    )

    binding = resolve_provider_binding("chat_final")

    assert binding.api_key == "env-key"
    assert binding.key_id is None
    assert binding.key_source == "env"


def test_resolve_provider_binding_capability_api_key_beats_keypool(monkeypatch):
    import core.provider_registry as registry
    from types import SimpleNamespace

    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_API_KEY", "cap-key")
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(
        registry,
        "_run_async_sync",
        lambda coro: SimpleNamespace(api_key="pool-key", key_id=17, label="pool-a"),
    )

    binding = resolve_provider_binding("chat_final")

    assert binding.api_key == "cap-key"
    assert binding.key_id is None
    assert binding.key_source == "env"


def test_resolve_provider_binding_billed_turn_prefers_keypool_over_capability_env(monkeypatch):
    import asyncio
    import core.provider_registry as registry
    from billing.context import BillingContext
    from billing.runtime import use_billing_context
    from types import SimpleNamespace

    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_API_KEY", "cap-key")
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(
        registry,
        "_run_async_sync",
        lambda coro: SimpleNamespace(api_key="pool-key", key_id=17, label="pool-a"),
    )

    async def _run():
        ctx = BillingContext(turn_id="t-1", account_id=1, chat_id=2, user_id=3)
        async with use_billing_context(ctx):
            return resolve_provider_binding("chat_final")

    binding = asyncio.run(_run())

    assert binding.api_key == "pool-key"
    assert binding.key_id == 17
    assert binding.key_source == "keypool"


def test_resolve_provider_binding_billed_turn_env_fallback_warns_once(monkeypatch):
    import asyncio
    import core.provider_registry as registry
    from billing.context import BillingContext
    from billing.runtime import use_billing_context

    warnings: list[tuple[str, tuple]] = []

    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_API_KEY", raising=False)
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(registry, "_run_async_sync", lambda coro: None)
    monkeypatch.setattr(
        registry.logger,
        "warning",
        lambda message, *args: warnings.append((message, args)),
    )

    async def _run():
        ctx = BillingContext(turn_id="t-1", account_id=1, chat_id=2, user_id=3)
        async with use_billing_context(ctx):
            first = resolve_provider_binding("chat_final")
            second = resolve_provider_binding("chat_final")
            return first, second

    first, second = asyncio.run(_run())

    assert first.api_key == "env-key"
    assert second.api_key == "env-key"
    assert first.key_source == second.key_source == "env_fallback"
    assert len(warnings) == 1
    assert warnings[0][0] == "provider_registry.env_fallback_used capability=%s provider=%s source=%s"
    assert warnings[0][1] == ("chat_final", "openai", "provider_api_key")


def test_resolve_provider_binding_caches_keypool_binding_per_turn(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import core.provider_registry as registry
    from billing.context import BillingContext
    from billing.runtime import use_billing_context

    calls = {"count": 0}

    def fake_run_async_sync(coro):
        calls["count"] += 1
        return SimpleNamespace(api_key="pool-key", key_id=23, label="pool-b")

    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("CAPABILITY_CHAT_FINAL_API_KEY", raising=False)
    monkeypatch.setattr(registry, "_run_async_sync", fake_run_async_sync)

    async def _run():
        ctx = BillingContext(turn_id="t-1", account_id=1, chat_id=2, user_id=3)
        async with use_billing_context(ctx):
            first = resolve_provider_binding("chat_final")
            second = resolve_provider_binding("chat_final")
            return first, second

    first, second = asyncio.run(_run())

    assert calls["count"] == 1
    assert first.api_key == "pool-key"
    assert second.api_key == "pool-key"
    assert first.key_id == second.key_id == 23
