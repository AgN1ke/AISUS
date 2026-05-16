"""Acceptance tests for category E (Search) and K (new requirements).

Maps to B-037..B-043, B-070 in behavior-audit.md.
"""
from __future__ import annotations

import pytest

from agent.runner import (
    _apply_inline_citation_links,
    _domain_label_from_url,
    _ensure_answer_has_citations,
)


# ===== B-070 NEW: domain-based citations =====

def test_B070_domain_label_strips_www():
    assert _domain_label_from_url("https://www.example.com/path") == "example.com"
    assert _domain_label_from_url("https://nasa.gov/article") == "nasa.gov"
    assert _domain_label_from_url("http://en.wikipedia.org/wiki/X") == "en.wikipedia.org"


def test_B070_bare_N_replaced_with_domain():
    """B-070: '[1]' → '[nasa.gov](url)' using citation_map."""
    citation_map = {1: "https://nasa.gov/artemis-ii/"}
    out = _apply_inline_citation_links(
        "NASA планує політ [1] на Місяць.", citation_map
    )
    assert "[nasa.gov](https://nasa.gov/artemis-ii/)" in out
    assert "[1]" not in out


def test_B070_repeated_N_replaced_consistently():
    """B-070: '[1]...[1]' → '[domain]...[domain]'."""
    citation_map = {1: "https://nasa.gov/x"}
    out = _apply_inline_citation_links(
        "Спершу [1], потім ще раз [1].", citation_map
    )
    assert out.count("[nasa.gov](https://nasa.gov/x)") == 2


def test_B070_already_linked_NN_url_converted_to_domain():
    """B-070: '[[1]](url)' (старий формат) → '[domain](url)'."""
    citation_map = {1: "https://nasa.gov/x"}
    out = _apply_inline_citation_links(
        "Старий формат [[1]](https://nasa.gov/x).", citation_map
    )
    assert "[nasa.gov](https://nasa.gov/x)" in out
    assert "[[1]]" not in out


def test_B070_unknown_index_left_as_is():
    """If [N] index not in citation_map, leave it intact (don't break text)."""
    citation_map = {1: "https://nasa.gov/x"}
    out = _apply_inline_citation_links(
        "Невідомий індекс [99] лишається.", citation_map
    )
    assert "[99]" in out


def test_B070_fallback_appends_domain_links():
    """B-070: якщо модель не вставила цитати — додаємо в кінець [domain](url)."""
    citation_map = {
        1: "https://nasa.gov/x",
        2: "https://reuters.com/y",
    }
    out = _ensure_answer_has_citations("Без цитат у тексті.", citation_map)
    assert "[nasa.gov](https://nasa.gov/x)" in out
    assert "[reuters.com](https://reuters.com/y)" in out


def test_B070_existing_domain_link_is_not_duplicated():
    citation_map = {1: "https://sinoptik.ua/pohoda/kyiv/2026-05-05"}
    out = _ensure_answer_has_citations(
        "Температура [sinoptik.ua](https://sinoptik.ua/pohoda/kyiv/2026-05-05).",
        citation_map,
    )

    assert out.count("sinoptik.ua") == 2


# ===== B-042 GREEN now (we restored the marker) =====

def test_B042_search_marker_constant_defined():
    """B-042: маркер пошуку — реалізовано в Session 102 round 2."""
    from app import message_logic
    assert hasattr(message_logic, "SEARCH_PERFORMED_MARKER")
    assert "ПОШУК" in message_logic.SEARCH_PERFORMED_MARKER


# ===== SearchOutcome contract (Codex's run_search refactor, Session 103) =====


def test_search_outcome_dataclass_contract():
    """Codex's SearchOutcome holds search results without composing answer.
    chat_final composes the user-facing reply from the [SEARCH-RESULT] block.
    """
    from agent.runner import SearchOutcome

    outcome = SearchOutcome(
        status="ok",
        evidence_block="status: ok\nresults: ...",
        queries=["q1"],
        citation_map={1: "https://nasa.gov/x"},
        intent_hypothesis="користувач хоче новин про NASA",
    )
    assert outcome.status == "ok"
    assert "ok" in outcome.evidence_block
    assert outcome.queries == ["q1"]
    assert outcome.citation_map == {1: "https://nasa.gov/x"}
    assert outcome.intent_hypothesis.startswith("користувач")


