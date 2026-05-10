from pathlib import Path

import app.admin_ui as admin_ui


def test_write_env_updates_preserves_comments_and_updates_values(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        '# Header\nOPENAI_API_KEY=old-key\nEMPTY=""\n\n# Footer\n',
        encoding="utf-8",
    )

    admin_ui.write_env_updates(
        env_path,
        {
            "OPENAI_API_KEY": "new-key",
            "CAPABILITY_CHAT_FINAL_MODEL": "gpt-5.4-mini",
        },
    )

    text = env_path.read_text(encoding="utf-8")
    assert "# Header" in text
    assert "OPENAI_API_KEY=new-key" in text
    assert "CAPABILITY_CHAT_FINAL_MODEL=gpt-5.4-mini" in text
    assert "# Footer" in text


def test_session_token_roundtrip():
    token = admin_ui.session_token("korol", "secret-123")
    payload = admin_ui.parse_session_token(token, "secret-123")

    assert payload is not None
    assert payload["u"] == "korol"


def test_ensure_session_secret_writes_missing_secret(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("SMARTEST_ADMIN_USERNAME=korol\n", encoding="utf-8")
    monkeypatch.setattr(admin_ui, "ENV_PATH", env_path)

    secret = admin_ui.ensure_session_secret({"SMARTEST_ADMIN_USERNAME": "korol"})

    assert secret
    current = admin_ui.read_current_config()
    assert current["SMARTEST_ADMIN_SESSION_SECRET"] == secret


def test_admin_ui_exposes_search_provider_keys():
    provider_keys = {f.key for f in admin_ui.PROVIDER_FIELDS}
    assert "PROVIDER_PERPLEXITY_API_KEY" in provider_keys
    assert "PROVIDER_EXA_API_KEY" in provider_keys
    assert "PROVIDER_BRAVE_API_KEY" in provider_keys


def test_admin_ui_exposes_global_search_fields():
    global_keys = {f.key for f in admin_ui.GLOBAL_FIELDS}
    assert "SEARCH_OPENAI_MODEL" in global_keys
    assert "DEFAULT_LLM_PROVIDER" in global_keys


def test_admin_ui_capabilities_include_all_agents():
    slugs = {cap.slug for cap in admin_ui.CAPABILITIES}
    assert "chat_final" in slugs
    assert "planner_reasoning" in slugs
    assert "search_query_planner" in slugs
    assert "search_query_composer" in slugs
    assert "search_evaluator" in slugs
    assert "search_synthesis" in slugs
    assert "vision_image" in slugs
    assert "video_understanding" in slugs
    assert "stt_voice" in slugs
    assert "memory_summary" in slugs
    assert "document_context" in slugs
    assert "agent_reasoning" in slugs


def test_admin_ui_capability_groups():
    groups = {cap.group for cap in admin_ui.CAPABILITIES}
    assert groups == {"smart", "functional", "media"}


def test_admin_ui_media_capabilities_have_correct_model_type():
    media_caps = {cap.slug: cap for cap in admin_ui.CAPABILITIES if cap.group == "media"}
    assert media_caps["vision_image"].model_type == "vision"
    assert media_caps["video_understanding"].model_type == "video"


def test_admin_ui_stt_voice_is_chat_capability():
    cap = next(c for c in admin_ui.CAPABILITIES if c.slug == "stt_voice")
    assert cap.group == "smart"
    assert cap.model_type == "text"
    assert "Whisper" in cap.help_text


def test_auto_adapter():
    assert admin_ui._auto_adapter("gemini", "text") == "gemini_generate_content"
    assert admin_ui._auto_adapter("openai", "vision") == "openai_vision"
    assert admin_ui._auto_adapter("openai", "text") == "openai_chat"
    assert admin_ui._auto_adapter("deepseek", "text") == "openai_chat"


def test_model_options_cover_media_types():
    assert "vision" in admin_ui.MODELS
    assert "video" in admin_ui.MODELS
    assert "stt" in admin_ui.MODELS
    # Video only has gemini
    assert set(admin_ui.MODELS["video"].keys()) == {"gemini"}
    # STT only has openai
    assert set(admin_ui.MODELS["stt"].keys()) == {"openai"}


def test_render_dashboard_includes_token_calculator(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("SMARTEST_ADMIN_USERNAME=korol\n", encoding="utf-8")
    monkeypatch.setattr(admin_ui, "ENV_PATH", env_path)
    monkeypatch.setattr(admin_ui, "service_status", lambda _name: "active")
    monkeypatch.setattr(
        admin_ui,
        "token_dashboard_data",
        lambda **_kwargs: {
            "log_path": str(tmp_path / "token_usage.jsonl"),
            "memory_error": "",
            "usage": {
                "calls": 2,
                "failed": 1,
                "tokens_in": 1200,
                "tokens_out": 345,
                "tokens_total": 1545,
                "by_model": [
                    {
                        "provider": "openai",
                        "model": "gpt-test",
                        "capability": "chat_final",
                        "calls": 2,
                        "failed": 1,
                        "tokens_in": 1200,
                        "tokens_out": 345,
                        "tokens_total": 1545,
                    }
                ],
            },
            "memory": {
                "recent": {"rows_count": 3, "tokens": 900},
                "long": {"rows_count": 2, "tokens": 500},
                "core": {"rows_count": 1, "tokens": 100},
                "total_tokens": 1500,
                "chats": [
                    {
                        "chat_id": "-10042",
                        "recent_tokens": 900,
                        "long_tokens": 500,
                        "core_tokens": 100,
                        "total_tokens": 1500,
                    }
                ],
            },
        },
    )

    rendered = admin_ui.render_dashboard({})

    assert "Token calculator" in rendered
    assert "Token calendar" in rendered
    assert "Tracked LLM calls by model" in rendered
    assert "Working memory context by chat" in rendered
    assert "gpt-test" in rendered
    assert "chat_final" in rendered
    assert "-10042" in rendered
    assert "1 545" in rendered
    assert "/clear-memory" in rendered


def test_clear_bot_memory_calls_global_clear(monkeypatch):
    called = {}

    async def fake_clear_global():
        called["ok"] = True

    monkeypatch.setattr(admin_ui.memory_manager, "clear_global", fake_clear_global)

    ok, detail = admin_ui.clear_bot_memory()

    assert ok is True
    assert detail == "ok"
    assert called["ok"] is True
