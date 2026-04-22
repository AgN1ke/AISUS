from __future__ import annotations

import pytest

from db import portal_repository


@pytest.mark.asyncio
async def test_update_portal_settings_persists_valid_choices(monkeypatch):
    captured: list[tuple[int, str, str | None]] = []

    async def fake_set_user_setting(user_id: int, key: str, value: str | None) -> None:
        captured.append((user_id, key, value))

    async def fake_list_provider_keys(_provider: str) -> list[dict]:
        return []

    async def fake_get_user_settings(_user_id: int) -> dict[str, str]:
        return {"voice_id": "alloy"}

    monkeypatch.setattr(portal_repository, "set_user_setting", fake_set_user_setting)
    monkeypatch.setattr(portal_repository, "list_provider_keys", fake_list_provider_keys)
    monkeypatch.setattr(portal_repository, "get_user_settings", fake_get_user_settings)
    monkeypatch.setattr(portal_repository, "provider_api_key", lambda provider: "key" if provider == "openai" else "")

    settings = await portal_repository.update_portal_settings(
        77,
        model_choices={
            "chat": "openai::gpt-5.4-mini",
            "think": "",
            "media": "",
        },
        voice_id="nova",
        persona_slug="technical",
    )

    assert settings == {"voice_id": "alloy"}
    assert (77, "chat_provider", "openai") in captured
    assert (77, "chat_model", "gpt-5.4-mini") in captured
    assert (77, "think_provider", None) in captured
    assert (77, "think_model", None) in captured
    assert (77, "voice_id", "nova") in captured
    assert (77, "persona_slug", "technical") in captured


@pytest.mark.asyncio
async def test_update_portal_settings_rejects_provider_without_available_key(monkeypatch):
    async def fake_list_provider_keys(_provider: str) -> list[dict]:
        return []

    monkeypatch.setattr(portal_repository, "list_provider_keys", fake_list_provider_keys)
    monkeypatch.setattr(portal_repository, "provider_api_key", lambda _provider: "")

    with pytest.raises(ValueError, match="немає доступного API-ключа"):
        await portal_repository.update_portal_settings(
            77,
            model_choices={"chat": "openai::gpt-5.4-mini"},
            voice_id="",
            persona_slug="",
        )


@pytest.mark.asyncio
async def test_create_portal_topup_request_creates_pending_row(monkeypatch):
    async def fake_get_user(_user_id: int) -> dict:
        return {"user_id": 77, "tg_username": "agnike"}

    async def fake_get_account_by_owner(_user_id: int) -> dict:
        return {"account_id": 11}

    created: dict = {}

    async def fake_create_topup(**kwargs):
        created.update(kwargs)
        return 91

    async def fake_get_topup(topup_id: int) -> dict:
        return {"id": topup_id, "status": "pending", "amount_uah": "150.00", "note": created["note"]}

    monkeypatch.setattr(portal_repository, "get_user", fake_get_user)
    monkeypatch.setattr(portal_repository, "get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr(portal_repository, "create_topup", fake_create_topup)
    monkeypatch.setattr(portal_repository, "get_topup", fake_get_topup)

    payload = await portal_repository.create_portal_topup_request(
        77,
        amount_uah="150",
        note="поповнення на тест",
    )

    assert created["account_id"] == 11
    assert created["status"] == "pending"
    assert created["note"].startswith("portal_request:")
    assert payload["topup"]["id"] == 91
