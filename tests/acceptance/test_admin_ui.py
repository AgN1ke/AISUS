from __future__ import annotations

import app.admin_ui as admin_ui


def _patch_dashboard_runtime(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("SMARTEST_ADMIN_USERNAME=admin\n", encoding="utf-8")
    monkeypatch.setattr(admin_ui, "ENV_PATH", env_path)
    monkeypatch.setattr(admin_ui, "service_status", lambda _name: "active")
    monkeypatch.setattr(
        admin_ui,
        "token_dashboard_data",
        lambda **_kwargs: {
            "log_path": str(tmp_path / "token_usage.jsonl"),
            "memory_error": "",
            "usage": {
                "calls": 0,
                "failed": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_total": 0,
                "by_model": [],
            },
            "memory": {
                "recent": {"rows_count": 0, "tokens": 0},
                "long": {"rows_count": 0, "tokens": 0},
                "core": {"rows_count": 0, "tokens": 0},
                "total_tokens": 0,
                "chats": [],
            },
        },
    )


def test_search_gate_prompt_in_prompt_defs():
    slugs = {pd.slug for pd in admin_ui.PROMPT_DEFS}
    assert "search_gate" in slugs

    prompt = next(pd for pd in admin_ui.PROMPT_DEFS if pd.slug == "search_gate")
    assert prompt.env_key == "PROMPT_SEARCH_GATE"
    assert prompt.capability == "planner_reasoning"


def test_voice_fields_exposed():
    keys = {f.key for f in admin_ui.VOICE_FIELDS}
    assert {
        "OPENAI_WHISPER_MODEL",
        "OPENAI_TTS_MODEL",
        "OPENAI_VOCALIZER_VOICE",
    }.issubset(keys)


def test_tuning_fields_exposed():
    keys = {f.key for f in admin_ui.TUNING_FIELDS}
    assert {
        "MEMORY_CONTEXT_BUDGET",
        "MEMORY_WORKING_CONTEXT_BUDGET",
        "MEMORY_LONG_CONTEXT_BUDGET",
        "MEMORY_CORE_CONTEXT_BUDGET",
        "MEMORY_RECENT_BUDGET",
        "MEMORY_LONG_BUDGET",
        "MEMORY_CORE_BUDGET",
        "ALBUM_PROCESSING_SETTLE_SECONDS",
        "MEDIA_TMP_MAX_AGE_HOURS",
    }.issubset(keys)


def test_stt_voice_is_chat_capability_not_stt():
    cap = next(c for c in admin_ui.CAPABILITIES if c.slug == "stt_voice")
    assert cap.group == "smart"
    assert cap.model_type == "text"
    assert cap.model_type != "stt"


def test_render_dashboard_contains_voice_section(monkeypatch, tmp_path):
    _patch_dashboard_runtime(monkeypatch, tmp_path)

    rendered = admin_ui.render_dashboard({})

    assert "Voice &amp; STT" in rendered or "Voice & STT" in rendered
    assert "OPENAI_WHISPER_MODEL" in rendered
    assert "OPENAI_TTS_MODEL" in rendered
    assert "OPENAI_VOCALIZER_VOICE" in rendered


def test_render_dashboard_contains_tuning_section(monkeypatch, tmp_path):
    _patch_dashboard_runtime(monkeypatch, tmp_path)

    rendered = admin_ui.render_dashboard({})

    assert "Memory &amp; Albums" in rendered or "Memory & Albums" in rendered
    assert "MEMORY_CONTEXT_BUDGET" in rendered
    assert "MEMORY_RECENT_BUDGET" in rendered
    assert "ALBUM_PROCESSING_SETTLE_SECONDS" in rendered
    assert "MEDIA_TMP_MAX_AGE_HOURS" in rendered


def test_render_dashboard_contains_token_calendar(monkeypatch, tmp_path):
    _patch_dashboard_runtime(monkeypatch, tmp_path)

    rendered = admin_ui.render_dashboard({})

    assert "Token calendar" in rendered
    assert "Selected period by model" in rendered


def test_render_prompts_lists_search_gate():
    rendered = admin_ui.render_prompts_page({})

    assert "Search Gate" in rendered
    assert "PROMPT_SEARCH_GATE" in rendered
