"""Wiring tests — verify modules are CONNECTED to the main bot flow.

Problem this catches: an agent (Codex / Claude / human) writes a function
plus tests, all green — but forgets to wire the function into the main
pipeline. Function exists, tests pass, but the bot never calls it. From the
user's side: the bug isn't fixed.

Strategy: source-level integration check. We parse the source of critical
entry-points (`_process_message_inner`, `select_context`, adapter `_on_message`,
`run_search`, etc.) and assert that expected callees are present. This is
fast (no DB / no network), catches structural disconnection (lost imports,
removed calls, renamed callees).

Doesn't catch: dynamic dispatch (rare in this codebase). Trade-off accepted.
"""
from __future__ import annotations

import inspect

import pytest


def _src(target) -> str:
    """Source of a function/method/class."""
    return inspect.getsource(target)


def _has_master_wiring() -> bool:
    """Heuristic: master has REASONING_MARKER in message_logic;
    multitenant uses different message_logic structure."""
    try:
        from app import message_logic
        return hasattr(message_logic, "REASONING_MARKER")
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_master_wiring(),
    reason=(
        "wiring tests are master-scoped (different module structure on multitenant)"
    ),
)


# ===== _process_message_inner — main bot pipeline =====


def test_process_message_inner_wires_album_observe():
    """observe_album_message must be called early in flow (before processing
    decisions) so siblings register before claim/settle."""
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "observe_album_message(msg)" in src, (
        "album registry must be wired into _process_message_inner — "
        "without it, fresh albums lose siblings"
    )


def test_process_message_inner_wires_geometry_resolution():
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "resolve_message_geometry" in src


def test_process_message_inner_wires_clear_context_command():
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "_is_clear_context_command" in src


def test_process_message_inner_wires_access_check():
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "check_access" in src


def test_process_message_inner_wires_voice_command_parser():
    """B-007..B-015: /a /v dispatch must run BEFORE planner / media flow."""
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "_parse_voice_command" in src
    # And the dispatch must happen — not just parse
    assert "speak_text" in src or "speak_last" in src


def test_process_message_inner_wires_voice_reply_decision():
    """B-026: voice-in voice-out — _should_reply_with_voice must be checked."""
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "_should_reply_with_voice" in src, (
        "voice-in voice-out broken: _should_reply_with_voice not checked in flow"
    )


def test_process_message_inner_wires_media_resolution():
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "_resolve_media_instruction" in src


def test_process_message_inner_wires_task_builder_and_planner():
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "build_user_task" in src
    assert "plan_execution" in src
    assert "execute_plan" in src


def test_process_message_inner_wires_response_send():
    """Bot must actually send response — either text or voice."""
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "send_response" in src
    assert "send_voice_response" in src


def test_process_message_inner_wires_album_claim_finish():
    """B-024: album gate (claim before processing, finish after handled)."""
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "claim_album_processing" in src
    assert "finish_album_processing" in src


def test_process_message_inner_appends_visible_markers():
    """B-042 / B-069: visible debug markers (search/reasoning) must be
    appended to answer in flow, not lost."""
    from app import message_logic
    src = _src(message_logic._process_message_inner)
    assert "SEARCH_PERFORMED_MARKER" in src
    assert "REASONING_MARKER" in src


# ===== memory.manager.select_context — context assembly =====


def test_select_context_wires_speaker_annotation():
    """B-046/B-048: speaker prefix must be applied. _annotate_recent_rows
    is the function that drops [CHAT-TURN] noise and lifts speaker labels."""
    from memory import manager
    src = _src(manager.MemoryManager.select_context)
    assert "_annotate_recent_rows" in src, (
        "speaker disambiguation not wired: select_context bypasses "
        "_annotate_recent_rows, model will mix up who said what in groups"
    )


def test_select_context_uses_fetch_recent():
    from memory import manager
    src = _src(manager.MemoryManager.select_context)
    assert "fetch_recent" in src


# ===== PTB adapter — early album observation =====


def test_adapter_on_message_observes_album_before_handler():
    """observe_album_message must be invoked in adapter (before handler
    delegation) so siblings register even if handler is busy."""
    from adapters.telegram_bot import TelegramBotAdapter
    src = _src(TelegramBotAdapter.start)
    observe_idx = src.find("observe_album_message(um)")
    handler_idx = src.find("await handler(um)")
    assert observe_idx > 0, "observe_album_message not wired in adapter"
    assert handler_idx > 0, "handler dispatch not wired in adapter"
    assert observe_idx < handler_idx, (
        "observe_album_message must run BEFORE await handler(um) — "
        "otherwise concurrent siblings register too late"
    )


def test_adapter_uses_concurrent_updates():
    """Without concurrent_updates(True), album sibling updates queue
    behind first item's processing → registry sees only 1 item."""
    from adapters.telegram_bot import TelegramBotAdapter
    src = _src(TelegramBotAdapter)
    assert "concurrent_updates(True)" in src


