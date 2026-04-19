import json

from core import podcast as podcast_core


def test_store_service_account_secret_writes_outside_env(tmp_path, monkeypatch):
    payload = {
        "type": "service_account",
        "project_id": "notebooklm-492911",
        "private_key_id": "abc123",
        "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
        "client_email": "podcast@notebooklm-492911.iam.gserviceaccount.com",
        "client_id": "103856477389359726705",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setenv("SMARTEST_SECRET_DIR", str(tmp_path))

    info, secret_path = podcast_core.store_service_account_secret(
        (json.dumps(payload) + "\n").encode("utf-8")
    )

    assert info.project_id == "notebooklm-492911"
    assert secret_path.parent == tmp_path
    assert secret_path.exists()
    assert "private_key" in secret_path.read_text(encoding="utf-8")


def test_podcast_runtime_config_is_fail_closed(tmp_path):
    secret_path = tmp_path / "podcast.json"
    secret_path.write_text("{}", encoding="utf-8")

    values = {
        "PODCAST_NOTEBOOKLM_ENABLED": "1",
        "PODCAST_NOTEBOOKLM_PROJECT_ID": "notebooklm-492911",
        "PODCAST_NOTEBOOKLM_LOCATION": "global",
        "PODCAST_NOTEBOOKLM_SECRET_PATH": str(secret_path),
        "PODCAST_NOTEBOOKLM_READY": "",
        "PODCAST_NOTEBOOKLM_STATUS": "method_not_found",
        "PODCAST_NOTEBOOKLM_STATUS_MESSAGE": "API недоступний",
    }
    cfg = podcast_core.podcast_runtime_config(values)

    assert cfg.enabled is True
    assert cfg.ready is False
    assert podcast_core.podcast_runtime_ready(values) is False


def test_podcast_healthcheck_marks_endpoint_ready_on_400(tmp_path, monkeypatch):
    secret_path = tmp_path / "podcast.json"
    secret_path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "notebooklm-492911",
                "private_key_id": "abc123",
                "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
                "client_email": "podcast@notebooklm-492911.iam.gserviceaccount.com",
                "client_id": "103856477389359726705",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        encoding="utf-8",
    )

    class DummyCreds:
        token = "token-123"

        @classmethod
        def from_service_account_info(cls, _payload, scopes=None):
            assert scopes == [podcast_core.GOOGLE_SCOPE]
            return cls()

        def refresh(self, _request):
            return None

    class DummyResponse:
        status_code = 400

        def json(self):
            return {"error": {"message": "Invalid payload"}}

    monkeypatch.setattr(
        podcast_core,
        "service_account",
        type("Svc", (), {"Credentials": DummyCreds}),
    )
    monkeypatch.setattr(podcast_core, "GoogleAuthRequest", lambda: object())
    monkeypatch.setattr(podcast_core.requests, "post", lambda *args, **kwargs: DummyResponse())

    health = podcast_core.podcast_healthcheck(secret_path, "notebooklm-492911", "global")

    assert health.credential_valid is True
    assert health.endpoint_reachable is True
    assert health.ready is True
    assert health.status == "ready"
