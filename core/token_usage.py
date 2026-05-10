from __future__ import annotations

import calendar as _calendar
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.tokens import count_tokens_messages, count_tokens_text

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python always has zoneinfo here.
    ZoneInfo = None  # type: ignore[assignment]


_LOCK = threading.Lock()
DEFAULT_TIMEZONE = "Europe/Kiev"


def _default_log_path() -> Path:
    server_log_dir = Path("/opt/smartest/logs")
    if server_log_dir.exists():
        return server_log_dir / "token_usage.jsonl"
    return Path(__file__).resolve().parents[1] / "logs" / "token_usage.jsonl"


def token_usage_log_path() -> Path:
    configured = (os.getenv("TOKEN_USAGE_LOG_PATH") or "").strip()
    return Path(configured) if configured else _default_log_path()


def _admin_event_limit() -> int:
    raw = (os.getenv("TOKEN_USAGE_ADMIN_EVENT_LIMIT") or "200000").strip()
    try:
        return max(1, int(raw))
    except Exception:
        return 200000


def _timezone(tz_name: str | None = None):
    name = (tz_name or os.getenv("TOKEN_USAGE_TIMEZONE") or DEFAULT_TIMEZONE).strip()
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone.utc


def _get_attr_or_item(container: Any, name: str) -> Any:
    if container is None:
        return None
    if isinstance(container, dict):
        return container.get(name)
    return getattr(container, name, None)


def _usage_int(container: Any, *names: str) -> int:
    for name in names:
        value = _get_attr_or_item(container, name)
        if value not in (None, ""):
            try:
                return int(value)
            except Exception:
                continue
    return 0


def extract_usage(response: Any) -> tuple[int, int]:
    usage = _get_attr_or_item(response, "usage")
    if usage is None:
        usage = _get_attr_or_item(response, "usageMetadata")
    if usage is None:
        return 0, 0
    tokens_in = _usage_int(
        usage,
        "prompt_tokens",
        "input_tokens",
        "prompt_token_count",
        "promptTokenCount",
    )
    tokens_out = _usage_int(
        usage,
        "completion_tokens",
        "output_tokens",
        "candidates_tokens",
        "candidatesTokenCount",
    ) + _usage_int(
        usage,
        "thoughts_tokens",
        "thoughtsTokenCount",
    )
    return tokens_in, tokens_out


def _response_text(response: Any) -> str:
    try:
        choices = _get_attr_or_item(response, "choices") or []
        first = choices[0]
        message = _get_attr_or_item(first, "message")
        return str(_get_attr_or_item(message, "content") or "")
    except Exception:
        return ""


def _content_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = (
                    item.get("text")
                    or item.get("input_text")
                    or item.get("type")
                    or item.get("mime_type")
                    or item.get("mimeType")
                    or ""
                )
                parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _message_token_estimate(messages: Iterable[dict[str, Any]], model: str) -> int:
    normalized: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            normalized.append({"role": "unknown", "content": str(message)})
            continue
        normalized.append(
            {
                "role": str(message.get("role") or "unknown"),
                "content": _content_to_text(message.get("content")),
            }
        )
    return count_tokens_messages(normalized, model)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def record_llm_usage(
    *,
    provider: str,
    model: str,
    capability: str,
    messages: Iterable[dict[str, Any]],
    response: Any = None,
    status: str = "success",
    latency_ms: int | None = None,
    error_text: str | None = None,
) -> None:
    try:
        now = datetime.now(timezone.utc)
        messages_list = list(messages or [])
        tokens_in, tokens_out = extract_usage(response)
        if not tokens_in:
            tokens_in = _message_token_estimate(messages_list, model)
        if not tokens_out and response is not None:
            tokens_out = count_tokens_text(_response_text(response), model)
        row = {
            "ts": int(now.timestamp()),
            "created_at_utc": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "provider": (provider or "unknown").strip() or "unknown",
            "model": (model or "unknown").strip() or "unknown",
            "capability": (capability or "unknown").strip() or "unknown",
            "status": (status or "success").strip() or "success",
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "latency_ms": latency_ms,
        }
        if error_text:
            row["error_text"] = str(error_text)[:500]
        path = token_usage_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        return


def read_usage_events(limit: int | None = None) -> list[dict[str, Any]]:
    path = token_usage_log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    if limit is None:
        limit = _admin_event_limit()
    selected = lines[-max(1, int(limit)):]
    events: list[dict[str, Any]] = []
    for line in selected:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _event_datetime(event: dict[str, Any], *, tz_name: str | None = None) -> datetime | None:
    tz = _timezone(tz_name)
    ts = event.get("ts")
    if ts not in (None, ""):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(tz)
        except Exception:
            pass
    for key in ("created_at_utc", "created_at", "timestamp"):
        raw = event.get(key)
        if not raw:
            continue
        try:
            value = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(tz)
        except Exception:
            continue
    return None


