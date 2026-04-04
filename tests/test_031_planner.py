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

    decision = planner.plan_message(planner.PlannerInput(user_text="звичайне питання"))

    assert decision.route == "chat"
    assert decision.capability == "chat_final"
    assert decision.planner_source == "heuristic"