# ===== media.router — full media pipeline =====


def test_router_handle_ptb_mention_uses_album_download():
    """B-024..B-027: handle_ptb_mention must use album download for
    multi-message groups, not just first item."""
    from media import router
    src = _src(router.handle_ptb_mention)
    assert "download_from_ptb_album" in src, (
        "album download not wired: bot will see only first item of album"
    )
    assert "download_from_ptb_message" in src
    assert "_build_media_context" in src
    assert "_append_media_context" in src
    assert "cleanup_downloaded_media" in src, (
        "media tmp files not cleaned up after processing — disk leak"
    )


def test_build_media_context_uses_real_handlers():
    """transcribe_audio for voice (NOT legacy whisper_tool), describe_images
    for photos, analyze_video for videos — all must be wired."""
    from media import router
    src = _src(router._build_media_context)
    assert "transcribe_audio" in src, (
        "voice route doesn't call transcribe_audio — STT broken"
    )
    assert "describe_images" in src, "photo route doesn't call describe_images"
    assert "analyze_video" in src, "video route doesn't call analyze_video"


def test_router_does_not_use_legacy_whisper_tool():
    """B-020/B-021: legacy whisper_tool wrote .txt files that silently
    failed on prod. Must be gone everywhere in router."""
    import inspect
    from media import router
    src = inspect.getsource(router)
    assert "whisper_tool" not in src, (
        "legacy whisper_tool import survived; STT will silently fail again"
    )


# ===== agent.runner — search and citations =====


def test_run_search_wires_direct_search_and_chat_final():
    """B-070 + Codex refactor: run_search delegates evidence collection to
    _run_direct_search, then chat_final composes the user-facing reply."""
    from agent import runner
    src = _src(runner.run_search)
    assert "_run_direct_search" in src, (
        "run_search no longer pulls evidence — search broken"
    )
    assert "run_capability" in src, (
        "run_search must hand evidence to chat_final via run_capability"
    )


def test_run_search_applies_citation_rewriting():
    """B-070: bare [N] from chat_final must be rewritten to [domain](url)."""
    from agent import runner
    src = _src(runner.run_search)
    assert "_apply_inline_citation_links" in src, (
        "citations not rewritten: bare [N] will leak to user"
    )
    assert "_ensure_answer_has_citations" in src, (
        "fallback citations not added when model produced none"
    )


def test_run_capability_prepends_now_marker():
    """run_capability must inject [NOW] today_date so model knows the
    freshness of [SEARCH-RESULT] data."""
    from agent import runner
    src = _src(runner.run_capability)
    assert "_now_system_msg" in src, (
        "run_capability not injecting [NOW] — model can't reason about freshness"
    )


# ===== agent.planner — search gate =====


def test_plan_message_wires_search_gate():
    """B-040: search_gate must validate every potential search trigger.
    Without this, planner heuristic alone decides — too permissive."""
    from agent import planner
    src = _src(planner.plan_message)
    assert "_validate_search" in src, (
        "search gate not wired into plan_message — bot will gugle on stuff "
        "it shouldn't (engineering principles, theory, mythology)"
    )


def test_validate_search_uses_gate_prompt():
    """Search gate must use SEARCH_GATE_SYSTEM_PROMPT — otherwise prompt
    rules (engineering principles → CHAT) won't reach the model."""
    from agent import planner
    src = _src(planner._validate_search)
    assert "SEARCH_GATE_SYSTEM_PROMPT" in src


# ===== Module-level imports must survive =====


def test_message_logic_imports_album_registry():
    """If anyone removes album_registry import, album dedup silently breaks."""
    from app import message_logic
    src = inspect.getsource(message_logic)
    assert "from media.album_registry import" in src
    assert "claim_album_processing" in src
    assert "observe_album_message" in src


def test_message_logic_imports_voice_helpers():
    from app import message_logic
    src = inspect.getsource(message_logic)
    assert "from media.voice import" in src
    assert "send_voice_response" in src


def test_runner_imports_chat_once_and_capability_router():
    from agent import runner
    src = inspect.getsource(runner)
    assert "chat_once" in src
    assert "capability_model" in src or "_resolve_binding" in src or "run_capability" in src


def test_planner_imports_search_gate_prompt():
    from agent import planner
    src = inspect.getsource(planner)
    assert "SEARCH_GATE_SYSTEM_PROMPT" in src


# ===== Constants present and exported =====


def test_search_marker_used_in_flow():
    """B-042: marker must be used (not just defined as dead constant)."""
    from app import message_logic
    src = inspect.getsource(message_logic)
    # Defined
    assert "SEARCH_PERFORMED_MARKER" in src
    # Used in flow (not just defined once)
    assert src.count("SEARCH_PERFORMED_MARKER") >= 2


def test_reasoning_marker_used_in_flow():
    """B-069: marker must be used in flow."""
    from app import message_logic
    src = inspect.getsource(message_logic)
    assert src.count("REASONING_MARKER") >= 2
