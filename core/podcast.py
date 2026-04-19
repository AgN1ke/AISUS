from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from core.env import env_bool, env_first

logger = logging.getLogger(__name__)

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except Exception:  # pragma: no cover - optional dependency guard
    GoogleAuthRequest = None
    service_account = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_SECRET_DIR = Path("/opt/smartest/secrets")
DEFAULT_LOCAL_SECRET_DIR = PROJECT_ROOT / ".secrets"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True)
class PodcastRuntimeConfig:
    enabled: bool
    project_id: str
    location: str
    secret_path: str
    client_email: str
    client_id: str
    ready: bool
    status: str
    status_message: str


@dataclass(frozen=True)
class PodcastServiceAccountInfo:
    project_id: str
    client_email: str
    client_id: str


@dataclass(frozen=True)
class PodcastHealthStatus:
    credential_valid: bool
    endpoint_reachable: bool
    ready: bool
    status: str
    message: str
    http_status: int | None = None
    client_email: str = ""
    client_id: str = ""
    project_id: str = ""


def podcast_secret_dir() -> Path:
    configured = (env_first("SMARTEST_SECRET_DIR", default="") or "").strip()
    if configured:
        return Path(configured)
    if DEFAULT_SERVER_SECRET_DIR.parent.exists():
        return DEFAULT_SERVER_SECRET_DIR
    return DEFAULT_LOCAL_SECRET_DIR


