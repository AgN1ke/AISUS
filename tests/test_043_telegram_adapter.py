from types import SimpleNamespace

from adapters.telegram_bot import _is_edited_message_update


def test_edited_message_update_is_detected():
    update = SimpleNamespace(
        message=None,
        edited_message=SimpleNamespace(message_id=123),
    )

    assert _is_edited_message_update(update) is True


def test_normal_message_update_is_not_edited():
    update = SimpleNamespace(
        message=SimpleNamespace(message_id=123),
        edited_message=None,
    )

    assert _is_edited_message_update(update) is False
