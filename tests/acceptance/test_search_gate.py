"""Search-gate behavior tests (Session 109 architecture).

Two-stage architecture:
  1. Primary planner (heuristic / LLM) picks a route — including `search`.
  2. IF planner picked `search` → focused gate-LLM verifies.
     - Gate confirms (SEARCH) → keep `search` route.
     - Gate rejects (CHAT) → downgrade to `chat`.
     - Gate exception → fail-closed → downgrade to `chat`.

Anti-rule: gate must NOT be called on chat-decisions (zero token cost on
ordinary turns). Anti-rule: gate must NOT promote chat → search.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent.planner as planner_mod
from agent.planner import PlanDecision, PlannerInput


def _make_task(text: str = "якесь питання") -> PlannerInput:
    return PlannerInput(
        user_text=text,
        is_private=False,
        addressed_via_mention=True,
        reply_to_bot=False,
        has_media_context=False,
        media_kind=None,
        dialogue_context=(),
    )


def _fake_response(content: str):
    """Build a minimal openai-like response with .choices[0].message.content."""
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


# ===== _normalize_route accepts search =====


def test_normalize_route_accepts_search():
    """Session 109: search is now a valid planner route (was collapsed to chat)."""
    assert planner_mod._normalize_route("search") == "search"
    assert planner_mod._normalize_route("SEARCH") == "search"


def test_normalize_route_accepts_modal_routes():
    for route in ("image", "video", "voice", "document", "chat"):
        assert planner_mod._normalize_route(route) == route


def test_normalize_route_unknown_falls_back_to_chat():
    assert planner_mod._normalize_route("foobar") == "chat"
    assert planner_mod._normalize_route(None) == "chat"
    assert planner_mod._normalize_route("") == "chat"


# ===== _validate_search uses focused payload =====


def test_validate_search_calls_chat_once_with_gate_prompt(monkeypatch):
    """Gate sends focused payload (today_date + last_user_message +
    recent_exchange) and reads the verdict from chat_once."""
    captured = {}

    def fake_chat_once(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return _fake_response("SEARCH")

    monkeypatch.setattr(planner_mod, "chat_once", fake_chat_once)

    task = _make_task("яка погода в Києві зараз?")
    result = planner_mod._validate_search(task)

    assert result is True
    # The system prompt MUST be the gate prompt
    sys_msgs = [m for m in captured["messages"] if m["role"] == "system"]
    assert sys_msgs, "gate must inject SEARCH_GATE_SYSTEM_PROMPT as system msg"
    assert "детектор" in sys_msgs[0]["content"].lower() or "search" in sys_msgs[0]["content"].lower()
    # Capability is planner_reasoning (cheap model)
    assert captured["kwargs"].get("capability") == "planner_reasoning"
    # Temperature 0 for deterministic verdict
    assert captured["kwargs"].get("temperature") == 0


def test_validate_search_returns_true_on_search_verdict(monkeypatch):
    monkeypatch.setattr(
        planner_mod, "chat_once", lambda *a, **kw: _fake_response("SEARCH")
    )
    assert planner_mod._validate_search(_make_task()) is True


def test_validate_search_returns_false_on_chat_verdict(monkeypatch):
    monkeypatch.setattr(
        planner_mod, "chat_once", lambda *a, **kw: _fake_response("CHAT")
    )
    assert planner_mod._validate_search(_make_task()) is False


def test_validate_search_fails_closed_on_exception(monkeypatch):
    """If gate-LLM throws, _validate_search returns False (downgrade to chat).
    Anti-rule: never default to SEARCH on classifier failure."""
    def explode(*a, **kw):
        raise RuntimeError("OpenAI 500")
    monkeypatch.setattr(planner_mod, "chat_once", explode)
    assert planner_mod._validate_search(_make_task()) is False


def test_validate_search_treats_garbled_verdict_as_chat(monkeypatch):
    """If the gate model returns junk (not 'SEARCH'/'CHAT'), default to chat."""
    monkeypatch.setattr(
        planner_mod, "chat_once",
        lambda *a, **kw: _fake_response("ну якось так, мабуть"),
    )
    assert planner_mod._validate_search(_make_task()) is False


def test_validate_search_strips_user_message_to_600_chars(monkeypatch):
    """Gate payload truncates user_message to 600 chars to avoid token waste."""
    captured = {}

    def fake_chat_once(messages, **kwargs):
        captured["messages"] = messages
        return _fake_response("CHAT")

    monkeypatch.setattr(planner_mod, "chat_once", fake_chat_once)
    long_text = "x" * 5000
    planner_mod._validate_search(_make_task(long_text))

    user_payload = captured["messages"][-1]["content"]
    # The truncated text must appear in payload, but not the full 5000-char input
    assert "x" * 600 in user_payload
    assert "x" * 5000 not in user_payload


# ===== plan_message: gate as filter (search→chat downgrade) =====


def test_plan_message_keeps_search_when_gate_confirms(monkeypatch):
    """Planner picked search, gate says SEARCH → keep search route."""
    monkeypatch.setattr(
        planner_mod, "_planner_enabled", lambda: True
    )
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=False,
            planner_source="llm",
            notes="planner picked search",
        ),
    )
    monkeypatch.setattr(
        planner_mod, "chat_once",
        lambda *a, **kw: _fake_response("SEARCH"),
    )

    decision = planner_mod.plan_message(_make_task("пошукай новини про NASA"))
    assert decision.route == "search"
    assert decision.capability == "search_web"


def test_plan_message_downgrades_search_when_gate_rejects(monkeypatch):
    """Planner picked search, gate says CHAT → downgrade to chat.

    This is the core fix of Session 109: false-positive search picks
    (game lore, theory, principles) get cut off by the gate."""
    monkeypatch.setattr(planner_mod, "_planner_enabled", lambda: True)
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=False,
            planner_source="llm",
            notes="planner picked search",
        ),
    )
    monkeypatch.setattr(
        planner_mod, "chat_once",
        lambda *a, **kw: _fake_response("CHAT"),
    )

    decision = planner_mod.plan_message(_make_task("розкажи про танок хуман містіка в л2"))
    assert decision.route == "chat"
    assert decision.capability == "chat_final"
    assert decision.planner_source == "search_gate_downgrade"


def test_plan_message_does_NOT_call_gate_when_planner_picked_chat(monkeypatch):
    """Anti-rule (Session 098-108 bug): gate must NOT fire on every chat turn.

    Cost matters — gate-LLM call per chat-message was burning tokens."""
    monkeypatch.setattr(planner_mod, "_planner_enabled", lambda: True)
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="chat",
            capability="chat_final",
            use_reasoning=False,
            planner_source="llm",
            notes="planner picked chat",
        ),
    )
    gate_calls = []
    monkeypatch.setattr(
        planner_mod, "_validate_search",
        lambda task: gate_calls.append(task) or False,
    )

    decision = planner_mod.plan_message(_make_task("привіт як справи"))
    assert decision.route == "chat"
    assert len(gate_calls) == 0, (
        "search gate must NOT be called when planner picked chat — "
        "that was the old buggy promoter-mode burning tokens"
    )


def test_plan_message_does_NOT_call_gate_for_media_routes(monkeypatch):
    """Gate is only relevant to text turns. Image/video/voice/document
    routes never touch the gate."""
    media_task = PlannerInput(
        user_text="опиши",
        is_private=False,
        addressed_via_mention=True,
        reply_to_bot=False,
        has_media_context=True,
        media_kind="image",
        dialogue_context=(),
    )
    gate_calls = []
    monkeypatch.setattr(
        planner_mod, "_validate_search",
        lambda task: gate_calls.append(task) or False,
    )

    decision = planner_mod.plan_message(media_task)
    assert decision.route == "image"
    assert len(gate_calls) == 0


def test_plan_message_does_NOT_call_gate_when_search_disabled(monkeypatch):
    """SEARCH_ENABLED=false → gate skipped, planner's search stays as search
    (admin manually disabled feature; gate would be no-op anyway)."""
    monkeypatch.setattr(planner_mod, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner_mod, "_search_enabled", lambda: False)
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=False,
            planner_source="llm",
            notes="planner picked search",
        ),
    )
    gate_calls = []
    monkeypatch.setattr(
        planner_mod, "_validate_search",
        lambda task: gate_calls.append(task) or True,
    )

    decision = planner_mod.plan_message(_make_task("пошукай"))
    # When SEARCH disabled globally, gate is skipped entirely
    assert len(gate_calls) == 0


def test_plan_message_gate_downgrade_preserves_use_reasoning(monkeypatch):
    """When gate downgrades search→chat, use_reasoning from original
    decision is preserved (user's /think intent shouldn't be lost)."""
    monkeypatch.setattr(planner_mod, "_planner_enabled", lambda: True)
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=True,  # /think prefix
            planner_source="llm",
            notes="planner picked search",
        ),
    )
    monkeypatch.setattr(
        planner_mod, "chat_once",
        lambda *a, **kw: _fake_response("CHAT"),
    )

    decision = planner_mod.plan_message(_make_task("/think чому небо синє"))
    assert decision.route == "chat"
    assert decision.use_reasoning is True  # preserved through downgrade


def test_plan_message_does_NOT_call_gate_on_empty_user_text(monkeypatch):
    """Empty user_text → no gate call (nothing to validate)."""
    monkeypatch.setattr(planner_mod, "_planner_enabled", lambda: True)
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=False,
            planner_source="llm",
            notes="",
        ),
    )
    gate_calls = []
    monkeypatch.setattr(
        planner_mod, "_validate_search",
        lambda task: gate_calls.append(task) or False,
    )

    decision = planner_mod.plan_message(_make_task(""))
    # Empty text: gate skipped via guard `(task.user_text or "").strip()`
    assert len(gate_calls) == 0


# ===== logging: verdict + truncated user message =====


def test_explicit_keyword_search_bypasses_reply_to_bot_downgrade(monkeypatch):
    """Session 115 fix: explicit 'Гугли/пошукай/загугли' in reply-to-bot
    must NOT be auto-downgraded. Session 114's blanket downgrade killed
    legitimate explicit-search requests in reply chains
    (trace 257752/4/7/9: 'Гугли - сбу операція павутина')."""
    monkeypatch.setattr(planner_mod, "_planner_enabled", lambda: True)
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=False,
            planner_source="llm",
            notes="",
        ),
    )
    # Gate not consulted in this path; if it would be, return True so the
    # final decision is still 'search' (we want to verify the BYPASS path).
    monkeypatch.setattr(planner_mod, "_validate_search", lambda task: True)

    for explicit_text in (
        "Гугли - сбу операція павутина",
        "загугли сбу операція павутина",
        "пошукай новини про NASA",
        "погугли курс долара",
    ):
        task = PlannerInput(
            user_text=explicit_text,
            is_private=False,
            addressed_via_mention=False,
            reply_to_bot=True,  # in a reply chain with bot
            has_media_context=False,
            media_kind=None,
            dialogue_context=(),
        )
        decision = planner_mod.plan_message(task)
        assert decision.route == "search", (
            f"explicit keyword '{explicit_text}' must reach search "
            f"despite reply_to_bot; got route={decision.route} "
            f"source={decision.planner_source}"
        )


def test_short_form_keywords_recognized_as_explicit_search():
    """Session 115: short forms 'гугли' / 'шукай' (without 'за'/'по' prefix)
    must count as explicit search requests."""
    from agent.search_task import is_explicit_search_request
    assert is_explicit_search_request("Гугли - сбу операція") is True
    assert is_explicit_search_request("гугли новини") is True
    assert is_explicit_search_request("Шукай останнє про NASA") is True
    # And the longer forms still work
    assert is_explicit_search_request("пошукай новини") is True
    assert is_explicit_search_request("загугли курс") is True


def test_vision_prompt_extracts_maximum_detail():
    """Session 115: vision prompt must instruct extraction of maximum
    information for handoff to flagship model — NOT a 'стисло' summary."""
    from core.prompts import VISION_IMAGE_DESCRIPTION_PROMPT
    p = VISION_IMAGE_DESCRIPTION_PROMPT.lower()
    # Must NOT contain restricting word "стисло"
    assert "стисло" not in p, (
        "vision prompt must not restrict to short summary — flagship model "
        "composes the user-facing answer, vision should extract everything"
    )
    # Must include category-instructions for text/people/objects/context
    for kw in ("ocr", "впізнавані", "брен", "контекст", "не цензуруй"):
        assert kw in p, f"vision prompt missing '{kw}'"


def test_video_extractor_prompt_demands_full_detail():
    """Session 115: video extraction prompt must request structured full
    detail (text, people, characters, objects, context, action)."""
    import inspect
    from media import video
    src = inspect.getsource(video).lower()
    for kw in ("text:", "people:", "objects:", "context:", "не цензуруй"):
        assert kw in src, f"video prompt missing '{kw}'"


def test_plan_message_auto_downgrades_search_when_reply_to_bot(monkeypatch):
    """Session 114: when user is in reply-to-bot conversation, planner-picked
    search must be auto-downgraded WITHOUT calling the LLM gate.

    Real failure: trace 257692 — user reply'ed bot with 'шо там пишуть?',
    planner picked search, gate said SEARCH → bot googled. Anti-rule: if
    you're talking to me, you're not asking me to fetch fresh data."""
    monkeypatch.setattr(planner_mod, "_planner_enabled", lambda: True)
    monkeypatch.setattr(
        planner_mod, "_plan_with_model",
        lambda task: PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=False,
            planner_source="llm",
            notes="",
        ),
    )
    gate_calls = []
    monkeypatch.setattr(
        planner_mod, "_validate_search",
        lambda task: gate_calls.append(task) or True,
    )

    task = PlannerInput(
        user_text="шо там пишуть?",
        is_private=False,
        addressed_via_mention=False,
        reply_to_bot=True,
        has_media_context=False,
        media_kind=None,
        dialogue_context=(),
    )
    decision = planner_mod.plan_message(task)
    assert decision.route == "chat"
    assert decision.planner_source == "search_auto_downgrade_reply_to_bot"
    # Gate should NOT have been consulted (auto-downgrade saves tokens)
    assert len(gate_calls) == 0


def test_search_gate_prompt_covers_contextual_clarification():
    """Session 114 origin: 'шо там пишуть?' / 'а тут що?' / 'це правда?' refer
    to in-context objects (prev bot message, replied media). Session 118
    redesign: rather than listing specific deictic phrases as anti-examples
    (which caused pattern-overfit), the prompt names 'контекстне уточнення'
    as a CHAT category and instructs the gate not to extrapolate intent
    from prior turns."""
    from core.prompts import SEARCH_GATE_SYSTEM_PROMPT
    assert "контекстне уточнення" in SEARCH_GATE_SYSTEM_PROMPT.lower()
    assert "disambiguation" in SEARCH_GATE_SYSTEM_PROMPT.lower()


def test_search_prompts_cover_semantic_external_evidence_intent():
    from core.prompts import (
        PLANNER_SYSTEM_PROMPT,
        SEARCH_COMPOSER_SYSTEM_PROMPT,
        SEARCH_GATE_SYSTEM_PROMPT,
        SEARCH_QUERY_PLANNER_PROMPT,
    )

    planner = PLANNER_SYSTEM_PROMPT.lower()
    gate = SEARCH_GATE_SYSTEM_PROMPT.lower()
    composer = SEARCH_COMPOSER_SYSTEM_PROMPT.lower()
    query_planner = SEARCH_QUERY_PLANNER_PROMPT.lower()

    assert "external-evidence intent" in gate
    assert "osint" in planner
    assert "osint" in gate
    assert "відкритих джерел" in planner
    assert "відкриті джерела" in gate
    assert "обшукай інтернет" in composer
    assert "ніколи не змінюй тему запиту" in query_planner


def test_gemini_timeout_is_at_least_120s():
    """Session 114: Gemini /think reasoning often takes 90-150s. Old 60s
    timeout caused recurring ReadTimeout on /think turns (trace 257552)."""
    import inspect
    from agent import llm
    src = inspect.getsource(llm)
    # Find the Gemini request line. Hard-coded timeout must be >= 120.
    import re
    matches = re.findall(r"timeout=(\d+)", src)
    gemini_timeouts = [int(m) for m in matches if int(m) >= 60]
    assert any(t >= 120 for t in gemini_timeouts), (
        "Gemini request timeout must be at least 120s (was 60s, caused "
        "ReadTimeout for /think reasoning)"
    )


def test_validate_search_logs_verdict_and_short_excerpt(monkeypatch, caplog):
    """Gate must log verdict + first ~120 chars of user_msg for ops debugging."""
    import logging
    monkeypatch.setattr(
        planner_mod, "chat_once",
        lambda *a, **kw: _fake_response("SEARCH"),
    )
    with caplog.at_level(logging.INFO, logger="agent.planner"):
        planner_mod._validate_search(_make_task("пошукай новини NASA Artemis"))
    record_text = " ".join(r.getMessage() for r in caplog.records)
    assert "planner.search_gate" in record_text
    assert "verdict=SEARCH" in record_text
    assert "пошукай" in record_text
