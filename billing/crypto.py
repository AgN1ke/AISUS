"""AES-GCM encryption for provider keys at rest.

The master key lives in the `BILLING_MASTER_KEY` env var (hex or base64,
32 bytes decoded). Ciphertext format: base64(nonce12 || ct || tag16).

Uses the standard library `hashlib` for key derivation and the `cryptography`
package for AES-GCM. If `cryptography` is not installed, we fall back to a
reversible XOR scheme — ONLY for dev/test, NEVER for production.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets

logger = logging.getLogger(__name__)


def _master_key_bytes() -> bytes:
    raw = os.getenv("BILLING_MASTER_KEY", "").strip()
    if not raw:
        logger.warning("BILLING_MASTER_KEY not set — using zero key (DEV ONLY)")
        return b"\x00" * 32
    try:
        if all(c in "0123456789abcdefABCDEF" for c in raw) and len(raw) in (64,):
            return bytes.fromhex(raw)
        decoded = base64.b64decode(raw)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _use_aes_gcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError:
        return None


def encrypt_key(raw_key: str) -> str:
    if not raw_key:
        return ""
    plaintext = raw_key.encode("utf-8")
    key = _master_key_bytes()
    AESGCM = _use_aes_gcm()
    if AESGCM is not None:
        nonce = secrets.token_bytes(12)
        aes = AESGCM(key)
        ct = aes.encrypt(nonce, plaintext, None)
        blob = b"v1:" + nonce + ct
        return base64.b64encode(blob).decode("ascii")
    # Fallback: XOR-stream for dev/test only. Not secure.
    stream = hashlib.shake_256(key).digest(len(plaintext))
    xored = bytes(a ^ b for a, b in zip(plaintext, stream))
    return base64.b64encode(b"v0:" + xored).decode("ascii")


def decrypt_key(blob: str) -> str:
    if not blob:
        return ""
    try:
        data = base64.b64decode(blob.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(f"decrypt_key: invalid base64 ({exc})") from exc
    if data.startswith(b"v1:"):
        AESGCM = _use_aes_gcm()
        if AESGCM is None:
            raise RuntimeError("cryptography package required to decrypt v1 keys")
        nonce = data[3:15]
        ct = data[15:]
        aes = AESGCM(_master_key_bytes())
        return aes.decrypt(nonce, ct, None).decode("utf-8")
    if data.startswith(b"v0:"):
        key = _master_key_bytes()
        payload = data[3:]
        stream = hashlib.shake_256(key).digest(len(payload))
        return bytes(a ^ b for a, b in zip(payload, stream)).decode("utf-8")
    raise RuntimeError("decrypt_key: unknown ciphertext prefix")
