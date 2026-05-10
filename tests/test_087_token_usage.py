from __future__ import annotations

from core import token_usage


def test_token_usage_records_and_summarizes(tmp_path, monkeypatch):
    log_path = tmp_path / "token_usage.jsonl"
    monkeypatch.setenv("TOKEN_USAGE_LOG_PATH", str(log_path))

    token_usage.record_llm_usage(
        provider="openai",
        model="gpt-test",
        capability="chat_final",
        messages=[{"role": "user", "content": "hello"}],
        response={"usage": {"prompt_tokens": 11, "completion_tokens": 7}},
    )
    token_usage.record_llm_usage(
        provider="openai",
        model="gpt-test",
        capability="chat_final",
        messages=[{"role": "user", "content": "hello again"}],
        status="failed",
        error_text="boom",
    )

    events = token_usage.read_usage_events()
    summary = token_usage.summarize_usage_events(events)

    assert log_path.exists()
    assert all("created_at_utc" in event for event in events)
    assert summary["calls"] == 2
    assert summary["failed"] == 1
    assert summary["tokens_in"] >= 11
    assert summary["tokens_out"] == 7
    assert summary["by_model"][0]["provider"] == "openai"
    assert summary["by_model"][0]["model"] == "gpt-test"
    assert summary["by_model"][0]["capability"] == "chat_final"


def test_token_usage_handles_multimodal_message_content(tmp_path, monkeypatch):
    log_path = tmp_path / "token_usage.jsonl"
    monkeypatch.setenv("TOKEN_USAGE_LOG_PATH", str(log_path))

    token_usage.record_llm_usage(
        provider="gemini",
        model="gemini-test",
        capability="vision_image",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is in this image?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ],
    )

    summary = token_usage.summarize_usage_events(token_usage.read_usage_events())

    assert summary["calls"] == 1
    assert summary["tokens_in"] > 0
    assert summary["by_model"][0]["provider"] == "gemini"
    assert summary["by_model"][0]["capability"] == "vision_image"


def test_token_usage_calendar_groups_by_month_and_day():
    events = [
        {
            "ts": 1778351428,
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "capability": "planner_reasoning",
            "status": "success",
            "tokens_in": 100,
            "tokens_out": 20,
        },
        {
            "ts": 1778355000,
            "provider": "openai",
            "model": "gpt-test",
            "capability": "chat_final",
            "status": "success",
            "tokens_in": 300,
            "tokens_out": 50,
        },
    ]

    calendar = token_usage.summarize_usage_calendar(
        events,
        selected_month="2026-05",
        selected_day="2026-05-09",
        tz_name="Europe/Kiev",
    )

    assert calendar["selected_month"] == "2026-05"
    assert calendar["selected_day"] == "2026-05-09"
    assert calendar["period_kind"] == "day"
    assert calendar["period_usage"]["calls"] == 2
    assert calendar["period_usage"]["tokens_total"] == 470
    assert any(row["date"] == "2026-05-09" and row["tokens_total"] == 470 for row in calendar["days"])
    assert calendar["months"][0]["month"] == "2026-05"


def test_token_usage_calendar_month_period():
    events = [
        {"created_at_utc": "2026-05-01T12:00:00Z", "tokens_in": 10, "tokens_out": 5},
        {"created_at_utc": "2026-05-20T12:00:00Z", "tokens_in": 20, "tokens_out": 5},
        {"created_at_utc": "2026-06-01T12:00:00Z", "tokens_in": 100, "tokens_out": 1},
    ]

    calendar = token_usage.summarize_usage_calendar(
        events,
        selected_month="2026-05",
        tz_name="Europe/Kiev",
    )

    assert calendar["period_kind"] == "month"
    assert calendar["period_usage"]["calls"] == 2
    assert calendar["period_usage"]["tokens_total"] == 40