def test_search_outcome_default_factories():
    """Defaults: empty queries, empty citation_map, empty intent."""
    from agent.runner import SearchOutcome

    o = SearchOutcome(status="no_results", evidence_block="empty")
    assert o.queries == []
    assert o.citation_map == {}
    assert o.intent_hypothesis == ""


@pytest.mark.asyncio
async def test_run_search_strips_bare_N_from_chat_final_output(monkeypatch):
    """B-070 + Codex: run_search must convert bare [N] from chat_final's
    answer to [domain](url) using SearchOutcome.citation_map."""
    import agent.runner as runner

    async def fake_direct_search(*_args, **_kwargs):
        return runner.SearchOutcome(
            status="ok",
            evidence_block="status: ok\n[1] NASA Artemis II",
            queries=["NASA Artemis"],
            citation_map={1: "https://nasa.gov/artemis-ii"},
        )

    async def fake_run_capability(*_args, **_kwargs):
        return "Літає [1] на Місяць."  # bare [N], must be rewritten

    monkeypatch.setattr(runner, "_run_direct_search", fake_direct_search)
    monkeypatch.setattr(runner, "run_capability", fake_run_capability)

    out = await runner.run_search(123, "пошукай новини про Artemis")

    assert "[nasa.gov](https://nasa.gov/artemis-ii)" in out
    assert "[1]" not in out


@pytest.mark.asyncio
async def test_run_search_no_results_status_propagates(monkeypatch):
    """When _run_direct_search returns status=no_results, run_search still
    delegates to chat_final with the evidence block; status is in [SEARCH-RESULT]."""
    import agent.runner as runner

    captured = {}

    async def fake_direct_search(*_args, **_kwargs):
        return runner.SearchOutcome(
            status="no_results",
            evidence_block="status: no_results\ndetails: нічого не знайшов",
            queries=[],
            citation_map={},
        )

    async def fake_run_capability(_chat, _text, *, capability, use_reasoning, turn_context_msgs):
        captured["context"] = turn_context_msgs
        return "Не знайшов даних, вибач."

    monkeypatch.setattr(runner, "_run_direct_search", fake_direct_search)
    monkeypatch.setattr(runner, "run_capability", fake_run_capability)

    out = await runner.run_search(123, "пошукай рідкісну штуку")

    assert "Не знайшов даних" in out
    # [SEARCH-RESULT] block injected with status info
    search_msgs = [
        m for m in (captured.get("context") or [])
        if m.get("role") == "system" and "[SEARCH-RESULT]" in (m.get("content") or "")
    ]
    assert search_msgs, "run_search must inject [SEARCH-RESULT] system message"
    assert "no_results" in search_msgs[0]["content"]


# ===== _now_system_msg adds today's date for fresh-info reasoning =====


def test_now_system_msg_emits_iso_date():
    """run_capability prepends [NOW]\\ntoday_date_utc: YYYY-MM-DD so the model
    can reason about freshness of [SEARCH-RESULT] data."""
    from agent.runner import _now_system_msg, _today_iso

    msg = _now_system_msg()
    assert msg["role"] == "system"
    assert "[NOW]" in msg["content"]
    assert _today_iso() in msg["content"]


# ===== B-040 search_gate prompt rubric — must reject technical/theoretical questions =====


