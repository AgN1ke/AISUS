from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SERVER_LOG_DIR = Path("/opt/smartest/logs")


def resolve_log_dir() -> Path:
    override = (os.getenv("SMARTEST_LOG_DIR") or "").strip()
    if override:
        return Path(override)
    if _SERVER_LOG_DIR.parent.exists():
        return _SERVER_LOG_DIR
    return PROJECT_ROOT / "logs"


def log_file_for(slug: str) -> Path:
    log_dir = resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = (slug or "smartest").strip().replace(" ", "-")
    return log_dir / f"{safe_slug}.log"


def setup_logging(
    service_slug: str,
    level_name: str = "INFO",
    *,
    stream=None,
    force: bool = True,
) -> Path:
    level = getattr(logging, (level_name or "INFO").upper(), logging.INFO)
    log_path = log_file_for(service_slug)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")

    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler(stream or sys.stdout)
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers, force=force)
    return log_path
