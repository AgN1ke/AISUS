"""Acceptance tests for voice commands /a /v on master @saintaibot.

Master version uses 3-tuple parser signature: (cmd, payload, addressed)
that handles @bot suffix.
"""
from __future__ import annotations

import pytest

from app.message_logic import _parse_voice_command


# ===== B-007 / B-015: /a@saintaibot <text> in group =====

def test_B007_a_with_tag_and_text():
    cmd, payload, addressed = _parse_voice_command(
        "/a@saintaibot Привіт", "saintaibot"
    )
    assert cmd == "speak_text"
    assert payload == "Привіт"
    assert addressed is True


# ===== B-008: bare /a in private =====

def test_B008_bare_a_with_text():
    cmd, payload, _ = _parse_voice_command("/a Привіт", "saintaibot")
    assert cmd == "speak_text"
    assert payload == "Привіт"


# ===== B-009: /a@saintaibot as reply (no payload) =====

def test_B009_a_with_tag_no_payload():
    cmd, payload, addressed = _parse_voice_command("/a@saintaibot", "saintaibot")
    assert cmd == "speak_text"
    assert payload == ""
    assert addressed is True


# ===== B-010: /v@saintaibot → speak last assistant reply =====

def test_B010_v_with_tag():
    cmd, payload, addressed = _parse_voice_command("/v@saintaibot", "saintaibot")
    assert cmd == "speak_last"
    assert payload == ""
    assert addressed is True


# ===== B-011: bare /v in private =====

def test_B011_bare_v():
    cmd, payload, _ = _parse_voice_command("/v", "saintaibot")
    assert cmd == "speak_last"
    assert payload == ""


# ===== B-013: parser distinguishes voice cmds from regular text =====

def test_B013_parser_negatives():
    assert _parse_voice_command("@saintaibot привіт", "saintaibot")[0] is None
    assert _parse_voice_command("/think що", "saintaibot")[0] is None
    assert _parse_voice_command("/c@saintaibot", "saintaibot")[0] is None
    assert _parse_voice_command("привіт", "saintaibot")[0] is None
    assert _parse_voice_command("", "saintaibot")[0] is None


# ===== B-015: /a@otherbot must NOT trigger us =====

def test_B015_other_bot_tag_ignored():
    cmd, _, _ = _parse_voice_command("/a@otherbot Привіт", "saintaibot")
    assert cmd is None


@pytest.mark.skip(reason="B-014 PENDING: integration test with mocked TTS failure")
def test_B014_tts_failure_no_text_fallback():
    pass


# ===== B-012 DROP: /v as reply removed (was duplicate of /a) =====


def test_B012_DROP_v_does_not_speak_reply_target_text():
    """B-012 DROP: /v always speaks last assistant text, never the reply target.

    Раніше /v як reply брало text з reply_target — це дублювало функціонал /a
    (де reply target — це що саме озвучити). Тепер /v має ОДНУ роль:
    озвучити останню текстову відповідь бота.
    """
    import inspect
    from app import message_logic

    src = inspect.getsource(message_logic._process_message_inner)
    # Find the speak_last branch
    speak_last_branch_start = src.find('voice_cmd == "speak_last"')
    assert speak_last_branch_start > 0, "speak_last branch must exist"
    # The branch must NOT read geometry.reply_target.text — that was the
    # removed B-012 duplicate behavior.
    next_branch = src.find('if not text_to_speak.strip()', speak_last_branch_start)
    speak_last_block = src[speak_last_branch_start:next_branch]
    assert "reply_target.text" not in speak_last_block, (
        "B-012 DROP: /v must not consume reply_target.text — that's /a's job"
    )


# ===== Bare /v as reply-to-bot in group is allowed (no multi-bot conflict) =====