def podcast_secret_filename(project_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", (project_id or "").strip()).strip("-")
    return f"notebooklm-podcast-{normalized or 'service-account'}.json"


def podcast_runtime_config(values: dict[str, str] | None = None) -> PodcastRuntimeConfig:
    def _read(key: str, default: str = "") -> str:
        if values is not None:
            return str(values.get(key, default) or "").strip()
        return str(env_first(key, default=default) or "").strip()

    if values is not None:
        enabled = str(values.get("PODCAST_NOTEBOOKLM_ENABLED", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        ready_flag = str(values.get("PODCAST_NOTEBOOKLM_READY", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    else:
        enabled = env_bool("PODCAST_NOTEBOOKLM_ENABLED", default=False)
        ready_flag = env_bool("PODCAST_NOTEBOOKLM_READY", default=False)
    project_id = _read("PODCAST_NOTEBOOKLM_PROJECT_ID")
    location = _read("PODCAST_NOTEBOOKLM_LOCATION", "global") or "global"
    secret_path = _read("PODCAST_NOTEBOOKLM_SECRET_PATH")
    client_email = _read("PODCAST_NOTEBOOKLM_CLIENT_EMAIL")
    client_id = _read("PODCAST_NOTEBOOKLM_CLIENT_ID")
    status = _read("PODCAST_NOTEBOOKLM_STATUS", "not_configured") or "not_configured"
    status_message = _read(
        "PODCAST_NOTEBOOKLM_STATUS_MESSAGE",
        "Сервіс подкастів ще не налаштований.",
    ) or "Сервіс подкастів ще не налаштований."
    secret_exists = bool(secret_path and Path(secret_path).exists())
    ready = bool(enabled and ready_flag and project_id and location and secret_exists)
    return PodcastRuntimeConfig(
        enabled=enabled,
        project_id=project_id,
        location=location,
        secret_path=secret_path,
        client_email=client_email,
        client_id=client_id,
        ready=ready,
        status=status,
        status_message=status_message,
    )


def podcast_runtime_ready(values: dict[str, str] | None = None) -> bool:
    return podcast_runtime_config(values).ready


def validate_service_account_json_bytes(raw: bytes) -> tuple[PodcastServiceAccountInfo, dict[str, Any]]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("JSON-файл не читається як валідний UTF-8 service account secret.") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON-файл має містити об’єкт service account, а не інший тип даних.")
    if payload.get("type") != "service_account":
        raise ValueError("Завантажений JSON не є service account secret від Google Cloud.")
    required = ("project_id", "client_email", "client_id", "private_key", "token_uri")
    missing = [key for key in required if not str(payload.get(key) or "").strip()]
    if missing:
        raise ValueError(f"У service account JSON бракує обов’язкових полів: {', '.join(missing)}.")
    return (
        PodcastServiceAccountInfo(
            project_id=str(payload["project_id"]).strip(),
            client_email=str(payload["client_email"]).strip(),
            client_id=str(payload["client_id"]).strip(),
        ),
        payload,
    )


def store_service_account_secret(raw: bytes, project_id: str | None = None) -> tuple[PodcastServiceAccountInfo, Path]:
    info, payload = validate_service_account_json_bytes(raw)
    target_project = (project_id or info.project_id).strip()
    if target_project and target_project != info.project_id:
        raise ValueError(
            "Project ID у формі не збігається з project_id усередині service account JSON."
        )
    secret_dir = podcast_secret_dir()
    secret_dir.mkdir(parents=True, exist_ok=True)
    path = secret_dir / podcast_secret_filename(info.project_id)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(rendered, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return info, path


def _podcast_endpoint(project_id: str, location: str) -> str:
    return (
        "https://discoveryengine.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/podcasts"
    )


def podcast_healthcheck(secret_path: str | Path, project_id: str, location: str = "global") -> PodcastHealthStatus:
    path = Path(secret_path)
    if not path.exists():
        return PodcastHealthStatus(
            credential_valid=False,
            endpoint_reachable=False,
            ready=False,
            status="missing_secret",
            message="Service account JSON не знайдено на сервері.",
        )
    try:
        info, payload = validate_service_account_json_bytes(path.read_bytes())
    except Exception as exc:
        return PodcastHealthStatus(
            credential_valid=False,
            endpoint_reachable=False,
            ready=False,
            status="invalid_secret",
            message=str(exc),
        )

    if service_account is None or GoogleAuthRequest is None:
        return PodcastHealthStatus(
            credential_valid=False,
            endpoint_reachable=False,
            ready=False,
            status="missing_dependency",
            message="У середовищі немає google-auth, тому readiness-check подкастів недоступний.",
            client_email=info.client_email,
            client_id=info.client_id,
            project_id=info.project_id,
        )

    resolved_project_id = (project_id or info.project_id).strip()
    if resolved_project_id != info.project_id:
        return PodcastHealthStatus(
            credential_valid=False,
            endpoint_reachable=False,
            ready=False,
            status="project_mismatch",
            message="Project ID у конфігу не збігається з project_id у service account JSON.",
            client_email=info.client_email,
            client_id=info.client_id,
            project_id=info.project_id,
        )

    try:
        credentials = service_account.Credentials.from_service_account_info(
            payload,
            scopes=[GOOGLE_SCOPE],
        )
        credentials.refresh(GoogleAuthRequest())
    except Exception as exc:
        logger.warning("podcast.health.token_failed project_id=%s error=%s", resolved_project_id, exc)
        return PodcastHealthStatus(
            credential_valid=False,
            endpoint_reachable=False,
            ready=False,
            status="token_failed",
            message=f"Не вдалося отримати OAuth token для Podcast API: {exc}",
            client_email=info.client_email,
            client_id=info.client_id,
            project_id=info.project_id,
        )

    try:
        response = requests.post(
            _podcast_endpoint(resolved_project_id, location or "global"),
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=20,
        )
    except Exception as exc:
        logger.warning("podcast.health.request_failed project_id=%s error=%s", resolved_project_id, exc)
        return PodcastHealthStatus(
            credential_valid=True,
            endpoint_reachable=False,
            ready=False,
            status="request_failed",
            message=f"Не вдалося дістатися до Google Podcast API: {exc}",
            client_email=info.client_email,
            client_id=info.client_id,
            project_id=info.project_id,
        )

    if response.status_code in {200, 201, 202, 400}:
        message = (
            "Service account валідний, OAuth token отримується, "
            "endpoint Podcast API відповідає. Сервіс можна вважати готовим."
        )
        return PodcastHealthStatus(
            credential_valid=True,
            endpoint_reachable=True,
            ready=True,
            status="ready",
            message=message,
            http_status=response.status_code,
            client_email=info.client_email,
            client_id=info.client_id,
            project_id=info.project_id,
        )

    try:
        payload = response.json()
        error_message = (
            payload.get("error", {}).get("message")
            or payload.get("message")
            or response.text
        )
    except Exception:
        error_message = response.text
    status = "api_unavailable"
    if response.status_code == 403:
        status = "forbidden"
    elif response.status_code == 404:
        status = "method_not_found"
    elif response.status_code == 401:
        status = "unauthorized"
    message = (
        "Service account валідний, але Podcast API недоступний. "
        f"HTTP {response.status_code}: {error_message.strip()[:800]}"
    )
    return PodcastHealthStatus(
        credential_valid=True,
        endpoint_reachable=False,
        ready=False,
        status=status,
        message=message,
        http_status=response.status_code,
        client_email=info.client_email,
        client_id=info.client_id,
        project_id=info.project_id,
    )
