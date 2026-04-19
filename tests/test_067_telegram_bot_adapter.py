from types import SimpleNamespace

from adapters.telegram_bot import _is_edited_update


def test_is_edited_update_true_for_edited_message():
    update = SimpleNamespace(
        edited_message=SimpleNamespace(message_id=10),
        edited_channel_post=None,
        edited_business_message=None,
    )

    assert _is_edited_update(update) is True


def test_is_edited_update_false_for_regular_message():
    update = SimpleNamespace(
        edited_message=None,
        edited_channel_post=None,
        edited_business_message=None,
        effective_message=SimpleNamespace(message_id=11),
    )

    assert _is_edited_update(update) is False
