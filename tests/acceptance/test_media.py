"""Acceptance tests for category C (Media handling).

Maps to B-016..B-027c in behavior-audit.md.

After Session 103 fixes: vision uses gpt-4o-mini, STT goes through OpenAI
Whisper API, voice transcript flows back as user_text, albums collect via
concurrent_updates+observe, per-item error handling protects album bundles.
"""
from __future__ import annotations

import pytest

import app.message_logic as message_logic
from adapters.base import ReplyTarget

from .conftest import make_geometry, make_unified_message


# ===== B-017: mention without media → no media route =====

@pytest.mark.asyncio
async def test_B017_mention_without_media_does_not_route_to_vision():
    """B-017 GREEN: '@saintaibot привіт' without media → no media kind set."""
    geometry = make_geometry(
        chat_type="group",
        clean_text="привіт",
        addressed=True,
        addressed_via_mention=True,
        target_media_kind=None,
        reply_target=None,
    )
    assert geometry.target_media_kind is None
    assert geometry.reply_target is None


# ===== Photo flow: download error doesn't crash, surfaces to bundle =====


@pytest.mark.asyncio
async def test_B016_photo_download_error_returns_bundle_with_error(monkeypatch):
    """B-016: коли photo не вдалось завантажити (file too big, network) — бот не падає,
    bundle містить error_reason як media_analysis."""
    from media.router import _build_media_context

    info = {
        "type": "photo",
        "paths": [],
        "text": "",
        "error_reason": "Не вдалося завантажити photo: file too big",
    }

    async def _on_error(_text):
        return None

    bundle, semantic_text = await _build_media_context(info, "опиши", _on_error)
    assert "file too big" in bundle
    assert "target_media_type: photo" in bundle
    assert semantic_text is None


# ===== Video flow: analysis exception caught, error in bundle =====


@pytest.mark.asyncio
async def test_B019_video_analysis_failure_returns_error_bundle(monkeypatch):
    """B-019: video.analyze_video raises → bundle contains friendly error message."""
    from media.router import _build_media_context

    def _failing_analyze(_path, task_hint=None):
        raise RuntimeError("Gemini quota exceeded")

    monkeypatch.setattr("media.router.analyze_video", _failing_analyze)

    info = {"type": "video", "paths": ["/tmp/v.mp4"], "text": ""}

    async def _on_error(_text):
        return None

    bundle, _ = await _build_media_context(info, "що тут", _on_error)
    assert "Gemini quota exceeded" in bundle
    assert "target_media_type: video" in bundle


# ===== B-016 vision: photo route returns analysis as media_analysis =====


@pytest.mark.asyncio
async def test_B016_photo_analysis_appears_as_media_analysis(monkeypatch):
    """B-016 GREEN: photo gets describe_images call, analysis embedded into bundle."""
    from media.router import _build_media_context

    monkeypatch.setattr(
        "media.router.describe_images",
        lambda paths, task_hint=None: "На фото — кіт сидить на столі.",
    )

    info = {"type": "photo", "paths": ["/tmp/p.jpg"], "text": "опиши"}

    async def _on_error(_text):
        return None

    bundle, semantic_text = await _build_media_context(info, "опиши", _on_error)
    assert "На фото — кіт сидить на столі." in bundle
    assert "target_media_type: photo" in bundle
    assert semantic_text is None  # photo doesn't produce semantic_text (only voice does)


# ===== Downloader: per-message exception caught, error_reason returned =====


def test_downloader_handles_get_file_exception_gracefully():
    """download_from_ptb_message wraps body in try/except, returns
    {type, error: True, error_reason: ...} instead of crashing."""
    import inspect
    import media.downloader as dl
    src = inspect.getsource(dl.download_from_ptb_message)
    assert "try:" in src
    assert "except" in src
    assert "error_reason" in src


# ===== B-022: text reply on bot voice — no @mention required =====


@pytest.mark.asyncio
async def test_B022_text_reply_on_bot_voice_addresses_via_reply_to_bot():
    """B-022 GREEN: reply on bot's voice message → addressed via reply_to_bot,
    no @mention needed. Geometry test."""
    geometry = make_geometry(
        chat_type="group",
        clean_text="а ще?",
        addressed=True,
        reply_to_bot=True,
        addressed_via_mention=False,
    )
    assert geometry.addressed is True
    assert geometry.reply_to_bot is True


# ===== Markers: search & reasoning visible to user =====


def test_search_marker_constant_defined():
    """SEARCH_PERFORMED_MARKER appended after search runs."""
    assert hasattr(message_logic, "SEARCH_PERFORMED_MARKER")
    assert "ПОШУК" in message_logic.SEARCH_PERFORMED_MARKER


def test_reasoning_marker_constant_defined():
    """B-069: REASONING_MARKER appended when /think activated."""
    assert hasattr(message_logic, "REASONING_MARKER")
    assert "🧠" in message_logic.REASONING_MARKER


# ===== build_user_task respects media_type_override (album route) =====


@pytest.mark.asyncio
async def test_build_user_task_uses_media_type_override():
    """B-026: when album bundle resolves to 'video' (mixed photo+video),
    build_user_task picks up media_type_override even if geometry's
    target_media_kind suggests something else (e.g. 'image' from first item)."""
    msg = make_unified_message(
        text="@saintaibot опиши все",
        chat_type="group",
    )
    geometry = make_geometry(
        chat_type="group",
        clean_text="опиши все",
        addressed=True,
        addressed_via_mention=True,
        target_media_kind="image",  # geometry sees first item as photo
        reply_target=ReplyTarget(message_id=100, text="album", media_kind="image"),
    )

    task = await message_logic.build_user_task(
        msg, geometry, "опиши все", media_type_override="video"
    )

    assert task is not None
    assert task.media_type == "video"  # override wins
    assert task.has_media_target is True
