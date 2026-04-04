from __future__ import annotations

import datetime as dt

from db import search_repository


def test_is_expired_accepts_naive_datetime():
    created_at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=61)).replace(
        tzinfo=None
    )

    assert search_repository._is_expired(created_at, 60) is True


def test_is_expired_accepts_aware_datetime():
    created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)

    assert search_repository._is_expired(created_at, 60) is False
