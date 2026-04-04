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


def test_admin_ui_exposes_search_provider_keys_and_orders():
    provider_keys = {field.key for field in admin_ui.PROVIDER_FIELDS}
    global_keys = {field.key for field in admin_ui.GLOBAL_FIELDS}
    capability_slugs = {cap.slug for cap in admin_ui.CAPABILITIES}

    assert "PROVIDER_PERPLEXITY_API_KEY" in provider_keys
    assert "PROVIDER_EXA_API_KEY" in provider_keys
    assert "PROVIDER_BRAVE_API_KEY" in provider_keys
    assert "SEARCH_OPENAI_MODEL" in global_keys
    assert "search_web" in capability_slugs
