import agent.planner as planner


class DummyResponse:
    def __init__(self, content):
        class _Msg:
            pass

        class _Choice:
            pass

        msg = _Msg()
        msg.content = content
        choice = _Choice()
        choice.message = msg
        self.choices = [choice]


def test_heuristic_media_plan():
    decision = planner.plan_message(
        planner.PlannerInput(
            user_text="поясни це",
            has_media_context=True,
            media_kind="image",
            addressed_via_mention=True,
        )
    )
    assert decision.route == "image"
    assert decision.capability == "vision_image"
    assert decision.planner_source == "heuristic"


def test_heuristic_text_falls_to_chat_no_keyword_search(monkeypatch):
    """Heuristic search routing is gone — only the LLM intent classifier
    can promote a text turn to search."""
    monkeypatch.setattr(planner, "_planner_enabled", lambda: False)
    monkeypatch.setattr(planner, "_search_enabled", lambda: False)

    decision = planner.plan_message(
        planner.PlannerInput(user_text="пошукай новини про OpenAI")
    )
    assert decision.route == "chat"
    assert decision.capability == "chat_final"
    assert decision.planner_source == "heuristic"


def test_planner_llm_search_route_survives_when_gate_disabled(monkeypatch):
    """Current architecture: planner may pick search directly.
    If SEARCH_ENABLED=false, the search gate is skipped and the planner
    decision is left untouched for the caller to handle."""
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(planner, "_search_enabled", lambda: False)
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"search","capability":"search_web","use_reasoning":false}'
        ),
    )

    decision = planner.plan_message(planner.PlannerInput(user_text="що там з OpenAI"))

    assert decision.route == "search"
    assert decision.capability == "search_web"


def test_search_gate_does_not_promote_non_explicit_chat_to_search(monkeypatch):
    """Search gate is a filter, not a promoter. If planner picked chat,
    the gate must not be called for non-command text."""
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(planner, "_search_enabled", lambda: True)
    monkeypatch.setattr(
        planner,
        "_validate_search",
        lambda task: (_ for _ in ()).throw(AssertionError("gate must not promote chat")),
    )
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"chat","capability":"chat_final","use_reasoning":false}'
        ),
    )

    decision = planner.plan_message(
        planner.PlannerInput(user_text="що там з курсом долара")
    )

    assert decision.route == "chat"
    assert decision.capability == "chat_final"
    assert decision.planner_source == "llm"


def test_search_intent_classifier_keeps_chat_for_shitpost(monkeypatch):
    """Classifier returns CHAT → no search. This is the user-reported
    case ('хуїн хуїксу' must NOT trigger search)."""
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(planner, "_search_enabled", lambda: True)
    monkeypatch.setattr(planner, "_validate_search", lambda task: False)
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"chat","capability":"chat_final","use_reasoning":false}'
        ),
    )

    decision = planner.plan_message(
        planner.PlannerInput(user_text="хуїн хуїксу")
    )

    assert decision.route == "chat"
    assert decision.capability == "chat_final"


def test_search_classifier_skipped_when_search_disabled(monkeypatch):
    """SEARCH_ENABLED=false → classifier never runs."""
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(planner, "_search_enabled", lambda: False)

    def fail_classifier(task):
        raise AssertionError("classifier must not run when search is disabled")

    monkeypatch.setattr(planner, "_validate_search", fail_classifier)
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"chat","capability":"chat_final","use_reasoning":false}'
        ),
    )

    decision = planner.plan_message(
        planner.PlannerInput(user_text="загугли курс долара")
    )
    assert decision.route == "chat"


def test_classifier_payload_excludes_system_blocks(monkeypatch):
    """Intent classifier sees only user/assistant pairs, no [SEARCH],
    [SEARCH-RESULT], [CHAT-TURN], [LONG-MEMO], etc. — so past search
    activity in memory doesn't bias the current decision."""
    captured = {}

    def fake_chat_once(messages, **kwargs):
        captured["messages"] = messages
        return DummyResponse("CHAT")

    monkeypatch.setattr(planner, "chat_once", fake_chat_once)

    task = planner.PlannerInput(
        user_text="це звичайне повідомлення",
        dialogue_context=(
            {"role": "system", "content": "[SEARCH]\nrequest: загугли...\nresults: ..."},
            {"role": "system", "content": "[SEARCH-RESULT]\nstatus: ok"},
            {"role": "system", "content": "[CHAT-TURN]\nuser_id: 1"},
            {"role": "system", "content": "[LONG-MEMO]\nстисло про чат"},
            {"role": "user", "content": "попереднє повідомлення юзера"},
            {"role": "assistant", "content": "попередня відповідь бота"},
        ),
    )
    assert planner._validate_search(task) is False

    payload_msg = captured["messages"][-1]["content"]
    assert "[SEARCH]" not in payload_msg
    assert "[SEARCH-RESULT]" not in payload_msg
    assert "[CHAT-TURN]" not in payload_msg
    assert "[LONG-MEMO]" not in payload_msg
    assert "попереднє повідомлення юзера" in payload_msg
    assert "попередня відповідь бота" in payload_msg


def test_classifier_fail_closed(monkeypatch):
    """When the classifier LLM call itself errors, default to CHAT
    (no search) — fail-closed, the user prefers no false positives."""
    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(planner, "chat_once", boom)

    decision = planner._validate_search(
        planner.PlannerInput(user_text="загугли щось")
    )
    assert decision is False


def test_planner_fallback_on_invalid_json(monkeypatch):
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(planner, "_search_enabled", lambda: False)
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse("невалідна відповідь"),
    )

    decision = planner.plan_message(
        planner.PlannerInput(user_text="звичайне питання")
    )

    assert decision.route == "chat"
    assert decision.capability == "chat_final"
    assert decision.planner_source == "heuristic"
