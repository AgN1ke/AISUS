"""Acceptance test scaffolding.

Each test in this folder corresponds to a `B-NNN` invariant from
`docs/project/behavior-audit.md`. Tests verify product-level behavior
through internal data structures (MessageGeometry, UserTask, ExecutionPlan)
on synthetic Telegram updates — without invoking real LLMs or hitting
the network.

Convention:
- Test name starts with `test_BNNN_*` matching the audit ID.
- 🟢 GREEN invariants → no skip/xfail (gate enforcement).
- 🟡 YELLOW invariants → @pytest.mark.xfail(reason="B-NNN: <symptom>").
- 🔴 RED invariants → @pytest.mark.skip(reason="B-NNN: <symptom>").
- 🗑 DROP → no test (feature being removed).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from adapters.base import MessageGeometry, ReplyTarget, UnifiedMessage


# ── DB fixture override ────────────────────────────────────────────────
# Parent tests/conftest.py auto-applies a MariaDB migration fixture for the
# whole session. Acceptance tests are pure routing-logic checks and must run
# without a live database (CI / pre-deploy gate).
@pytest.fixture(scope="session", autouse=True)
def _load_env():
    """No-op: acceptance tests don't read env vars from DB-backed paths."""
    return True


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _db_migrated(_load_env):
    """No-op replacement for parent fixture — acceptance never touches DB."""
    yield


def make_unified_message(
    *,
    text: str = "",
    caption: str | None = None,
    chat_id: int = 99950,
    chat_type: str = "private",
    message_id: int = 77,
    bot_username: str = "saintaibot",
    bot_id: int = 42,
    reply_to_message_id: int | None = None,
    has_photo: bool = False,
    has_voice: bool = False,
    has_video: bool = False,
    has_document: bool = False,
) -> UnifiedMessage:
    """Build a minimal UnifiedMessage for routing-decision tests."""
    raw_message = SimpleNamespace(_sent=[], _sent_kwargs=[])

    async def _reply_text(t, **kw):
        raw_message._sent.append(t)
        raw_message._sent_kwargs.append(kw)

    raw_message.reply_text = _reply_text

    update = SimpleNamespace(
        effective_message=raw_message,
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        _bot=SimpleNamespace(bot=SimpleNamespace(id=bot_id, username=bot_username)),
    )
    return UnifiedMessage(
        platform="ptb",
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        caption=caption,
        reply_to_message_id=reply_to_message_id,
        has_photo=has_photo,
        has_voice=has_voice,
        has_video=has_video,
        has_document=has_document,
        raw_update=update,
        bot_username=bot_username,
    )


def make_geometry(
    *,
    chat_type: str = "private",
    clean_text: str = "",
    addressed: bool = True,
    addressed_via_mention: bool = False,
    reply_to_bot: bool = False,
    target_media_kind: str | None = None,
    reply_target: ReplyTarget | None = None,
) -> MessageGeometry:
    return MessageGeometry(
        chat_type=chat_type,
        clean_text=clean_text,
        addressed=addressed,
        addressed_via_mention=addressed_via_mention,
        reply_to_bot=reply_to_bot,
        target_media_kind=target_media_kind,
        reply_target=reply_target,
    )


@pytest.fixture
def authed_session_factory():
    """Returns a callable that builds an authenticated SessionState."""
    import app.message_logic as message_logic

    def _make(chat_id: int = 99950):
        return message_logic.SessionState(chat_id=chat_id, authed=True)

    return _make
