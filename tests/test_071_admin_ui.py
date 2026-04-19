from pathlib import Path
import re

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
    assert media_caps["stt_voice"].model_type == "stt"


def test_render_dashboard_has_clear_memory_button():
    html = admin_ui.render_dashboard(
        {
            "SMARTEST_ADMIN_USERNAME": "korol",
            "SMARTEST_ADMIN_PASSWORD": "secret",
        }
    )

    assert 'formaction="/clear-memory"' in html
    assert "Очистити пам'ять" in html


def test_render_dashboard_has_podcast_panel():
    html = admin_ui.render_dashboard(
        {
            "SMARTEST_ADMIN_USERNAME": "korol",
            "SMARTEST_ADMIN_PASSWORD": "secret",
            "PODCAST_NOTEBOOKLM_PROJECT_ID": "notebooklm-492911",
            "PODCAST_NOTEBOOKLM_LOCATION": "global",
            "PODCAST_NOTEBOOKLM_STATUS_MESSAGE": "Podcast API ще не готовий.",
        }
    )

    assert "NotebookLM Podcast" in html
    assert 'formaction="/upload-podcast-secret"' in html
    assert 'formaction="/check-podcast"' in html


def test_clear_bot_memory_runs_global_clear(monkeypatch):
    called = {}

    async def fake_clear_global():
        called["ok"] = True

    monkeypatch.setattr(admin_ui.memory_manager, "clear_global", fake_clear_global)

    ok, message = admin_ui.clear_bot_memory()

    assert ok is True
    assert message == "ok"
    assert called["ok"] is True


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


def test_effective_model_for_video_capability_ignores_invalid_legacy_openai_model():
    cap = next(c for c in admin_ui.CAPABILITIES if c.slug == "video_understanding")
    values = {
        "OPENAI_CHAT_MODEL": "gpt-4o-mini",
        "DEFAULT_LLM_PROVIDER": "openai",
    }

    assert admin_ui._effective_provider(cap, values) == "gemini"
    assert admin_ui._effective_model(cap, values) == "gemini-2.5-flash"


def test_normalized_capability_binding_rejects_invalid_video_provider_and_model():
    cap = next(c for c in admin_ui.CAPABILITIES if c.slug == "video_understanding")

    provider, model, adapter = admin_ui._normalized_capability_binding(
        cap,
        {},
        provider="openai",
        model="gpt-4o-mini",
    )

    assert provider == "gemini"
    assert model == "gemini-2.5-flash"
    assert adapter == "gemini_generate_content"


def test_render_dashboard_video_card_does_not_show_openai_model():
    html = admin_ui.render_dashboard(
        {
            "SMARTEST_ADMIN_USERNAME": "korol",
            "SMARTEST_ADMIN_PASSWORD": "secret",
            "PROVIDER_GEMINI_API_KEY": "gem-key",
            "OPENAI_CHAT_MODEL": "gpt-4o-mini",
            "DEFAULT_LLM_PROVIDER": "openai",
        }
    )

    match = re.search(
        r'<div class="cap-card" data-cap="video_understanding".*?</div>\s*</div>',
        html,
        re.DOTALL,
    )
    assert match is not None
    card = match.group(0)
    assert 'name="CAPABILITY_VIDEO_UNDERSTANDING_PROVIDER"' in card
    assert '<option value="gemini" selected>' in card
    assert '<option value="gemini-2.5-flash" selected>' in card
    assert "gpt-4o-mini" not in card


def test_render_dashboard_reasoning_controls_enabled_for_supported_model():
    html = admin_ui.render_dashboard(
        {
            "SMARTEST_ADMIN_USERNAME": "korol",
            "SMARTEST_ADMIN_PASSWORD": "secret",
            "PROVIDER_OPENAI_API_KEY": "openai-key",
            "CAPABILITY_CHAT_FINAL_PROVIDER": "openai",
            "CAPABILITY_CHAT_FINAL_MODEL": "gpt-5.4-mini",
            "CAPABILITY_CHAT_FINAL_REASONING_ENABLED": "1",
            "CAPABILITY_CHAT_FINAL_REASONING_EFFORT": "high",
        }
    )

    match = re.search(
        r'<div class="cap-card" data-cap="chat_final".*?</div>\s*</div>',
        html,
        re.DOTALL,
    )
    assert match is not None
    card = match.group(0)
    assert 'name="CAPABILITY_CHAT_FINAL_REASONING_ENABLED"' in card
    assert 'name="CAPABILITY_CHAT_FINAL_REASONING_EFFORT"' in card
    assert 'checked' in card
    assert '<option value="high" selected>' in card