def test_search_gate_prompt_is_principle_first():
    """B-040: search_gate prompt encodes a stable principle, not a list of
    specific anti-examples.

    Session 118 lesson: enumerating anti-examples (engine, supersonic, lore,
    etc.) led the gate model to pattern-match on those topics and miss new
    ones (medical lab interpretation at 11:30 16-05). The prompt now states
    the principle plainly: would the answer change month-over-month? Numbers
    and specifics don't promote SEARCH; interpretation is stable knowledge.
    """
    from core.prompts import SEARCH_GATE_SYSTEM_PROMPT

    # Core principle: search only for data that changes over time
    assert "в часі" in SEARCH_GATE_SYSTEM_PROMPT
    # The month-ago time-stability test must be stated explicitly
    assert "місяць тому" in SEARCH_GATE_SYSTEM_PROMPT
    # Stable-knowledge categories must include theory and interpretation
    assert "теорія" in SEARCH_GATE_SYSTEM_PROMPT
    assert "інтерпретація" in SEARCH_GATE_SYSTEM_PROMPT
    # Numbers/specifics rule — protects medical lab values, parameters, etc.
    assert "конкретних чисел" in SEARCH_GATE_SYSTEM_PROMPT
    assert "SEARCH-ом" in SEARCH_GATE_SYSTEM_PROMPT
    # "Що робити коли X" stability rule
    assert "Що робити коли" in SEARCH_GATE_SYSTEM_PROMPT


def test_search_gate_prompt_explicit_dont_search_phrases():
    """B-040: gate prompt must tell model that 'не шукай' / 'подумай'
    in user message → ALWAYS CHAT."""
    from core.prompts import SEARCH_GATE_SYSTEM_PROMPT

    assert "не шукай" in SEARCH_GATE_SYSTEM_PROMPT
    assert "не гугли" in SEARCH_GATE_SYSTEM_PROMPT
    assert "подумай" in SEARCH_GATE_SYSTEM_PROMPT


def test_search_gate_prompt_default_is_chat():
    """B-040: prompt explicitly states default = CHAT, fail-safe."""
    from core.prompts import SEARCH_GATE_SYSTEM_PROMPT

    assert "За замовчуванням" in SEARCH_GATE_SYSTEM_PROMPT
    assert "CHAT" in SEARCH_GATE_SYSTEM_PROMPT


def test_search_gate_prompt_complexity_is_not_search_signal():
    """B-040: prompt explicitly negates 'long technical question = SEARCH'
    fallacy. Complex theoretical questions are still CHAT."""
    from core.prompts import SEARCH_GATE_SYSTEM_PROMPT

    # The prompt has explicit clause: technical complexity is NOT a search arg
    assert "складність" in SEARCH_GATE_SYSTEM_PROMPT.lower() or (
        "технічно складний" in SEARCH_GATE_SYSTEM_PROMPT
    )


def test_search_gate_prompt_covers_lore_as_principle():
    """Session 108 origin: '/ідентифікуй танок хуман містіка в л2' triggered
    SEARCH. Session 118 redesign: rather than enumerating specific anti-examples
    (lore, identify, deictic — which caused pattern-overfit), the prompt now
    carries them under the umbrella of stable knowledge categories.
    """
    from core.prompts import SEARCH_GATE_SYSTEM_PROMPT

    # "lore" must still be named as a stable-knowledge category
    assert "lore" in SEARCH_GATE_SYSTEM_PROMPT.lower()
    # "Identify / what is this" must still be named as a CHAT pattern, but as
    # a category description, not a concrete example.
    assert "ідентифікація" in SEARCH_GATE_SYSTEM_PROMPT.lower() or (
        "що це" in SEARCH_GATE_SYSTEM_PROMPT.lower()
    )


def test_search_gate_prompt_protects_numeric_and_actionable_questions():
    """Session 118: real failure — '@bot шо робити коли ттг 11, а т4 0,39?'
    voted SEARCH because the prompt enumerated lore/physics anti-examples
    but did not state that numbers and actionable wording don't promote SEARCH.

    The new prompt makes this an explicit principle, not an example list.
    """
    from core.prompts import SEARCH_GATE_SYSTEM_PROMPT

    # Specific numbers / values / parameters rule
    assert "конкретних чисел" in SEARCH_GATE_SYSTEM_PROMPT
    # 'Що робити коли X' actionability rule
    assert "Що робити коли" in SEARCH_GATE_SYSTEM_PROMPT
    # Stable interpretation should be named as CHAT
    assert "інтерпретація" in SEARCH_GATE_SYSTEM_PROMPT


# ===== Still YELLOW =====

@pytest.mark.xfail(reason="B-039 YELLOW: search gate occasionally permissive", strict=False)
def test_B039_normal_questions_dont_trigger_search():
    pytest.fail("known-yellow: search gate occasionally permissive")
