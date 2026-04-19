import pytest

from app.podcast_dossier import build_podcast_dossier


@pytest.mark.asyncio
async def test_build_podcast_dossier_collects_relevant_recent_turns_and_memory():
    pending = {
        "topic_label": "одомашнення бавовни, льону і конопель",
        "style_instruction": "у форматі дискусії",
        "request_text": "зроби на цю тему подкаст",
        "source_scope": "recent_context",
        "source_message_id": 321,
        "anchor_excerpt": "бавовна, льон і коноплі",
    }
    recent_rows = [
        {
            "role": "system",
            "content": (
                "[CHAT-TURN]\n"
                "current_message_id: 300\n"
                "sender: Микита @agnike\n"
                "current_message_time_local: 2026-04-10 12:00:00 EEST\n"
                "current_user_text: а як бавовну одомашнювали в Індії і Перу?"
            ),
        },
        {"role": "user", "content": "а як бавовну одомашнювали в Індії і Перу?"},
        {
            "role": "assistant",
            "content": "У Південній Азії та в Америці це відбувалося незалежно, з різними лініями одомашнення.",
        },
        {
            "role": "system",
            "content": (
                "[CHAT-TURN]\n"
                "current_message_id: 321\n"
                "sender: Микита @agnike\n"
                "current_message_time_local: 2026-04-10 12:05:00 EEST\n"
                "reply_target_message_id: 300\n"
                "reply_target_text: бавовна, льон і коноплі\n"
                "resolved_instruction: порівняй ще льон, коноплі й кропиву по тканинах і технології обробки"
            ),
        },
        {"role": "user", "content": "порівняй ще льон, коноплі й кропиву по тканинах і технології обробки"},
        {
            "role": "assistant",
            "content": "Льон дає тонше полотно, коноплі витриваліші, кропива історично рідкісніша, але теж текстильна культура.",
        },
        {
            "role": "system",
            "content": (
                "[CHAT-TURN]\n"
                "current_message_id: 330\n"
                "sender: Микита @agnike\n"
                "current_message_time_local: 2026-04-10 12:09:00 EEST\n"
                "current_user_text: зроби на цю тему подкаст"
            ),
        },
        {"role": "user", "content": "зроби на цю тему подкаст"},
    ]
    core_rows = [
        {
            "fact_key": "бавовна",
            "fact_value": "бавовна була одомашнена незалежно в Старому і Новому Світі",
        },
        {
            "fact_key": "коноплі",
            "fact_value": "конопляні волокна зазвичай грубіші, але дуже міцні",
        },
        {
            "fact_key": "нерелевантне",
            "fact_value": "це не про тему",
        },
    ]
    long_rows = [
        {
            "summary": "У розмові вже порівнювали льон, коноплі та кропиву як текстильні культури й окремо акцентували на відмінностях технології обробки.",
        },
        {
            "summary": "Це стороння тема про ракети.",
        },
    ]

    dossier = await build_podcast_dossier(
        99991,
        pending,
        recent_rows=recent_rows,
        core_rows=core_rows,
        long_rows=long_rows,
    )

    assert dossier.topic_label == "одомашнення бавовни, льону і конопель"
    assert dossier.style_instruction == "у форматі дискусії"
    assert dossier.source_message_id == 321
    assert len(dossier.recent_turns) >= 2
    assert any("бавовну одомашнювали" in turn for turn in dossier.recent_turns)
    assert any("льон, коноплі й кропиву" in signal for signal in dossier.user_interest_signals)
    assert any("Старому і Новому Світі" in fact for fact in dossier.core_facts)
    assert any("технології обробки" in item for item in dossier.long_memory_notes)
    assert "[PODCAST-DOSSIER]" in dossier.assembled_text
    assert "relevant_conversation_turns:" in dossier.assembled_text