def test_render_dashboard_reasoning_controls_disabled_for_unsupported_model():
    html = admin_ui.render_dashboard(
        {
            "SMARTEST_ADMIN_USERNAME": "korol",
            "SMARTEST_ADMIN_PASSWORD": "secret",
            "PROVIDER_OPENAI_API_KEY": "openai-key",
            "CAPABILITY_CHAT_FINAL_PROVIDER": "openai",
            "CAPABILITY_CHAT_FINAL_MODEL": "gpt-4.1-mini",
            "CAPABILITY_CHAT_FINAL_REASONING_ENABLED": "1",
        }
    )

    match = re.search(
        r'<div class="cap-card" data-cap="chat_final".*?</div>\s*</div>',
        html,
        re.DOTALL,
    )
    assert match is not None
    card = match.group(0)
    assert 'name="CAPABILITY_CHAT_FINAL_REASONING_ENABLED"' in card
    assert 'disabled' in card


def test_filter_log_text_filters_by_trace_chat_and_level():
    log_text = "\n".join(
        [
            "2026-04-08 INFO app.message_logic | flow.start trace=ptb:99913:8 chat_id=99913 message_id=8 capability=chat_final",
            "2026-04-08 WARNING agent.runner | search.retry trace=ptb:99913:8 chat_id=99913 message_id=8 capability=search_synthesis",
            "2026-04-08 ERROR media.router | media.ptb.failed trace=ptb:99914:9 chat_id=99914 message_id=9 capability=vision_image",
        ]
    )

    filtered = admin_ui._filter_log_text(
        log_text,
        trace="ptb:99913:8",
        chat_id="99913",
        message_id="8",
        capability="search_synthesis",
        level="WARNING",
    )

    assert "search.retry" in filtered
    assert "flow.start" not in filtered
    assert "media.ptb.failed" not in filtered


def test_read_log_text_prefers_trace_file_in_auto_mode(tmp_path, monkeypatch):
    trace_path = tmp_path / "smartest-bot.log"
    trace_path.write_text(
        "2026-04-08 INFO app.message_logic | flow.start trace=ptb:1:2 chat_id=1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(admin_ui, "_service_log_file", lambda _service: trace_path)
    monkeypatch.setattr(
        admin_ui,
        "_read_journal_log",
        lambda _service, _lines: "journal fallback should not be used",
    )

    text, source, location = admin_ui._read_log_text(
        admin_ui.MANAGED_BOT_SERVICE,
        lines=100,
        source="auto",
    )

    assert "flow.start" in text
    assert source == "trace"
    assert location == str(trace_path)


def test_render_logs_page_has_source_and_filter_controls(monkeypatch):
    monkeypatch.setattr(
        admin_ui,
        "_read_log_text",
        lambda *args, **kwargs: (
            "2026-04-08 INFO run | runtime.boot",
            "trace",
            "/tmp/smartest-bot.log",
        ),
    )

    html = admin_ui.render_logs_page(
        {},
        service=admin_ui.MANAGED_BOT_SERVICE,
        lines=500,
        source="trace",
        contains="runtime.boot",
        trace="ptb:1:2",
        chat_id="1",
        message_id="2",
        capability="chat_final",
        level="INFO",
    )

    assert 'id="source-select"' in html
    assert 'id="chatid-input"' in html
    assert 'id="messageid-input"' in html
    assert 'id="trace-input"' in html
    assert 'id="capability-input"' in html
    assert 'id="contains-input"' in html
    assert "/logs-text?" in html
    assert "runtime.boot" in html