def test_bare_v_as_reply_to_bot_in_group_is_NOT_ignored():
    """When user replies on bot's message with bare /v in group — accept it.

    Multi-bot safety rule blocks bare /a/v in group BECAUSE there might be
    other bots and we don't know who's addressed. But reply-to-bot is
    unambiguous — the user explicitly chose THIS bot's message to reply to.

    Source check: the multi-bot guard must include `not geometry.reply_to_bot`.
    """
    import inspect
    from app import message_logic

    src = inspect.getsource(message_logic._process_message_inner)
    # Locate the multi-bot guard
    guard_start = src.find("flow.voice_cmd_ignored_bare_in_group")
    assert guard_start > 0, "multi-bot guard must exist"
    # Look back ~200 chars to find the condition
    guard_block = src[max(0, guard_start - 400):guard_start]
    assert "reply_to_bot" in guard_block, (
        "multi-bot guard must exempt reply_to_bot=True — otherwise users "
        "can't use bare /v as reply on bot's own message in group chats"
    )


# ===== B-026: voice-in → voice-out =====

def test_B026_voice_input_triggers_voice_reply():
    """B-026: when user sends voice/audio, bot replies via TTS."""
    from app.message_logic import _should_reply_with_voice
    from adapters.base import MessageGeometry

    voice_geo = MessageGeometry(chat_type="private", current_media_kind="voice")
    audio_geo = MessageGeometry(chat_type="private", current_media_kind="audio")
    text_geo = MessageGeometry(chat_type="private", current_media_kind=None)
    image_geo = MessageGeometry(chat_type="private", current_media_kind="image")

    assert _should_reply_with_voice(voice_geo) is True
    assert _should_reply_with_voice(audio_geo) is True
    assert _should_reply_with_voice(text_geo) is False
    assert _should_reply_with_voice(image_geo) is False


# ===== B-020/B-021: STT goes through OpenAI Whisper API (transcribe_audio) =====


def test_B020_router_uses_openai_whisper_transcribe():
    """B-020/B-021: master uses transcribe_audio from media.voice (OpenAI API),
    NOT the legacy whisper_tool that wrote .txt files (which silently failed)."""
    import inspect
    import media.router as router
    src = inspect.getsource(router)
    assert "transcribe_audio" in src, "router must call transcribe_audio (OpenAI API)"
    assert "whisper_tool" not in src, "legacy whisper_tool must be gone"


# ===== B-021/B-022 (semantic_text): voice transcript becomes user_text =====


@pytest.mark.asyncio
async def test_B021_voice_transcript_becomes_semantic_text(monkeypatch):
    """B-021/B-022: voice → transcript returned as semantic_text → becomes user_text.

    Without this, LLM saw only [MEDIA] system block + 'Проаналізуй наведене медіа'
    placeholder and replied 'не маю доступу до вмісту'. Fixed by returning the
    transcript as semantic_text from _build_media_context."""
    from media.router import _build_media_context

    async def _fake_transcribe(_path):
        return "Привіт, як справи у тебе сьогодні?"

    monkeypatch.setattr("media.router.transcribe_audio", _fake_transcribe)

    info = {
        "type": "voice",
        "paths": ["/tmp/v.ogg"],
        "text": "",
    }

    async def _on_error(_text):
        return None

    bundle, semantic_text = await _build_media_context(info, "", _on_error)
    assert "Привіт" in bundle  # transcript embedded in [MEDIA] block
    assert semantic_text == "Привіт, як справи у тебе сьогодні?"


@pytest.mark.asyncio
async def test_B021_voice_transcribe_failure_returns_none_semantic(monkeypatch):
    """B-021 anti-rule: при failed transcribe — semantic_text=None (не падає,
    bundle отримує помилку як media_analysis)."""
    from media.router import _build_media_context

    async def _failing_transcribe(_path):
        raise RuntimeError("STT API down")

    monkeypatch.setattr("media.router.transcribe_audio", _failing_transcribe)

    info = {"type": "voice", "paths": ["/tmp/v.ogg"], "text": ""}

    async def _on_error(_text):
        return None

    bundle, semantic_text = await _build_media_context(info, "", _on_error)
    assert "STT API down" in bundle  # error injected so bot knows what happened
    assert semantic_text is None
