"""Tests for billing.crypto — encryption round-trip with both backends."""
from __future__ import annotations

import os

import pytest

from billing import crypto


def _set_master_key(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("BILLING_MASTER_KEY", raising=False)
    else:
        monkeypatch.setenv("BILLING_MASTER_KEY", value)


def test_encrypt_decrypt_roundtrip_default_key(monkeypatch):
    _set_master_key(monkeypatch, "test-master-key")
    plain = "sk-proj-FAKE-1234567890"
    blob = crypto.encrypt_key(plain)
    assert blob and blob != plain
    assert crypto.decrypt_key(blob) == plain


def test_encrypt_empty_returns_empty(monkeypatch):
    _set_master_key(monkeypatch, "test-master-key")
    assert crypto.encrypt_key("") == ""
    assert crypto.decrypt_key("") == ""


def test_decrypt_invalid_blob_raises(monkeypatch):
    _set_master_key(monkeypatch, "test-master-key")
    with pytest.raises(RuntimeError):
        crypto.decrypt_key("not-base64-and-no-prefix-!!")


def test_unknown_prefix_rejected(monkeypatch):
    import base64

    _set_master_key(monkeypatch, "test-master-key")
    junk = base64.b64encode(b"v9:garbage").decode("ascii")
    with pytest.raises(RuntimeError):
        crypto.decrypt_key(junk)


def test_master_key_change_breaks_decrypt(monkeypatch):
    _set_master_key(monkeypatch, "key-A")
    blob = crypto.encrypt_key("payload")

    _set_master_key(monkeypatch, "key-B")
    # Either v1 (AESGCM) raises during auth check, or v0 returns garbage that
    # may not be valid utf-8 → both manifest as an exception.
    with pytest.raises(Exception):
        crypto.decrypt_key(blob)
