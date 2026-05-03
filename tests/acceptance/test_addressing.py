"""Acceptance tests for category B (Addressing).

Maps to B-009 .. B-015 in behavior-audit.md (B-section).
"""
from __future__ import annotations

import pytest

import app.message_logic as message_logic
from adapters.base import ReplyTarget

from .conftest import make_geometry, make_unified_message


@pytest.mark.asyncio
async def test_B009_private_chat_always_addressed():
    """B-009 GREEN: private chat → bot always considers itself addressed."""
    msg = make_unified_message(text="привіт", chat_type="private")
    geometry = make_geometry(
        chat_type="private",
        clean_text="привіт",
        addressed=True,
    )
    assert geometry.addressed is True


@pytest.mark.asyncio
async def test_B010_mention_in_group_addresses_bot():
    """B-010 GREEN: @saintaibot mention in group addresses the bot."""
    msg = make_unified_message(
        text="@saintaibot привіт",
        chat_type="group",
    )
    geometry = make_geometry(
        chat_type="group",
        clean_text="привіт",
        addressed=True,
        addressed_via_mention=True,
    )
    assert geometry.addressed
    assert geometry.addressed_via_mention
    assert geometry.clean_text == "привіт"  # mention is stripped


@pytest.mark.asyncio
async def test_B012_reply_to_bot_addresses_without_mention():
    """B-012 GREEN: reply on bot's message addresses without explicit @mention."""
    geometry = make_geometry(
        chat_type="group",
        clean_text="а ще?",
        addressed=True,
        reply_to_bot=True,
    )
    assert geometry.addressed
    assert geometry.reply_to_bot
    assert not geometry.addressed_via_mention


@pytest.mark.asyncio
async def test_B013_group_unaddressed_message_is_silent():
    """B-013 GREEN: group message without mention/reply → bot stays silent."""
    geometry = make_geometry(
        chat_type="group",
        clean_text="хелло як справи",
        addressed=False,
        addressed_via_mention=False,
        reply_to_bot=False,
    )
    assert geometry.addressed is False


# ===== RED items (skipped — known broken, see audit) =====

@pytest.mark.skip(
    reason=(
        "B-049 RED: multi-bot ізоляція зламана. Бот реагує на bare /c, /think, "
        "/a без @saintaibot тегу — у multi-bot чаті це знищить пам'ять усім."
    )
)
@pytest.mark.asyncio
async def test_B049_multibot_chat_ignores_bare_commands():
    """B-049 RED: in a multi-bot group, bare /c, /think, /a must NOT be picked up."""
    # Will be implemented when fixed.
    pass


# ===== B-011: text_mention entity (UI-click mention without literal @username) =====


class _FakeEntity:
    def __init__(self, type_: str, user_id: int | None = None, username: str = ""):
        self.type = type_
        if user_id is not None:
            self.user = type("U", (), {"id": user_id, "username": username})()
        else:
            self.user = None


class _FakeMessage:
    def __init__(self, text: str = "", caption: str | None = None, entities=None, caption_entities=None):
        self.text = text
        self.caption = caption
        self.entities = entities or []
        self.caption_entities = caption_entities or []


class _FakeUpdate:
    def __init__(self, message, bot_id: int = 42, bot_username: str = "saintaibot"):
        self.effective_message = message
        self._bot = type(
            "Ctx", (), {"bot": type("Bot", (), {"id": bot_id, "username": bot_username})()}
        )()


def test_B011_text_mention_entity_with_bot_id_detected():
    """B-011: text_mention entity (UI click) recognized via bot.id match.

    Telegram desktop/mobile click on bot in autocomplete creates a `text_mention`
    entity carrying user.id reference but NO literal @username in the text.
    Master mention detection must still recognize this as addressing.
    """
    from app.chat_geometry import _has_mention_ptb

    msg = _FakeMessage(
        text="опиши",  # NO literal @saintaibot — entity carries the link
        entities=[_FakeEntity("text_mention", user_id=42, username="saintaibot")],
    )
    update = _FakeUpdate(msg, bot_id=42, bot_username="saintaibot")
    assert _has_mention_ptb(update, "saintaibot") is True


def test_B011_text_mention_entity_with_other_bot_id_NOT_detected():
    """B-011: text_mention pointing to OTHER bot → not addressing us."""
    from app.chat_geometry import _has_mention_ptb

    msg = _FakeMessage(
        text="hi",
        entities=[_FakeEntity("text_mention", user_id=99, username="otherbot")],
    )
    update = _FakeUpdate(msg, bot_id=42, bot_username="saintaibot")
    assert _has_mention_ptb(update, "saintaibot") is False


def test_B011_literal_at_username_in_text_detected():
    """B-011: literal @saintaibot in text recognized (no entity needed)."""
    from app.chat_geometry import _has_mention_ptb

    msg = _FakeMessage(text="@saintaibot опиши", entities=[])
    update = _FakeUpdate(msg, bot_id=42, bot_username="saintaibot")
    assert _has_mention_ptb(update, "saintaibot") is True


def test_B011_text_mention_in_caption_entities_detected():
    """B-011: text_mention in caption_entities (photo with click-mention) detected."""
    from app.chat_geometry import _has_mention_ptb

    msg = _FakeMessage(
        text="",
        caption="опиши",
        caption_entities=[_FakeEntity("text_mention", user_id=42)],
    )
    update = _FakeUpdate(msg, bot_id=42, bot_username="saintaibot")
    assert _has_mention_ptb(update, "saintaibot") is True


def test_B011_no_mention_no_addressing():
    """B-011 negative: text without literal mention or entity → not addressed."""
    from app.chat_geometry import _has_mention_ptb

    msg = _FakeMessage(text="привіт всім", entities=[])
    update = _FakeUpdate(msg, bot_id=42, bot_username="saintaibot")
    assert _has_mention_ptb(update, "saintaibot") is False