def _event_date_key(event: dict[str, Any], *, tz_name: str | None = None) -> str:
    dt = _event_datetime(event, tz_name=tz_name)
    return dt.date().isoformat() if dt else ""


def _event_month_key(event: dict[str, Any], *, tz_name: str | None = None) -> str:
    date_key = _event_date_key(event, tz_name=tz_name)
    return date_key[:7] if date_key else ""


def _empty_usage_row(**extra: Any) -> dict[str, Any]:
    return {
        **extra,
        "calls": 0,
        "failed": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "tokens_total": 0,
    }


def _add_event(row: dict[str, Any], event: dict[str, Any]) -> None:
    tokens_in = _safe_int(event.get("tokens_in"))
    tokens_out = _safe_int(event.get("tokens_out"))
    status = str(event.get("status") or "success")
    row["calls"] += 1
    row["tokens_in"] += tokens_in
    row["tokens_out"] += tokens_out
    row["tokens_total"] += tokens_in + tokens_out
    if status != "success":
        row["failed"] += 1


def summarize_usage_events(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    summary = _empty_usage_row(by_model=[])
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        _add_event(summary, event)
        key = (
            str(event.get("provider") or "unknown"),
            str(event.get("model") or "unknown"),
            str(event.get("capability") or "unknown"),
        )
        row = grouped.setdefault(
            key,
            _empty_usage_row(provider=key[0], model=key[1], capability=key[2]),
        )
        _add_event(row, event)
    summary["by_model"] = sorted(
        grouped.values(),
        key=lambda item: int(item.get("tokens_total") or 0),
        reverse=True,
    )
    return summary


def summarize_usage_calendar(
    events: Iterable[dict[str, Any]],
    *,
    selected_month: str = "",
    selected_day: str = "",
    tz_name: str | None = None,
) -> dict[str, Any]:
    event_list = list(events)
    month_rows: dict[str, dict[str, Any]] = {}
    day_rows: dict[str, dict[str, Any]] = {}
    undated = _empty_usage_row(label="undated")

    for event in event_list:
        date_key = _event_date_key(event, tz_name=tz_name)
        if not date_key:
            _add_event(undated, event)
            continue
        month_key = date_key[:7]
        _add_event(month_rows.setdefault(month_key, _empty_usage_row(month=month_key)), event)
        _add_event(day_rows.setdefault(date_key, _empty_usage_row(date=date_key, day=int(date_key[-2:]))), event)

    months = sorted(month_rows.values(), key=lambda row: str(row.get("month")), reverse=True)
    today_month = datetime.now(_timezone(tz_name)).strftime("%Y-%m")
    if not re_fullmatch_month(selected_month):
        selected_month = str(months[0].get("month")) if months else today_month
    if not re_fullmatch_day(selected_day) or not selected_day.startswith(selected_month):
        selected_day = ""

    try:
        year, month = [int(part) for part in selected_month.split("-")]
        days_count = _calendar.monthrange(year, month)[1]
    except Exception:
        now = datetime.now(_timezone(tz_name))
        selected_month = now.strftime("%Y-%m")
        days_count = _calendar.monthrange(now.year, now.month)[1]

    days: list[dict[str, Any]] = []
    for day in range(1, days_count + 1):
        date_key = f"{selected_month}-{day:02d}"
        row = dict(day_rows.get(date_key) or _empty_usage_row(date=date_key, day=day))
        row["selected"] = date_key == selected_day
        days.append(row)

    if selected_day:
        period_events = [event for event in event_list if _event_date_key(event, tz_name=tz_name) == selected_day]
        period_label = selected_day
        period_kind = "day"
    else:
        period_events = [event for event in event_list if _event_month_key(event, tz_name=tz_name) == selected_month]
        period_label = selected_month
        period_kind = "month"

    return {
        "timezone": str(getattr(_timezone(tz_name), "key", DEFAULT_TIMEZONE)),
        "selected_month": selected_month,
        "selected_day": selected_day,
        "period_kind": period_kind,
        "period_label": period_label,
        "period_usage": summarize_usage_events(period_events),
        "months": months,
        "days": days,
        "undated": undated,
    }


def re_fullmatch_month(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}", value or ""))


def re_fullmatch_day(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""))
