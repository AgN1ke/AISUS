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


def test_heuristic_search_plan(monkeypatch):
    monkeypatch.setattr(planner, "_planner_enabled", lambda: False)
    decision = planner.plan_message(
        planner.PlannerInput(user_text="пошукай новини про OpenAI")
    )
    assert decision.route == "search"
    assert decision.capability == "search_web"
    assert decision.planner_source == "heuristic"


def test_llm_planner_parse(monkeypatch):
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(planner, "_validate_search", lambda task: True)
    monkeypatch.setenv("CAPABILITY_SEARCH_WEB_REASONING_ENABLED", "1")
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"search","capability":"search_web","use_reasoning":true,"notes":"fresh info"}'
        ),
    )

    decision = planner.plan_message(planner.PlannerInput(user_text="що там з OpenAI"))

    assert decision.route == "search"
    assert decision.capability == "search_web"
    assert decision.use_reasoning is True
    assert decision.planner_source == "llm"


def test_llm_planner_fallback_on_invalid_json(monkeypatch):
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
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


def test_reasoning_phrase_trigger():
    assert planner._needs_reasoning("подумай глибше над цим")
    assert planner._needs_reasoning("think carefully about it")
    assert planner._needs_reasoning("запусти різонінг для цієї відповіді")
    assert not planner._needs_reasoning("я думаю, що все ок")


def test_reasoning_explicit_request_overrides_llm_false(monkeypatch):
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_REASONING_ENABLED", "1")
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"chat","capability":"chat_final","use_reasoning":false,"notes":"default"}'
        ),
    )

    decision = planner.plan_message(
        planner.PlannerInput(user_text="як роблять ракетний двигун твердопаливний? запусти різонінг")
    )

    assert decision.route == "chat"
    assert decision.capability == "chat_final"
    assert decision.use_reasoning is True


def test_reasoning_gate_disables_when_capability_off(monkeypatch):
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(planner, "_validate_search", lambda task: True)
    monkeypatch.delenv("CAPABILITY_SEARCH_WEB_REASONING_ENABLED", raising=False)
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"search","capability":"search_web","use_reasoning":true,"notes":"fresh info"}'
        ),
    )

    decision = planner.plan_message(planner.PlannerInput(user_text="що там з OpenAI"))

    assert decision.route == "search"
    assert decision.capability == "search_web"
    assert decision.use_reasoning is False


def test_explicit_search_overrides_llm_chat_decision(monkeypatch):
    """When user says 'шукай!', search must happen even if LLM says chat."""
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"chat","capability":"chat_final","use_reasoning":false,"notes":"general knowledge"}'
        ),
    )

    decision = planner.plan_message(
        planner.PlannerInput(user_text="ні, на воді як пальне, шукай!")
    )

    assert decision.route == "search"
    assert decision.capability == "search_web"
    assert decision.planner_source == "heuristic"
    assert decision.notes == "explicit_search_intent"


def test_explicit_search_bypasses_gate(monkeypatch):
    """When user says 'шукай!', the search gate must be skipped."""
    monkeypatch.setattr(planner, "_planner_enabled", lambda: True)
    monkeypatch.setattr(planner, "_should_short_circuit", lambda task: False)
    # Gate would return False (CHAT) — but it should never be called
    monkeypatch.setattr(planner, "_validate_search", lambda task: (_ for _ in ()).throw(RuntimeError("gate should not be called")))
    monkeypatch.setattr(
        planner,
        "chat_once",
        lambda *args, **kwargs: DummyResponse(
            '{"route":"search","capability":"search_web","use_reasoning":false,"notes":"user asked"}'
        ),
    )

    decision = planner.plan_message(
        planner.PlannerInput(user_text="шукай інфу про водневе пальне")
    )

    assert decision.route == "search"
    assert decision.capability == "search_web"


def test_heuristic_voice_plan_uses_chat_capability():
    decision = planner.plan_message(
        planner.PlannerInput(
            user_text="я зараз піду спати",
            has_media_context=True,
            media_kind="voice",
            reply_to_bot=True,
        )
    )
    assert decision.route == "chat"
    assert decision.capability == "chat_final"
    assert decision.notes == "voice_input_transcribed"
    assert decision.planner_source == "heuristic"
